"""SQLite storage: one file holds settings, rules, the board and the audit log."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL              -- JSON
);

CREATE TABLE IF NOT EXISTS rules (
    id         TEXT PRIMARY KEY,     -- Brain-compatible id, e.g. tower-1760900000000-ab12
    kind       TEXT NOT NULL,        -- rule | preference | context
    content    TEXT NOT NULL,
    summary    TEXT NOT NULL DEFAULT '',
    archived   INTEGER NOT NULL DEFAULT 0,
    source     TEXT NOT NULL DEFAULT 'local',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS board_items (
    id         TEXT PRIMARY KEY,     -- c-<ms>-<rand4>
    status     TEXT NOT NULL,
    division   TEXT NOT NULL,
    due        TEXT,
    data       TEXT NOT NULL,        -- full cos-board/v1 item as JSON
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    at     TEXT NOT NULL,
    actor  TEXT NOT NULL,            -- assistant | user | system
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}'
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def default_path() -> Path:
    return Path(os.environ.get("COS_DATA_DIR", "./data")) / "cos.db"


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(path) if path else default_path()
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    return conn


def audit(conn: sqlite3.Connection, actor: str, action: str, **detail) -> None:
    conn.execute(
        "INSERT INTO audit_log (at, actor, action, detail) VALUES (?, ?, ?, ?)",
        (now(), actor, action, json.dumps(detail)),
    )
