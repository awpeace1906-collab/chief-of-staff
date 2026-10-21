"""Capture, brief, model calls, usage and the scheduler, with fake Google and fake Anthropic."""

import base64
import json
import threading
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from cos import ai, brief, capture, db, llm, scheduler, store
from cos.google.api import Google
from cos.importer import import_config
from cos.main import create_app
from test_google import REPO_CONFIG, FakeGoogle, b64, connect_google

DENVER = ZoneInfo("America/Denver")


def gmail_message(mid, sender, subject, body, labels=("INBOX",)):
    return {"id": mid, "threadId": f"t-{mid}", "labelIds": list(labels), "snippet": body[:40],
            "payload": {"mimeType": "text/plain", "body": {"data": b64(body)}, "headers": [
                {"name": "From", "value": sender}, {"name": "To", "value": "pat@example.com"},
                {"name": "Subject", "value": subject}, {"name": "Date", "value": "Mon, 19 Oct 2026 18:34:34 +0000"}]}}


class MailboxGoogle(FakeGoogle):
    """FakeGoogle with a configurable mailbox and a send endpoint."""

    def __init__(self, messages):
        super().__init__()
        self.messages = {m["id"]: m for m in messages}
        self.sent = []

    def __call__(self, request):
        path = request.url.path
        if path.endswith("/messages/send"):
            raw = json.loads(request.content)["raw"]
            self.sent.append(base64.urlsafe_b64decode(raw).decode())
            return httpx.Response(200, json={"id": "sent-1"})
        if path.endswith("/messages") and request.method == "GET":
            return httpx.Response(200, json={"messages": [{"id": i} for i in self.messages]})
        if "/messages/" in path:
            return httpx.Response(200, json=self.messages[path.rsplit("/", 1)[1]])
        return super().__call__(request)


class FakeClaude:
    """Stands in for anthropic.Anthropic: records requests, answers from a queue."""

    def __init__(self, *answers, stop_reason="end_turn"):
        self.answers = list(answers)
        self.calls = []
        self.stop_reason = stop_reason
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        answer = self.answers.pop(0)
        return SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=json.dumps(answer))],
            stop_reason=self.stop_reason,
            stop_details=SimpleNamespace(category="other") if self.stop_reason == "refusal" else None,
            model=kw["model"],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=500,
                                  cache_creation_input_tokens=0),
        )


def change(op, title, source="m1", item_id=None, evidence=None, division="me"):
    return {"op": op, "itemId": item_id, "title": title, "direction": "i-owe", "division": division,
            "counterparty": "Northfield", "due": "2026-10-21", "dueConfidence": "explicit", "notes": "",
            "evidence": evidence, "sourceRef": source}


BRIEF = {"subject": "Northfield reply due, coverage fine", "markdown": "**You owe**\n- Reply to Northfield", "proposals": [
    {"n": 1, "kind": "email", "summary": "Draft reply to Ross Martinez"}]}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csecret")
    monkeypatch.delenv("COS_API_TOKEN", raising=False)
    conn = db.connect(tmp_path / "cos.db")
    import_config(conn, REPO_CONFIG)
    fake = MailboxGoogle([
        gmail_message("m1", "Ross <rossela@salud.northfield.edu>", "Reserved CA1 spot", "Please reply if interested."),
        gmail_message("m2", "Dexcom <noreply@email.clarity.dexcom.com>", "Weekly glucose", "health data"),
    ])
    connect_google(conn, fake)
    google = Google(conn, httpx.Client(transport=httpx.MockTransport(fake)))
    yield SimpleNamespace(conn=conn, fake=fake, google=google, tmp=tmp_path)
    conn.close()


def test_capture_adds_dedupes_and_never_sends_health_mail(env):
    claude = FakeClaude({"changes": [change("add", "Reply to Northfield about reserved CA1 spot")], "questions": []},
                        {"changes": [change("add", "Reply to Northfield about reserved CA1 spot")], "questions": []})
    first = capture.run(env.conn, env.google, client=claude)
    assert [a["title"] for a in first["added"]] == ["Reply to Northfield about reserved CA1 spot"]
    sent_to_model = json.loads(claude.calls[0]["messages"][0]["content"])
    assert [m["id"] for m in sent_to_model["emails"]] == ["m1"]  # Dexcom (sensitive adapter) never sent
    assert "health data" not in claude.calls[0]["messages"][0]["content"]

    second = capture.run(env.conn, env.google, client=claude)
    assert second["added"] == [] and second["skipped"] == ["Reply to Northfield about reserved CA1 spot"]
    assert len(store.list_items(env.conn)) == 1


