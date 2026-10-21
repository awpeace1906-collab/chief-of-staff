import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cos import ai, db, store
from cos.importer import export_all, import_board, import_brain, import_config
from cos.main import create_app

REPO_CONFIG = Path(__file__).resolve().parents[2] / "examples" / "memory"


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "cos.db")
    yield c
    c.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("COS_API_TOKEN", raising=False)
    with TestClient(create_app(str(tmp_path / "cos.db"))) as c:
        yield c


def test_import_repo_config(conn):
    counts = import_config(conn, REPO_CONFIG)
    assert counts["settings"] >= 5
    assert store.assistant_name(conn) == "Juno"
    assert set(store.get_setting(conn, "divisions")) == {"me", "sam", "kids"}
    assert store.get_setting(conn, "digests")["schema"] == "cos-digests/v1"
    contents = [r["content"] for r in store.list_rules(conn)]
    assert any(c.startswith("Dr. Lee:") for c in contents)


def test_import_is_idempotent(conn):
    import_config(conn, REPO_CONFIG)
    first = len(store.list_rules(conn))
    import_config(conn, REPO_CONFIG)
    assert len(store.list_rules(conn)) == first


def test_board_lifecycle(conn):
    item = store.add_item(conn, {"title": "Upload flu shot", "direction": "i-owe", "division": "me", "due": "2026-10-14"})
    assert item["id"].startswith("c-") and item["status"] == "open"
    store.update_item(conn, item["id"], {"status": "done", "evidence": "Sent Oct 14"})
    assert store.list_items(conn) == []
    assert store.list_items(conn, ("done",))[0]["evidence"] == "Sent Oct 14"


def test_board_rejects_bad_items(conn):
    with pytest.raises(ValueError):
        store.add_item(conn, {"title": "x", "direction": "i-owe", "division": "me", "status": "maybe"})
    with pytest.raises(ValueError):
        store.add_item(conn, {"direction": "i-owe", "division": "me"})


def test_brain_import_skips_other_tags_and_deleted(conn, tmp_path):
    brain = tmp_path / "brain-data.json"
    brain.write_text(json.dumps({
        "schema": "brain/v1",
        "entries": [
            {"id": "juno-1-aaaa", "content": "Lee goes remote", "tags": ["juno", "rule"], "timestamp": "2026-10-19T20:00:00.000Z"},
            {"id": "e-2", "content": "A recipe", "tags": ["food"], "timestamp": "2026-10-19T20:00:00.000Z"},
            {"id": "juno-3-bbbb", "content": "Old", "tags": ["juno"], "timestamp": "2026-10-19T20:00:00.000Z"},
        ],
        "deleted": ["juno-3-bbbb"],
    }))
    assert import_brain(conn, brain, "juno") == 1
    assert store.list_rules(conn)[0]["kind"] == "rule"


def test_export_round_trips_board(conn, tmp_path):
    import_config(conn, REPO_CONFIG)
    store.add_item(conn, {"title": "Reply to Northfield", "direction": "i-owe", "division": "me"})
    out = export_all(conn)
    assert out["brain"]["schema"] == "brain/v1"
    assert all(e["source"] == "juno" for e in out["brain"]["entries"])
    board = tmp_path / "board.json"
    board.write_text(json.dumps(out["board"]))
    fresh = db.connect(tmp_path / "fresh.db")
    assert import_board(fresh, board) == 1
    assert import_board(fresh, board) == 0


def test_ai_routes_default_and_validation(conn):
    assert ai.resolve(conn, "triage")["model"] == "claude-haiku-5-5"
    local = json.loads(json.dumps(ai.DEFAULT_AI))
    local["routes"]["triage"] = {"provider": "local", "model": "qwen3:8b"}
    ai.validate(local)
    store.put_setting(conn, "ai", local)
    with pytest.raises(RuntimeError):
        ai.resolve(conn, "triage")  # local provider still disabled
    local["routes"]["triage"]["provider"] = "nowhere"
    with pytest.raises(ValueError):
        ai.validate(local)


def test_api(client):
    assert client.get("/health").json()["ok"]
    r = client.post("/api/board", json={"title": "Check in for AA", "direction": "i-owe", "division": "me"})
    assert r.status_code == 201
    item_id = r.json()["id"]
    assert client.patch(f"/api/board/{item_id}", json={"status": "done"}).json()["status"] == "done"
    assert client.patch("/api/board/c-0-none", json={"status": "done"}).status_code == 404
    assert client.put("/api/settings/ai", json={"routes": {"bogus": {}}}).status_code == 422
    assert client.get("/api/ai/routes").json()["plan"]["ready"]
    assert "Chief of Staff" in client.get("/").text


def test_api_token(tmp_path, monkeypatch):
    monkeypatch.setenv("COS_API_TOKEN", "s3cret")
    with TestClient(create_app(str(tmp_path / "cos.db"))) as c:
        assert c.get("/api/board").status_code == 401
        assert c.get("/api/board", headers={"Authorization": "Bearer s3cret"}).status_code == 200
        assert c.get("/health").status_code == 200


def test_old_database_gets_new_columns(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)  # a v0.4 messages table, before channel/ref existed
    old.execute("CREATE TABLE messages (id TEXT PRIMARY KEY, at TEXT NOT NULL, sender TEXT NOT NULL, status TEXT NOT NULL, text TEXT NOT NULL)")
    old.execute("INSERT INTO messages VALUES ('m1', '2026-10-20T00:00:00Z', 'owner', 'new', 'hi')")
    old.commit()
    old.close()
    c = db.connect(path)
    assert store.list_messages(c)[0]["channel"] == "app"
    store.add_message(c, "owner", "by text", channel="sms")
    assert c.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    c.close()
