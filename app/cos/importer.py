"""Import the current setup (repo config, Brain export, board export) into the database."""

import json
import sqlite3
from pathlib import Path

from .db import audit, now
from .store import (
    BOARD_STATUSES,
    PROPOSAL_FIELDS,
    _write_proposal,
    add_message,
    get_setting,
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
        for key in ("assistant", "timezone", "brief", "approvals", "divisions", "hosting", "openItems", "google",
                    "microsoft"):
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
        for field, tag, summary in (("mailRules", "mail", "Mail handling rule"),
                                    ("calendarRules", "calendar", "Calendar rule"),
                                    ("notificationRules", "notify", "Notification rule")):
            for i, rule in enumerate(cfg.get(field, [])):
                upsert_rule(conn, {
                    "id": f"{prefix}-import-{tag}-{i}",
                    "kind": "rule",
                    "content": rule,
                    "summary": summary,
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


SOURCE_KINDS = {"gmail": "gmail", "calendar": "calendar", "readywhen": "readywhen", "you": "manual"}


def import_page(conn: sqlite3.Connection, data: dict) -> dict:
    """Bring over the old Claude-hosted page: to-dos, proposals, messages, the latest brief and the
    assistant's name. Ids already present are skipped, so running it twice is harmless."""
    counts = {"items": 0, "proposals": 0, "messages": 0, "brief": 0}
    for it in data.get("items", []):
        item_id = f"page-{it['id']}"
        if get_item(conn, item_id) is not None or not it.get("title"):
            continue
        label = str(it.get("source") or "")
        kind = next((v for k, v in SOURCE_KINDS.items() if k in label.lower()), "manual")
        add_item(conn, {
            "id": item_id, "title": it["title"], "direction": it.get("direction") or "i-owe",
            "division": it.get("division") if it.get("division") in {"me", "stephanie", "kids"} else "me",
            "status": "done" if it.get("status") == "done" else "open",
            "due": it.get("due"), "notes": it.get("notes") or "",
            "source": {"kind": kind, "label": label} if label else {"kind": "manual"},
            "createdAt": it.get("createdAt") or now(),
        }, actor="system")
        counts["items"] += 1
    for p in data.get("proposals", []):
        if not (p.get("day") and p.get("n")) or conn.execute(
                "SELECT 1 FROM proposals WHERE id = ?", (f"{p['day']}-{p['n']}",)).fetchone():
            continue
        row = {k: p.get(k) or "" for k in PROPOSAL_FIELDS} | {
            "id": f"{p['day']}-{p['n']}", "day": p["day"], "n": int(p["n"]),
            "status": p.get("status") if p.get("status") in {"pending", "approved", "declined", "done", "failed"} else "pending",
            "createdAt": p.get("createdAt") or now()}
        row |= {k: p[k] for k in ("changes", "result", "decidedAt") if p.get(k)}
        _write_proposal(conn, row)
        counts["proposals"] += 1
    for m in data.get("messages", []):
        sender = "owner" if m.get("from") in {"andrew", "owner"} else "assistant"
        if m.get("text") and not conn.execute("SELECT 1 FROM messages WHERE id = ?", (f"page-{m['id']}",)).fetchone():
            add_message(conn, sender, m["text"], at=m.get("createdAt"), status=m.get("status"), message_id=f"page-{m['id']}")
            counts["messages"] += 1
    b = data.get("brief")
    if b and b.get("markdown") and not conn.execute(
            "SELECT 1 FROM briefs WHERE day = ? AND subject = ?", (b.get("day"), b.get("subject"))).fetchone():
        conn.execute("INSERT INTO briefs (at, day, subject, markdown, proposals, capture) VALUES (?, ?, ?, ?, '[]', '{}')",
                     (b.get("updatedAt") or now(), b.get("day") or now()[:10], b.get("subject") or "Brief", b["markdown"]))
        counts["brief"] = 1
    name = (data.get("settings") or {}).get("agentName")
    if name:
        put_setting(conn, "assistant", (get_setting(conn, "assistant", {}) or {}) | {"name": name}, actor="system")
    audit(conn, "system", "import.page", **counts)
    conn.commit()
    return counts


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
        "proposals": [json.loads(r["data"]) for r in conn.execute("SELECT data FROM proposals ORDER BY day, n")],
        "messages": [dict(r) for r in conn.execute("SELECT * FROM messages ORDER BY at")],
    }
