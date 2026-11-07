"""The memory connector: MCP over HTTP, off by default, read-only unless scoped to propose, writes never act."""

import json

import pytest
from fastapi.testclient import TestClient

from cos import db, store
from cos.main import create_app

TOKEN = "t0ken"
AUTH = {"Authorization": f"Bearer {TOKEN}", "User-Agent": "test-client/1"}


def rpc(method, params=None, mid=1):
    m = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        m["params"] = params
    return m


def call(c, tool, args=None, headers=AUTH):
    r = c.post("/mcp", json=rpc("tools/call", {"name": tool, "arguments": args or {}}), headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["result"]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("COS_API_TOKEN", TOKEN)
    path = tmp_path / "cos.db"
    c = db.connect(path)
    store.put_setting(c, "assistant", {"id": "ace", "name": "Ace"})
    store.put_setting(c, "divisions", {"me": {"label": "Me", "calendars": {}}, "kids": {"label": "Kids"}})
    store.add_item(c, {"title": "Send the housing deposit", "direction": "i-owe", "division": "me",
                       "due": "2020-01-01"})
    store.add_item(c, {"title": "Renew passport", "direction": "i-owe", "division": "me", "status": "done"})
    store.put_record(c, "trip", "tucson", {"title": "Tucson sub-internship", "start": "2026-11-23", "end": "2026-12-18"})
    store.put_record(c, "card", "tomorrow", {"day": "2026-11-08", "markdown": "**First movement:** none."})
    store.add_proposal(c, {"title": "Add: Drive to Tucson", "kind": "calendar", "division": "me", "when": "Sun 10am"})
    c.close()

    def build(cfg):
        cc = db.connect(path)
        if cfg is not None:
            store.put_setting(cc, "connector", cfg)
        cc.close()
        return TestClient(create_app(str(path)))
    return build, path


def test_off_by_default(setup):
    build, _ = setup
    with build(None) as c:
        assert c.post("/mcp", json=rpc("initialize"), headers=AUTH).status_code == 404


def test_needs_the_bearer_token_not_the_cookie(setup):
    build, _ = setup
    with build({"enabled": True}) as c:
        assert c.post("/mcp", json=rpc("ping")).status_code == 401
        assert c.post("/mcp", json=rpc("ping"), headers={"Authorization": "Bearer nope"}).status_code == 401
        c.cookies.set("cos_session", "anything")
        assert c.post("/mcp", json=rpc("ping")).status_code == 401
        assert c.post("/mcp", json=rpc("ping"), headers=AUTH).json() == {"jsonrpc": "2.0", "id": 1, "result": {}}


def test_refuses_other_sites(setup):
    build, _ = setup
    with build({"enabled": True}) as c:
        evil = AUTH | {"Origin": "https://evil.example"}
        assert c.post("/mcp", json=rpc("ping"), headers=evil).status_code == 403
        local = AUTH | {"Origin": "http://localhost:3000"}
        assert c.post("/mcp", json=rpc("ping"), headers=local).status_code == 200


def test_handshake_and_notifications(setup):
    build, _ = setup
    with build({"enabled": True}) as c:
        r = c.post("/mcp", json=rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                                  "clientInfo": {"name": "t", "version": "1"}}), headers=AUTH).json()
        res = r["result"]
        assert res["protocolVersion"] == "2025-03-26"
        assert res["serverInfo"]["name"] == "ace-memory" and "Ace" in res["serverInfo"]["title"]
        assert "read-only" in res["instructions"]
        unknown = c.post("/mcp", json=rpc("initialize", {"protocolVersion": "1999-01-01"}), headers=AUTH).json()
        assert unknown["result"]["protocolVersion"] == "2025-06-18"
        note = c.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=AUTH)
        assert note.status_code == 202 and note.content == b""
        assert c.get("/mcp", headers=AUTH).status_code == 405
        assert c.post("/mcp", json=rpc("resources/list"), headers=AUTH).json()["error"]["code"] == -32601
        bad = c.post("/mcp", content=b"{not json", headers=AUTH | {"Content-Type": "application/json"})
        assert bad.status_code == 400 and bad.json()["error"]["code"] == -32700


