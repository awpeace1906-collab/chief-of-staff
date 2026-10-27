"""Noticing new people: names that keep coming up are asked about in the Situation Room, and only the
principal's answer (or their own message) adds someone."""

import json
import shutil
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from cos import agent, brief, db, people, store
from cos.importer import import_config
from cos.main import create_app
from test_agent import Calendar, ToolClaude, google
from test_brief import BRIEF, FakeClaude, env  # noqa: F401 (fixture)
from test_google import REPO_CONFIG

DENVER = ZoneInfo("America/Denver")
D1, D2 = date(2026, 10, 20), date(2026, 10, 21)
ELLIE = {"name": "Ellie", "relation": "child", "division": "kids", "evidence": "daycare enrollment email"}


@pytest.fixture
def conn(tmp_path, monkeypatch):
    mem = tmp_path / "assistant-memory"
    shutil.copytree(REPO_CONFIG, mem)
    monkeypatch.setenv("COS_MEMORY_DIR", str(mem))
    c = db.connect(tmp_path / "cos.db")
    import_config(c, mem)
    yield c
    c.close()


def test_the_household_comes_from_memory(conn):
    assert [p["name"] for p in people.known(conn)] == ["Pat Rivera", "Sam", "Robin", "Casey"]
    # first names, full names and coverage people all count as known
    for name in ("Pat", "pat rivera", "Robin", "Casey", ""):
        assert people.is_known(conn, name)
    assert not people.is_known(conn, "Ellie")


def test_asked_only_after_it_keeps_coming_up(conn):
    assert people.note(conn, [ELLIE, {"name": "Robin", "relation": "child", "division": "kids", "evidence": "x"}],
                       "mail", D1) == ["Ellie"]
    people.note(conn, [ELLIE], "calendar", D1)
    assert people.ask(conn, D1) == []  # three mentions, but all on one day
    people.note(conn, [ELLIE], "mail", D2)
    assert people.ask(conn, D2) == ["person-ellie"]
    d = store.get_record(conn, "decision", "person-ellie")
    assert d["title"] == "Is Ellie new to the household? Track them?" and d["deadline"] == "2026-10-28"
    assert [o["id"] for o in d["options"]] == ["track-kids", "track-me", "no"]
    assert d["options"][0]["label"] == "Yes, track under Kids & coverage"
    assert "daycare enrollment email" in d["context"]
    people.note(conn, [ELLIE], "mail", D2)
    assert people.ask(conn, D2) == []  # asked once


def test_yes_adds_them_to_the_app_and_to_memory(conn, tmp_path):
    for day in (D1, D1, D2):
        people.note(conn, [ELLIE], "mail", day)
    people.ask(conn, D2)
    store.choose(conn, "person-ellie", "track-kids")
    out = agent.act_on_decisions(conn, google(conn, Calendar()), client=ToolClaude())  # no model call needed
    assert out[0]["actions"].startswith("Now tracking Ellie under Kids & coverage.")
    assert "assistant-memory/memory.json" in out[0]["actions"]
    assert people.known(conn)[-1] == {"name": "Ellie", "role": "child", "division": "kids"}
    saved = json.loads((tmp_path / "assistant-memory" / "memory.json").read_text())
    assert saved["people"][-1] == {"name": "Ellie", "role": "child", "division": "kids"}
    assert store.get_setting(conn, "peopleCandidates")["ellie"]["status"] == "added"
    people.note(conn, [ELLIE], "mail", D2)  # known now: not noted again
    assert store.get_setting(conn, "peopleCandidates")["ellie"]["count"] == 3


def test_no_is_remembered(conn):
    for day in (D1, D1, D2):
        people.note(conn, [ELLIE], "mail", day)
    people.ask(conn, D2)
    store.choose(conn, "person-ellie", "no")
    out = agent.act_on_decisions(conn, google(conn, Calendar()), client=ToolClaude())
    assert out[0]["actions"] == "Not tracking Ellie; won't ask again."
    assert not people.is_known(conn, "Ellie") and people.note(conn, [ELLIE], "mail", D2) == []
    assert people.context(conn)["notPeopleToTrack"] == ["Ellie"]


def test_a_new_nanny_joins_the_coverage(conn):
    assert people.add(conn, "Jordan", "nanny", "kids").startswith("Now tracking Jordan under Kids & coverage (coverage).")
    assert store.divisions(conn)["kids"]["coverage"] == ["Casey", "Jordan"]
    assert people.add(conn, "jordan", "nanny", "kids") == "jordan is already tracked."
    assert people.add(conn, "Lee", "pirate", "nowhere").startswith("Now tracking Lee under Me.")  # unknown role/division
    with pytest.raises(ValueError):
        people.add(conn, "  ", "child", "kids")


def test_without_the_memory_directory_it_says_so(conn, monkeypatch, tmp_path):
    monkeypatch.delenv("COS_MEMORY_DIR")
    monkeypatch.setenv("COS_MEMORY_BASE", str(tmp_path / "elsewhere"))
    assert people.add(conn, "Ellie", "child", "kids").endswith("isn't on this machine.")


def test_the_principal_can_ask_for_it_in_talk(conn):
    store.add_message(conn, "owner", "We had a daughter, Ellie! Please track her under the kids.")
    claude = ToolClaude([("add_person", {"name": "Ellie", "role": "child", "division": "kids"})],
                        [("reply", {"text": "Congratulations! I'm tracking Ellie under Kids now."})])
    agent.handle_messages(conn, google(conn, Calendar()), client=claude)
    assert people.known(conn)[-1]["name"] == "Ellie"
    assert "add_person" in {t["name"] for t in claude.calls[0]["tools"]}


def test_capture_and_the_brief_report_new_people(env):
    claude = FakeClaude(
        {"changes": [], "questions": [], "trips": [], "binders": [], "expenses": [], "newPeople": [ELLIE]},
        BRIEF | {"decisions": [], "newPeople": [ELLIE | {"evidence": "Family calendar: Ellie's checkup"}]},
    )
    brief.run(env.conn, env.google, client=claude, today=datetime(2026, 10, 20, 8, 25, tzinfo=DENVER))
    triage, plan = (json.loads(c["messages"][0]["content"]) for c in claude.calls)
    assert [p["name"] for p in triage["knownPeople"]][:2] == ["Pat Rivera", "Sam"] and "knownPeople" in plan
    assert "newPeople" in claude.calls[0]["system"][0]["text"] and "Never patients" in claude.calls[1]["system"][0]["text"]
    cand = store.get_setting(env.conn, "peopleCandidates")["ellie"]
    assert cand["count"] == 2 and [m["source"] for m in cand["mentions"]] == ["mail", "calendar"]
    assert store.get_record(env.conn, "decision", "person-ellie") is None  # one day so far: not asked yet


def test_people_api(tmp_path, monkeypatch):
    monkeypatch.delenv("COS_API_TOKEN", raising=False)
    monkeypatch.setenv("COS_MEMORY_BASE", str(tmp_path))
    monkeypatch.delenv("COS_MEMORY_DIR", raising=False)
    with TestClient(create_app(str(tmp_path / "cos.db"))) as c:
        conn = db.connect(tmp_path / "cos.db")
        import_config(conn, REPO_CONFIG)
        r = c.post("/api/people", json={"name": "Ellie", "role": "child", "division": "kids"})
        assert r.status_code == 201 and r.json()["result"].startswith("Now tracking Ellie")
        assert c.post("/api/people", json={"name": ""}).status_code == 422
        assert c.get("/api/people").json()["people"][-1]["name"] == "Ellie"
        conn.close()
