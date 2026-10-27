"""Connected accounts: the principal's main Google account, plus any number of other Google and
Microsoft 365 accounts the agent watches for incoming mail and calendar events.

The main Google account (tokens under `google.tokens`) is the one the agent acts through: it emails the
principal, sends drafts they approve and makes approved calendar changes. Every other account is
watch-only. Its mail goes through capture alongside the main inbox, and the calendars mapped to a
division join that division's agenda. Each account keeps its tokens under its own secret key; the list
lives in the `accounts` setting:

    {"google": [{"id": "you-work-example-org", "email": "you@work.example.org", "label": "Work",
                 "mail": true, "calendars": {"Work": {"id": "primary", "division": "me"}}}],
     "microsoft": [{"id": "you-outlook-com", "email": "you@outlook.com", "label": "Outlook",
                    "mail": true, "calendars": {"Outlook": {"id": "default", "division": "me"}}}]}

A Microsoft account connected before there could be several (tokens under `microsoft.tokens`, calendars
in the `microsoft.divisions` setting) is listed too, and moves into the list the first time it's edited.
"""

import re
import sqlite3
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx

from . import store
from .db import audit, get_secret, put_secret
from .google import oauth as g_oauth
from .google.api import Google, _sort_key
from .microsoft import oauth as ms_oauth
from .microsoft.api import Microsoft

PROVIDERS = ("google", "microsoft")
MAIN = "main"  # the id of the principal's main Google account


def slug(email: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (email or "").lower()).strip("-")[:60]
    if not s:
        raise ValueError("an account needs an email address")
    return s


def token_key(provider: str, account_id: str) -> str:
    base = {"google": g_oauth.TOKEN_KEY, "microsoft": ms_oauth.TOKEN_KEY}[provider]
    return f"{base}/{account_id}"


def _registry(conn: sqlite3.Connection) -> dict:
    reg = store.get_setting(conn, "accounts", {}) or {}
    return {p: list(reg.get(p) or []) for p in PROVIDERS}


def _legacy_microsoft(conn: sqlite3.Connection, reg: dict) -> dict | None:
    """The single Microsoft account from before, if it isn't in the list yet."""
    if any(a.get("tokenKey") == ms_oauth.TOKEN_KEY for a in reg["microsoft"]):
        return None
    tok = get_secret(conn, ms_oauth.TOKEN_KEY)
    if not tok:
        return None
    email = tok.get("account") or ""
    calendars = {name: {"id": cal_id, "division": div}
                 for div, cals in ((store.get_setting(conn, "microsoft", {}) or {}).get("divisions")
                                   or {store.owner_division(conn): {"Outlook": "default"}}).items()
                 for name, cal_id in cals.items()}
    return {"id": slug(email) if email else "outlook", "email": email, "label": "Outlook", "mail": True,
            "calendars": calendars, "tokenKey": ms_oauth.TOKEN_KEY}


def entries(conn: sqlite3.Connection, provider: str) -> list[dict]:
    """The watched accounts of one provider, each with its tokenKey."""
    reg = _registry(conn)
    out = [a | {"tokenKey": a.get("tokenKey") or token_key(provider, a["id"])} for a in reg[provider]]
    if provider == "microsoft" and (legacy := _legacy_microsoft(conn, reg)):
        out.insert(0, legacy)
    return out


def get(conn: sqlite3.Connection, provider: str, account_id: str) -> dict:
    for a in entries(conn, provider):
        if a["id"] == account_id:
            return a
    raise KeyError(account_id)


def list_accounts(conn: sqlite3.Connection) -> list[dict]:
    """Everything the Settings screen shows: the main Google account first, then the watched ones."""
    main = g_oauth.status(conn)
    out = [{"provider": "google", "id": MAIN, "role": "main", "email": main.get("account") or
            (store.get_setting(conn, "assistant", {}) or {}).get("email"), "label": "Main",
            "connected": main["connected"], "canSend": main.get("canSend", False),
            "canWriteCalendar": main.get("canWriteCalendar", False)}]
    for provider in PROVIDERS:
        status = g_oauth.status if provider == "google" else ms_oauth.status
        for a in entries(conn, provider):
            st = status(conn, a["tokenKey"])
            out.append({"provider": provider, "id": a["id"], "role": "watch", "email": a.get("email"),
                        "label": a.get("label") or a.get("email"), "mail": a.get("mail", True),
                        "calendars": a.get("calendars") or {}, "connected": st["connected"],
                        "connectedAt": st.get("connectedAt")})
    return out


def adopt(conn: sqlite3.Connection, provider: str, temp_key: str, email: str) -> dict:
    """File a freshly signed-in account: move its tokens from `temp_key` to the account's own key and add
    it to the list. Signing in again to an account already listed refreshes its tokens and keeps its
    settings. Returns the account."""
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider '{provider}'")
    tok = get_secret(conn, temp_key)
    if not tok:
        raise KeyError(temp_key)
    email = (email or "").strip()
    main_email = (g_oauth.status(conn).get("account") or "").lower()
    if provider == "google" and main_email and email.lower() == main_email:
        put_secret(conn, temp_key, None)
        conn.commit()
        raise ValueError(f"{email} is already the main Google account")
    existing = next((a for a in entries(conn, provider) if (a.get("email") or "").lower() == email.lower()), None)
    account = existing or {"id": slug(email), "email": email, "label": email, "mail": True,
                           "calendars": {email if provider == "google" else "Outlook": {
                               "id": "primary" if provider == "google" else "default",
                               "division": store.owner_division(conn)}}}
    key = account.get("tokenKey") or token_key(provider, account["id"])
    put_secret(conn, key, tok | {"account": email})
    put_secret(conn, temp_key, None)
    _save(conn, provider, account | {"tokenKey": key})
    audit(conn, "user", "account.connect", provider=provider, id=account["id"])
    conn.commit()
    return get(conn, provider, account["id"])


