"""SQLite storage: one file holds settings, rules, the board and the audit log."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 6

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL              -- JSON
);

CREATE TABLE IF NOT EXISTS rules (
    id         TEXT PRIMARY KEY,     -- Brain-compatible id, e.g. <assistant>-1760900000000-ab12
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

CREATE TABLE IF NOT EXISTS secrets (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL              -- JSON; OAuth tokens and the like, never exported
);

CREATE TABLE IF NOT EXISTS ai_usage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    route       TEXT NOT NULL,
    provider    TEXT NOT NULL,
    model       TEXT NOT NULL,
    input       INTEGER NOT NULL,
    output      INTEGER NOT NULL,
    cache_read  INTEGER NOT NULL DEFAULT 0,
    cache_write INTEGER NOT NULL DEFAULT 0,
    stop_reason TEXT
);

CREATE TABLE IF NOT EXISTS briefs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        TEXT NOT NULL,
    day       TEXT NOT NULL,         -- local date the brief is for
    subject   TEXT NOT NULL,
    markdown  TEXT NOT NULL,
    proposals TEXT NOT NULL,         -- JSON list
    capture   TEXT NOT NULL,         -- JSON changelog from the capture step
    sent      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS proposals (
    id         TEXT PRIMARY KEY,     -- <day>-<n>, e.g. 2026-10-20-3
    day        TEXT NOT NULL,
    n          INTEGER NOT NULL,
    status     TEXT NOT NULL,        -- pending | approved | declined | done | failed
    data       TEXT NOT NULL,        -- full proposal as JSON
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id     TEXT PRIMARY KEY,         -- m-<ms>-<rand4>
    at     TEXT NOT NULL,
    sender TEXT NOT NULL,            -- owner | assistant
    status TEXT NOT NULL,            -- new | handled
    text   TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'app',  -- app | email
    ref    TEXT,                     -- e.g. the email's message id, for replies
    kind   TEXT NOT NULL DEFAULT 'text', -- text | replan
    data   TEXT                      -- JSON extras, e.g. a replan's day and time zone
);

CREATE TABLE IF NOT EXISTS records (
    kind       TEXT NOT NULL,        -- decision | trip | binder | expense | card
    id         TEXT NOT NULL,        -- a slug, e.g. job-offer-reply, or tomorrow / week for cards
    data       TEXT NOT NULL,        -- JSON
    updated_at TEXT NOT NULL,
    PRIMARY KEY (kind, id)
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
        path.touch(mode=0o600, exist_ok=True)  # holds OAuth tokens: owner-only
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    return conn


# Columns added after a table first shipped: (table, column, definition)
ADDED_COLUMNS = [
    ("messages", "channel", "TEXT NOT NULL DEFAULT 'app'"),  # v5
    ("messages", "ref", "TEXT"),                              # v5
    ("messages", "kind", "TEXT NOT NULL DEFAULT 'text'"),     # v6
    ("messages", "data", "TEXT"),                             # v6
]


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring an older database up to date; CREATE TABLE IF NOT EXISTS never adds columns."""
    for table, column, definition in ADDED_COLUMNS:
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.commit()


def audit(conn: sqlite3.Connection, actor: str, action: str, **detail) -> None:
    conn.execute(
        "INSERT INTO audit_log (at, actor, action, detail) VALUES (?, ?, ?, ?)",
        (now(), actor, action, json.dumps(detail)),
    )


def get_secret(conn: sqlite3.Connection, key: str):
    row = conn.execute("SELECT value FROM secrets WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else None


def put_secret(conn: sqlite3.Connection, key: str, value) -> None:
    """Store a secret; None deletes it. The caller commits."""
    if value is None:
        conn.execute("DELETE FROM secrets WHERE key = ?", (key,))
    else:
        conn.execute(
            "INSERT INTO secrets (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
