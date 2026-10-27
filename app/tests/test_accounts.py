"""More than one account: the main Google account plus watched Google and Microsoft 365 accounts, whose
mail goes through capture and whose mapped calendars join the agenda."""

import base64
import json
import time
from datetime import date
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from cos import accounts, capture, db, store
from cos.db import get_secret, put_secret
from cos.google import oauth
from cos.google.api import Google
from cos.importer import import_config
from cos.main import create_app
from cos.microsoft import oauth as ms_oauth
from test_brief import FakeClaude, MailboxGoogle, gmail_message
from test_google import REPO_CONFIG, connect_google
from test_microsoft import FakeGraph

WORK = "pat@work.example.org"


def id_token(email: str) -> str:
    part = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    return f"{part({'alg': 'none'})}.{part({'email': email})}.sig"


class TwoGoogles:
    """The main mailbox answers token at-1/at-2; the watched one (signed in with code 'watch-code') at-w."""

    def __init__(self):
        self.main = MailboxGoogle([gmail_message("m1", "Ross <ross@northfield.edu>", "Reserved spot", "Reply if interested.")])
        self.work = MailboxGoogle([gmail_message("m1", "Dean <dean@work.example.org>", "Board packet", "Send the packet by Friday."),
                                   gmail_message("w2", "Dexcom <noreply@email.clarity.dexcom.com>", "Weekly", "health data")])
        self.revoked = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            form = parse_qs(request.content.decode())
            if form.get("code") == ["watch-code"]:
                return httpx.Response(200, json={"access_token": "at-w", "refresh_token": "rt-w", "expires_in": 3600,
                                                 "scope": " ".join(oauth.WATCH_SCOPES), "id_token": id_token(WORK)})
            if form.get("code") == ["main-again"]:
                return httpx.Response(200, json={"access_token": "at-x", "refresh_token": "rt-x", "expires_in": 3600,
                                                 "scope": " ".join(oauth.WATCH_SCOPES),
                                                 "id_token": id_token("pat@example.com")})
        if request.url.path == "/revoke":
            self.revoked.append(parse_qs(request.content.decode())["token"][0])
            return httpx.Response(200)
        if request.headers.get("Authorization") == "Bearer at-w":
            if "/calendars/" in request.url.path:
                assert "/calendars/primary/" in request.url.path
                return httpx.Response(200, json={"items": [{"id": "w-ev", "summary": "Board meeting",
                                                            "start": {"dateTime": "2026-10-20T12:00:00-06:00"},
                                                            "end": {"dateTime": "2026-10-20T13:00:00-06:00"}}]})
            return self.work(request)
        return self.main(request)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("MS_CLIENT_ID", "client-123")
    monkeypatch.delenv("COS_API_TOKEN", raising=False)
    return tmp_path


def test_add_a_watched_google_account_through_the_app(env):
    fake = TwoGoogles()
    http = httpx.Client(transport=httpx.MockTransport(fake))
    with TestClient(create_app(str(env / "cos.db"), http=http)) as c:
        conn = db.connect(env / "cos.db")
        import_config(conn, REPO_CONFIG)
        r = c.get("/oauth/google/start?add=1", follow_redirects=False)
        q = parse_qs(urlparse(r.headers["location"]).query)
        assert "gmail.send" not in q["scope"][0] and "calendar.events" not in q["scope"][0]  # watch-only
        assert "select_account" in q["prompt"][0]
        done = c.get(f"/oauth/google/callback?state={q['state'][0]}&code=watch-code")
        assert WORK in done.text
        listed = c.get("/api/accounts").json()
        main, work = listed["accounts"][0], listed["accounts"][1]
        assert main["role"] == "main" and not main["connected"]  # the main account is separate and untouched
        assert work | {"connectedAt": None} == {
            "provider": "google", "id": "pat-work-example-org", "role": "watch", "email": WORK, "label": WORK,
            "mail": True, "calendars": {WORK: {"id": "primary", "division": "me"}}, "connected": True, "connectedAt": None}
        assert get_secret(conn, "google.tokens/pat-work-example-org")["refresh_token"] == "rt-w"
        assert get_secret(conn, oauth.TOKEN_KEY) is None
        assert not [k for (k,) in conn.execute("SELECT key FROM secrets") if "pending" in k]

        # settings: a bad division is refused; label and mail can change
        assert c.patch("/api/accounts/google/pat-work-example-org",
                       json={"calendars": {"Work": {"id": "primary", "division": "nope"}}}).status_code == 422
        assert c.patch("/api/accounts/google/pat-work-example-org", json={"label": "Work"}).json()["label"] == "Work"
        assert c.patch("/api/accounts/google/nobody", json={"label": "x"}).status_code == 404
        assert c.patch("/api/accounts/slack/x", json={}).status_code == 404

        # removing it revokes Google's access and forgets it
        assert c.delete("/api/accounts/google/pat-work-example-org").json() == {"ok": True}
        assert fake.revoked == ["rt-w"]
        assert [a["role"] for a in c.get("/api/accounts").json()["accounts"]] == ["main"]
        conn.close()


