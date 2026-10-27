"""Calendar and Gmail reads, normalized for the assistant."""

import base64
import re
from email.message import EmailMessage
import sqlite3
from datetime import date, datetime, time, timedelta
from html import unescape
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from ..store import get_setting
from .oauth import TOKEN_KEY, GoogleNotConnected, access_token, expire, status

CAL = "https://www.googleapis.com/calendar/v3"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"


class Google:
    """One authenticated session; pass `http` to swap the transport in tests. `key` picks the account
    (default: the principal's main one; see cos/accounts.py for the others)."""

    def __init__(self, conn: sqlite3.Connection, http: httpx.Client | None = None, key: str = TOKEN_KEY):
        self.conn = conn
        self.http = http or httpx.Client(timeout=30)
        self.key = key

    def _get(self, url: str, **params) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        for attempt in (1, 2):
            token = access_token(self.conn, self.http, self.key)
            r = self.http.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
            if r.status_code != 401:
                r.raise_for_status()
                return r.json()
            expire(self.conn, self.key)  # token rejected early (revoked or rotated): refresh once and retry
        raise GoogleNotConnected("Google rejected the stored access; connect again at /oauth/google/start")

    # Calendar

    def calendars(self) -> list[dict]:
        items, page = [], None
        while True:
            data = self._get(f"{CAL}/users/me/calendarList", pageToken=page)
            items += [{"id": c["id"], "name": c.get("summaryOverride") or c.get("summary", c["id"]),
                       "timezone": c.get("timeZone"), "access": c.get("accessRole")} for c in data.get("items", [])]
            page = data.get("nextPageToken")
            if not page:
                return items

    def events(self, calendar_id: str, start: datetime, end: datetime) -> list[dict]:
        out, page = [], None
        while True:
            data = self._get(
                f"{CAL}/calendars/{quote(calendar_id, safe='')}/events",
                timeMin=start.isoformat(), timeMax=end.isoformat(),
                singleEvents="true", orderBy="startTime", maxResults=250, pageToken=page,
            )
            out += [_event(e, calendar_id) for e in data.get("items", []) if e.get("status") != "cancelled"]
            page = data.get("nextPageToken")
            if not page:
                return out

    def _send(self, method: str, url: str, body: dict, **params) -> dict:
        if not status(self.conn, self.key).get("canWriteCalendar"):
            raise GoogleNotConnected("Google is connected without calendar write permission; reconnect at /oauth/google/start")
        for attempt in (1, 2):
            token = access_token(self.conn, self.http, self.key)
            r = self.http.request(method, url, params=params or None, json=body, headers={"Authorization": f"Bearer {token}"})
            if r.status_code != 401:
                r.raise_for_status()
                return r.json()
            expire(self.conn, self.key)
        raise GoogleNotConnected("Google rejected the stored access; connect again at /oauth/google/start")

    def create_event(self, calendar_id: str, event: dict) -> dict:
        """Create an event; never invites anyone (sendUpdates=none)."""
        e = self._send("POST", f"{CAL}/calendars/{quote(calendar_id, safe='')}/events", event, sendUpdates="none")
        return _event(e, calendar_id)

    def update_event(self, calendar_id: str, event_id: str, patch: dict) -> dict:
        e = self._send("PATCH", f"{CAL}/calendars/{quote(calendar_id, safe='')}/events/{quote(event_id, safe='')}",
                       patch, sendUpdates="none")
        return _event(e, calendar_id)

    def agenda(self, days: int = 7, today: date | None = None) -> dict:
        """Events from today through `days` ahead, grouped by division."""
        tz = ZoneInfo(get_setting(self.conn, "timezone", "UTC"))
        today = today or datetime.now(tz).date()
        start = datetime.combine(today, time.min, tz)
        end = start + timedelta(days=days + 1)
        access_token(self.conn, self.http, self.key)  # fail fast when Google isn't connected
        divisions = get_setting(self.conn, "divisions", {})
        result = {"timezone": str(tz), "from": start.isoformat(), "to": end.isoformat(), "divisions": {}}
        for key, div in divisions.items():
            events, errors = [], []
            for name, cal_id in div.get("calendars", {}).items():
                try:
                    events += [e | {"calendarName": name} for e in self.events(cal_id, start, end)]
                except httpx.HTTPStatusError as e:
                    errors.append({"calendar": name, "status": e.response.status_code})
            events.sort(key=lambda e: _sort_key(e, tz))
            result["divisions"][key] = {"label": div.get("label", key), "events": events, "errors": errors}
        return result

    # Gmail

    def search(self, query: str, limit: int = 25) -> list[dict]:
        ids, page = [], None
        while len(ids) < limit:
            data = self._get(f"{GMAIL}/messages", q=query, maxResults=min(100, limit - len(ids)), pageToken=page)
            ids += [m["id"] for m in data.get("messages", [])]
            page = data.get("nextPageToken")
            if not page:
                break
        return [self.message(i) for i in ids[:limit]]

    def message(self, message_id: str) -> dict:
        m = self._get(f"{GMAIL}/messages/{message_id}", format="full")
        headers = {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}
        return {
            "id": m["id"],
            "threadId": m.get("threadId"),
            "labels": m.get("labelIds", []),
            "from": headers.get("from"),
            "to": headers.get("to"),
            "cc": headers.get("cc"),
            "deliveredTo": headers.get("delivered-to"),
            "subject": headers.get("subject"),
            "date": headers.get("date"),
            "snippet": unescape(m.get("snippet", "")),
            "body": _body(m.get("payload", {})),
            "url": f"https://mail.google.com/mail/u/0/#all/{m.get('threadId', m['id'])}",
        }

    def send_to_owner(self, subject: str, text: str) -> str:
        """Email the principal (and only the principal). Returns the Gmail message id."""
        owner = get_setting(self.conn, "assistant", {}).get("email")
        if not owner:
            raise RuntimeError("no owner email; set assistant.email in settings")
        return self.send(owner, subject, text)

    def send(self, to: str, subject: str, text: str, thread_id: str | None = None) -> str:
        """Send one email from the principal's Gmail. Callers other than send_to_owner must hold the principal's
        approval of this exact email (an approved Send: proposal). Returns the Gmail message id."""
        owner = get_setting(self.conn, "assistant", {}).get("email")
        if not status(self.conn, self.key).get("canSend"):
            raise GoogleNotConnected("Google is connected without send permission; reconnect at /oauth/google/start")
        msg = EmailMessage()
        msg["To"] = to
        if owner:
            msg["From"] = owner
        msg["Subject"] = subject
        msg.set_content(text)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        body = {"raw": raw} | ({"threadId": thread_id} if thread_id else {})
        token = access_token(self.conn, self.http, self.key)
        r = self.http.post(f"{GMAIL}/messages/send", json=body, headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        return r.json()["id"]

    def intake(self, since_days: int = 2, limit: int = 50) -> list[dict]:
        """Mail sent to the intake plus-address (e.g. you+assistant@gmail.com)."""
        address = get_setting(self.conn, "google", {}).get("intakeAddress")
        if not address:
            raise RuntimeError("no intake address; set google.intakeAddress in settings")
        return self.search(f"to:{address} newer_than:{since_days}d", limit)


def _sort_key(e: dict, tz: ZoneInfo) -> datetime:
    """All-day events sort at the start of their day in the user's timezone."""
    if e["allDay"]:
        return datetime.combine(date.fromisoformat(e["start"]), time.min, tz)
    return datetime.fromisoformat(e["start"])


def _event(e: dict, calendar_id: str) -> dict:
    all_day = "date" in e.get("start", {})
    return {
        "id": e["id"],
        "calendarId": calendar_id,
        "title": e.get("summary", "(no title)"),
        "start": e["start"].get("dateTime") or e["start"].get("date"),
        "end": e.get("end", {}).get("dateTime") or e.get("end", {}).get("date"),
        "allDay": all_day,
        "location": e.get("location"),
        "busy": e.get("transparency") != "transparent",
        "url": e.get("htmlLink"),
    }


def _body(payload: dict, limit: int = 20000) -> str:
    """Plain text of a message: text/plain if present, else stripped text/html."""
    plain, html = [], []

    def walk(part: dict) -> None:
        mime, data = part.get("mimeType", ""), part.get("body", {}).get("data")
        if data and mime == "text/plain":
            plain.append(_b64(data))
        elif data and mime == "text/html":
            html.append(_b64(data))
        for p in part.get("parts", []):
            walk(p)

    walk(payload)
    if plain:
        text = "\n".join(plain)
    else:
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", "\n".join(html), flags=re.S | re.I)
        text = unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()[:limit]


def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
