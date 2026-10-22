"""Text messaging (v0.5): talk to the assistant and approve proposals by SMS.

Providers: Telnyx (API key) or VoIP.ms (API user + password); the number is rented from either.
Inbound texts arrive at /hooks/sms/<provider>/<COS_HOOK_SECRET>. Only the principal's number is
answered. "approve 1, 3", "decline 2", "approve all" and "list" are handled at once; anything else
becomes a message the assistant answers by text, the same way it answers the web app.
"""

import os
import re
import sqlite3

import httpx

from . import store
from .db import audit

TELNYX = "https://api.telnyx.com/v2/messages"
VOIPMS = "https://voip.ms/api/v1/rest.php"
LIMITS = {"telnyx": 1500, "voipms": 160}


class SmsNotConfigured(RuntimeError):
    pass


def settings(conn: sqlite3.Connection) -> dict:
    return store.get_setting(conn, "sms", {}) or {}


def configured(conn: sqlite3.Connection) -> bool:
    s = settings(conn)
    return bool(s.get("provider") and s.get("number") and s.get("ownerNumber"))


def digits(number: str | None) -> str:
    """Last 10 digits, so +1 (575) 555-0100 and 5755550100 compare equal."""
    return re.sub(r"\D", "", number or "")[-10:]


def e164(number: str) -> str:
    """+15755550100 from any US-style or E.164 input."""
    d = re.sub(r"\D", "", number or "")
    return "+1" + d if len(d) == 10 else "+" + d


def parse_inbound(provider: str, payload: dict) -> tuple[str, str] | None:
    """(from, text) from a provider's webhook body or query, or None for other events."""
    if provider == "telnyx":
        data = payload.get("data") or {}
        if data.get("event_type") != "message.received":
            return None
        p = data.get("payload") or {}
        return (p.get("from") or {}).get("phone_number", ""), p.get("text") or ""
    if provider == "voipms":  # callback URL configured as ...?from={FROM}&to={TO}&message={MESSAGE}
        if not payload.get("from"):
            return None
        return str(payload["from"]), str(payload.get("message") or "")
    raise ValueError(f"unknown SMS provider '{provider}'")


def send(conn: sqlite3.Connection, text: str, http: httpx.Client | None = None, to: str | None = None) -> int:
    """Text the principal (only the principal). Splits long text; returns the number of parts sent."""
    s = settings(conn)
    if not configured(conn):
        raise SmsNotConfigured("set sms.provider, sms.number and sms.ownerNumber (docs/setup/sms.md)")
    to = e164(to or s["ownerNumber"])
    if digits(to) != digits(s["ownerNumber"]):
        raise ValueError("texts only go to the principal")
    http = http or httpx.Client(timeout=20)
    provider, limit = s["provider"], LIMITS.get(s["provider"], 160)
    parts = _split(text.strip(), limit)
    for part in parts:
        if provider == "telnyx":
            key = os.environ.get("TELNYX_API_KEY")
            if not key:
                raise SmsNotConfigured("set TELNYX_API_KEY")
            r = http.post(TELNYX, headers={"Authorization": f"Bearer {key}"},
                          json={"from": e164(s["number"]), "to": to, "text": part})
        elif provider == "voipms":
            user, pw = os.environ.get("VOIPMS_USER"), os.environ.get("VOIPMS_PASSWORD")
            if not (user and pw):
                raise SmsNotConfigured("set VOIPMS_USER and VOIPMS_PASSWORD")
            r = http.get(VOIPMS, params={"api_username": user, "api_password": pw, "method": "sendSMS",
                                         "did": digits(s["number"]), "dst": digits(to), "message": part})
            if r.is_success and r.json().get("status") != "success":
                raise RuntimeError(f"VoIP.ms: {r.json().get('status')}")
        else:
            raise SmsNotConfigured(f"unknown SMS provider '{provider}'")
        r.raise_for_status()
    audit(conn, "assistant", "sms.sent", parts=len(parts))
    conn.commit()
    return len(parts)


def _split(text: str, limit: int) -> list[str]:
    parts = []
    while len(text) > limit:
        cut = text.rfind(" ", 0, limit)
        cut = cut if cut > limit // 2 else limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return parts + ([text] if text else [])


COMMAND = re.compile(r"^\s*(approve|ok|yes|decline|no|skip)\s+(all|[\d,\s&and]+)\s*\.?\s*$", re.I)


def pending_by_number(conn: sqlite3.Connection) -> dict[int, dict]:
    """Pending proposals by number, newest day first (numbers restart each day)."""
    out = {}
    for p in store.list_proposals(conn, ("pending",)):
        out.setdefault(p["n"], p)
    return out


def proposal_list(conn: sqlite3.Connection) -> str:
    pending = pending_by_number(conn)
    if not pending:
        return "Nothing waiting for your OK."
    lines = [f"{n}. {p.get('title') or p.get('summary')}" + (f" ({p['when']})" if p.get("when") else "")
             for n, p in sorted(pending.items())]
    return "Waiting for your OK:\n" + "\n".join(lines) + "\nReply \"approve 1, 3\" or \"decline 2\"."


def handle_inbound(conn: sqlite3.Connection, sender: str, text: str) -> dict:
    """Decide what an inbound text is. Returns {"reply": str|None, "approved": [ids], "message": id|None}."""
    s = settings(conn)
    if not configured(conn) or digits(sender) != digits(s["ownerNumber"]):
        audit(conn, "system", "sms.ignored", sender=digits(sender)[-4:])
        conn.commit()
        return {"reply": None, "approved": [], "message": None}
    text = (text or "").strip()
    if text.lower() in {"list", "?", "proposals", "pending"}:
        return {"reply": proposal_list(conn), "approved": [], "message": None}
    m = COMMAND.match(text)
    if m:
        verb, which = m.group(1).lower(), m.group(2).lower()
        pending = pending_by_number(conn)
        numbers = sorted(pending) if which == "all" else [int(x) for x in re.findall(r"\d+", which)]
        status = "approved" if verb in {"approve", "ok", "yes"} else "declined"
        done, missing = [], []
        for n in numbers:
            if n in pending:
                store.update_proposal(conn, pending[n]["id"], {"status": status})
                done.append(pending[n])
            else:
                missing.append(n)
        parts = []
        if done:
            word = "Approved" if status == "approved" else "Declined"
            parts.append(f"{word}: " + "; ".join(f"{p['n']}. {p.get('title') or p.get('summary')}" for p in done))
            if status == "approved":
                parts.append("Working on it now; I'll text when it's done.")
        if missing:
            parts.append(f"No pending proposal {', '.join(map(str, missing))}. Text \"list\" to see them.")
        return {"reply": " ".join(parts), "approved": [p["id"] for p in done if status == "approved"], "message": None}
    if not text:
        return {"reply": None, "approved": [], "message": None}
    msg = store.add_message(conn, "owner", text, channel="sms")
    return {"reply": None, "approved": [], "message": msg["id"]}


def brief_text(brief: dict, link: str | None = None) -> str:
    """The short morning text: subject, numbered proposals, how to approve."""
    lines = [brief["subject"]]
    for p in brief.get("proposals", []):
        lines.append(f"{p['n']}. {p.get('title') or p.get('summary')}")
    if brief.get("proposals"):
        lines.append('Reply "approve 1, 3" or "decline 2".')
    if link:
        lines.append(link)
    return "\n".join(lines)