def test_capture_closes_only_with_evidence_and_known_ids(env):
    item = store.add_item(env.conn, {"title": "Check in for AA", "direction": "i-owe", "division": "me"})
    claude = FakeClaude({"changes": [
        change("close", "Check in for AA", item_id=item["id"], evidence=None),        # no evidence: kept open
        change("close", "Ghost", item_id="c-0-none", evidence="sent"),                # unknown id: skipped
        change("update", "Check in for AA", item_id=item["id"]),
    ], "questions": ["Was the Walgreens pickup done?"]})
    result = capture.run(env.conn, env.google, client=claude)
    assert result["closed"] == [] and result["skipped"] == ["Check in for AA", "Ghost"]
    assert store.get_item(env.conn, item["id"])["status"] == "open"
    assert store.get_item(env.conn, item["id"])["due"] == "2026-10-21"
    assert result["questions"] == ["Was the Walgreens pickup done?"]


def test_model_request_shape(env):
    claude = FakeClaude({"changes": [], "questions": []}, BRIEF)
    capture.run(env.conn, env.google, client=claude)
    triage = claude.calls[0]
    assert triage["model"] == "claude-haiku-5-5" and "fallbacks" not in triage
    assert triage["output_config"]["effort"] == "low"
    assert triage["output_config"]["format"]["type"] == "json_schema"
    assert triage["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "Dr. Lee" in triage["system"][0]["text"]  # standing rules reach the model

    llm.complete(env.conn, "plan", "s", "u", brief.SCHEMA, client=claude)
    plan = claude.calls[1]
    assert plan["model"] == "claude-opus-5-5" and plan["output_config"]["effort"] == "high"
    assert plan["fallbacks"] == "default" and plan["betas"] == ["server-side-fallback-2026-07-01"]


def test_refusal_and_local_provider(env):
    with pytest.raises(llm.ModelError, match="declined"):
        llm.complete(env.conn, "plan", "s", "u", brief.SCHEMA, client=FakeClaude(BRIEF, stop_reason="refusal"))
    local = json.loads(json.dumps(ai.DEFAULT_AI))
    local["providers"]["local"]["enabled"] = True
    local["routes"]["triage"] = {"provider": "local", "model": "qwen3:8b"}
    store.put_setting(env.conn, "ai", local)
    sent = []

    def local_model(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "qwen3:8b", "usage": {"prompt_tokens": 50, "completion_tokens": 9},
                                         "choices": [{"finish_reason": "stop",
                                                      "message": {"content": '{"changes": [], "questions": []}'}}]})

    out = llm.complete(env.conn, "triage", "s", "u", capture.SCHEMA, http=httpx.Client(transport=httpx.MockTransport(local_model)))
    assert out == {"changes": [], "questions": []}
    assert sent[0]["response_format"]["json_schema"]["schema"] == capture.SCHEMA and sent[0]["messages"][0]["role"] == "system"
    assert any(r["model"] == "qwen3:8b" and r["estimatedUsd"] is None for r in llm.usage_summary(env.conn)["routes"])
    down = httpx.Client(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused"))))
    with pytest.raises(llm.ModelError, match="could not reach the local model"):
        llm.complete(env.conn, "triage", "s", "u", capture.SCHEMA, http=down)


def test_brief_stores_sends_only_to_owner_and_logs_usage(env):
    claude = FakeClaude({"changes": [], "questions": []}, BRIEF)
    result = brief.run(env.conn, env.google, client=claude, send=True,
                       today=datetime(2026, 10, 20, 8, 25, tzinfo=DENVER))
    assert result["subject"] == "Juno: Northfield reply due, coverage fine"
    assert result["sent"] and len(env.fake.sent) == 1
    assert "To: pat@example.com" in env.fake.sent[0] and "Reply to Northfield" in env.fake.sent[0]
    plan_input = json.loads(claude.calls[1]["messages"][0]["content"])
    assert set(plan_input["agenda"]["divisions"]) == {"me", "sam", "kids"}
    assert plan_input["coveragePeople"] == {"kids": ["Casey"]}
    assert brief.latest(env.conn)["sent"]

    usage = llm.usage_summary(env.conn)
    by_route = {r["route"]: r for r in usage["routes"]}
    assert by_route["triage"]["calls"] == 1 and by_route["plan"]["calls"] == 1
    # haiku: 1000*0.10 + 200*0.50 + 500*0.01 = 205 per 1M; opus: 1000*4 + 200*20 + 500*0.2 = 8100 per 1M
    assert usage["estimatedUsd"] == round((205 + 8100) / 1_000_000, 4)


def test_scheduler_runs_once_per_day(env, monkeypatch):
    assert not scheduler.due(env.conn, datetime(2026, 10, 20, 8, 0, tzinfo=DENVER))
    assert scheduler.due(env.conn, datetime(2026, 10, 20, 8, 30, tzinfo=DENVER))
    store.put_setting(env.conn, "scheduler", {"lastBriefDay": "2026-10-20"})
    assert not scheduler.due(env.conn, datetime(2026, 10, 20, 9, 0, tzinfo=DENVER))
    assert scheduler.due(env.conn, datetime(2026, 10, 21, 9, 0, tzinfo=DENVER))

    # a failure is recorded, and the next check inside 15 minutes doesn't retry
    store.put_setting(env.conn, "scheduler", {})
    monkeypatch.setattr(scheduler, "due", lambda conn, now=None: True)
    broken = FakeClaude(stop_reason="refusal")
    broken.answers = [{"changes": [], "questions": []}]
    scheduler.tick(env.conn, threading.Lock(), http=env.google.http, client=broken)
    state = store.get_setting(env.conn, "scheduler")
    assert "declined" in state["lastError"] and state["lastAttempt"] > 0
    monkeypatch.undo()
    assert not scheduler.due(env.conn, datetime(2026, 10, 22, 9, 0, tzinfo=DENVER))


def test_send_failure_keeps_brief_and_counts_as_done(env, monkeypatch):
    from cos.google import oauth
    tok = db.get_secret(env.conn, oauth.TOKEN_KEY)
    db.put_secret(env.conn, oauth.TOKEN_KEY, tok | {"scope": "https://www.googleapis.com/auth/gmail.readonly"})
    claude = FakeClaude({"changes": [], "questions": []}, BRIEF)
    monkeypatch.setattr(scheduler, "due", lambda conn, now=None: True)
    scheduler.tick(env.conn, threading.Lock(), http=env.google.http, client=claude)
    state = store.get_setting(env.conn, "scheduler")
    assert state["lastBriefDay"] and "send permission" in state["lastError"]
    assert brief.latest(env.conn)["subject"].startswith("Juno:") and not brief.latest(env.conn)["sent"]
    assert env.fake.sent == [] and len(claude.calls) == 2  # one capture + one plan, no re-run


def test_scheduler_caps_attempts_per_day(env, monkeypatch):
    monkeypatch.setattr(scheduler, "RETRY_SECONDS", 0)
    at = datetime(2026, 10, 20, 9, 0, tzinfo=DENVER)
    store.put_setting(env.conn, "scheduler", {"attemptsDay": "2026-10-20", "attempts": 2, "lastAttempt": 0})
    assert scheduler.due(env.conn, at)
    store.put_setting(env.conn, "scheduler", {"attemptsDay": "2026-10-20", "attempts": 3, "lastAttempt": 0})
    assert not scheduler.due(env.conn, at)
    assert scheduler.due(env.conn, datetime(2026, 10, 21, 9, 0, tzinfo=DENVER))  # new day resets


def test_api_brief_and_usage(env):
    claude = FakeClaude({"changes": [change("add", "Reply to Northfield")], "questions": []}, BRIEF)
    app = create_app(str(env.tmp / "cos.db"), http=env.google.http, client=claude)
    with TestClient(app) as c:
        assert c.get("/api/brief/latest").status_code == 404
        r = c.post("/api/brief/run")
        assert r.status_code == 200 and r.json()["proposals"][0]["n"] == 1 and not r.json()["sent"]
        assert c.get("/api/brief/latest").json()["subject"].startswith("Juno:")
        posted = c.get("/api/proposals").json()  # the brief's proposals land in the web app
        assert [(x["n"], x["status"], x["summary"]) for x in posted] == [(1, "pending", "Draft reply to Ross Martinez")]
        assert c.get("/api/ai/usage").json()["estimatedUsd"] > 0
        assert c.get("/api/google/status").json()["canSend"]
