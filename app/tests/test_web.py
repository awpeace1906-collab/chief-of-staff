"""The web app: sign-in, proposals, messages, Ask, and moving data over from the old page."""

import pytest
from fastapi.testclient import TestClient

from cos import db, store
from cos.importer import import_page
from cos.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("COS_API_TOKEN", "secret-key")
    monkeypatch.setenv("COS_SECURE_COOKIE", "0")  # TestClient talks plain http
    with TestClient(create_app(str(tmp_path / "cos.db"))) as c:
        yield c


def auth():
    return {"Authorization": "Bearer secret-key"}


def test_home_needs_sign_in(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert client.get("/api/board").status_code == 401


def test_wrong_key_is_rejected(client):
    r = client.post("/login", data={"key": "nope"}, follow_redirects=False)
    assert r.headers["location"] == "/login?error=1"
    assert "didn't match" in client.get("/login?error=1").text
    assert "cos_session" not in client.cookies


def test_sign_in_sets_cookie_and_opens_app(client):
    r = client.post("/login", data={"key": "secret-key"}, follow_redirects=False)
    assert r.status_code == 303
    cookie = r.cookies.get("cos_session")
    assert cookie and cookie != "secret-key"  # never the raw key
    page = client.get("/")
    assert page.status_code == 200 and "Chief of Staff" in page.text and "/static/app.js" in page.text
    assert client.get("/api/board").status_code == 200  # cookie works for the API
    assert client.get("/static/manifest.webmanifest").json()["display"] == "standalone"
    sw = client.get("/sw.js")
    assert sw.headers["content-type"].startswith("text/javascript") and "/api/" in sw.text  # never caches data
    client.post("/logout")
    assert client.get("/api/board").status_code == 401


def test_proposal_flow(client):
    p = client.post("/api/proposals", headers=auth(), json={
        "day": "2026-10-20", "kind": "calendar", "division": "me", "calendar": "Pat Work",
        "title": "Add: Lakeside interview", "when": "Tue Dec 8, 12:20–3:00pm", "summary": "Not on any calendar"}).json()
    assert p["id"] == "2026-10-20-1" and p["status"] == "pending"
    second = client.post("/api/proposals", headers=auth(), json={"day": "2026-10-20", "summary": "Fix the time"}).json()
    assert second["n"] == 2  # numbered after the day's existing ones

    r = client.patch(f"/api/proposals/{p['id']}", headers=auth(), json={"status": "approved", "changes": "make it 1pm"})
    assert r.json()["status"] == "approved" and r.json()["changes"] == "make it 1pm"
    # the owner can't decide twice, and can't mark things done
    assert client.patch(f"/api/proposals/{p['id']}", headers=auth(), json={"status": "declined"}).status_code == 409
    assert client.patch(f"/api/proposals/{second['id']}", headers=auth(), json={"status": "done"}).status_code == 409
    # the assistant records the outcome
    done = client.patch(f"/api/proposals/{p['id']}?as_assistant=1", headers=auth(),
                        json={"status": "done", "result": "Added at 1pm"}).json()
    assert done["status"] == "done" and done["result"] == "Added at 1pm"
    listed = {x["id"]: x["status"] for x in client.get("/api/proposals?days=10000", headers=auth()).json()}
    assert listed == {"2026-10-20-1": "done", "2026-10-20-2": "pending"}
    assert client.patch("/api/proposals/nope", headers=auth(), json={"status": "approved"}).status_code == 404


def test_messages(client):
    m = client.post("/api/messages", headers=auth(), json={"text": "  Move Lee to remote  "}).json()
    assert m["from"] == "owner" and m["status"] == "new" and m["text"] == "Move Lee to remote"
    client.post("/api/messages", headers=auth(), json={"from": "assistant", "text": "Done."})
    assert [x["id"] for x in client.get("/api/messages?status=new", headers=auth()).json()] == [m["id"]]
    client.patch(f"/api/messages/{m['id']}", headers=auth(), json={"status": "handled"})
    assert client.get("/api/messages?status=new", headers=auth()).json() == []
    assert [x["from"] for x in client.get("/api/messages", headers=auth()).json()] == ["owner", "assistant"]
    assert client.post("/api/messages", headers=auth(), json={"text": " "}).status_code == 422


def test_board_from_the_page(client):
    item = client.post("/api/board", headers=auth(), json={
        "title": "Pick up prescription", "direction": "i-owe", "division": "me", "due": "2026-10-21",
        "source": {"kind": "manual"}}).json()
    client.patch(f"/api/board/{item['id']}", headers=auth(), json={"due": "2026-10-22"})
    client.patch(f"/api/board/{item['id']}", headers=auth(), json={"status": "done"})
    done = client.get("/api/board?status=open,done", headers=auth()).json()
    assert done[0]["due"] == "2026-10-22" and done[0]["status"] == "done"


class FakeText:
    def __init__(self, text):
        self.type, self.text = "text", text


class FakeUsage:
    input_tokens = output_tokens = 10
    cache_read_input_tokens = cache_creation_input_tokens = 0


class FakeClient:
    """Stands in for anthropic.Anthropic: records the request, returns a canned answer."""

    def __init__(self):
        self.calls = []
        self.messages = self
        self.beta = self

    def create(self, **kw):
        self.calls.append(kw)
        r = type("R", (), {})()
        r.content, r.stop_reason, r.stop_details = [FakeText('{"answer": "Two things are due today."}')], "end_turn", None
        r.usage, r.model = FakeUsage(), kw["model"]
        return r


def test_ask_answers_from_the_board(tmp_path, monkeypatch):
    monkeypatch.delenv("COS_API_TOKEN", raising=False)
    fake = FakeClient()
    with TestClient(create_app(str(tmp_path / "cos.db"), client=fake)) as c:
        c.post("/api/board", json={"title": "Finish the mid-point eval", "direction": "deadline", "division": "me"})
        r = c.post("/api/ask", json={"question": "What's due?", "history": [{"from": "owner", "text": "hi"}]})
        assert r.json() == {"answer": "Two things are due today."}
        sent = fake.calls[0]["messages"][0]["content"]
        assert "Finish the mid-point eval" in sent and "What's due?" in sent
        assert c.post("/api/ask", json={"question": ""}).status_code == 422


PAGE = {
    "items": [
        {"id": "walgreens-rx", "title": "Pick up prescription", "due": "2026-10-21", "division": "me",
         "notes": "Ready since Oct 16", "status": "open", "source": "Gmail"},
        {"id": "meal", "title": "Meal prep", "division": "kids", "status": "done", "source": "Added in Juno"},
    ],
    "proposals": [
        {"day": "2026-10-20", "n": 1, "kind": "calendar", "status": "done", "summary": "Lee remote", "result": "8 updated"},
        {"day": "2026-10-20", "n": 3, "kind": "calendar", "status": "pending", "title": "Add: Lakeside interview",
         "when": "Tue Dec 8", "calendar": "Pat Work", "division": "me"},
    ],
    "messages": [{"id": "welcome", "from": "juno", "text": "Hello", "status": "handled", "createdAt": "2026-10-20T01:30:00Z"}],
    "brief": {"day": "2026-10-20", "subject": "Fly home", "markdown": "**Tue:** fly", "updatedAt": "2026-10-20T01:50:00Z"},
    "decisions": [{"id": "northfield-ca1", "title": "Keep the Northfield spot?", "deadline": "2026-10-23", "status": "open",
                   "options": [{"id": "keep", "label": "Keep it"}, {"id": "release", "label": "Release it"}]}],
    "tomorrow": {"day": "2026-10-21", "markdown": "First: clinic 8am"},
    "settings": {"agentName": "Juno"},
}


def test_import_page_is_idempotent(tmp_path):
    conn = db.connect(tmp_path / "cos.db")
    first = import_page(conn, PAGE)
    assert first == {"items": 2, "proposals": 2, "messages": 1, "brief": 1, "records": 2}
    assert import_page(conn, PAGE) == {"items": 0, "proposals": 0, "messages": 0, "brief": 0, "records": 0}
    assert store.get_record(conn, "decision", "northfield-ca1")["status"] == "open"
    assert store.get_record(conn, "card", "tomorrow")["markdown"] == "First: clinic 8am"
    rx = store.get_item(conn, "page-walgreens-rx")
    assert rx["source"] == {"kind": "gmail", "label": "Gmail"} and rx["direction"] == "i-owe"
    assert store.get_item(conn, "page-meal")["status"] == "done"
    assert store.get_proposal(conn, "2026-10-20-3")["title"] == "Add: Lakeside interview"
    assert store.assistant_name(conn) == "Juno"
    # new proposals that day number after the imported ones
    assert store.add_proposal(conn, {"day": "2026-10-20", "summary": "x"})["n"] == 4
    conn.close()
