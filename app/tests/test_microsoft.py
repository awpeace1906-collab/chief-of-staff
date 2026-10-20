"""Microsoft 365 via Graph: sign-in, token refresh, calendar, mail and To Do, against a fake transport."""

import time
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from cos import capture, db, store
from cos.db import get_secret, put_secret
from cos.main import create_app
from cos.microsoft import oauth
from cos.microsoft.api import Microsoft


class FakeGraph:
    def __init__(self):
        self.token_forms = []
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.host == "login.microsoftonline.com":
            assert url.path == "/consumers/oauth2/v2.0/token"
            form = parse_qs(request.content.decode())
            self.token_forms.append(form)
            if form["grant_type"] == ["authorization_code"]:
                assert form["code"] == ["good-code"] and form["code_verifier"][0] and "client_secret" not in form
                return httpx.Response(200, json={"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600,
                                                 "scope": "Mail.Read Calendars.Read Tasks.Read"})
            if form["refresh_token"] == ["dead"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 3600})
        self.requests.append(request)
        if request.headers["Authorization"] == "Bearer stale":
            return httpx.Response(401, json={})
        path = url.path.removeprefix("/v1.0")
        if path == "/me":
            return httpx.Response(200, json={"displayName": "Andrew", "userPrincipalName": "awpeace1906@gmail.com"})
        if path == "/me/calendars":
            return httpx.Response(200, json={"value": [{"id": "cal-1", "name": "Calendar", "isDefaultCalendar": True,
                                                        "owner": {"address": "awpeace1906@gmail.com"}}]})
        if path.endswith("calendarView"):
            assert request.headers["Prefer"] == 'outlook.timezone="UTC"'
            if "cal-broken" in path:
                return httpx.Response(403, json={})
            return httpx.Response(200, json={"value": [
                {"id": "e1", "subject": "Board meeting", "isAllDay": False, "showAs": "busy",
                 "start": {"dateTime": "2026-10-21T15:00:00.0000000"}, "end": {"dateTime": "2026-10-21T16:00:00.0000000"},
                 "location": {"displayName": "Teams"}, "webLink": "https://outlook.live.com/e1"},
                {"id": "e2", "subject": "Cancelled", "isCancelled": True, "start": {"dateTime": "2026-10-21T17:00:00"},
                 "end": {"dateTime": "2026-10-21T18:00:00"}},
            ]})
        if path in {"/me/messages", "/me/mailFolders/inbox/messages", "/me/mailFolders/sentitems/messages"}:
            sent = "sentitems" in path
            return httpx.Response(200, json={"value": [{
                "id": "m-sent" if sent else "m-1", "conversationId": "conv-1",
                "subject": "Re: lunch" if sent else "Lunch Thursday?",
                "from": {"emailAddress": {"name": "Ryan", "address": "ryan@example.com"}},
                "toRecipients": [{"emailAddress": {"address": "awpeace1906@gmail.com"}}],
                "receivedDateTime": "2026-10-20T14:00:00Z", "bodyPreview": "Can you do lunch",
                "body": {"contentType": "html", "content": "<p>Can you do <b>lunch</b> Thursday?</p><style>x{}</style>"},
                "webLink": "https://outlook.live.com/m-1"}]})
        if path == "/me/todo/lists":
            return httpx.Response(200, json={"value": [{"id": "l1", "displayName": "Tasks"}],
                                             "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/todo/lists?page=2"}
                                  if "page" not in str(url.query) else {"value": [{"id": "l2", "displayName": "Groceries"}]})
        if path.startswith("/me/todo/lists/") and path.endswith("/tasks"):
            assert "status ne 'completed'" in url.params.get("$filter", "")
            lid = path.split("/")[4]
            return httpx.Response(200, json={"value": [{"id": f"t-{lid}", "title": f"Task in {lid}", "status": "notStarted",
                                                        "dueDateTime": {"dateTime": "2026-10-25T00:00:00.0000000"}}]})
        return httpx.Response(404, json={"path": path})


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("MS_CLIENT_ID", "client-123")
    monkeypatch.delenv("MS_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("MS_TENANT", raising=False)
    monkeypatch.delenv("COS_API_TOKEN", raising=False)


@pytest.fixture
def conn(tmp_path, env):
    c = db.connect(tmp_path / "cos.db")
    store.put_setting(c, "timezone", "America/Denver")
    yield c
    c.close()


def connected(conn, fake, token="at-1", expires_in=3600):
    put_secret(conn, oauth.TOKEN_KEY, {"access_token": token, "refresh_token": "rt-1", "expires_at": time.time() + expires_in,
                                       "scope": "Mail.Read", "connected_at": "2026-10-20T00:00:00Z"})
    conn.commit()
    return Microsoft(conn, httpx.Client(transport=httpx.MockTransport(fake)))


def test_needs_client_id(conn, monkeypatch):
    monkeypatch.delenv("MS_CLIENT_ID")
    with pytest.raises(oauth.MicrosoftNotConnected, match="MS_CLIENT_ID"):
        oauth.start(conn)


def test_start_uses_pkce_and_personal_accounts(conn):
    url, state, verifier = oauth.start(conn)
    u = urlparse(url)
    q = parse_qs(u.query)
    assert u.path == "/consumers/oauth2/v2.0/authorize"
    assert q["code_challenge_method"] == ["S256"] and q["state"] == [state] and len(verifier) > 40
    assert "offline_access" in q["scope"][0] and "Calendars.Read" in q["scope"][0]


def test_sign_in_through_the_app(tmp_path, env):
    fake = FakeGraph()
    http = httpx.Client(transport=httpx.MockTransport(fake))
    with TestClient(create_app(str(tmp_path / "cos.db"), http=http)) as c:
        r = c.get("/oauth/microsoft/start", follow_redirects=False)
        state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
        done = c.get(f"/oauth/microsoft/callback?state={state}&code=good-code")
        assert "awpeace1906@gmail.com" in done.text
        st = c.get("/api/microsoft/status").json()
        assert st["connected"] and st["account"] == "awpeace1906@gmail.com"
        assert c.get(f"/oauth/microsoft/callback?state={state}&code=good-code").status_code == 400  # state is single-use
        assert c.get("/api/microsoft/calendars").json()[0]["isDefault"] is True
        c.post("/api/microsoft/disconnect")
        assert c.get("/api/microsoft/status").json() == {"connected": False}
        assert c.get("/api/microsoft/todo").status_code == 409


def test_refresh_rotates_the_refresh_token(conn):
    fake = FakeGraph()
    ms = connected(conn, fake, expires_in=0)
    ms.me()
    assert fake.token_forms[-1]["grant_type"] == ["refresh_token"]
    tok = get_secret(conn, oauth.TOKEN_KEY)
    assert tok["access_token"] == "at-2" and tok["refresh_token"] == "rt-2" and tok["account"] == "awpeace1906@gmail.com"


def test_revoked_refresh_token(conn):
    fake = FakeGraph()
    ms = connected(conn, fake, expires_in=0)
    put_secret(conn, oauth.TOKEN_KEY, get_secret(conn, oauth.TOKEN_KEY) | {"refresh_token": "dead"})
    with pytest.raises(oauth.MicrosoftNotConnected, match="connect again"):
        ms.calendars()


def test_rejected_access_token_refreshes_once(conn):
    fake = FakeGraph()
    ms = connected(conn, fake, token="stale")
    assert ms.calendars()[0]["id"] == "cal-1"
    assert sum(1 for f in fake.token_forms if f["grant_type"] == ["refresh_token"]) == 1


def test_agenda_by_division(conn):
    store.put_setting(conn, "microsoft", {"divisions": {"me": {"Outlook": "default", "Broken": "cal-broken"}}})
    ms = connected(conn, FakeGraph())
    agenda = ms.agenda(3, today=date(2026, 10, 20))
    me = agenda["divisions"]["me"]
    assert [e["title"] for e in me["events"]] == ["Board meeting"]  # cancelled one dropped
    e = me["events"][0]
    assert e["start"] == "2026-10-21T15:00:00+00:00" and e["location"] == "Teams" and e["source"] == "microsoft"
    assert me["errors"] == [{"calendar": "Broken", "status": 403}]


def test_mail_search_strips_html(conn):
    ms = connected(conn, FakeGraph())
    m = ms.search("lunch")[0]
    assert m["body"] == "Can you do lunch Thursday?" and m["from"] == "Ryan <ryan@example.com>" and m["threadId"] == "conv-1"


def test_todo_follows_pages_and_skips_completed(conn):
    ms = connected(conn, FakeGraph())
    tasks = ms.todo()
    assert [(t["list"], t["due"]) for t in tasks] == [("Tasks", "2026-10-25"), ("Groceries", "2026-10-25")]


def test_capture_reads_outlook_too(conn, monkeypatch):
    ms = connected(conn, FakeGraph())
    seen = {}

    class NoGoogle:
        def search(self, q, limit):
            return []

    def fake_complete(c, route, system, user, schema, client=None, **kw):
        seen["user"] = user
        return {"changes": [{"op": "add", "itemId": None, "title": "Reply to Ryan about lunch", "direction": "i-owe",
                             "division": "me", "counterparty": "Ryan", "due": None, "dueConfidence": "none",
                             "notes": "", "evidence": None, "sourceRef": "m-1"}], "questions": []}

    monkeypatch.setattr(capture.llm, "complete", fake_complete)
    result = capture.run(conn, NoGoogle(), microsoft=ms, since=datetime(2026, 10, 19, tzinfo=timezone.utc))
    assert result["messages"] == 2 and "Lunch Thursday?" in seen["user"]
    item = store.list_items(conn)[0]
    assert item["source"]["kind"] == "outlook" and item["source"]["ref"] == "conv-1"
