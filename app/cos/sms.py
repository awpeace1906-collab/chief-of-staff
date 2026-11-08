"""Text messaging (v0.5): talk to the assistant and approve proposals by SMS.

Providers: Telnyx (API key) or VoIP.ms (API user + password); the number is rented from either.
Inbound texts arrive at /hooks/sms/<provider>/<COS_HOOK_SECRET>. Only the principal's number is
answered. "approve 1, 3", "decline 2", "approve all" and "list" are handled at once; anything else
becomes a message the assistant answers by text, the same way it answers the web app.
"""

import base64
import os
import re
import sqlite3
import time

import httpx

from . import store
from .db import audit

TELNYX_API = "https://api.telnyx.com/v2"
TELNYX = TELNYX_API + "/messages"
SIGNATURE_MAX_AGE = 300  # seconds a signed Telnyx webhook stays valid (replay window)
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


# Telnyx webhook signatures: with TELNYX_PUBLIC_KEY set (Portal → Account → Keys & Credentials → Public Key),
# every inbound webhook must carry a valid Ed25519 signature over "<timestamp>|<raw body>", less than five
# minutes old. Without the key, the hook secret in the URL is the only check (readiness flags that).

def verify_telnyx(raw: bytes, headers, now: float | None = None) -> bool:
    key = os.environ.get("TELNYX_PUBLIC_KEY")
    if not key:
        return True
    sig, ts = headers.get("telnyx-signature-ed25519"), headers.get("telnyx-timestamp")
    if not (sig and ts):
        return False
    try:
        if abs((now or time.time()) - int(ts)) > SIGNATURE_MAX_AGE:
            return False
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(base64.b64decode(key)).verify(base64.b64decode(sig), ts.encode() + b"|" + raw)
        return True
    except Exception:  # bad key, bad signature, missing library: refuse
        return False


# Readiness: everything that has to be true before texting goes live, with the fix for each step.

def webhook_url(conn: sqlite3.Connection, base: str | None = None, reveal: bool = False) -> str | None:
    s = settings(conn)
    base = (base or store.get_setting(conn, "appUrl") or "").rstrip("/")
    secret = os.environ.get("COS_HOOK_SECRET") or ""
    if not (base and s.get("provider") and secret):
        return None
    shown = secret if reveal else secret[:4] + "…"
    return f"{base}/hooks/sms/{s['provider']}/{shown}"


def readiness(conn: sqlite3.Connection, base: str | None = None, live: bool = False,
              http: httpx.Client | None = None, reveal: bool = False) -> dict:
    """[{id, ok, label, fix}] for each go-live step. ok is None for a check that wasn't run."""
    s = settings(conn)
    provider = s.get("provider")
    base = (base or store.get_setting(conn, "appUrl") or "").rstrip("/")
    secret = os.environ.get("COS_HOOK_SECRET") or ""
    checks = []

    def check(cid, ok, label, fix):
        checks.append({"id": cid, "ok": ok, "label": label, "fix": "" if ok else fix})

    check("provider", provider in LIMITS, f"Provider: {provider or 'not set'}",
          'Set sms.provider to "telnyx" (or "voipms") in memory.json or Settings.')
    check("number", bool(s.get("number")), "The agent's number" + (f" ending {digits(s['number'])[-4:]}" if s.get("number") else ": not set"),
          "Buy a local number in the Telnyx portal and set sms.number.")
    check("owner", bool(s.get("ownerNumber")), "Your number" + (f" ending {digits(s['ownerNumber'])[-4:]}" if s.get("ownerNumber") else ": not set"),
          "Set sms.ownerNumber to your mobile number.")
    if provider == "voipms":
        check("apiKey", bool(os.environ.get("VOIPMS_USER") and os.environ.get("VOIPMS_PASSWORD")), "VoIP.ms API user and password",
              "fly secrets set VOIPMS_USER=... VOIPMS_PASSWORD=...")
    else:
        check("apiKey", bool(os.environ.get("TELNYX_API_KEY")), "Telnyx API key", "fly secrets set TELNYX_API_KEY=...")
        check("signatures", bool(os.environ.get("TELNYX_PUBLIC_KEY")), "Webhook signatures checked (Telnyx public key)",
              "fly secrets set TELNYX_PUBLIC_KEY=... (Portal → Keys & Credentials → Public Key)")
    check("hookSecret", len(secret) >= 16, "Webhook secret (COS_HOOK_SECRET)", "fly secrets set COS_HOOK_SECRET=$(openssl rand -hex 16)")
    check("https", base.startswith("https://"), f"Public address: {base or 'not set'}", "Set appUrl to the app's https address, e.g. https://<app>.fly.dev")

    if live and provider == "telnyx" and all(c["ok"] for c in checks if c["id"] in {"number", "apiKey", "hookSecret", "https"}):
        http = http or httpx.Client(timeout=20)
        hdr = {"Authorization": f"Bearer {os.environ['TELNYX_API_KEY']}"}
        try:
            r = http.get(f"{TELNYX_API}/phone_numbers", headers=hdr, params={"filter[phone_number]": e164(s["number"])})
            r.raise_for_status()
            nums = r.json().get("data") or []
            profile = (nums[0] if nums else {}).get("messaging_profile_id")
            check("owned", bool(nums), "The number is on your Telnyx account", "Check sms.number matches the number you bought.")
            check("profile", bool(profile), "The number is in a messaging profile",
                  "Portal → Numbers → your number → Messaging profile: pick one.")
            if profile:
                p = http.get(f"{TELNYX_API}/messaging_profiles/{profile}", headers=hdr)
                p.raise_for_status()
                hook = (p.json().get("data") or {}).get("webhook_url") or ""
                check("webhook", hook == webhook_url(conn, base, reveal=True), "The messaging profile sends inbound texts to this app",
                      "Portal → Messaging → your profile → Inbound webhook URL: run `cos sms status --show-webhook` and paste it.")
        except httpx.HTTPError as e:
            check("live", False, "Telnyx API reachable", f"Telnyx answered {getattr(getattr(e, 'response', None), 'status_code', '') or e.__class__.__name__}; check TELNYX_API_KEY.")
    elif provider == "telnyx":
        checks.append({"id": "live", "ok": None, "label": "Number, messaging profile and webhook on Telnyx", "fix": "Run `cos sms status --live` once the steps above pass."})

    checks.append({"id": "registration", "ok": None, "label": "US texting registration (10DLC): brand and campaign approved",
                   "fix": "Telnyx portal → Messaging → Compliance. Can't be checked from here; texts are filtered until it's approved."})
    required = [c for c in checks if c["ok"] is not None]
    return {"ready": all(c["ok"] for c in required), "provider": provider, "webhook": webhook_url(conn, base, reveal),
            "checks": checks}


def test_text(conn: sqlite3.Connection, http: httpx.Client | None = None) -> int:
    name = store.assistant_name(conn)
    return send(conn, f"{name} here. Texting works. Reply \"list\" to see what's waiting for your OK.", http)

