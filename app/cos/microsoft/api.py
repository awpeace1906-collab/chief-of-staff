"""Outlook mail, calendars and Microsoft To Do via Microsoft Graph, normalized like the Google reads."""

import re
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from html import unescape
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from ..store import get_setting
from .oauth import TOKEN_KEY, MicrosoftNotConnected, access_token, expire, remember_account

GRAPH = "https://graph.microsoft.com/v1.0"


class Microsoft:
    """One authenticated Graph session; pass `http` to swap the transport in tests. `key` and `account`
    pick one of several connected accounts (cos/accounts.py); the account's `calendars` map its calendars
    to divisions."""

    def __init__(self, conn: sqlite3.Connection, http: httpx.Client | None = None, key: str = TOKEN_KEY,
                 account: dict | None = None):
        self.conn = conn
        self.http = http or httpx.Client(timeout=30)
        self.key = key
        self.account = account or {}

    def _get(self, url: str, params: dict | None = None, headers: dict | None = None) -> dict:
        if not url.startswith("http"):
            url = GRAPH + url
        for _ in (1, 2):
            token = access_token(self.conn, self.http, self.key)
            r = self.http.get(url, params=params, headers={"Authorization": f"Bearer {token}", **(headers or {})})
            if r.status_code != 401:
                r.raise_for_status()
                return r.json()
            expire(self.conn, self.key)
        raise MicrosoftNotConnected("Microsoft rejected the stored access; connect again at /oauth/microsoft/start")

    def _pages(self, url: str, params: dict | None = None, headers: dict | None = None, limit: int = 500) -> list[dict]:
        out = []
        while url and len(out) < limit:
            data = self._get(url, params, headers)
            out += data.get("value", [])
            url, params = data.get("@odata.nextLink"), None  # nextLink carries the query
        return out[:limit]

    def me(self) -> dict:
        me = self._get("/me", {"$select": "displayName,mail,userPrincipalName"})
        remember_account(self.conn, me.get("mail") or me.get("userPrincipalName"), self.key)
        return me

    # Calendar

    def calendars(self) -> list[dict]:
        return [{"id": c["id"], "name": c.get("name"), "owner": (c.get("owner") or {}).get("address"),
                 "canEdit": c.get("canEdit"), "isDefault": c.get("isDefaultCalendar", False)}
                for c in self._pages("/me/calendars")]

    def events(self, calendar_id: str | None, start: datetime, end: datetime) -> list[dict]:
        path = f"/me/calendars/{quote(calendar_id, safe='')}/calendarView" if calendar_id else "/me/calendarView"
        rows = self._pages(path, {
            "startDateTime": start.astimezone(timezone.utc).isoformat(),
            "endDateTime": end.astimezone(timezone.utc).isoformat(),
            "$select": "id,subject,start,end,isAllDay,location,showAs,webLink,isCancelled",
            "$orderby": "start/dateTime", "$top": 100,
        }, headers={"Prefer": 'outlook.timezone="UTC"'})
        return [_event(e, calendar_id) for e in rows if not e.get("isCancelled")]

    def agenda(self, days: int = 7, today: date | None = None) -> dict:
        """Events by division, from the calendars mapped in settings microsoft.divisions
        ({division: {calendar name: calendar id or "default"}}); unmapped → the default calendar under "me"."""
        tz = ZoneInfo(get_setting(self.conn, "timezone", "UTC"))
        today = today or datetime.now(tz).date()
        start = datetime.combine(today, time.min, tz)
        end = start + timedelta(days=days + 1)
        access_token(self.conn, self.http, self.key)  # fail fast when not connected
        if "calendars" in self.account:  # an account from the list: only the calendars mapped there
            mapping = {}
            for name, cal in self.account["calendars"].items():
                mapping.setdefault(cal["division"], {})[name] = cal["id"]
        else:
            mapping = get_setting(self.conn, "microsoft", {}).get("divisions") or {"me": {"Outlook": "default"}}
        result = {"timezone": str(tz), "from": start.isoformat(), "to": end.isoformat(), "divisions": {}}
        for key, cals in mapping.items():
            events, errors = [], []
            for name, cal_id in cals.items():
                try:
                    found = self.events(None if cal_id == "default" else cal_id, start, end)
                    events += [e | {"calendarName": name, "source": "microsoft",
                                    **({"account": self.account["email"]} if self.account.get("email") else {})}
                               for e in found]
                except httpx.HTTPStatusError as e:
                    errors.append({"calendar": name, "status": e.response.status_code})
            events.sort(key=lambda e: e["start"])
            result["divisions"][key] = {"events": events, "errors": errors}
        return result

    # Mail

    def search(self, query: str | None = None, limit: int = 25, folder: str | None = None,
               since: datetime | None = None) -> list[dict]:
        """Messages matching a KQL search (`query`), or the newest in `folder` since a time."""
        params = {"$top": min(limit, 50),
                  "$select": "id,conversationId,subject,from,toRecipients,ccRecipients,receivedDateTime,"
                             "bodyPreview,body,webLink,parentFolderId"}
        path = f"/me/mailFolders/{folder}/messages" if folder else "/me/messages"
        if query:
            params["$search"] = f'"{query}"'
        else:
            params["$orderby"] = "receivedDateTime desc"
            if since:
                params["$filter"] = f"receivedDateTime ge {since.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
        return [_message(m, folder) for m in self._pages(path, params, limit=limit)]

    # Microsoft To Do

    def todo(self, include_completed: bool = False, limit: int = 200) -> list[dict]:
        out = []
        for lst in self._pages("/me/todo/lists"):
            params = None if include_completed else {"$filter": "status ne 'completed'"}
            for t in self._pages(f"/me/todo/lists/{quote(lst['id'], safe='')}/tasks", params, limit=limit):
                due = (t.get("dueDateTime") or {}).get("dateTime")
                out.append({"id": t["id"], "list": lst.get("displayName"), "title": t.get("title"),
                            "status": t.get("status"), "importance": t.get("importance"),
                            "due": due[:10] if due else None})
        return out[:limit]


