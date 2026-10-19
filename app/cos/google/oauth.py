"""Google OAuth 2.0 (authorization code + PKCE) and token storage.

The client id and secret come from the environment (GOOGLE_CLIENT_ID,
GOOGLE_CLIENT_SECRET). The refresh token lives in the database's secrets table.
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

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",  # only ever used to email the owner (the brief)
    "openid",
    "email",
]

SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"

DEFAULT_REDIRECT = "http://127.0.0.1:8700/oauth/google/callback"
TOKEN_KEY = "google.tokens"


class GoogleNotConnected(RuntimeError):
    pass


def client_credentials() -> tuple[str, str]:
    cid, secret = os.environ.get("GOOGLE_CLIENT_ID"), os.environ.get("GOOGLE_CLIENT_SECRET")
    if not cid or not secret:
        raise GoogleNotConnected("set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET (see docs/setup/google.md)")
    return cid, secret


def redirect_uri(conn: sqlite3.Connection) -> str:
    return get_setting(conn, "google", {}).get("redirectUri") or os.environ.get("COS_GOOGLE_REDIRECT", DEFAULT_REDIRECT)


def start(conn: sqlite3.Connection) -> tuple[str, str, str]:
    """Return (authorization URL, state, PKCE verifier)."""
    cid, _ = client_credentials()
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri(conn),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",  # always return a refresh token
        "include_granted_scopes": "true",
    }
    return f"{AUTH_URL}?{urlencode(params)}", state, verifier


def finish(conn: sqlite3.Connection, code: str, verifier: str, http: httpx.Client | None = None) -> dict:
    """Exchange the authorization code for tokens and store them."""
    cid, secret = client_credentials()
    http = http or httpx.Client(timeout=20)
    r = http.post(TOKEN_URL, data={
        "code": code,
        "client_id": cid,
        "client_secret": secret,
        "redirect_uri": redirect_uri(conn),
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    })
    _raise_for_token_error(r)
    tok = r.json()
    if "refresh_token" not in tok:
        raise RuntimeError("Google returned no refresh token; remove the app's access at myaccount.google.com/permissions and connect again")
    stored = _store(conn, tok)
    audit(conn, "user", "google.connect", scopes=stored["scope"])
    conn.commit()
    return stored


def access_token(conn: sqlite3.Connection, http: httpx.Client | None = None) -> str:
    """A valid access token, refreshed when it has less than a minute left."""
    tok = get_secret(conn, TOKEN_KEY)
    if not tok:
        raise GoogleNotConnected("Google is not connected; open /oauth/google/start")
    if tok["expires_at"] - time.time() > 60:
        return tok["access_token"]
    cid, secret = client_credentials()
    http = http or httpx.Client(timeout=20)
    r = http.post(TOKEN_URL, data={
        "client_id": cid,
        "client_secret": secret,
        "refresh_token": tok["refresh_token"],
        "grant_type": "refresh_token",
    })
    _raise_for_token_error(r)
    return _store(conn, r.json(), refresh_token=tok["refresh_token"])["access_token"]


def expire(conn: sqlite3.Connection) -> None:
    """Force a refresh on next use (Google rejected the current access token)."""
    tok = get_secret(conn, TOKEN_KEY)
    if tok:
        put_secret(conn, TOKEN_KEY, tok | {"expires_at": 0})
        conn.commit()


def _raise_for_token_error(r: httpx.Response) -> None:
    if r.is_success:
        return
    error = r.json().get("error") if r.headers.get("content-type", "").startswith("application/json") else None
    if error == "invalid_grant":
        raise GoogleNotConnected("Google access expired or was revoked; connect again at /oauth/google/start")
    if error in {"invalid_client", "unauthorized_client"}:
        raise GoogleNotConnected("Google rejected the client id/secret; check GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET")
    r.raise_for_status()


def status(conn: sqlite3.Connection) -> dict:
    tok = get_secret(conn, TOKEN_KEY)
    if not tok:
        return {"connected": False}
    scopes = tok["scope"].split()
    return {"connected": True, "scopes": scopes, "canSend": SEND_SCOPE in scopes,
            "connectedAt": tok.get("connected_at")}


def disconnect(conn: sqlite3.Connection, http: httpx.Client | None = None) -> None:
    tok = get_secret(conn, TOKEN_KEY)
    if tok:
        http = http or httpx.Client(timeout=20)
        http.post(REVOKE_URL, data={"token": tok["refresh_token"]})
    put_secret(conn, TOKEN_KEY, None)
    audit(conn, "user", "google.disconnect")
    conn.commit()


def _store(conn: sqlite3.Connection, tok: dict, refresh_token: str | None = None) -> dict:
    previous = get_secret(conn, TOKEN_KEY) or {}
    stored = {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token") or refresh_token,
        "expires_at": time.time() + int(tok.get("expires_in", 3600)),
        "scope": tok.get("scope") or previous.get("scope", ""),
        "connected_at": previous.get("connected_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    put_secret(conn, TOKEN_KEY, stored)
    conn.commit()
    return stored
