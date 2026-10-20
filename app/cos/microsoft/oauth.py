"""Microsoft identity platform OAuth 2.0 (authorization code + PKCE) and token storage.

Works with personal Microsoft accounts (Outlook.com, Microsoft 365 Personal/Family,
including ones signed in with a Gmail address) and, with MS_TENANT=common, work or
school accounts too. MS_CLIENT_ID comes from an app registration
(docs/setup/microsoft.md); MS_CLIENT_SECRET is only needed for a "Web" platform
registration. Microsoft rotates refresh tokens, so each refresh stores the new one.
"""

import base64
import hashlib
import os
import secrets
import sqlite3
import time
from urllib.parse import urlencode

import httpx

from ..db import audit, get_secret, put_secret
from ..store import get_setting

LOGIN = "https://login.microsoftonline.com"

SCOPES = [
    "offline_access",
    "openid",
    "email",
    "User.Read",
    "Mail.Read",
    "Calendars.Read",
    "Tasks.Read",   # Microsoft To Do
    "Files.Read",   # OneDrive, for documents the brief points at
]

DEFAULT_REDIRECT = "http://localhost:8700/oauth/microsoft/callback"
TOKEN_KEY = "microsoft.tokens"


class MicrosoftNotConnected(RuntimeError):
    pass


def tenant() -> str:
    # consumers: personal accounts only; common: personal + work/school; or a tenant id
    return os.environ.get("MS_TENANT", "consumers")


def client_id() -> str:
    cid = os.environ.get("MS_CLIENT_ID")
    if not cid:
        raise MicrosoftNotConnected("set MS_CLIENT_ID (see docs/setup/microsoft.md)")
    return cid


def _client_auth() -> dict:
    data = {"client_id": client_id()}
    if os.environ.get("MS_CLIENT_SECRET"):
        data["client_secret"] = os.environ["MS_CLIENT_SECRET"]
    return data


def redirect_uri(conn: sqlite3.Connection) -> str:
    return (get_setting(conn, "microsoft", {}).get("redirectUri")
            or os.environ.get("COS_MS_REDIRECT", DEFAULT_REDIRECT))


def start(conn: sqlite3.Connection) -> tuple[str, str, str]:
    """Return (authorization URL, state, PKCE verifier)."""
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {
        "client_id": client_id(),
        "redirect_uri": redirect_uri(conn),
        "response_type": "code",
        "response_mode": "query",
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{LOGIN}/{tenant()}/oauth2/v2.0/authorize?{urlencode(params)}", state, verifier


def finish(conn: sqlite3.Connection, code: str, verifier: str, http: httpx.Client | None = None) -> dict:
    http = http or httpx.Client(timeout=20)
    r = http.post(f"{LOGIN}/{tenant()}/oauth2/v2.0/token", data=_client_auth() | {
        "code": code,
        "redirect_uri": redirect_uri(conn),
        "grant_type": "authorization_code",
        "code_verifier": verifier,
        "scope": " ".join(SCOPES),
    })
    _raise_for_token_error(r)
    tok = r.json()
    if "refresh_token" not in tok:
        raise RuntimeError("Microsoft returned no refresh token; check that offline_access is allowed and connect again")
    stored = _store(conn, tok)
    audit(conn, "user", "microsoft.connect", scopes=stored["scope"])
    conn.commit()
    return stored


def access_token(conn: sqlite3.Connection, http: httpx.Client | None = None) -> str:
    tok = get_secret(conn, TOKEN_KEY)
    if not tok:
        raise MicrosoftNotConnected("Microsoft 365 is not connected; open /oauth/microsoft/start")
    if tok["expires_at"] - time.time() > 60:
        return tok["access_token"]
    http = http or httpx.Client(timeout=20)
    r = http.post(f"{LOGIN}/{tenant()}/oauth2/v2.0/token", data=_client_auth() | {
        "refresh_token": tok["refresh_token"],
        "grant_type": "refresh_token",
        "scope": " ".join(SCOPES),
    })
    _raise_for_token_error(r)
    return _store(conn, r.json(), refresh_token=tok["refresh_token"])["access_token"]


def expire(conn: sqlite3.Connection) -> None:
    tok = get_secret(conn, TOKEN_KEY)
    if tok:
        put_secret(conn, TOKEN_KEY, tok | {"expires_at": 0})
        conn.commit()


def status(conn: sqlite3.Connection) -> dict:
    tok = get_secret(conn, TOKEN_KEY)
    if not tok:
        return {"connected": False}
    return {"connected": True, "account": tok.get("account"), "scopes": tok["scope"].split(),
            "connectedAt": tok.get("connected_at")}


def disconnect(conn: sqlite3.Connection) -> None:
    """Forget the tokens. (Microsoft has no revoke endpoint for personal accounts;
    remove the app at account.live.com/consent/Manage to revoke it fully.)"""
    put_secret(conn, TOKEN_KEY, None)
    audit(conn, "user", "microsoft.disconnect")
    conn.commit()


def remember_account(conn: sqlite3.Connection, account: str | None) -> None:
    tok = get_secret(conn, TOKEN_KEY)
    if tok and account:
        put_secret(conn, TOKEN_KEY, tok | {"account": account})
        conn.commit()


def _raise_for_token_error(r: httpx.Response) -> None:
    if r.is_success:
        return
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    error = body.get("error")
    if error == "invalid_grant":
        raise MicrosoftNotConnected("Microsoft access expired or was revoked; connect again at /oauth/microsoft/start")
    if error in {"invalid_client", "unauthorized_client"}:
        raise MicrosoftNotConnected(f"Microsoft rejected the app registration ({body.get('error_description', error)[:200]}); "
                                    "check MS_CLIENT_ID, MS_CLIENT_SECRET and MS_TENANT")
    r.raise_for_status()


def _store(conn: sqlite3.Connection, tok: dict, refresh_token: str | None = None) -> dict:
    previous = get_secret(conn, TOKEN_KEY) or {}
    stored = {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token") or refresh_token,  # rotated on each refresh
        "expires_at": time.time() + int(tok.get("expires_in", 3600)),
        "scope": tok.get("scope") or previous.get("scope", ""),
        "account": previous.get("account"),
        "connected_at": previous.get("connected_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    put_secret(conn, TOKEN_KEY, stored)
    conn.commit()
    return stored
