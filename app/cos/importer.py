"""Import the current setup (repo config, Brain export, board export) into the database."""

import json
import sqlite3
from pathlib import Path

from .db import audit, now
from .store import (
    BOARD_STATUSES,
    DRAFT_FIELDS,
    PROPOSAL_FIELDS,
    RECORD_KINDS,
    _write_proposal,
    add_message,
    assistant_name,
    division_or_owner,
    get_setting,
    add_item,
    all_settings,
    get_item,
    get_record,
    list_items,
    list_records,
    list_rules,
    put_record,
    put_setting,
    upsert_rule,
)

RULE_KINDS = {"rule", "preference", "context"}


def import_config(conn: sqlite3.Connection, config_dir: Path) -> dict:
    """Load the assistant config (any *.json with an "assistant" key) and config/digests.json."""
    counts = {"settings": 0, "rules": 0}
    config_dir = Path(config_dir)

    assistant_files = [p for p in config_dir.glob("*.json") if p.name != "digests.json"]
    for path in assistant_files:
        cfg = json.loads(path.read_text())
        if "assistant" not in cfg:
            continue
        for key in ("assistant", "timezone", "brief", "approvals", "divisions", "hosting", "openItems", "google",
                    "microsoft", "sms", "appUrl", "check"):
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


ITEM_EXTRAS = ("promise", "counterparty", "nudges", "lastSurfaced", "top", "kind", "expires")
SOURCE_KINDS = {"gmail": "gmail", "calendar": "calendar", "readywhen": "readywhen", "you": "manual"}


def import_page(conn: sqlite3.Connection, data: dict) -> dict:
    """Bring over the old Claude-hosted page: to-dos, proposals, messages, the latest brief, decisions,
    trips, binders, expenses, the tomorrow and week cards, and the assistant's name. Ids already present
    are skipped, so running it twice is harmless."""
    counts = {"items": 0, "proposals": 0, "messages": 0, "brief": 0, "records": 0}
    for it in data.get("items", []):
        item_id = f"page-{it['id']}"
        if get_item(conn, item_id) is not None or not it.get("title"):
            continue
        label = str(it.get("source") or "")
        kind = next((v for k, v in SOURCE_KINDS.items() if k in label.lower()), "manual")
        add_item(conn, {
            "id": item_id, "title": it["title"], "direction": it.get("direction") or "i-owe",
            "division": division_or_owner(conn, it.get("division")),
            "status": "done" if it.get("status") == "done" else "open",
            "due": it.get("due"), "notes": it.get("notes") or "",
            "source": {"kind": kind, "label": label} if label else {"kind": "manual"},
            "createdAt": it.get("createdAt") or now(),
        } | {k: it[k] for k in ITEM_EXTRAS if it.get(k) not in (None, "")}, actor="system")
        counts["items"] += 1
    for p in data.get("proposals", []):
        if not (p.get("day") and p.get("n")) or conn.execute(
                "SELECT 1 FROM proposals WHERE id = ?", (f"{p['day']}-{p['n']}",)).fetchone():
            continue
        row = {k: p.get(k) or "" for k in PROPOSAL_FIELDS} | {
            "id": f"{p['day']}-{p['n']}", "day": p["day"], "n": int(p["n"]),
            "status": p.get("status") if p.get("status") in {"pending", "approved", "declined", "done", "failed"} else "pending",
            "createdAt": p.get("createdAt") or now()}
        row |= {k: p[k] for k in ("changes", "result", "decidedAt", "draftBody") if p.get(k)}
        if isinstance(p.get("draft"), dict) and p["draft"].get("to"):
            row["draft"] = {k: str(p["draft"].get(k) or "") for k in DRAFT_FIELDS}
        _write_proposal(conn, row)
        counts["proposals"] += 1
    agent = str((data.get("settings") or {}).get("agentName") or assistant_name(conn)).lower()
    for m in data.get("messages", []):
        sender = "assistant" if str(m.get("from") or "").lower() in {"assistant", agent} else "owner"
        if m.get("text") and not conn.execute("SELECT 1 FROM messages WHERE id = ?", (f"page-{m['id']}",)).fetchone():
            add_message(conn, sender, m["text"], at=m.get("createdAt"), status=m.get("status"), message_id=f"page-{m['id']}")
            counts["messages"] += 1
    b = data.get("brief")
    if b and b.get("markdown") and not conn.execute(
            "SELECT 1 FROM briefs WHERE day = ? AND subject = ?", (b.get("day"), b.get("subject"))).fetchone():
        conn.execute("INSERT INTO briefs (at, day, subject, markdown, proposals, capture) VALUES (?, ?, ?, ?, '[]', '{}')",
                     (b.get("updatedAt") or now(), b.get("day") or now()[:10], b.get("subject") or "Brief", b["markdown"]))
        counts["brief"] = 1
    for key, kind in (("decisions", "decision"), ("trips", "trip"), ("binders", "binder"), ("expenses", "expense")):
        for r in data.get(key, []):
            if r.get("id") and get_record(conn, kind, r["id"]) is None:
                try:
                    put_record(conn, kind, r["id"], r, actor="system")
                    counts["records"] += 1
                except ValueError:
                    pass
    for card in ("tomorrow", "week"):
        c = data.get(card)
        if c and c.get("markdown") and get_record(conn, "card", card) is None:
            put_record(conn, "card", card, c, actor="system")
            counts["records"] += 1
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
        "records": {kind: list_records(conn, kind) for kind in sorted(RECORD_KINDS)},
    }
