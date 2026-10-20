"""The assistant between briefs: approved proposals, messages, the hourly check, error notices."""

import json
import threading
import time
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from cos import agent, db, scheduler, store
from cos.db import put_secret
from cos.google import oauth
from cos.google.api import Google
from cos.main import create_app

DENVER = ZoneInfo("America/Denver")
SCOPES = " ".join(oauth.SCOPES)


class Calendar:
    """Fake Google: one calendar's events, create/patch, and the send endpoint."""

    def __init__(self, events=()):
        self.events = list(events)
        self.created, self.patched, self.sent = [], [], []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/messages/send"):
            self.sent.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "s1"})
        if path.endswith("/messages") and request.method == "GET":
            return httpx.Response(200, json={})
        if path.endswith("/events") and request.method == "POST":
            assert request.url.params["sendUpdates"] == "none"
            body = json.loads(request.content) | {"id": f"new-{len(self.created)}", "htmlLink": "https://cal/x"}
            self.created.append(body)
            return httpx.Response(200, json=body)
        if "/events/" in path and request.method == "PATCH":
            body = json.loads(request.content)
            self.patched.append((path.rsplit("/", 1)[1], body))
            return httpx.Response(200, json={"id": path.rsplit("/", 1)[1], "summary": "x", "start": {"date": "2026-10-25"},
                                             "end": {"date": "2026-10-26"}})
        if path.endswith("/events"):
            return httpx.Response(200, json={"items": self.events})
        return httpx.Response(404, json={})


