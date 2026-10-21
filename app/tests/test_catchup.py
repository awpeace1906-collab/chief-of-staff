"""The page's features in the app: decisions, records, email drafts, Move:, re-plan, protected time,
renewals and the week's top 3."""

import json
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from cos import accountability, agent, db, schedule, store
from cos.main import create_app
from test_agent import DENVER, Calendar, ToolClaude, approved, conn, google  # noqa: F401 (fixture)

DECISION = {"title": "Keep the UNM reserved CA-1 spot?", "deadline": "2026-10-23", "context": "UNM asked by Friday",
            "options": [{"id": "keep", "label": "Keep it"}, {"id": "release", "label": "Release it"}]}


# Records and decisions

def test_records_and_a_decision_choice(conn):
    store.put_record(conn, "decision", "unm-ca1", DECISION)
    assert store.list_records(conn, "decision")[0]["status"] == "open"
    with pytest.raises(ValueError):
        store.choose(conn, "unm-ca1", "maybe")
    d = store.choose(conn, "unm-ca1", "release")
    assert d["status"] == "decided" and d["choiceLabel"] == "Release it"
    with pytest.raises(ValueError):
        store.choose(conn, "unm-ca1", "keep")  # decided once
    # the assistant refiling the decision (e.g. the next brief) keeps the owner's choice
    store.put_record(conn, "decision", "unm-ca1", DECISION | {"status": "open"})
    assert store.get_record(conn, "decision", "unm-ca1")["choice"] == "release"
    with pytest.raises(ValueError):
        store.put_record(conn, "nope", "x", {})
    with pytest.raises(ValueError):
        store.put_record(conn, "decision", "bad", {"title": "no options"})


def test_a_decision_becomes_next_steps(conn):
    store.put_record(conn, "decision", "unm-ca1", DECISION)
    store.choose(conn, "unm-ca1", "release")
    claude = ToolClaude(
        [("add_item", {"title": "Confirm release with UNM GME", "division": "me", "due": "2026-10-22"})],
        [("finish", {"actions": "Added a to-do to confirm with UNM GME by Thu."})],
    )
    out = agent.act_on_decisions(conn, google(conn, Calendar()), client=claude)
    assert out == [{"id": "unm-ca1", "actions": "Added a to-do to confirm with UNM GME by Thu."}]
    assert store.get_record(conn, "decision", "unm-ca1")["actions"].startswith("Added")
    assert "Release it" in claude.calls[0]["messages"][0]["content"]
    assert agent.act_on_decisions(conn, google(conn, Calendar()), client=ToolClaude()) == []  # only once


# Email drafts

def draft_proposal(conn, **extra):
    return approved(conn, kind="email", title="Send: reply to Gaby",
                    draft={"to": "gaby@example.org", "subject": "Re: BEAR", "body": "Done, thanks.", "threadId": "t-9"}, **extra)


def test_an_approved_draft_is_sent_only_when_sending_is_on(conn):
    cal = Calendar()
    p = draft_proposal(conn)
    out = agent.execute_approved(conn, google(conn, cal))
    assert out[0]["status"] == "failed" and "sendApprovedDrafts" in out[0]["result"] and cal.sent == []

    store.put_setting(conn, "email", {"sendApprovedDrafts": True})
    p = store.add_proposal(conn, {"day": "2026-10-21", "kind": "email", "title": "Send: reply to Gaby",
                                  "draft": {"to": "gaby@example.org", "subject": "Re: BEAR", "body": "Done.", "threadId": "t-9"}})
    store.update_proposal(conn, p["id"], {"status": "approved", "draftBody": "Done, signed and sent back."})
    out = agent.execute_approved(conn, google(conn, cal))
    assert out == [{"id": p["id"], "status": "done", "result": "Sent to gaby@example.org."}]
    sent = cal.sent[0]
    assert sent["threadId"] == "t-9"
    import base64
    raw = base64.urlsafe_b64decode(sent["raw"]).decode()
    assert "To: gaby@example.org" in raw and "Done, signed and sent back." in raw


def test_drafts_are_validated_and_only_the_owner_edits_them(conn):
    with pytest.raises(ValueError):
        store.add_proposal(conn, {"day": "2026-10-21", "title": "Send: x", "draft": {"subject": "no recipient"}})
    p = store.add_proposal(conn, {"day": "2026-10-21", "title": "Add: x"})
    with pytest.raises(ValueError):
        store.update_proposal(conn, p["id"], {"status": "approved", "draftBody": "hi"})  # no draft to edit


# Move: and re-plan

def test_an_approved_move_changes_the_event(conn):
    cal = Calendar()
    p = approved(conn, calendar="Andrew Work", title="Move: Study block", eventId="ev-7",
                 start="2026-10-21T19:00:00-06:00", end="2026-10-21T20:00:00-06:00", timeZone="America/Denver")
    out = agent.execute_approved(conn, google(conn, cal))
    assert out[0]["status"] == "done" and out[0]["result"].startswith("Moved to Wed Oct 21, 7:00 PM")
    event_id, body = cal.patched[0]
    assert event_id == "ev-7" and body["start"] == {"dateTime": "2026-10-21T19:00:00-06:00", "timeZone": "America/Denver"}
    assert cal.created == []


