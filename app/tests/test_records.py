"""The app's runs file their own records: capture files trips, binders and expenses from mail; the brief files
decisions and reply drafts; the evening run writes the Book and, on Sundays, the week card."""

import json
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from cos import brief, capture, evening, scheduler, store
from test_brief import BRIEF, FakeClaude, env  # noqa: F401 (fixture)

DENVER = ZoneInfo("America/Denver")


def triage(**records):
    return {"changes": [], "questions": [], "trips": [], "binders": [], "expenses": []} | records


TRIP = {"id": "stl-rotation", "title": "St. Louis rotation", "start": "2026-10-25", "end": "2026-11-20", "status": "booked",
        "note": "Return flight not found", "base": "",
        "legs": [{"when": "Sun Oct 25 5:36pm MT", "what": "El Paso to Dallas", "detail": "", "flight": "AA 690",
                  "date": "2026-10-25", "from": "ELP", "to": "DFW"}]}


def test_capture_files_trips_binders_and_expenses(env):
    claude = FakeClaude(
        triage(trips=[TRIP],
               binders=[{"id": "stl-rotation", "title": "CTICU elective", "start": "2026-10-26", "end": "2026-11-20",
                         "sections": [{"h": "Day 1", "lines": ["Badge at 7am"]}]}],
               expenses=[{"id": "aa-bags-2026-10-24", "date": "2026-10-24", "vendor": "American Airlines (bags)",
                          "amount": 45, "group": "St. Louis rotation"},
                         {"id": "Bad Slug!", "date": "2026-10-24", "vendor": "x", "amount": 1, "group": ""}]),
        triage(trips=[TRIP | {"note": "", "base": "Clayton apartment",
                              "legs": [TRIP["legs"][0] | {"flight": "AA 4967", "detail": "rebooked from AA 690"}]}],
               binders=[{"id": "stl-rotation", "title": "CTICU elective", "start": "", "end": "",
                         "sections": [{"h": "Contacts", "lines": ["Coordinator: Alexis"]}]}],
               expenses=[{"id": "aa-bags-again", "date": "2026-10-24", "vendor": "american airlines (bags)",
                          "amount": 45.0, "group": ""}]),
    )
    first = capture.run(env.conn, env.google, client=claude)
    assert first["records"] == {"trips": ["stl-rotation"], "binders": ["stl-rotation"], "expenses": ["aa-bags-2026-10-24"]}
    trip = store.get_record(env.conn, "trip", "stl-rotation")
    assert trip["legs"][0]["flight"] == "AA 690" and "base" not in trip

    # the model sees what's on file, so the next capture updates instead of duplicating
    sent = json.loads(claude.calls[0]["messages"][0]["content"])
    assert sent["trips"] == [] and "recentExpenses" in sent
    capture.run(env.conn, env.google, client=claude, since=datetime(2026, 10, 19, tzinfo=DENVER))
    sent = json.loads(claude.calls[1]["messages"][0]["content"])
    assert sent["trips"][0]["id"] == "stl-rotation" and sent["binders"][0]["headings"] == ["Day 1"]

    trip = store.get_record(env.conn, "trip", "stl-rotation")
    assert trip["note"] == "Return flight not found"  # an empty field keeps the old value
    assert trip["base"] == {"label": "Clayton apartment"}
    assert trip["legs"][0]["flight"] == "AA 4967"
    binder = store.get_record(env.conn, "binder", "stl-rotation")
    assert [s["h"] for s in binder["sections"]] == ["Day 1", "Contacts"] and binder["start"] == "2026-10-26"
    assert [e["id"] for e in store.list_records(env.conn, "expense")] == ["aa-bags-2026-10-24"]  # same receipt: skipped


def test_live_flight_status_survives_a_trip_update(env):
    store.put_record(env.conn, "trip", "stl-rotation", {k: v for k, v in TRIP.items() if k != "base"}
                     | {"legs": [TRIP["legs"][0] | {"live": {"status": "Delayed"}}]})
    capture.apply_records(env.conn, triage(trips=[TRIP | {"legs": [TRIP["legs"][0] | {"detail": "gate A3"}]}]))
    leg = store.get_record(env.conn, "trip", "stl-rotation")["legs"][0]
    assert leg["live"] == {"status": "Delayed"} and leg["detail"] == "gate A3"


DECISION = {"id": "return-flight", "title": "Rebook the return to Sat Nov 21?", "deadline": "2026-10-30",
            "context": "The Friday flight leaves before the last shift ends.", "recommendation": "rebook", "itemId": "",
            "options": [{"id": "rebook", "label": "Rebook to Saturday", "detail": "About $260; no rush after the shift"},
                        {"id": "keep", "label": "Keep Friday", "detail": "Leave the shift early"}]}

DRAFT_PROPOSAL = {"n": 1, "kind": "email", "division": "me", "calendar": "", "title": "Send: reply to Ross",
                  "when": "", "where": "", "change": "", "summary": "Reply owed since Oct 19", "itemId": "",
                  "draft": {"to": "ross@northfield.edu", "subject": "Re: Reserved spot", "body": "Yes, interested.\nPat",
                            "threadId": "t-m1"}}
BLOCK_PROPOSAL = DRAFT_PROPOSAL | {"n": 2, "kind": "calendar", "title": "Add: advance for Thursday's interview",
                                   "draft": {"to": "", "subject": "", "body": "", "threadId": ""}}


