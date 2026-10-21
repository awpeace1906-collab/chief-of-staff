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


# Divisions: who an item is for. Keys and labels are the owner's data (the divisions setting,
# imported from their config); the code never names a person.

def divisions(conn: sqlite3.Connection) -> dict:
    return get_setting(conn, "divisions", {}) or {}


def owner_division(conn: sqlite3.Connection) -> str:
    """The owner's own division: schedule.division, else "me" if it exists, else the first one."""
    keys = list(divisions(conn))
    return (get_setting(conn, "schedule", {}) or {}).get("division") or ("me" if "me" in keys or not keys else keys[0])


def division_or_owner(conn: sqlite3.Connection, key: str | None) -> str:
    return key if key and key in divisions(conn) else owner_division(conn)


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


# Proposals: actions the assistant wants to take, waiting for the owner's OK

PROPOSAL_STATUSES = {"pending", "approved", "declined", "done", "failed"}
PROPOSAL_FIELDS = ("kind", "division", "calendar", "title", "when", "where", "change", "summary",
                   "start", "end", "timeZone", "itemId", "source",  # exact blocks from the day view
                   "eventId")  # Move: the event to change
DRAFT_FIELDS = ("to", "subject", "body", "threadId")  # Send: the email, shown to the owner before it goes


def add_proposal(conn: sqlite3.Connection, proposal: dict, actor: str = "assistant") -> dict:
    """Store a pending proposal. Numbered after the day's existing ones unless `n` is given."""
    day = proposal.get("day") or now()[:10]
    n = proposal.get("n") or 1 + (conn.execute("SELECT MAX(n) FROM proposals WHERE day = ?", (day,)).fetchone()[0] or 0)
    p = {k: proposal.get(k) or "" for k in PROPOSAL_FIELDS} | {
        "id": f"{day}-{n}", "day": day, "n": n, "status": "pending", "createdAt": now()}
    if not (p["title"] or p["summary"]):
        raise ValueError("a proposal needs a title or a summary")
    draft = proposal.get("draft")
    if draft:
        if not (isinstance(draft, dict) and draft.get("to") and draft.get("body")):
            raise ValueError("an email draft needs 'to' and 'body'")
        p["draft"] = {k: str(draft.get(k) or "") for k in DRAFT_FIELDS}
    existing = get_proposal(conn, p["id"])
    if existing and existing["status"] != "pending":
        raise ValueError(f"proposal {p['id']} was already {existing['status']}")
    _write_proposal(conn, p)
    audit(conn, actor, "proposal.add", id=p["id"])
    conn.commit()
    return p


def update_proposal(conn: sqlite3.Connection, proposal_id: str, patch: dict, actor: str = "user") -> dict:
    """The owner approves or declines (optionally with changes); the assistant records done/failed."""
    p = get_proposal(conn, proposal_id)
    if p is None:
        raise KeyError(proposal_id)
    status = patch.get("status", p["status"])
    if status not in PROPOSAL_STATUSES:
        raise ValueError(f"unknown status '{status}'")
    allowed = {"user": {"approved", "declined"}, "assistant": {"done", "failed", "declined", "pending"}}.get(actor, PROPOSAL_STATUSES)
    if "status" in patch and status not in allowed:
        raise ValueError(f"{actor} can't set a proposal to '{status}'")
    if actor == "user" and p["status"] != "pending":
        raise ValueError(f"proposal {proposal_id} is already {p['status']}")
    for k in ("changes", "result"):
        if patch.get(k):
            p[k] = str(patch[k])[:2000]
    if patch.get("draftBody"):
        if actor != "user" or not p.get("draft"):
            raise ValueError("only the owner can edit an email draft")
        p["draftBody"] = str(patch["draftBody"])[:10000]
    p["status"] = status
    p["decidedAt" if actor == "user" else "handledAt"] = now()
    _write_proposal(conn, p)
    audit(conn, actor, "proposal.update", id=proposal_id, status=status)
    conn.commit()
    return p