def test_replan_proposes_moves_and_replies(conn):
    store.put_setting(conn, "schedule", {"division": "me"})
    m = store.add_message(conn, "owner", "Re-plan 2026-10-21 (it's 17:30): ran long", kind="replan",
                          data={"day": "2026-10-21", "at": "17:30", "timeZone": "America/Denver"})
    claude = ToolClaude(
        [("free_time", {"date": "2026-10-21"})],
        [("propose_move", {"calendar": "Andrew Work", "event_id": "ev-7", "title": "Study block",
                           "start": "2026-10-21T19:00", "end": "2026-10-21T20:00", "reason": "Ran long at work"})],
        [("reply", {"text": "Moved your study block to 7pm (waiting on Today). Dinner is still fine."})],
    )
    out = agent.handle_messages(conn, google(conn, Calendar()), client=claude)
    assert out[0]["reply"].startswith("Moved your study block")
    p = store.list_proposals(conn, ("pending",))[0]
    assert p["title"] == "Move: Study block" and p["eventId"] == "ev-7" and p["source"] == "replan"
    assert p["start"] == "2026-10-21T19:00:00-06:00"
    assert "propose_move" in json.dumps(claude.calls[0]["tools"]) and "ran long" in claude.calls[0]["messages"][0]["content"]
    assert store.list_messages(conn, status="new") == []
    assert [x for x in store.list_messages(conn) if x["id"] == m["id"]][0]["kind"] == "replan"


# Protected time, renewals, top 3

def test_protected_windows_are_never_free():
    cfg = schedule.DEFAULTS | {"protect": [{"label": "Dinner with family", "start": "17:30", "end": "19:00"},
                                           {"label": "Sunday rest", "start": "07:00", "end": "21:00", "days": [0]}]}
    agenda = {"timezone": "America/Denver", "divisions": {"me": {"events": []}}}
    wed = schedule.free_slots(agenda, date(2026, 10, 21), cfg, days=0)
    assert [(s["start"][11:16], s["end"][11:16]) for s in wed] == [("07:00", "17:30"), ("19:00", "21:00")]
    assert schedule.free_slots(agenda, date(2026, 10, 25), cfg, days=0) == []  # Sunday
    day = schedule.day(agenda, date(2026, 10, 21), DENVER, cfg, [])
    assert day["protected"] == [{"label": "Dinner with family", "start": "2026-10-21T17:30:00-06:00",
                                 "end": "2026-10-21T19:00:00-06:00"}]


def test_renewals_and_the_weeks_top_three(tmp_path):
    c = db.connect(tmp_path / "cos.db")
    add = lambda title, **kw: store.add_item(c, {"title": title, "direction": "i-owe", "division": "me", **kw})
    add("Renew ACLS", kind="renewal", expires="2026-11-20")      # 30 days: an alert
    add("Renew DEA", kind="renewal", expires="2026-12-01")       # 41 days: listed, quiet
    add("Renew license", kind="renewal", expires="2027-06-01")   # too far off
    add("Mid-point eval", top="2026-10-19")
    add("Old top pick", top="2026-10-12")
    r = accountability.review(c, date(2026, 10, 21))
    assert [(x["title"], x["daysLeft"], x["alert"]) for x in r["renewals"]] == [("Renew ACLS", 30, True), ("Renew DEA", 41, False)]
    assert [x["title"] for x in r["top"]] == ["Mid-point eval"]
    c.close()


# The API

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("COS_API_TOKEN", "k")
    monkeypatch.setenv("COS_SECURE_COOKIE", "0")
    claude = ToolClaude([("finish", {"actions": "Added a to-do to tell UNM."})])
    with TestClient(create_app(str(tmp_path / "cos.db"), client=claude, runner=lambda fn: fn())) as c:
        c.claude = claude
        yield c


def test_api_records_choose_and_replan(client):
    h = {"Authorization": "Bearer k"}
    assert client.put("/api/records/decision/unm-ca1", headers=h, json=DECISION).status_code == 200
    assert client.get("/api/records/trip", headers=h).json() == []
    assert client.get("/api/records/nope", headers=h).status_code == 404
    assert client.post("/api/decisions/unm-ca1/choose", headers=h, json={"choice": "maybe"}).status_code == 409
    d = client.post("/api/decisions/unm-ca1/choose", headers=h, json={"choice": "keep"}).json()
    assert d["status"] == "decided"
    # the follow-up ran straight away (the test runner is synchronous)
    assert client.get("/api/records/decision", headers=h).json()[0]["actions"] == "Added a to-do to tell UNM."
    assert client.post("/api/replan", headers=h, json={"day": "2026-10-21", "what": ""}).status_code == 422
    m = client.post("/api/replan", headers=h, json={"day": "2026-10-21", "at": "17:30", "timeZone": "America/Chicago",
                                                    "what": "ran long"}).json()
    assert m["kind"] == "replan" and m["data"] == {"day": "2026-10-21", "at": "17:30", "timeZone": "America/Chicago"}
    assert m["text"] == "Re-plan 2026-10-21 (it's 17:30): ran long"
    assert client.delete("/api/records/decision/unm-ca1", headers=h).json() == {"ok": True}
