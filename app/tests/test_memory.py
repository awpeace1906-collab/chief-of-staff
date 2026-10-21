"""The agent's memory lives in <alias>-memory; a rename keeps the agent and moves its memory."""

import json

import pytest
from fastapi.testclient import TestClient

from cos import brain, db, memory, store
from cos.importer import import_config
from cos.main import create_app


def make(base, name="Juno", **extra):
    path = base / memory.dir_name(name)
    path.mkdir()
    (path / "memory.json").write_text(json.dumps({"assistant": {"name": name, **extra}, "divisions": {"me": {}}}))
    return path


def test_locate_by_alias_or_the_only_one(tmp_path, monkeypatch):
    monkeypatch.delenv("COS_MEMORY_DIR", raising=False)
    path = make(tmp_path)
    assert memory.dir_name("Juno") == "juno-memory" and memory.dir_name("Ms. Juno 2") == "ms-juno-2-memory"
    assert memory.locate("Juno", base=tmp_path) == path
    assert memory.locate(base=tmp_path) == path
    monkeypatch.setenv("COS_MEMORY_BASE", str(tmp_path))
    assert memory.locate("juno") == path
    with pytest.raises(FileNotFoundError):
        memory.locate("Kai")
    make(tmp_path, "Kai")
    with pytest.raises(FileNotFoundError):
        memory.locate(base=tmp_path)  # two memories: say which
    monkeypatch.setenv("COS_MEMORY_DIR", str(path))
    assert memory.locate() == path


def test_rename_moves_the_directory_and_keeps_the_id(tmp_path):
    path = make(tmp_path)
    new = memory.rename(path, "Kai")
    assert new == tmp_path / "kai-memory" and not path.exists()
    cfg = json.loads((new / "memory.json").read_text())
    assert cfg["assistant"] == {"name": "Kai", "id": "juno", "formerNames": ["Juno"]}
    assert memory.identity(cfg) == {"id": "juno", "name": "Kai"}
    make(tmp_path, "Juno")
    with pytest.raises(FileExistsError):
        memory.rename(tmp_path / "juno-memory", "Kai")


def test_the_id_survives_a_rename_in_the_app(tmp_path, monkeypatch):
    monkeypatch.setenv("COS_MEMORY_BASE", str(tmp_path))
    monkeypatch.delenv("COS_MEMORY_DIR", raising=False)
    path = make(tmp_path)
    c = db.connect(tmp_path / "cos.db")
    import_config(c, path)
    assert store.get_setting(c, "assistant")["id"] == "juno"
    rule = store.new_rule_id(c)
    store.rename_assistant(c, "Kai")
    assert store.assistant_name(c) == "Kai" and store.assistant_id(c) == "juno"
    assert store.new_rule_id(c).split("-")[0] == rule.split("-")[0] == "juno"  # Brain ids and tags don't change
    assert (tmp_path / "kai-memory" / "memory.json").exists()
    assert store.get_setting(c, "assistant")["formerNames"] == ["Juno"]
    with pytest.raises(ValueError):
        store.rename_assistant(c, "!!")
    c.close()


def test_renaming_in_settings_is_a_rename(tmp_path, monkeypatch):
    monkeypatch.setenv("COS_MEMORY_BASE", str(tmp_path))
    monkeypatch.delenv("COS_MEMORY_DIR", raising=False)
    monkeypatch.setenv("COS_API_TOKEN", "k")
    make(tmp_path)
    with TestClient(create_app(str(tmp_path / "cos.db"))) as client:
        h = {"Authorization": "Bearer k"}
        client.put("/api/settings/assistant", headers=h, json={"name": "Juno", "email": "pat@example.com"})
        assert client.put("/api/settings/assistant", headers=h, json={"name": "Kai", "id": "x"}).json() == {"ok": True}
        a = client.get("/api/settings", headers=h).json()["assistant"]
        assert a["name"] == "Kai" and a["id"] == "juno" and a["email"] == "pat@example.com"  # id can't be overwritten
        assert (tmp_path / "kai-memory").exists() and not (tmp_path / "juno-memory").exists()
        assert client.put("/api/settings/assistant", headers=h, json={"name": "  "}).status_code == 422
