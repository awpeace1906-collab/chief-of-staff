"""Import the current setup (repo config, Brain export, board export) into the database."""

import json
import sqlite3
from pathlib import Path

from .db import audit, now
from .store import (
    BOARD_STATUSES,
    add_item,
    all_settings,
    get_item,
    list_items,
    list_rules,
    put_setting,
    upsert_rule,
)

RULE_KINDS = {"rule", "preference", "context"}


def import_config(conn: sqlite3.Connection, config_dir: Path) -> dict:
    """Load config/tower.json-style assistant config and config/digests.json."""
    counts = {"settings": 0, "rules": 0}
    config_dir = Path(config_dir)

    assistant_files = [p for p in config_dir.glob("*.json") if p.name != "digests.json"]
    for path in assistant_files:
        cfg = json.loads(path.read_text())
        if "assistant" not in cfg:
            continue
        for key in ("assistant", "timezone", "brief", "approvals", "divisions", "hosting", "openItems"):
            if key in cfg:
                put_setting(conn, key, cfg[key], actor="system")
                counts["settings"] += 1
        prefix = cfg["assistant"].get("name", "assistant").lower()
        for i, agreement in enumerate(cfg.get("standingAgreements", [])):
            upsert_rule(conn, {
                "id": f"{prefix}-import-agreement-{i}",
                "kind": "rule",
                "content": f"{agreement['who']}: {agreement['rule']}",
                "summary": f"Standing agreement with {agreement['who']}",
                "source": "import",
            })
            counts["rules"] += 1
        for i, rule in enumerate(cfg.get("mailRules", [])):
            upsert_rule(conn, {
                "id": f"{prefix}-import-mail-{i}",
                "kind": "rule",
                "content": rule,
                "summary": "Mail handling rule",
                "source": "import",
            })
            counts["rules"] += 1

    digests = config_dir / "digests.json"
    if digests.exists():
        put_setting(conn, "digests", json.loads(digests.read_text()), actor="system")
        counts["settings"] += 1

    audit(conn, "system", "import.config", dir=str(config_dir), **counts)
    conn.commit()
    return counts


def import_brain(conn: sqlite3.Connection, brain_file: Path, tag: str) -> int:
    """Import entries tagged `tag` from a brain/v1 export (brain-data.json)."""
    data = json.loads(Path(brain_file).read_text())
    deleted = set(data.get("deleted", []))
    n = 0
    for e in data.get("entries", []):
        tags = e.get("tags", [])
        if tag not in tags or e.get("id") in deleted:
            continue
        kind = next((t for t in tags if t in RULE_KINDS), "context")
        upsert_rule(conn, {
            "id": e["id"],
            "kind": kind,
            "content": e["content"],
            "summary": e.get("summary", ""),
            "archived": int(bool(e.get("archived"))),
            "source": "brain",
            "updated_at": e["timestamp"],
        })
        n += 1
    audit(conn, "system", "import.brain", file=str(brain_file), entries=n)
    conn.commit()
    return n


def import_board(conn: sqlite3.Connection, board_file: Path) -> int:
    """Import items from a cos-board/v1 export, skipping ids already present."""
    data = json.loads(Path(board_file).read_text())
    n = 0
    for item in data.get("items", []):
        if get_item(conn, item["id"]) is None:
            add_item(conn, item, actor="system")
            n += 1
    return n


def export_all(conn: sqlite3.Connection) -> dict:
    """Everything portable, in the formats Brain and the board already use."""
    rules = list_rules(conn, include_archived=True)
    name = all_settings(conn).get("assistant", {}).get("name", "assistant").lower()
    return {
        "settings": all_settings(conn),
        "brain": {
            "schema": "brain/v1",
            "entries": [
                {
                    "id": r["id"],
                    "content": r["content"],
                    "type": "text",
                    "tags": [name, r["kind"]],
                    "summary": r["summary"],
                    "pinned": False,
                    "archived": r["archived"],
                    "timestamp": r["updated_at"],
                    "source": name,
                }
                for r in rules
            ],
            "deleted": [],
            "syncedAt": now(),
        },
        "board": {
            "schema": "cos-board/v1",
            "updatedAt": now(),
            "items": list_items(conn, statuses=tuple(BOARD_STATUSES)),
        },
    }