def _event(e: dict, calendar_id: str | None) -> dict:
    all_day = bool(e.get("isAllDay"))
    s, en = (e.get("start") or {}).get("dateTime", ""), (e.get("end") or {}).get("dateTime", "")
    return {
        "id": e["id"],
        "calendarId": calendar_id or "default",
        "title": e.get("subject") or "(no title)",
        "start": s[:10] if all_day else _utc(s),
        "end": en[:10] if all_day else _utc(en),
        "allDay": all_day,
        "location": (e.get("location") or {}).get("displayName") or None,
        "busy": e.get("showAs") not in {"free", "workingElsewhere"},
        "url": e.get("webLink"),
    }


def _utc(s: str) -> str:
    """Graph returns '2026-10-20T15:00:00.0000000' in UTC (per the Prefer header)."""
    return s[:19] + "+00:00" if s else s


def _addr(r: dict | None) -> str | None:
    if not r:
        return None
    a = r.get("emailAddress") or {}
    return f"{a.get('name')} <{a.get('address')}>" if a.get("name") else a.get("address")


def _message(m: dict, folder: str | None) -> dict:
    body = m.get("body") or {}
    text = body.get("content", "")
    if body.get("contentType") == "html":
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
        text = unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()[:20000]
    return {
        "id": m["id"],
        "threadId": m.get("conversationId"),
        "labels": ["SENT"] if folder == "sentitems" else [],
        "from": _addr(m.get("from")),
        "to": ", ".join(filter(None, (_addr(r) for r in m.get("toRecipients", [])))),
        "cc": ", ".join(filter(None, (_addr(r) for r in m.get("ccRecipients", [])))),
        "subject": m.get("subject"),
        "date": m.get("receivedDateTime"),
        "snippet": m.get("bodyPreview", ""),
        "body": text,
        "url": m.get("webLink"),
        "source": "outlook",
    }
