"""Silent APNs pushes that wake the iOS shell to refresh.

Synchronous on purpose: `agent.check()` runs on the scheduler thread, which has no event loop.
Configuration comes from the environment only (the key never lives in the repo or the database):
APNS_KEY_ID, APNS_TEAM_ID, APNS_BUNDLE, APNS_KEY_PATH, and APNS_ENV (`sandbox` for Xcode debug
builds, anything else for production). Device tokens are kept in the secrets table, so they are
never exported to memory. Needs the optional `push` extra: `pip install -e '.[push]'`.
"""

import os
import re
import sqlite3
import time

from .db import audit, get_secret, put_secret

TOKENS_KEY = "apns.tokens"
JWT_TTL = 50 * 60  # Apple accepts a provider token for up to an hour
TOKEN_RE = re.compile(r"^[0-9a-fA-F]{64,}$")
ENV_VARS = ("APNS_KEY_ID", "APNS_TEAM_ID", "APNS_BUNDLE", "APNS_KEY_PATH")

_jwt: dict = {"token": None, "at": 0.0, "key": None}


def configured() -> bool:
    return all(os.environ.get(v) for v in ENV_VARS)


def host() -> str:
    return "api.sandbox.push.apple.com" if os.environ.get("APNS_ENV") == "sandbox" else "api.push.apple.com"


def valid_token(token) -> bool:
    return isinstance(token, str) and bool(TOKEN_RE.match(token))


def tokens(conn: sqlite3.Connection) -> list[str]:
    return list(get_secret(conn, TOKENS_KEY) or [])


def register(conn: sqlite3.Connection, token: str) -> int:
    """Add a device token; returns how many are stored. Raises ValueError on a malformed token."""
    if not valid_token(token):
        raise ValueError("token must be hex, at least 64 characters")
    token = token.lower()
    have = tokens(conn)
    if token not in have:
        have.append(token)
        put_secret(conn, TOKENS_KEY, have)
        audit(conn, "user", "push.register", count=len(have))
        conn.commit()
    return len(have)


def _provider_token() -> str:
    """ES256 JWT for APNs, cached for about 50 minutes."""
    import jwt  # optional dependency (pyjwt[crypto])

    ident = (os.environ["APNS_KEY_ID"], os.environ["APNS_TEAM_ID"], os.environ["APNS_KEY_PATH"])
    now = time.time()
    if _jwt["token"] and _jwt["key"] == ident and now - _jwt["at"] < JWT_TTL:
        return _jwt["token"]
    key_id, team_id, key_path = ident
    with open(key_path) as f:
        secret = f.read()
    token = jwt.encode({"iss": team_id, "iat": int(now)}, secret, algorithm="ES256", headers={"kid": key_id})
    _jwt.update(token=token, at=now, key=ident)
    return token


def _client():
    import httpx

    return httpx.Client(http2=True, timeout=10)


def send_silent(token: str, client=None) -> tuple[int, str]:
    """One background push. Returns (status code, APNs reason or "")."""
    own = client is None
    client = client or _client()
    try:
        r = client.post(
            f"https://{host()}/3/device/{token}",
            headers={"authorization": f"bearer {_provider_token()}", "apns-topic": os.environ["APNS_BUNDLE"],
                     "apns-push-type": "background", "apns-priority": "5"},
            json={"aps": {"content-available": 1}},
        )
        reason = ""
        if r.status_code != 200:
            try:
                reason = (r.json() or {}).get("reason", "")
            except ValueError:
                pass
        return r.status_code, reason
    finally:
        if own:
            client.close()


def notify_all(conn: sqlite3.Connection, client=None) -> dict:
    """Wake every registered device; drop tokens Apple says are dead (410, or 400 BadDeviceToken)."""
    have = tokens(conn)
    if not (configured() and have):
        return {"sent": 0, "dropped": 0}
    own = client is None
    client = client or _client()
    keep, sent, failed = [], 0, 0
    try:
        for t in have:
            status, reason = send_silent(t, client)
            if status == 200:
                sent += 1
            if status == 410 or (status == 400 and reason == "BadDeviceToken"):
                continue
            if status != 200:
                failed += 1
            keep.append(t)
    finally:
        if own:
            client.close()
    dropped = len(have) - len(keep)
    if dropped:
        put_secret(conn, TOKENS_KEY, keep)
    audit(conn, "system", "push.notify", sent=sent, dropped=dropped, failed=failed)
    conn.commit()
    return {"sent": sent, "dropped": dropped, "failed": failed}
