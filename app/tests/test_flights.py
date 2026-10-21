"""Flight watch: FAA airport events and flight status turn into messages, re-plans and alerts."""

import json
from datetime import datetime, timezone

import httpx
import pytest

from cos import db, flights, store

FAA_XML = """<AIRPORT_STATUS_INFORMATION><Update_Time>Sun Oct 25 22:01:00 2026 GMT</Update_Time>
<Delay_type><Name>Ground Stop Programs</Name><Ground_Stop_List><Program><ARPT>DFW</ARPT><Reason>thunderstorms</Reason>
<End_Time>6:45 pm CDT</End_Time></Program></Ground_Stop_List></Delay_type>
<Delay_type><Name>General Arrival/Departure Delay Info</Name><Arrival_Departure_Delay_List><Delay><ARPT>STL</ARPT>
<Reason>WX:Wind</Reason><Arrival_Departure Type="Arrival"><Min>16 minutes</Min><Max>30 minutes</Max><Trend>Increasing</Trend>
</Arrival_Departure></Delay></Arrival_Departure_Delay_List></Delay_type></AIRPORT_STATUS_INFORMATION>"""

QUIET_XML = "<AIRPORT_STATUS_INFORMATION><Update_Time>now</Update_Time></AIRPORT_STATUS_INFORMATION>"


def adb(status="Expected", dep_rev=None, arr_rev=None, gate="A12"):
    leg = {"number": "AA 690", "status": status,
           "departure": {"airport": {"iata": "ELP"}, "scheduledTime": {"local": "2026-10-25 17:36-06:00"}, "gate": gate},
           "arrival": {"airport": {"iata": "DFW"}, "scheduledTime": {"local": "2026-10-25 20:20-05:00"}}}
    if dep_rev:
        leg["departure"]["revisedTime"] = {"local": dep_rev}
    if arr_rev:
        leg["arrival"]["revisedTime"] = {"local": arr_rev}
    return [leg]


class Sky:
    """Fake FAA + AeroDataBox."""

    def __init__(self):
        self.faa, self.flight, self.calls = QUIET_XML, adb(), []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(str(request.url))
        if "nasstatus.faa.gov" in request.url.host:
            return httpx.Response(200, text=self.faa)
        assert request.headers["X-RapidAPI-Key"] == "k" and request.url.path == "/flights/number/AA690/2026-10-25"
        return httpx.Response(200, json=self.flight)


class Owner:
    def __init__(self):
        self.sent = []

    def send_to_owner(self, subject, text):
        self.sent.append((subject, text))


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("AERODATABOX_KEY", "k")
    c = db.connect(tmp_path / "cos.db")
    store.put_setting(c, "timezone", "America/Denver")
    store.put_setting(c, "assistant", {"name": "Juno"})
    store.put_record(c, "trip", "stl", {"title": "St. Louis: WashU CTICU", "start": "2026-10-25", "end": "2026-11-21", "legs": [
        {"when": "Sun Oct 25 5:36pm MT", "what": "AA 690 El Paso to Dallas", "flight": "AA 690", "date": "2026-10-25",
         "from": "ELP", "to": "DFW"},
        {"when": "Mon Oct 26 7:00am CT", "what": "Badge at FISC"}]})  # no flight: not watched
    yield c
    c.close()


def run(conn, sky, at, owner=None):
    return flights.check(conn, httpx.Client(transport=httpx.MockTransport(sky)), now=at, google=owner)


def at(hhmm):
    return datetime.fromisoformat(f"2026-10-25T{hhmm}:00-06:00").astimezone(timezone.utc)


def test_parse_faa_and_flight_numbers():
    events = flights.parse_faa(FAA_XML)
    assert events["DFW"] == [{"kind": "ground stop", "reason": "thunderstorms", "until": "6:45 pm CDT"}]
    assert events["STL"][0]["kind"] == "delay" and events["STL"][0]["direction"] == "arrival" and events["STL"][0]["max"] == "30 minutes"
    assert flights.normalize("aa 690") == "AA690" and flights.normalize("AA 1445 Dallas to St. Louis") == "AA1445"
    assert flights.normalize("Badge at FISC") == ""


def test_only_legs_in_their_window_are_checked(conn):
    sky = Sky()
    assert run(conn, sky, datetime(2026, 10, 20, tzinfo=timezone.utc))["checked"] == []  # days away
    first = run(conn, sky, at("09:00"))
    assert first["checked"] == ["AA690"] and first["changes"] == []  # learned the schedule, nothing new
    live = store.get_record(conn, "trip", "stl")["legs"][0]["live"]
    assert live["scheduledDeparture"] == "2026-10-25T17:36-06:00" and live["gate"] == "A12"
    assert run(conn, sky, at("09:10"))["checked"] == []  # within the interval
    assert run(conn, sky, at("09:21"))["checked"] == []  # more than 6 hours out now that times are known
    assert run(conn, sky, at("12:00"))["checked"] == ["AA690"]
    assert all("/flights/number/AA690/2026-10-25" in u or "nasstatus" in u for u in sky.calls)


def test_a_delay_and_a_ground_stop_message_and_replan(conn):
    sky, owner = Sky(), Owner()
    run(conn, sky, at("12:00"), owner)
    sky.flight = adb("Delayed", dep_rev="2026-10-25 18:41-06:00", arr_rev="2026-10-25 21:25-05:00", gate="A14")
    sky.faa = FAA_XML
    r = run(conn, sky, at("12:30"), owner)
    changes = r["changes"][0]["changes"]
    assert "delayed" in changes and any(c.startswith("departure now Sun 6:41pm") and "1h 05m late" in c for c in changes)
    assert "gate A12 → A14" in changes and any(c.startswith("FAA ground stop at DFW") for c in changes)
    msgs = store.list_messages(conn)
    told = [m for m in msgs if m["from"] == "assistant"]
    assert len(told) == 1 and "re-planning" in told[0]["text"]
    replan = [m for m in msgs if m["kind"] == "replan"]
    assert len(replan) == 1 and replan[0]["id"] == r["replans"][0] and replan[0]["data"]["day"] == "2026-10-25"
    assert owner.sent == []  # still lands the same evening: no email
    assert run(conn, sky, at("13:00"), owner)["changes"] == []  # nothing new, nothing said


def test_cancellation_or_overnight_arrival_emails_the_owner(conn):
    sky, owner = Sky(), Owner()
    run(conn, sky, at("12:00"), owner)
    sky.flight = adb("Delayed", dep_rev="2026-10-25 22:50-06:00", arr_rev="2026-10-26 01:30-05:00")
    run(conn, sky, at("12:30"), owner)
    assert len(owner.sent) == 1 and owner.sent[0][0] == "Juno: AA 690 changed"
    sky.flight = adb("Canceled")
    run(conn, sky, at("13:00"), owner)
    assert owner.sent[-1][0] == "Juno: AA 690 cancelled" and "cancelled" in owner.sent[-1][1]


def test_without_a_key_only_faa_is_used(conn, monkeypatch):
    monkeypatch.delenv("AERODATABOX_KEY")
    sky = Sky()
    sky.faa = FAA_XML
    r = run(conn, sky, at("12:00"))
    assert r["changes"][0]["changes"] == ["FAA ground stop at DFW (thunderstorms) until 6:45 pm CDT"]
    assert all("nasstatus" in u for u in sky.calls)
    assert json.dumps(store.get_record(conn, "trip", "stl")["legs"][1]).find("live") == -1