def test_the_main_account_cant_be_added_as_a_watched_one(env):
    fake = TwoGoogles()
    http = httpx.Client(transport=httpx.MockTransport(fake))
    conn = db.connect(env / "cos.db")
    connect_google(conn, fake.main)
    put_secret(conn, oauth.TOKEN_KEY, get_secret(conn, oauth.TOKEN_KEY) | {"account": "pat@example.com"})
    conn.commit()
    with TestClient(create_app(str(env / "cos.db"), http=http)) as c:
        state = parse_qs(urlparse(c.get("/oauth/google/start?add=1", follow_redirects=False).headers["location"]).query)["state"][0]
        r = c.get(f"/oauth/google/callback?state={state}&code=main-again")
        assert r.status_code == 400 and "already the main" in r.text
    assert [a["id"] for a in accounts.list_accounts(conn)] == ["main"]
    assert not [k for (k,) in conn.execute("SELECT key FROM secrets") if k != oauth.TOKEN_KEY]
    conn.close()


@pytest.fixture
def two(env):
    """Main Google connected, plus the watched work account."""
    fake = TwoGoogles()
    conn = db.connect(env / "cos.db")
    import_config(conn, REPO_CONFIG)
    connect_google(conn, fake.main)
    http = httpx.Client(transport=httpx.MockTransport(fake))
    temp = "google.tokens/pending-test"
    oauth.finish(conn, "watch-code", "v", http, key=temp)
    accounts.adopt(conn, "google", temp, WORK)
    yield conn, Google(conn, http), fake
    conn.close()


def test_capture_reads_every_watched_mailbox(two):
    conn, google, _ = two
    claude = FakeClaude({"changes": [], "questions": []})
    result = capture.run(conn, google, client=claude)
    emails = json.loads(claude.calls[0]["messages"][0]["content"])["emails"]
    assert [(m["id"], m.get("account")) for m in emails] == [("m1", None), ("pat-work-example-org:m1", WORK)]
    assert "health data" not in claude.calls[0]["messages"][0]["content"]  # sensitive senders skipped there too
    assert result["errors"] == []

    # mail off for that account: only the main mailbox
    accounts.update(conn, "google", "pat-work-example-org", {"mail": False})
    claude = FakeClaude({"changes": [], "questions": []})
    capture.run(conn, google, client=claude, since=None)
    emails = json.loads(claude.calls[0]["messages"][0]["content"])["emails"]
    assert [m["id"] for m in emails] == ["m1"]


def test_a_watched_account_failing_doesnt_stop_capture(two):
    conn, google, _ = two
    tok = get_secret(conn, "google.tokens/pat-work-example-org")
    put_secret(conn, "google.tokens/pat-work-example-org", tok | {"expires_at": 0, "refresh_token": "revoked"})
    conn.commit()

    def refuse(request):
        if request.url.path == "/token" and parse_qs(request.content.decode()).get("refresh_token") == ["revoked"]:
            return httpx.Response(400, json={"error": "invalid_grant"})
        return two[2](request)

    google = Google(conn, httpx.Client(transport=httpx.MockTransport(refuse)))
    claude = FakeClaude({"changes": [], "questions": []})
    result = capture.run(conn, google, client=claude)
    assert result["messages"] == 1 and "pat@work.example.org" in result["errors"][0]


