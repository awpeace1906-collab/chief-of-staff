"""Read and write settings, rules and board items."""

import json
import random
import sqlite3
import string
import time

from .db import audit, now

BOARD_STATUSES = {"open", "proposed", "waiting", "snoozed", "done", "dropped"}
ACTIVE_STATUSES = ("open", "proposed", "waiting")


# Settings: one JSON value per key ("assistant", "divisions", "digests", "ai", ...)

def get_setting(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def all_settings(conn: sqlite3.Connection) -> dict:
    return {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT key, value FROM settings ORDER BY key")}


def put_setting(conn: sqlite3.Connection, key: str, value, actor: str = "user") -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )
    audit(conn, actor, "setting.put", key=key)
    conn.commit()


def assistant_name(conn: sqlite3.Connection) -> str:
    return get_setting(conn, "assistant", {}).get("name") or "Assistant"


# Rules: the assistant's long-term memory (Brain-compatible)

def new_rule_id(conn: sqlite3.Connection) -> str:
    prefix = assistant_name(conn).lower().replace(" ", "-")
    return f"{prefix}-{int(time.time() * 1000)}-{_rand4()}"


def upsert_rule(conn: sqlite3.Connection, rule: dict, actor: str = "system") -> None:
    conn.execute(
        """INSERT INTO rules (id, kind, content, summary, archived, source, updated_at)
           VALUES (:id, :kind, :content, :summary, :archived, :source, :updated_at)
           ON CONFLICT(id) DO UPDATE SET kind = excluded.kind, content = excluded.content,
             summary = excluded.summary, archived = excluded.archived, source = excluded.source,
             updated_at = excluded.updated_at""",
        {"summary": "", "archived": 0, "source": "local", "updated_at": now(), **rule},
    )
    audit(conn, actor, "rule.upsert", id=rule["id"])


def list_rules(conn: sqlite3.Connection, include_archived: bool = False) -> list[dict]:
    sql = "SELECT * FROM rules" + ("" if include_archived else " WHERE archived = 0") + " ORDER BY updated_at"
    return [dict(r) | {"archived": bool(r["archived"])} for r in conn.execute(sql)]


# Board: commitments (cos-board/v1 items)

def new_item_id() -> str:
    return f"c-{int(time.time() * 1000)}-{_rand4()}"


def add_item(conn: sqlite3.Connection, item: dict, actor: str = "assistant") -> dict:
    item = {"status": "open", **item}
    item.setdefault("id", new_item_id())
    item.setdefault("createdAt", now())
    item["updatedAt"] = now()
    _validate_item(item)
    _write_item(conn, item)
    audit(conn, actor, "board.add", id=item["id"], title=item["title"])
    conn.commit()
    return item


def update_item(conn: sqlite3.Connection, item_id: str, patch: dict, actor: str = "user") -> dict:
    item = get_item(conn, item_id)
    if item is None:
        raise KeyError(item_id)
    item.update({k: v for k, v in patch.items() if k not in {"id", "createdAt"}})
    item["updatedAt"] = now()
    _validate_item(item)
    _write_item(conn, item)
    audit(conn, actor, "board.update", id=item_id, fields=sorted(patch))
    conn.commit()
    return item


def get_item(conn: sqlite3.Connection, item_id: str) -> dict | None:
    row = conn.execute("SELECT data FROM board_items WHERE id = ?", (item_id,)).fetchone()
    return json.loads(row["data"]) if row else None


def list_items(conn: sqlite3.Connection, statuses=ACTIVE_STATUSES) -> list[dict]:
    marks = ",".join("?" * len(statuses))
    rows = conn.execute(
        f"SELECT data FROM board_items WHERE status IN ({marks}) ORDER BY due IS NULL, due, updated_at",
        tuple(statuses),
    )
    return [json.loads(r["data"]) for r in rows]


def _write_item(conn: sqlite3.Connection, item: dict) -> None:
    conn.execute(
        """INSERT INTO board_items (id, status, division, due, data, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET status = excluded.status, division = excluded.division,
             due = excluded.due, data = excluded.data, updated_at = excluded.updated_at""",
        (item["id"], item["status"], item["division"], item.get("due"), json.dumps(item), item["updatedAt"]),
    )


def _validate_item(item: dict) -> None:
    for field in ("title", "direction", "division", "status"):
        if not item.get(field):
            raise ValueError(f"board item needs '{field}'")
    if item["status"] not in BOARD_STATUSES:
        raise ValueError(f"unknown status '{item['status']}'")


def _rand4() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