def update(conn: sqlite3.Connection, provider: str, account_id: str, patch: dict) -> dict:
    """Change an account's label, whether its mail is captured, or which calendars join which division
    ({name: {id, division}})."""
    account = get(conn, provider, account_id)
    if "label" in patch:
        account["label"] = str(patch["label"] or "").strip()[:40] or account.get("email")
    if "mail" in patch:
        account["mail"] = bool(patch["mail"])
    if "calendars" in patch:
        divisions = set(store.divisions(conn)) or {store.owner_division(conn)}
        calendars = {}
        for name, cal in (patch["calendars"] or {}).items():
            if not (isinstance(cal, dict) and cal.get("id")):
                raise ValueError(f"calendar '{name}' needs an id")
            if cal.get("division") not in divisions:
                raise ValueError(f"calendar '{name}': unknown division '{cal.get('division')}'")
            calendars[str(name)[:80]] = {"id": str(cal["id"]), "division": cal["division"]}
        account["calendars"] = calendars
    _save(conn, provider, account)
    audit(conn, "user", "account.update", provider=provider, id=account_id, fields=sorted(patch))
    conn.commit()
    return get(conn, provider, account_id)


def remove(conn: sqlite3.Connection, provider: str, account_id: str, http: httpx.Client | None = None) -> None:
    """Disconnect a watched account and forget it (Google access is revoked too)."""
    account = get(conn, provider, account_id)
    if provider == "google":
        try:
            g_oauth.disconnect(conn, http, key=account["tokenKey"])
        except httpx.HTTPError:
            put_secret(conn, account["tokenKey"], None)  # revoking failed: still forget it here
    else:
        ms_oauth.disconnect(conn, key=account["tokenKey"])
    reg = _registry(conn)
    reg[provider] = [a for a in reg[provider] if a["id"] != account_id]
    store.put_setting(conn, "accounts", reg)
    audit(conn, "user", "account.remove", provider=provider, id=account_id)
    conn.commit()


def _save(conn: sqlite3.Connection, provider: str, account: dict) -> None:
    reg = _registry(conn)
    reg[provider] = [a for a in reg[provider] if a["id"] != account["id"]] + [account]
    store.put_setting(conn, "accounts", reg)


# Clients for the rest of the app

def google_watchers(conn: sqlite3.Connection, http: httpx.Client | None = None) -> list[tuple[dict, Google]]:
    """(account, Google session) for each connected, watched Google account."""
    return [(a, Google(conn, http, key=a["tokenKey"])) for a in entries(conn, "google")
            if g_oauth.status(conn, a["tokenKey"])["connected"]]


def microsoft_clients(conn: sqlite3.Connection, http: httpx.Client | None = None) -> list[Microsoft]:
    """A Graph session for each connected Microsoft 365 account."""
    return [Microsoft(conn, http, key=a["tokenKey"], account=a) for a in entries(conn, "microsoft")
            if ms_oauth.status(conn, a["tokenKey"])["connected"]]


def merge_calendars(conn: sqlite3.Connection, agenda: dict, http: httpx.Client | None, today: date,
                    days: int) -> dict:
    """Add the watched Google accounts' mapped calendars to an agenda from Google.agenda, by division.
    A calendar that can't be read is listed under its division's errors; it never stops the agenda."""
    watchers = [(a, g) for a, g in google_watchers(conn, http) if a.get("calendars")]
    if not watchers:
        return agenda
    tz = ZoneInfo(store.get_setting(conn, "timezone", "UTC"))
    start = datetime.combine(today, time.min, tz)
    end = start + timedelta(days=days + 1)
    labels = {k: d.get("label", k) for k, d in store.divisions(conn).items()}
    for account, google in watchers:
        for name, cal in account["calendars"].items():
            div = agenda["divisions"].setdefault(cal["division"], {"label": labels.get(cal["division"], cal["division"]),
                                                                   "events": [], "errors": []})
            try:
                div["events"] += [e | {"calendarName": name, "account": account.get("email")}
                                  for e in google.events(cal["id"], start, end)]
            except (httpx.HTTPError, g_oauth.GoogleNotConnected) as e:
                code = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else e.__class__.__name__
                div["errors"].append({"calendar": name, "account": account.get("email"), "status": code})
    for div in agenda["divisions"].values():
        div["events"].sort(key=lambda e: _sort_key(e, tz))
    return agenda


def outlook_agenda(clients: list[Microsoft], days: int, today: date) -> dict:
    """One agenda across all Microsoft 365 accounts, by division. An account that fails is listed in errors."""
    out: dict = {"divisions": {}, "errors": []}
    for ms in clients:
        try:
            ag = ms.agenda(days, today=today)
        except (httpx.HTTPError, ms_oauth.MicrosoftNotConnected) as e:
            out["errors"].append({"account": ms.account.get("email"), "error": f"{e.__class__.__name__}: {e}"[:200]})
            continue
        out.setdefault("timezone", ag["timezone"])
        for key, div in ag["divisions"].items():
            merged = out["divisions"].setdefault(key, {"events": [], "errors": []})
            merged["events"] = sorted(merged["events"] + div["events"], key=lambda e: e["start"])
            merged["errors"] += div["errors"]
    return out
