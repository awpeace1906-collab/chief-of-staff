"""Accountability: what the brief must keep in front of the owner, and promises from sent mail."""

import json
from datetime import date, datetime

from cos import accountability, brief, capture, db, store
from test_brief import BRIEF, DENVER, FakeClaude, change, env, gmail_message  # noqa: F401 (fixture)

TODAY = date(2026, 10, 21)


def item(conn, title, **kw):
    return store.add_item(conn, {"title": title, "direction": "i-owe", "division": "me", **kw})


def ids(entries):
    return [e["title"] for e in entries]


def test_review_sorts_the_board(tmp_path):
    conn = db.connect(tmp_path / "cos.db")
    item(conn, "Sign BEAR agreement", due="2026-10-19")
    item(conn, "Mid-point eval", due="2026-10-23")
    item(conn, "Book photos", due="2026-11-30")
    item(conn, "Send slides", promise=True, createdAt="2026-10-15T12:00:00Z")
    item(conn, "Send notes", promise=True, createdAt="2026-10-20T12:00:00Z")  # too new to chase
    item(conn, "Interview details from Veronica", direction="owed-to-me", due="2026-10-18")
    item(conn, "Reply to Gaby", status="snoozed", snoozedUntil="2026-10-21", due="2026-10-20")
    item(conn, "Later thing", status="snoozed", snoozedUntil="2026-10-30")
    done = item(conn, "Finished", due="2026-10-01")
    store.update_item(conn, done["id"], {"status": "done"})

    r = accountability.review(conn, TODAY)
    assert ids(r["overdue"]) == ["Sign BEAR agreement", "Reply to Gaby"]  # the snooze ended today
    assert r["overdue"][0]["daysLate"] == 2
    assert ids(r["dueSoon"]) == ["Mid-point eval"]
    assert ids(r["undatedPromises"]) == ["Send slides"]
    assert ids(r["waitingLate"]) == ["Interview details from Veronica"]
    assert len(r["woke"]) == 1 and r["stuck"] == []
    assert [i["title"] for i in store.list_items(conn, ("snoozed",))] == ["Later thing"]
    conn.close()


def test_surfacing_counts_once_a_day_then_escalates(tmp_path):
    conn = db.connect(tmp_path / "cos.db")
    late = item(conn, "Sign BEAR agreement", due="2026-10-19")
    item(conn, "Book photos", due="2026-11-30")  # not surfaced, never counted
    for day in (TODAY, TODAY, date(2026, 10, 22), date(2026, 10, 23)):
        accountability.mark_surfaced(conn, accountability.review(conn, day), day)
    assert store.get_item(conn, late["id"])["nudges"] == 3  # the repeat on the 21st didn't count
    stuck = accountability.review(conn, date(2026, 10, 24))["stuck"]
    assert ids(stuck) == ["Sign BEAR agreement"] and stuck[0]["nudges"] == 3
    conn.close()


def test_capture_marks_promises_from_sent_mail(env):
    env.fake.messages["m3"] = gmail_message("m3", "Andrew <awpeace1906@gmail.com>", "Re: BEAR Ambassador",
                                            "Yes, I will complete the paperwork asap.", labels=("SENT",))
    promise = change("add", "Complete BEAR paperwork", source="m3")
    ask = change("add", "Reply to UNM about reserved CA1 spot", source="m1")
    claude = FakeClaude({"changes": [promise, ask], "questions": []})
    capture.run(env.conn, env.google, client=claude)
    by_title = {i["title"]: i for i in store.list_items(env.conn)}
    assert by_title["Complete BEAR paperwork"]["promise"] is True
    assert by_title["Reply to UNM about reserved CA1 spot"]["promise"] is False
    assert "Sent mail" in json.dumps(claude.calls[0])  # the capture prompt explains promises


def test_brief_gets_accountability_and_counts_it(env):
    late = item(env.conn, "Sign BEAR agreement", due="2026-10-19")
    claude = FakeClaude({"changes": [], "questions": []}, BRIEF)
    brief.run(env.conn, env.google, client=claude, today=datetime(2026, 10, 21, 8, 25, tzinfo=DENVER))
    plan_input = json.loads(claude.calls[1]["messages"][0]["content"])
    assert ids(plan_input["accountability"]["overdue"]) == ["Sign BEAR agreement"]
    assert "accountability.stuck" in json.dumps(claude.calls[1])
    assert store.get_item(env.conn, late["id"])["nudges"] == 1
