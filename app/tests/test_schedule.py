"""Schedule builder: free time around busy events, and commitments slotted before they're due."""

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from cos import brief, schedule, store
from test_brief import BRIEF, DENVER, FakeClaude, env  # noqa: F401 (fixture)

CFG = schedule.DEFAULTS


def ev(start, end, busy=True, all_day=False):
    return {"title": "x", "start": start, "end": end, "busy": busy, "allDay": all_day}


def agenda(*events):
    return {"timezone": "America/Denver", "divisions": {"me": {"events": list(events)}}}


def test_free_slots_skip_busy_time_and_short_gaps():
    a = agenda(
        ev("2026-10-21T08:00:00-06:00", "2026-10-21T12:00:00-06:00"),
        ev("2026-10-21T12:20:00-06:00", "2026-10-21T13:00:00-06:00"),       # 20-min gap before it: too short
        ev("2026-10-21T15:00:00-06:00", "2026-10-21T16:00:00-06:00", busy=False),  # free time doesn't block
        ev("2026-10-22", "2026-10-23", all_day=True, busy=False),               # an Away-style marker
    )
    slots = schedule.free_slots(a, date(2026, 10, 21), CFG, days=1)
    assert [(s["start"][11:16], s["end"][11:16]) for s in slots] == [
        ("07:00", "08:00"), ("13:00", "21:00"), ("07:00", "21:00")]


def test_free_slots_start_from_now_on_the_quarter_hour():
    now = datetime(2026, 10, 21, 9, 7, tzinfo=DENVER)
    slots = schedule.free_slots(agenda(), date(2026, 10, 21), CFG, days=0, now=now)
    assert slots[0]["start"].startswith("2026-10-21T09:15")


def test_blocks_go_before_the_due_date_late_items_first_window():
    slots = [{"start": "2026-10-21T19:00:00-06:00", "end": "2026-10-21T19:45:00-06:00", "minutes": 45},
             {"start": "2026-10-24T09:00:00-06:00", "end": "2026-10-24T12:00:00-06:00", "minutes": 180}]
    review = {
        "overdue": [{"id": "a", "title": "Sign BEAR agreement", "due": "2026-10-19", "daysLate": 2}],
        "dueSoon": [{"id": "b", "title": "Mid-point eval", "due": "2026-10-22", "daysLate": 0}],
        "undatedPromises": [{"id": "c", "title": "Send slides", "due": None, "daysLate": 0}],
    }
    blocks = schedule.suggest_blocks(review, slots, CFG)
    assert [(b["itemId"], b["start"][5:16]) for b in blocks] == [
        ("a", "10-21T19:00"),  # late: first window
        ("c", "10-24T09:00"),  # undated: next window with room
    ]  # "b" is due the 22nd and nothing free before then fits: no block, so the brief proposes a date


def test_brief_passes_slots_and_blocks(env):
    store.add_item(env.conn, {"title": "Sign BEAR agreement", "direction": "i-owe", "division": "me",
                              "due": "2026-10-19"})
    claude = FakeClaude({"changes": [], "questions": []}, BRIEF)
    brief.run(env.conn, env.google, client=claude, today=datetime(2026, 10, 21, 8, 25, tzinfo=DENVER))
    plan_input = json.loads(claude.calls[1]["messages"][0]["content"])
    assert plan_input["freeSlots"] and plan_input["freeSlots"][0]["start"].startswith("2026-10-21T08:30")
    assert plan_input["suggestedBlocks"][0]["title"] == "Sign BEAR agreement"