def test_the_brief_files_decisions_and_reply_drafts(env):
    claude = FakeClaude(triage(), BRIEF | {"proposals": [DRAFT_PROPOSAL, BLOCK_PROPOSAL],
                                          "decisions": [DECISION, DECISION | {"id": "x", "options": DECISION["options"][:1]}]})
    result = brief.run(env.conn, env.google, client=claude, today=datetime(2026, 10, 20, 8, 25, tzinfo=DENVER))
    assert result["decisions"] == ["return-flight"]  # one option isn't a decision
    d = store.get_record(env.conn, "decision", "return-flight")
    assert d["status"] == "open" and d["recommendation"] == "rebook" and "itemId" not in d
    drafts = {p["n"]: p.get("draft") for p in store.list_proposals(env.conn, ("pending",))}
    assert drafts[1]["to"] == "ross@northfield.edu" and drafts[1]["threadId"] == "t-m1"
    assert drafts[2] is None  # a calendar proposal carries no empty draft
    plan_input = json.loads(claude.calls[1]["messages"][0]["content"])
    assert plan_input["openDecisions"] == [] and "trips" in plan_input
    assert "Situation Room" in claude.calls[1]["system"][0]["text"]

    # the next brief sees it and can't file it twice, even after the principal decides
    store.choose(env.conn, "return-flight", "rebook")
    claude = FakeClaude(triage(), BRIEF | {"decisions": [DECISION | {"recommendation": "keep"}]})
    again = brief.run(env.conn, env.google, client=claude, today=datetime(2026, 10, 21, 8, 25, tzinfo=DENVER))
    assert again["decisions"] == [] and store.get_record(env.conn, "decision", "return-flight")["choice"] == "rebook"
    assert json.loads(claude.calls[1]["messages"][0]["content"])["decidedDecisions"] == ["return-flight"]


def test_the_evening_run_writes_the_book(env):
    store.put_record(env.conn, "trip", "stl-rotation", {k: v for k, v in TRIP.items() if k != "base"}
                     | {"base": {"label": "Clayton apartment"}})
    store.add_item(env.conn, {"title": "Read the WashU policies", "direction": "i-owe", "division": "me",
                              "due": "2026-10-25"})
    claude = FakeClaude({"tomorrow": "**First movement:** badge at 7am CT, from the Clayton apartment.", "week": ""})
    out = evening.run(env.conn, env.google, client=claude, now=datetime(2026, 10, 25, 18, 47, tzinfo=DENVER))
    assert out == {"day": "2026-10-26", "tomorrow": "**First movement:** badge at 7am CT, from the Clayton apartment."}
    card = store.get_record(env.conn, "card", "tomorrow")
    assert card["day"] == "2026-10-26" and card["markdown"].startswith("**First movement:**")
    sent = json.loads(claude.calls[0]["messages"][0]["content"])
    assert sent["whereabouts"]["source"] == "trip" and sent["whereabouts"]["label"] == "Clayton apartment"
    assert [d["title"] for d in sent["due"]] == ["Read the WashU policies"]
    assert sent["trips"][0]["id"] == "stl-rotation"
    # Oct 25 is a Sunday: the weekly review is asked for, with last week's facts
    assert "weekly review" in claude.calls[0]["system"][0]["text"] and "lastWeek" in sent
    assert store.get_record(env.conn, "card", "week") is None  # the model left it empty

    claude = FakeClaude({"tomorrow": "Shift at 6am.", "week": "**Last week:** 3 done."})
    out = evening.run(env.conn, env.google, client=claude, now=datetime(2026, 10, 25, 19, 0, tzinfo=DENVER))
    assert store.get_record(env.conn, "card", "week")["weekOf"] == "2026-10-26"

    claude = FakeClaude({"tomorrow": "Shift at 6am.", "week": "ignored on a weekday"})
    evening.run(env.conn, env.google, client=claude, now=datetime(2026, 10, 27, 18, 47, tzinfo=DENVER))
    assert "weekly review" not in claude.calls[0]["system"][0]["text"]
    assert store.get_record(env.conn, "card", "week")["markdown"] == "**Last week:** 3 done."


def test_the_evening_run_is_scheduled(env, monkeypatch):
    store.put_setting(env.conn, "timezone", "America/Denver")
    early, late = datetime(2026, 10, 26, 18, 0, tzinfo=DENVER), datetime(2026, 10, 26, 18, 50, tzinfo=DENVER)
    assert not scheduler.due(env.conn, early, run="evening") and scheduler.due(env.conn, late, run="evening")
    store.put_setting(env.conn, "evening", {"time": "17:30"})
    assert scheduler.due(env.conn, early, run="evening")
    store.put_setting(env.conn, "evening", {"enabled": False})
    assert not scheduler.due(env.conn, late, run="evening")
    store.put_setting(env.conn, "evening", {})

    calls = []
    monkeypatch.setattr(scheduler, "due", lambda conn, now=None, run="brief": run == "evening")
    monkeypatch.setattr(scheduler.evening, "run", lambda conn, google, client=None, microsoft=None: calls.append(1) or {"day": "x"})
    scheduler.evening_tick(env.conn, threading.Lock(), http=env.google.http)
    assert calls == [1] and store.get_setting(env.conn, "scheduler")["lastEveningDay"]
    # a failure is recorded for Settings and retried later
    monkeypatch.setattr(scheduler.evening, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("model down")))
    assert scheduler.evening_tick(env.conn, threading.Lock(), http=env.google.http) is None
    assert store.get_setting(env.conn, "scheduler")["eveningError"] == "RuntimeError: model down"


@pytest.mark.parametrize("bad", [{"id": "", "title": "x"}, {"id": "ok", "title": ""}])
def test_records_need_a_slug_and_a_title(env, bad):
    filed = capture.apply_records(env.conn, triage(trips=[TRIP | bad]))
    assert filed["trips"] == []