def test_watched_calendars_join_the_agenda(two):
    conn, google, _ = two
    agenda = google.agenda(1, today=date(2026, 10, 20))
    merged = accounts.merge_calendars(conn, agenda, google.http, date(2026, 10, 20), 1)
    titles = [(e["title"], e.get("account")) for e in merged["divisions"]["me"]["events"]]
    assert ("Board meeting", WORK) in titles
    accounts.update(conn, "google", "pat-work-example-org", {"calendars": {}})
    again = accounts.merge_calendars(conn, google.agenda(1, today=date(2026, 10, 20)), google.http, date(2026, 10, 20), 1)
    assert ("Board meeting", WORK) not in [(e["title"], e.get("account")) for e in again["divisions"]["me"]["events"]]


class TwoGraphs(FakeGraph):
    """Each Microsoft sign-in is a different account; /me answers by token."""

    def __init__(self):
        super().__init__()
        self.n = 0

    def __call__(self, request):
        if request.url.host == "login.microsoftonline.com":
            form = parse_qs(request.content.decode())
            if form["grant_type"] == ["authorization_code"]:
                self.n += 1
                return httpx.Response(200, json={"access_token": f"at-{self.n}", "refresh_token": f"rt-{self.n}",
                                                 "expires_in": 3600, "scope": "Mail.Read Calendars.Read"})
        if request.url.path.endswith("/me"):
            who = {"Bearer at-1": "pat@outlook.com", "Bearer at-2": "pat@school.example.edu"}[request.headers["Authorization"]]
            return httpx.Response(200, json={"userPrincipalName": who})
        return super().__call__(request)


def test_several_microsoft_accounts(env):
    fake = TwoGraphs()
    http = httpx.Client(transport=httpx.MockTransport(fake))
    with TestClient(create_app(str(env / "cos.db"), http=http)) as c:
        for _ in range(2):
            state = parse_qs(urlparse(c.get("/oauth/microsoft/start", follow_redirects=False).headers["location"]).query)["state"][0]
            assert c.get(f"/oauth/microsoft/callback?state={state}&code=good-code").status_code == 200
        ms = [a for a in c.get("/api/accounts").json()["accounts"] if a["provider"] == "microsoft"]
        assert [a["email"] for a in ms] == ["pat@outlook.com", "pat@school.example.edu"]
        assert ms[0]["calendars"] == {"Outlook": {"id": "default", "division": "me"}}
        assert c.get("/api/microsoft/status").json()["connected"]
        # both are read by capture
        conn = db.connect(env / "cos.db")
        clients = accounts.microsoft_clients(conn, http)
        assert [m.account["email"] for m in clients] == ["pat@outlook.com", "pat@school.example.edu"]

        class NoGoogle:
            def search(self, q, limit):
                return []

        claude = FakeClaude({"changes": [], "questions": []})
        capture.run(conn, NoGoogle(), client=claude, microsoft=clients)
        emails = json.loads(claude.calls[0]["messages"][0]["content"])["emails"]
        assert {m["account"] for m in emails} == {"pat@outlook.com", "pat@school.example.edu"}
        # removing one leaves the other
        assert c.delete(f"/api/accounts/microsoft/{ms[0]['id']}").json() == {"ok": True}
        assert [a["email"] for a in c.get("/api/accounts").json()["accounts"] if a["provider"] == "microsoft"] \
            == ["pat@school.example.edu"]
        conn.close()


def test_the_microsoft_account_from_before_is_listed_and_kept(env):
    conn = db.connect(env / "cos.db")
    store.put_setting(conn, "microsoft", {"divisions": {"me": {"Outlook": "default"}}})
    put_secret(conn, ms_oauth.TOKEN_KEY, {"access_token": "at-1", "refresh_token": "rt-1", "expires_at": time.time() + 3600,
                                          "scope": "Mail.Read", "account": "pat@outlook.com"})
    conn.commit()
    listed = [a for a in accounts.list_accounts(conn) if a["provider"] == "microsoft"]
    assert listed[0]["id"] == "pat-outlook-com" and listed[0]["connected"]
    # signing in to it again refreshes the same tokens, not a second copy
    put_secret(conn, "microsoft.tokens/pending-x", {"access_token": "at-9", "refresh_token": "rt-9",
                                                     "expires_at": time.time() + 3600, "scope": "Mail.Read"})
    accounts.adopt(conn, "microsoft", "microsoft.tokens/pending-x", "PAT@outlook.com")
    assert get_secret(conn, ms_oauth.TOKEN_KEY)["refresh_token"] == "rt-9"
    assert len([a for a in accounts.list_accounts(conn) if a["provider"] == "microsoft"]) == 1
    conn.close()