def get_proposal(conn: sqlite3.Connection, proposal_id: str) -> dict | None:
    row = conn.execute("SELECT data FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    return json.loads(row["data"]) if row else None


def list_proposals(conn: sqlite3.Connection, statuses=None, since_day: str | None = None) -> list[dict]:
    sql, args = "SELECT data FROM proposals WHERE 1=1", []
    if statuses:
        sql += f" AND status IN ({','.join('?' * len(statuses))})"
        args += list(statuses)
    if since_day:
        sql += " AND day >= ?"
        args.append(since_day)
    return [json.loads(r["data"]) for r in conn.execute(sql + " ORDER BY day DESC, n", args)]


def _write_proposal(conn: sqlite3.Connection, p: dict) -> None:
    conn.execute(
        """INSERT INTO proposals (id, day, n, status, data, updated_at) VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET status = excluded.status, data = excluded.data,
             updated_at = excluded.updated_at""",
        (p["id"], p["day"], p["n"], p["status"], json.dumps(p), now()),
    )


# Messages: the owner's line to the assistant

MESSAGE_SENDERS = {"owner", "assistant"}
MESSAGE_KINDS = {"text", "replan"}


def add_message(conn: sqlite3.Connection, sender: str, text: str, at: str | None = None,
                status: str | None = None, message_id: str | None = None, channel: str = "app",
                ref: str | None = None, kind: str = "text", data: dict | None = None) -> dict:
    if sender not in MESSAGE_SENDERS:
        raise ValueError(f"unknown sender '{sender}'")
    if kind not in MESSAGE_KINDS:
        raise ValueError(f"unknown message kind '{kind}'")
    text = (text or "").strip()
    if not text:
        raise ValueError("empty message")
    m = {"id": message_id or f"m-{int(time.time() * 1000)}-{_rand4()}", "at": at or now(), "from": sender,
         "status": status or ("new" if sender == "owner" else "handled"), "text": text[:4000],
         "channel": channel, "ref": ref, "kind": kind, "data": data}
    conn.execute("INSERT OR IGNORE INTO messages (id, at, sender, status, text, channel, ref, kind, data) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (m["id"], m["at"], sender, m["status"], m["text"], channel, ref, kind, json.dumps(data) if data else None))
    conn.commit()
    return m


def list_messages(conn: sqlite3.Connection, limit: int = 40, status: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM messages", []
    if status:
        sql, args = sql + " WHERE status = ?", [status]
    rows = conn.execute(sql + " ORDER BY at DESC LIMIT ?", args + [limit]).fetchall()
    return [{"id": r["id"], "at": r["at"], "from": r["sender"], "status": r["status"], "text": r["text"],
             "channel": r["channel"], "ref": r["ref"], "kind": r["kind"],
             "data": json.loads(r["data"]) if r["data"] else None} for r in reversed(rows)]


def mark_message(conn: sqlite3.Connection, message_id: str, status: str = "handled") -> None:
    if status not in {"new", "handled"}:
        raise ValueError(f"unknown status '{status}'")
    if conn.execute("UPDATE messages SET status = ? WHERE id = ?", (status, message_id)).rowcount == 0:
        raise KeyError(message_id)
    conn.commit()


# Records: decisions, trips, binders, expenses and the tomorrow / week cards, one JSON doc per slug

RECORD_KINDS = {"decision", "trip", "binder", "expense", "card"}


def put_record(conn: sqlite3.Connection, kind: str, record_id: str, data: dict, actor: str = "assistant") -> dict:
    """Create or replace a record. A decided decision keeps the owner's choice."""
    if kind not in RECORD_KINDS:
        raise ValueError(f"unknown record kind '{kind}'")
    if not record_id or "/" in record_id:
        raise ValueError("a record needs a slug id")
    data = {k: v for k, v in data.items() if k not in {"id", "kind"}}
    old = get_record(conn, kind, record_id)
    if kind == "decision":
        if old and old.get("status") == "decided" and actor != "user":
            data |= {k: old[k] for k in ("status", "choice", "choiceLabel", "decidedAt") if k in old}
        data.setdefault("status", "open")
        if not data.get("title") or not data.get("options"):
            raise ValueError("a decision needs a title and options")
    rec = data | {"id": record_id, "kind": kind, "updatedAt": now()}
    conn.execute(
        """INSERT INTO records (kind, id, data, updated_at) VALUES (?, ?, ?, ?)
           ON CONFLICT(kind, id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at""",
        (kind, record_id, json.dumps(rec), rec["updatedAt"]),
    )
    audit(conn, actor, "record.put", kind=kind, id=record_id)
    conn.commit()
    return rec


def get_record(conn: sqlite3.Connection, kind: str, record_id: str) -> dict | None:
    row = conn.execute("SELECT data FROM records WHERE kind = ? AND id = ?", (kind, record_id)).fetchone()
    return json.loads(row["data"]) if row else None


def list_records(conn: sqlite3.Connection, kind: str) -> list[dict]:
    rows = conn.execute("SELECT data FROM records WHERE kind = ? ORDER BY updated_at DESC", (kind,))
    return [json.loads(r["data"]) for r in rows]


def delete_record(conn: sqlite3.Connection, kind: str, record_id: str, actor: str = "user") -> None:
    if conn.execute("DELETE FROM records WHERE kind = ? AND id = ?", (kind, record_id)).rowcount == 0:
        raise KeyError(record_id)
    audit(conn, actor, "record.delete", kind=kind, id=record_id)
    conn.commit()


def choose(conn: sqlite3.Connection, decision_id: str, choice: str) -> dict:
    """The owner picks an option. The assistant turns it into next steps (`actions`) on its next run."""
    d = get_record(conn, "decision", decision_id)
    if d is None:
        raise KeyError(decision_id)
    if d.get("status") != "open":
        raise ValueError(f"decision {decision_id} is already {d.get('status')}")
    option = next((o for o in d["options"] if o.get("id") == choice), None)
    if option is None:
        raise ValueError(f"'{choice}' isn't one of the options")
    return put_record(conn, "decision", decision_id, d | {"status": "decided", "choice": choice,
                                                          "choiceLabel": option.get("label") or choice,
                                                          "decidedAt": now()}, actor="user")