class ToolClaude:
    """Fake Anthropic that plays back a script of tool calls / texts and records what it was sent."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(json.loads(json.dumps(kw, default=str)))
        turn = self.turns.pop(0)
        blocks = [SimpleNamespace(type="tool_use", id=f"tu{i}", name=name, input=inp) for i, (name, inp) in enumerate(turn)] \
            if isinstance(turn, list) else [SimpleNamespace(type="text", text=turn)]
        return SimpleNamespace(content=blocks, stop_reason="tool_use" if isinstance(turn, list) else "end_turn",
                               stop_details=None, model=kw["model"],
                               usage=SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=0,
                                                     cache_creation_input_tokens=0))


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "cos.db")
    store.put_setting(c, "timezone", "America/Denver")
    store.put_setting(c, "assistant", {"name": "Tower", "email": "awpeace1906@gmail.com"})
    store.put_setting(c, "divisions", {"me": {"label": "Me", "calendars": {"Andrew Work": "work@group", "Andrew's Calendar": "me@gmail"}}})
    put_secret(c, oauth.TOKEN_KEY, {"access_token": "at-1", "refresh_token": "rt", "expires_at": time.time() + 3600,
                                    "scope": SCOPES})
    c.commit()
    yield c
    c.close()


def google(conn, cal):
    return Google(conn, httpx.Client(transport=httpx.MockTransport(cal)))


def approved(conn, **p):
    prop = store.add_proposal(conn, {"day": "2026-10-20", "kind": "calendar", "division": "me", **p})
    return store.update_proposal(conn, prop["id"], {"status": "approved", **({"changes": p["changes"]} if p.get("changes") else {})})


def test_executes_an_approved_calendar_proposal(conn):
    cal = Calendar()
    p = approved(conn, calendar="Andrew Work", title="Add: Tucson interview", when="Tue Dec 8, 12:20–3:00pm MT")
    claude = ToolClaude(
        [("find_events", {"calendar": "Andrew Work", "start_date": "2026-12-08", "end_date": "2026-12-08"})],
        [("create_event", {"calendar": "Andrew Work", "title": "Tucson interview", "start": "2026-12-08T12:20",
                           "end": "2026-12-08T15:00", "all_day": False})],
        [("finish", {"outcome": "done", "result": "Added Tue Dec 8, 12:20–3:00pm on Andrew Work."})],
    )
    out = agent.execute_approved(conn, google(conn, cal), client=claude)
    assert out == [{"id": p["id"], "status": "done", "result": "Added Tue Dec 8, 12:20–3:00pm on Andrew Work."}]
    assert cal.created[0]["start"] == {"dateTime": "2026-12-08T12:20", "timeZone": "America/Denver"}
    assert store.get_proposal(conn, p["id"])["status"] == "done"
    # the model saw the proposal, and the tool results came back to it
    assert "Tucson interview" in claude.calls[0]["messages"][0]["content"]
    assert claude.calls[1]["messages"][-1]["content"][0]["type"] == "tool_result"


def test_all_day_block_end_is_inclusive(conn):
    cal = Calendar()
    approved(conn, calendar="Andrew Work", title="Add: Away block", when="Oct 25 to Nov 21")
    claude = ToolClaude(
        [("create_event", {"calendar": "Andrew Work", "title": "Away: St. Louis", "start": "2026-10-25",
                           "end": "2026-11-21", "all_day": True})],
        [("finish", {"outcome": "done", "result": "ok"})],
    )
    agent.execute_approved(conn, google(conn, cal), client=claude)
    assert cal.created[0]["start"] == {"date": "2026-10-25"} and cal.created[0]["end"] == {"date": "2026-11-22"}


def test_held_by_the_owners_changes(conn):
    p = approved(conn, calendar="Andrew's Calendar", title="Fix: Sumulong time", changes="Hold this")
    claude = ToolClaude([("finish", {"outcome": "held", "result": "Held, per your note. Nothing changed."})])
    agent.execute_approved(conn, google(conn, Calendar()), client=claude)
    after = store.get_proposal(conn, p["id"])
    assert after["status"] == "declined" and "Held" in after["result"]
    assert "Hold this" in claude.calls[0]["messages"][0]["content"]


def test_tool_errors_go_back_to_the_model(conn):
    approved(conn, calendar="Nope", title="Add: x")
    claude = ToolClaude(
        [("create_event", {"calendar": "Nope", "title": "x", "start": "2026-10-21T10:00", "end": "2026-10-21T11:00", "all_day": False})],
        [("finish", {"outcome": "failed", "result": "There's no calendar called Nope."})],
    )
    out = agent.execute_approved(conn, google(conn, Calendar()), client=claude)
    assert out[0]["status"] == "failed"
    err = claude.calls[1]["messages"][-1]["content"][0]
    assert err["is_error"] and "unknown calendar" in err["content"]


def test_email_proposals_are_not_carried_out_yet(conn):
    approved(conn, title="Send: reply to Ryan", kind="email")
    out = agent.execute_approved(conn, google(conn, Calendar()), client=ToolClaude())
    assert out[0]["status"] == "failed" and "can't be carried out" in out[0]["result"]


def test_without_calendar_write_permission_proposals_stay_approved(conn):
    put_secret(conn, oauth.TOKEN_KEY, {"access_token": "at-1", "refresh_token": "rt", "expires_at": time.time() + 3600,
                                       "scope": SCOPES.replace("https://www.googleapis.com/auth/calendar.events", "")})
    conn.commit()
    p = approved(conn, calendar="Andrew Work", title="Add: x")
    claude = ToolClaude(
        [("create_event", {"calendar": "Andrew Work", "title": "x", "start": "2026-10-21T10:00", "end": "2026-10-21T11:00", "all_day": False})],
        [("finish", {"outcome": "failed", "result": "no permission"})],
    )
    agent.execute_approved(conn, google(conn, Calendar()), client=claude)
    # the model saw the permission error; since it reported failure, the proposal shows failed with the reason
    assert "write permission" in claude.calls[1]["messages"][-1]["content"][0]["content"]
    assert store.get_proposal(conn, p["id"])["status"] == "failed"


def test_message_can_edit_the_list_and_proposes_the_rest(conn):
    store.add_item(conn, {"id": "c-rx", "title": "Pick up prescription", "direction": "i-owe", "division": "me"})
    m = store.add_message(conn, "owner", "Got the Rx. Also put Micah's dentist on the family calendar Friday 3pm")
    claude = ToolClaude(
        [("update_item", {"id": "c-rx", "status": "done"}),
         ("add_proposal", {"kind": "calendar", "division": "kids", "calendar": "Family", "title": "Add: Micah dentist",
                           "when": "Fri Oct 23, 3:00pm", "summary": "You asked"})],
        [("reply", {"text": "Marked the Rx done. The dentist is waiting for your OK on the Today tab."})],
    )
    out = agent.handle_messages(conn, google(conn, Calendar()), client=claude)
    assert out[0]["reply"].startswith("Marked the Rx done")
    assert store.get_item(conn, "c-rx")["status"] == "done"
    assert store.list_proposals(conn, ("pending",))[0]["title"] == "Add: Micah dentist"
    thread = store.list_messages(conn)
    assert [(x["from"], x["status"]) for x in thread] == [("owner", "handled"), ("assistant", "handled")]
    # the message agent has no calendar-writing tools
    names = {t["name"] for t in claude.calls[0]["tools"]}
    assert "create_event" not in names and "add_proposal" in names and m["text"] in claude.calls[0]["messages"][0]["content"]


def test_failed_message_stays_new(conn):
    store.add_message(conn, "owner", "hello")

    report = agent.check(conn, google(conn, Calendar()), client=ToolClaude("not a tool call"), capture_mail=False)
    assert report["messages"][0]["reply"] == "not a tool call"  # a plain answer still counts as the reply
    store.add_message(conn, "owner", "again")
    report = agent.check(conn, google(conn, Calendar()), client=ToolClaude(), capture_mail=False)  # empty script → error
    assert report["errors"] and store.list_messages(conn, status="new")[0]["text"] == "again"


def test_check_slot_runs_once_per_hour_in_the_window(conn):
    at = lambda h, m: datetime(2026, 10, 20, h, m, tzinfo=DENVER)
    assert scheduler.check_slot(conn, at(6, 44)) is None
    assert scheduler.check_slot(conn, at(6, 45)) == "2026-10-20T06"
    store.put_setting(conn, "scheduler", {"lastCheckSlot": "2026-10-20T06"})
    assert scheduler.check_slot(conn, at(6, 59)) is None
    assert scheduler.check_slot(conn, at(7, 50)) == "2026-10-20T07"
    assert scheduler.check_slot(conn, at(22, 45)) is None
    store.put_setting(conn, "check", {"enabled": False})
    assert scheduler.check_slot(conn, at(9, 45)) is None


def test_errors_email_the_owner_at_most_every_three_hours(conn):
    cal = Calendar()
    g = google(conn, cal)
    assert scheduler.notify_errors(conn, g, ["proposal 2026-10-20-1: no permission"])
    assert not scheduler.notify_errors(conn, g, ["again"])
    assert len(cal.sent) == 1


def test_check_endpoint(tmp_path, monkeypatch):
    monkeypatch.delenv("COS_API_TOKEN", raising=False)
    path = tmp_path / "cos.db"
    c0 = db.connect(path)
    store.put_setting(c0, "timezone", "America/Denver")
    put_secret(c0, oauth.TOKEN_KEY, {"access_token": "at-1", "refresh_token": "rt", "expires_at": time.time() + 3600, "scope": SCOPES})
    c0.commit()
    c0.close()
    cal = Calendar()
    with TestClient(create_app(str(path), http=httpx.Client(transport=httpx.MockTransport(cal)), client=ToolClaude())) as c:
        r = c.post("/api/check/run").json()
        assert r["approvals"] == [] and r["messages"] == [] and r["capture"]["messages"] == 0 and r["errors"] == []


def test_email_to_the_intake_address_becomes_a_message_and_gets_an_emailed_reply(conn):
    store.put_setting(conn, "google", {"intakeAddress": "awpeace1906+tower@gmail.com"})

    class Mailbox(Calendar):
        def __call__(self, request):
            p = request.url.path
            if p.endswith("/messages") and request.method == "GET":
                assert "from:awpeace1906@gmail.com" in request.url.params["q"]
                return httpx.Response(200, json={"messages": [{"id": "g1"}]})
            if p.endswith("/messages/g1"):
                import base64
                body = base64.urlsafe_b64encode(b"Is Micah covered Nov 7?").decode()
                return httpx.Response(200, json={"id": "g1", "threadId": "t1", "labelIds": ["INBOX"], "snippet": "",
                    "payload": {"mimeType": "text/plain", "body": {"data": body}, "headers": [
                        {"name": "From", "value": "awpeace1906@gmail.com"}, {"name": "Subject", "value": "Coverage"}]}})
            return super().__call__(request)

    box = Mailbox()
    g = google(conn, box)
    assert agent.intake_messages(conn, g) == 1
    assert agent.intake_messages(conn, g) == 0  # seen once only
    claude = ToolClaude([("reply", {"text": "Not yet: no Tiffany on Nov 7."})])
    agent.handle_messages(conn, g, client=claude)
    assert len(box.sent) == 1  # the reply went back by email too
    import base64
    assert "Re: Coverage" in base64.urlsafe_b64decode(box.sent[0]["raw"]).decode()


def test_brain_sync_pulls_pushes_and_respects_deleted(conn, monkeypatch):
    from cos import brain
    monkeypatch.setenv("BRAIN_GIST_TOKEN", "t")
    gist = {"entries": [
        {"id": "tower-1-aaaa", "content": "Jason goes remote on rotation", "tags": ["tower", "rule"], "timestamp": "2026-10-19T00:00:00Z"},
        {"id": "note-1", "content": "Andrew's own note", "tags": ["personal"], "timestamp": "2026-10-19T00:00:00Z"},
        {"id": "tower-2-bbbb", "content": "deleted one", "tags": ["tower", "rule"], "timestamp": "2026-10-19T00:00:00Z"},
    ], "deleted": ["tower-2-bbbb", "tower-9-dead"]}
    patched = []

    def github(request):
        if request.url.path == "/gists":
            return httpx.Response(200, json=[{"id": "g42", "files": {"brain-data.json": {}}}])
        if request.method == "PATCH":
            patched.append(json.loads(json.loads(request.content)["files"]["brain-data.json"]["content"]))
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"files": {"brain-data.json": {"content": json.dumps(gist)}}})

    store.upsert_rule(conn, {"id": "tower-3-cccc", "kind": "preference", "content": "Silent hourly checks"})
    store.upsert_rule(conn, {"id": "tower-9-dead", "kind": "rule", "content": "was deleted in Brain"})
    conn.commit()
    http = httpx.Client(transport=httpx.MockTransport(github))
    assert brain.sync(conn, http) == {"pulled": 1, "pushed": 1}
    after = patched[0]
    assert [e["id"] for e in after["entries"]] == ["tower-1-aaaa", "note-1", "tower-2-bbbb", "tower-3-cccc"]  # nothing dropped
    assert after["deleted"] == gist["deleted"] and after["entries"][3]["source"] == "tower"
    assert store.get_setting(conn, "brain")["gistId"] == "g42"
    assert brain.sync(conn, http)["pushed"] == 0  # already there now
