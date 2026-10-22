"""Where the owner is: a fresh phone ping, else the trip covering the day, else home (said to be assumed)."""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from cos import db, location, store
from cos.main import create_app

NOW = datetime(2026, 10, 22, 0, 50, tzinfo=timezone.utc)  # the evening before
HOME = {"label": "Mesa Verde, NM", "lat": 32.30, "lon": -106.78}


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "cos.db")
    yield c
    c.close()


def test_falls_back_to_home_and_says_so(conn):
    assert location.whereabouts(conn, now=NOW)["source"] == "unknown"
    store.put_setting(conn, "home", HOME)
    w = location.whereabouts(conn, date(2026, 10, 22), now=NOW)
    assert w["source"] == "home" and w["label"] == "home (Mesa Verde, NM)" and "Assumed" in w["note"]


def test_a_fresh_phone_ping_wins(conn):
    store.put_setting(conn, "home", HOME)
    location.record(conn, 34.06, -106.89, at=(NOW - timedelta(hours=1)).isoformat(), place="Socorro, NM")
    w = location.whereabouts(conn, date(2026, 10, 22), now=NOW)
    assert (w["source"], w["label"]) == ("phone", "Socorro, NM")
    # near home it reads as home
    location.record(conn, 32.31, -106.77, at=NOW.isoformat())
    assert location.whereabouts(conn, now=NOW)["label"] == "home (Mesa Verde, NM)"
    # too old, or for a day further out than tomorrow, it doesn't count
    assert location.whereabouts(conn, now=NOW + timedelta(hours=7))["source"] == "home"
    assert location.whereabouts(conn, date(2026, 10, 24), now=NOW)["source"] == "home"


def test_a_trip_covering_the_day(conn):
    store.put_setting(conn, "home", HOME)
    store.put_record(conn, "trip", "rotation", {"title": "Away rotation", "start": "2026-10-25", "end": "2026-11-21",
                                                "base": {"label": "Clayton, MO", "lat": 38.65, "lon": -90.33}})
    w = location.whereabouts(conn, date(2026, 10, 27), now=NOW)
    assert (w["source"], w["label"], w["lat"]) == ("trip", "Clayton, MO", 38.65)
    assert location.whereabouts(conn, date(2026, 10, 23), now=NOW)["source"] == "home"


def test_bad_pings_are_refused(conn):
    with pytest.raises(ValueError):
        location.record(conn, 120, 0)
    with pytest.raises(ValueError):
        location.record(conn, 1, 1, at="yesterday")


def test_api(tmp_path, monkeypatch):
    monkeypatch.setenv("COS_API_TOKEN", "k")
    monkeypatch.setenv("COS_SECURE_COOKIE", "0")
    h = {"Authorization": "Bearer k"}
    with TestClient(create_app(str(tmp_path / "cos.db"), runner=lambda fn: fn())) as c:
        assert c.post("/api/location", json={"lat": 34.06, "lon": -106.89}).status_code == 401
        assert c.post("/api/location", headers=h, json={"lat": "x"}).status_code == 422
        ping = c.post("/api/location", headers=h, json={"lat": 34.06, "lon": -106.89, "place": "Socorro, NM",
                                                        "accuracy": 35}).json()
        assert ping["place"] == "Socorro, NM" and ping["accuracy"] == 35
        assert c.get("/api/location", headers=h).json()["source"] == "phone"
        assert c.get("/api/location?date=nope", headers=h).status_code == 422
