"""The day view: a day's events in the viewer's zone, free windows, and blocks booked from it."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from cos import agent, schedule, store
from cos.main import create_app
from test_agent import Calendar, conn, google  # noqa: F401 (fixture)

DENVER, CHICAGO = ZoneInfo("America/Denver"), ZoneInfo("America/Chicago")


def agenda():
    return {"timezone": "America/Denver", "divisions": {
        "me": {"events": [
            {"title": "CTICU", "start": "2026-10-27T05:00:00-06:00", "end": "2026-10-27T18:00:00-06:00", "busy": True},
            {"title": "Away", "start": "2026-10-25", "end": "2026-11-22", "allDay": True, "busy": False},
            {"title": "Yesterday", "start": "2026-10-26T09:00:00-06:00", "end": "2026-10-26T10:00:00-06:00", "busy": True}]},
        "kids": {"events": [
            {"title": "Swim", "start": "2026-10-27T15:00:00-06:00", "end": "2026-10-27T16:00:00-06:00", "busy": True}]}}}


def test_day_in_the_viewers_zone_with_planned_blocks():
    block = {"id": "2026-10-27-1", "title": "Add: BEAR paperwork", "status": "approved", "itemId": "c-1",
             "start": "2026-10-27T19:00:00-05:00", "end": "2026-10-27T19:30:00-05:00", "division": "me"}
    d = schedule.day(agenda(), date(2026, 10, 27), CHICAGO, schedule.DEFAULTS, [block, {"status": "done", "start": "x"}])
    assert [e["title"] for e in d["events"]] == ["CTICU", "Away", "Swim"]  # yesterday's event left out
    # CTICU is 6am-7pm Central; the block takes 7-7:30pm, so the evening starts at 7:30
    assert [(s["start"][11:16], s["end"][11:16]) for s in d["free"]] == [("19:30", "21:00")]
    assert d["planned"][0]["id"] == "2026-10-27-1" and d["timezone"] == "America/Chicago"


def test_past_days_have_no_free_time():
    later = datetime(2026, 10, 28, 9, 0, tzinfo=CHICAGO)
    assert schedule.day(agenda(), date(2026, 10, 27), CHICAGO, schedule.DEFAULTS, [], now=later)["free"] == []


def test_a_block_goes_on_the_calendar_at_exactly_its_time(conn):
    item = store.add_item(conn, {"title": "Sign BEAR agreement", "direction": "i-owe", "division": "me", "notes": "Gaby's Oct 1 email"})
    p = store.add_proposal(conn, {"kind": "calendar", "division": "me", "title": "Add: Sign BEAR agreement",
                                  "start": "2026-10-27T19:00:00-05:00", "end": "2026-10-27T19:30:00-05:00",
                                  "timeZone": "America/Chicago", "itemId": item["id"], "source": "schedule"}, actor="user")
    store.update_proposal(conn, p["id"], {"status": "approved"})
    cal = Calendar()
    out = agent.execute_approved(conn, google(conn, cal), client=None)  # no model: an exact block needs none
    assert out[0]["status"] == "done" and "Pat Work" in out[0]["result"] and "CDT" in out[0]["result"]
    made = cal.created[0]
    assert made["summary"] == "Sign BEAR agreement" and made["description"] == "Gaby's Oct 1 email"
    assert made["start"] == {"dateTime": "2026-10-27T19:00:00-05:00", "timeZone": "America/Chicago"}
    assert store.get_item(conn, item["id"])["status"] == "open"  # a block isn't proof it's done


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("COS_API_TOKEN", "k")
    monkeypatch.setenv("COS_SECURE_COOKIE", "0")
    with TestClient(create_app(str(tmp_path / "cos.db"))) as c:
        yield c


def test_block_endpoint_stores_an_approved_proposal_without_google(client):
    h = {"Authorization": "Bearer k"}
    item = client.post("/api/board", headers=h, json={"title": "Put Robin's clothes away", "direction": "household",
                                                      "division": "kids"}).json()
    body = {"itemId": item["id"], "start": "2026-10-23T18:00:00-06:00", "end": "2026-10-23T18:30:00-06:00",
            "timeZone": "America/Denver"}
    p = client.post("/api/schedule/block", headers=h, json=body).json()
    assert p["status"] == "approved" and p["source"] == "schedule" and p["itemId"] == item["id"]  # Google not connected: waits
    assert p["title"] == "Add: Put Robin's clothes away" and p["division"] == "kids"
    assert client.post("/api/schedule/block", headers=h, json=body | {"itemId": "nope"}).status_code == 404
    assert client.post("/api/schedule/block", headers=h, json=body | {"end": body["start"]}).status_code == 422
    assert client.get("/api/day?date=2026-10-23&tz=Nowhere/Land", headers=h).status_code == 422
    assert client.get("/api/day?date=2026-10-23", headers=h).status_code == 409  # Google not connected
