"""Google OAuth, Calendar and Gmail against a mock transport (no network)."""

import base64
import json
import time
from datetime import date
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from cos import db
from cos.google import oauth
from cos.google.api import Google
from cos.importer import import_config
from cos.main import create_app
from pathlib import Path

REPO_CONFIG = Path(__file__).resolve().parents[2] / "examples" / "memory"


def b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


class FakeGoogle:
    """Answers the handful of Google endpoints the app uses."""

    def __init__(self):
        self.token_calls = []
        self.revoked = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.host == "oauth2.googleapis.com" and url.path == "/token":
            form = parse_qs(request.content.decode())
            self.token_calls.append(form)
            if form["grant_type"] == ["authorization_code"]:
                assert form["code"] == ["good-code"] and form["code_verifier"][0]
                return httpx.Response(200, json={"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600,
                                                 "scope": " ".join(oauth.SCOPES)})
            if form["refresh_token"] == ["revoked"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            if form["client_id"] == ["wrong"]:
                return httpx.Response(401, json={"error": "invalid_client"})
            return httpx.Response(200, json={"access_token": "at-2", "expires_in": 3600})
        if url.path == "/revoke":
            self.revoked.append(parse_qs(request.content.decode())["token"][0])
            return httpx.Response(200)
        if request.headers["Authorization"] == "Bearer stale":
            return httpx.Response(401, json={})
        assert request.headers["Authorization"].startswith("Bearer at-")
        if url.path.endswith("/calendarList"):
            return httpx.Response(200, json={"items": [{"id": "pat@example.com", "summary": "Pat's Calendar"}]})
        if "/calendars/" in url.path and url.path.endswith("/events"):
            if "family" in url.path:
                return httpx.Response(404, json={})
            return httpx.Response(200, json={"items": [
                {"id": "e2", "summary": "Clinic", "start": {"dateTime": "2026-10-20T08:00:00-06:00"}, "end": {"dateTime": "2026-10-20T17:00:00-06:00"}},
                {"id": "e1", "summary": "Call 24", "start": {"date": "2026-10-20"}, "end": {"date": "2026-10-21"}, "transparency": "transparent"},
                {"id": "e3", "summary": "Gone", "status": "cancelled", "start": {"date": "2026-10-20"}},
            ]})
        if url.path.endswith("/messages") and request.method == "GET":
            return httpx.Response(200, json={"messages": [{"id": "m1"}]})
        if "/messages/m1" in url.path:
            return httpx.Response(200, json={
                "id": "m1", "threadId": "t1", "labelIds": ["INBOX"], "snippet": "Please reply &amp; confirm",
                "payload": {"mimeType": "multipart/alternative", "headers": [
                    {"name": "From", "value": "Ross <rossela@salud.northfield.edu>"},
                    {"name": "To", "value": "pat+juno@example.com"},
                    {"name": "Subject", "value": "Reserved CA1 spot"},
                    {"name": "Date", "value": "Mon, 19 Oct 2026 18:34:34 +0000"},
                ], "parts": [
                    {"mimeType": "text/html", "body": {"data": b64("<p>HTML version</p>")}},
                    {"mimeType": "text/plain", "body": {"data": b64("Reply if interested.\n\n\n\nThanks")}},
                ]},
            })
        return httpx.Response(404, json={"unexpected": str(url)})


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csecret")
    monkeypatch.delenv("COS_API_TOKEN", raising=False)
    return FakeGoogle()


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "cos.db")
    import_config(c, REPO_CONFIG)
    yield c
    c.close()


def connect_google(conn, fake):
    url, state, verifier = oauth.start(conn)
    q = parse_qs(urlparse(url).query)
    assert q["code_challenge_method"] == ["S256"] and q["access_type"] == ["offline"]
    assert "gmail.readonly" in q["scope"][0] and "gmail.modify" not in q["scope"][0]
    oauth.finish(conn, "good-code", verifier, httpx.Client(transport=httpx.MockTransport(fake)))


def test_db_file_is_owner_only(tmp_path):
    db.connect(tmp_path / "x.db").close()
    assert (tmp_path / "x.db").stat().st_mode & 0o077 == 0


def test_oauth_connect_refresh_and_revoke(conn, fake):
    http = httpx.Client(transport=httpx.MockTransport(fake))
    assert oauth.status(conn) == {"connected": False}
    connect_google(conn, fake)
    assert oauth.status(conn)["connected"]
    assert oauth.access_token(conn, http) == "at-1"

    tok = db.get_secret(conn, oauth.TOKEN_KEY)
    db.put_secret(conn, oauth.TOKEN_KEY, tok | {"expires_at": time.time() + 10})
    assert oauth.access_token(conn, http) == "at-2"
    assert db.get_secret(conn, oauth.TOKEN_KEY)["refresh_token"] == "rt-1"  # kept across refresh

    oauth.disconnect(conn, http)
    assert fake.revoked == ["rt-1"] and oauth.status(conn) == {"connected": False}


