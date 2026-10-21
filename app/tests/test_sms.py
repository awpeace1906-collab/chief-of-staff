"""Text messaging: webhook auth, owner-only, approve/decline by number, messages answered by text."""

import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from cos import db, sms, store
from cos.db import put_secret
from cos.google import oauth
from cos.main import create_app
from test_agent import Calendar, ToolClaude

OWNER = "+15755550100"


class Carrier(Calendar):
    """Fake Telnyx plus fake Google calendar."""

    def __init__(self):
        super().__init__()
        self.texts = []

    def __call__(self, request):
        if request.url.host == "api.telnyx.com":
            body = json.loads(request.content)
            assert request.headers["Authorization"] == "Bearer tk" and body["to"] == OWNER
            self.texts.append(body["text"])
            return httpx.Response(200, json={"data": {"id": "msg"}})
        return super().__call__(request)


def inbound(text, sender=OWNER):
    return {"data": {"event_type": "message.received", "payload": {"from": {"phone_number": sender}, "text": text}}}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("COS_HOOK_SECRET", "hook-secret")
    monkeypatch.setenv("TELNYX_API_KEY", "tk")
    monkeypatch.delenv("COS_API_TOKEN", raising=False)
    path = tmp_path / "cos.db"
    c = db.connect(path)
    store.put_setting(c, "timezone", "America/Denver")
    store.put_setting(c, "sms", {"provider": "telnyx", "number": "+15755550199", "ownerNumber": "(575) 555-0100"})
    store.put_setting(c, "divisions", {"me": {"calendars": {"Pat Work": "work@group"}}})
    put_secret(c, oauth.TOKEN_KEY, {"access_token": "at-1", "refresh_token": "rt", "expires_at": time.time() + 3600,
                                    "scope": " ".join(oauth.SCOPES)})
    c.commit()
    c.close()
    carrier = Carrier()

    def build(claude):
        return TestClient(create_app(str(path), http=httpx.Client(transport=httpx.MockTransport(carrier)),
                                     client=claude, runner=lambda fn: fn()))  # run follow-ups inline
    return build, carrier, path


def test_wrong_secret_or_provider_is_404(app):
    build, carrier, _ = app
    with build(ToolClaude()) as c:
        assert c.post("/hooks/sms/telnyx/nope", json=inbound("list")).status_code == 404
        assert c.post("/hooks/sms/carrier-pigeon/hook-secret", json=inbound("list")).status_code == 404
    assert carrier.texts == []


def test_strangers_are_ignored(app):
    build, carrier, path = app
    with build(ToolClaude()) as c:
        assert c.post("/hooks/sms/telnyx/hook-secret", json=inbound("list", sender="+12125550000")).json() == {"ok": True}
        assert c.get("/api/messages").json() == []
    assert carrier.texts == []


def test_list_and_approve_by_number(app):
    build, carrier, path = app
    claude = ToolClaude(
        [("create_event", {"calendar": "Pat Work", "title": "Interview", "start": "2026-12-08T12:20",
                           "end": "2026-12-08T15:00", "all_day": False})],
        [("finish", {"outcome": "done", "result": "Added Dec 8."})],
    )
    with build(claude) as c:
        c.post("/api/proposals", json={"day": "2026-10-20", "kind": "calendar", "title": "Add: Interview", "when": "Dec 8"})
        c.post("/api/proposals", json={"day": "2026-10-20", "kind": "calendar", "title": "Add: Dentist"})
        c.post("/hooks/sms/telnyx/hook-secret", json=inbound("list"))
        assert "1. Add: Interview (Dec 8)" in carrier.texts[-1] and "2. Add: Dentist" in carrier.texts[-1]
        c.post("/hooks/sms/telnyx/hook-secret", json=inbound("Approve 1"))
        assert carrier.texts[-2].startswith("Approved: 1. Add: Interview")
        assert carrier.texts[-1] == "✓ Add: Interview: Added Dec 8."  # done, then texted back
        assert carrier.created[0]["summary"] == "Interview"
        c.post("/hooks/sms/telnyx/hook-secret", json=inbound("decline 2 and 7"))
        assert "Declined: 2. Add: Dentist" in carrier.texts[-1] and "No pending proposal 7" in carrier.texts[-1]
        statuses = {p["n"]: p["status"] for p in c.get("/api/proposals?days=10000").json()}
        assert statuses == {1: "done", 2: "declined"}


def test_other_texts_are_answered_by_text(app):
    build, carrier, path = app
    claude = ToolClaude([("reply", {"text": "Nothing due today."})])
    with build(claude) as c:
        c.post("/hooks/sms/telnyx/hook-secret", json=inbound("What's due today?"))
        thread = c.get("/api/messages").json()
        assert [(m["from"], m["channel"], m["status"]) for m in thread] == [("owner", "sms", "handled"), ("assistant", "sms", "handled")]
    assert carrier.texts == ["Nothing due today."]


def test_voipms_inbound_and_split(tmp_path, monkeypatch):
    assert sms.parse_inbound("voipms", {"from": "5755550100", "to": "5755550199", "message": "list"}) == ("5755550100", "list")
    assert sms.parse_inbound("telnyx", {"data": {"event_type": "message.sent"}}) is None
    parts = sms._split("word " * 100, 160)
    assert all(len(p) <= 160 for p in parts) and " ".join(parts).split() == ["word"] * 100


def test_only_texts_the_owner(tmp_path):
    c = db.connect(tmp_path / "x.db")
    store.put_setting(c, "sms", {"provider": "telnyx", "number": "+1", "ownerNumber": OWNER})
    with pytest.raises(ValueError, match="only go to the owner"):
        sms.send(c, "hi", to="+12125550000")
    c.close()


def test_brief_text():
    text = sms.brief_text({"subject": "Juno: fly home", "proposals": [{"n": 1, "title": "Add: Away block"}]}, "https://cos.example")
    assert text.splitlines() == ["Juno: fly home", "1. Add: Away block", 'Reply "approve 1, 3" or "decline 2".', "https://cos.example"]


def test_status_endpoint(app):
    build, carrier, path = app
    with build(ToolClaude()) as c:
        st = c.get("/api/status").json()
        assert st["sms"] == {"configured": True, "provider": "telnyx", "briefByText": False}
        assert st["google"]["canWriteCalendar"] and st["check"]["minute"] == 45 and "triage" in st["ai"]