def test_read_scope_lists_only_read_tools(setup):
    build, path = setup
    with build({"enabled": True, "scope": "read"}) as c:
        tools = c.post("/mcp", json=rpc("tools/list"), headers=AUTH).json()["result"]["tools"]
        assert [t["name"] for t in tools] == ["today", "week", "recall"]
        assert all(t["annotations"]["readOnlyHint"] for t in tools)
        refused = c.post("/mcp", json=rpc("tools/call", {"name": "propose", "arguments": {"title": "Add: x"}}),
                         headers=AUTH).json()
        assert refused["error"]["code"] == -32602
    cc = db.connect(path)
    assert len(store.list_proposals(cc)) == 1  # only the fixture's
    cc.close()


def test_today_week_and_recall(setup):
    build, path = setup
    with build({"enabled": True}) as c:
        today = call(c, "today")["content"][0]["text"]
        assert "No brief yet." in today and "Add: Drive to Tucson" in today and "Send the housing deposit" in today
        week = call(c, "week")["content"][0]["text"]
        assert "First movement" in week and "housing deposit" in week
        hit = call(c, "recall", {"query": "tucson"})["content"][0]["text"]
        assert "[trip] Tucson sub-internship" in hit
        done = call(c, "recall", {"query": "passport"})["content"][0]["text"]
        assert "Renew passport" in done and "done" in done  # closed items are searchable too
        assert "Nothing matches" in call(c, "recall", {"query": "zebra"})["content"][0]["text"]
        only_items = call(c, "recall", {"query": "tucson", "kinds": ["item"]})["content"][0]["text"]
        assert "Nothing matches" in only_items
        empty = call(c, "recall", {"query": " "})
        assert empty["isError"] and "needs a query" in empty["content"][0]["text"]
    cc = db.connect(path)
    calls = [json.loads(r["detail"]) for r in cc.execute(
        "SELECT detail FROM audit_log WHERE action = 'connector.call'")]
    assert {d["tool"] for d in calls} == {"today", "week", "recall"} and calls[0]["client"] == "test-client/1"
    cc.close()


def test_propose_scope_writes_only_pending_proposals_and_messages(setup):
    build, path = setup
    with build({"enabled": True, "scope": "propose"}) as c:
        names = [t["name"] for t in c.post("/mcp", json=rpc("tools/list"), headers=AUTH).json()["result"]["tools"]]
        assert names == ["today", "week", "recall", "remember", "propose"]
        text = call(c, "propose", {"title": "Add: Dentist", "when": "Fri 3pm", "kind": "calendar",
                                   "division": "kids"})["content"][0]["text"]
        assert "waiting for the principal's approval" in text
        bad_kind = call(c, "propose", {"title": "Send: hi", "kind": "email"})
        assert bad_kind["isError"]
        call(c, "remember", {"text": "The kids' dentist moved to Friday"})
    cc = db.connect(path)
    p = [p for p in store.list_proposals(cc) if p["title"] == "Add: Dentist"][0]
    assert p["status"] == "pending" and p["kind"] == "calendar" and p["division"] == "kids"
    assert p["source"] == "connector:test-client/1"
    m = store.list_messages(cc)[-1]
    assert m["from"] == "owner" and m["status"] == "new" and m["channel"] == "connector"
    assert m["text"] == "The kids' dentist moved to Friday"
    cc.close()


def test_unknown_division_falls_back_to_the_owner(setup):
    build, path = setup
    with build({"enabled": True, "scope": "propose"}) as c:
        call(c, "propose", {"title": "Add: Something", "division": "nope"})
    cc = db.connect(path)
    p = [p for p in store.list_proposals(cc) if p["title"] == "Add: Something"][0]
    assert p["division"] == store.owner_division(cc)
    cc.close()