def test_revoked_refresh_token_asks_to_reconnect(conn, fake):
    http = httpx.Client(transport=httpx.MockTransport(fake))
    db.put_secret(conn, oauth.TOKEN_KEY, {"access_token": "x", "refresh_token": "revoked", "expires_at": 0, "scope": ""})
    with pytest.raises(oauth.GoogleNotConnected):
        oauth.access_token(conn, http)


def test_tokens_never_exported(conn, fake):
    from cos.importer import export_all
    connect_google(conn, fake)
    assert "rt-1" not in json.dumps(export_all(conn))


def test_agenda_groups_by_division_and_reports_errors(conn, fake):
    connect_google(conn, fake)
    g = Google(conn, httpx.Client(transport=httpx.MockTransport(fake)))
    agenda = g.agenda(days=1, today=date(2026, 10, 20))
    assert agenda["timezone"] == "America/Denver"
    me = agenda["divisions"]["me"]
    titles = [e["title"] for e in me["events"]]
    assert titles == ["Call 24", "Call 24", "Clinic", "Clinic"]  # two calendars; all-day first; cancelled dropped
    assert me["events"][0]["allDay"] and not me["events"][0]["busy"]
    kids = agenda["divisions"]["kids"]
    assert kids["errors"] == [{"calendar": "Family", "status": 404}]


def test_gmail_message_and_intake(conn, fake):
    connect_google(conn, fake)
    g = Google(conn, httpx.Client(transport=httpx.MockTransport(fake)))
    [m] = g.intake()
    assert m["subject"] == "Reserved CA1 spot"
    assert m["body"] == "Reply if interested.\n\nThanks"  # prefers text/plain, collapses blank lines
    assert m["snippet"] == "Please reply & confirm"


def test_api_oauth_flow_and_errors(tmp_path, fake):
    http = httpx.Client(transport=httpx.MockTransport(fake))
    with TestClient(create_app(str(tmp_path / "cos.db"), http=http), follow_redirects=False) as c:
        assert c.get("/api/calendar/agenda").status_code == 409  # not connected yet
        r = c.get("/oauth/google/start")
        assert r.status_code == 307 and r.headers["location"].startswith(oauth.AUTH_URL)
        state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
        assert c.get("/oauth/google/callback", params={"state": "forged", "code": "good-code"}).status_code == 400
        assert c.get("/oauth/google/callback", params={"state": state, "code": "good-code"}).status_code == 200
        assert c.get("/oauth/google/callback", params={"state": state, "code": "good-code"}).status_code == 400  # one use
        assert c.get("/api/google/status").json()["connected"]
        assert c.get("/api/calendar/calendars").json()[0]["name"] == "Pat's Calendar"
        assert c.get("/api/mail/intake").status_code == 409  # fresh db has no intake address


def test_oauth_start_needs_token_when_set(tmp_path, fake, monkeypatch):
    monkeypatch.setenv("COS_API_TOKEN", "s3cret")
    with TestClient(create_app(str(tmp_path / "cos.db")), follow_redirects=False) as c:
        assert c.get("/oauth/google/start").status_code == 401
        assert c.get("/oauth/google/start", params={"token": "s3cret"}).status_code == 307


def test_missing_client_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("COS_API_TOKEN", raising=False)
    with TestClient(create_app(str(tmp_path / "cos.db"))) as c:
        r = c.get("/oauth/google/start")
        assert r.status_code == 409 and "GOOGLE_CLIENT_ID" in r.json()["detail"]


def test_events_sort_by_real_time_across_offsets():
    from zoneinfo import ZoneInfo
    from cos.google.api import _sort_key
    tz = ZoneInfo("America/Denver")
    pacific_730 = {"allDay": False, "start": "2026-10-20T07:30:00-08:00"}  # 15:30Z
    mountain_800 = {"allDay": False, "start": "2026-10-20T08:00:00-06:00"}  # 14:00Z
    all_day = {"allDay": True, "start": "2026-10-20"}
    assert sorted([pacific_730, mountain_800, all_day], key=lambda e: _sort_key(e, tz)) == [all_day, mountain_800, pacific_730]


def test_rejected_access_token_refreshes_once(conn, fake):
    http = httpx.Client(transport=httpx.MockTransport(fake))
    db.put_secret(conn, oauth.TOKEN_KEY, {"access_token": "stale", "refresh_token": "rt-1", "expires_at": time.time() + 3600, "scope": ""})
    assert Google(conn, http).calendars()[0]["id"] == "pat@example.com"
    assert db.get_secret(conn, oauth.TOKEN_KEY)["access_token"] == "at-2"


def test_wrong_client_credentials_message(conn, fake, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "wrong")
    http = httpx.Client(transport=httpx.MockTransport(fake))
    db.put_secret(conn, oauth.TOKEN_KEY, {"access_token": "x", "refresh_token": "rt-1", "expires_at": 0, "scope": ""})
    with pytest.raises(oauth.GoogleNotConnected, match="GOOGLE_CLIENT_ID"):
        oauth.access_token(conn, http)
