"""Capture: turn new mail into board changes (the `triage` route).

Reads inbox, sent mail and the digest intake address since the last capture,
drops senders the digest adapters mark sensitive or ignored, asks the model
for board changes, and applies them. Health-data senders are never opened.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from . import llm, store
from .db import audit, now
from .google.api import Google

MAX_MESSAGES = 60
BODY_CHARS = 2500

SYSTEM = """You are the capture step of a personal chief-of-staff assistant named {name}.
You read the owner's recent email and keep a board of commitments: things the owner owes,
things owed to the owner, deadlines, and household tasks.

For each email decide whether it creates, updates or completes a commitment.
- A commitment needs an owner, a deliverable, and a reason to act. Newsletters, receipts,
  marketing, shipping notices and FYIs with no ask are not commitments: skip them.
- Digest emails (summaries from other systems) can hold several items; handle each.
- "add": a new commitment not already on the board. Title is imperative, under 12 words.
- "update": an open board item changed (new due date, new detail). Give its itemId.
- "close": an open board item is done, with evidence in the mail (the owner sent the
  deliverable, booked the meeting, or the other side confirmed). Give itemId and evidence.
  If the evidence is unclear, do not close; add a question instead.
- direction: i-owe, owed-to-me, deadline, or household.
- division: one of {divisions}. If the ask is really for someone else in the household and
  the owner is only copied, use that person's division.
- due: ISO date if stated (dueConfidence "explicit"), a best inference ("inferred"), or null ("none").
- notes: only what is needed to act. Never copy clinical, patient or health details; for a
  health question from a friend or relative write "Reply owed re: health question".
- sourceRef: the message id the change came from.

Standing rules from the owner:
{rules}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": ["add", "update", "close"]},
                    "itemId": {"type": ["string", "null"]},
                    "title": {"type": "string"},
                    "direction": {"type": "string", "enum": ["i-owe", "owed-to-me", "deadline", "household"]},
                    "division": {"type": "string"},
                    "counterparty": {"type": ["string", "null"]},
                    "due": {"type": ["string", "null"]},
                    "dueConfidence": {"type": "string", "enum": ["explicit", "inferred", "none"]},
                    "notes": {"type": "string"},
                    "evidence": {"type": ["string", "null"]},
                    "sourceRef": {"type": "string"},
                },
                "required": ["op", "itemId", "title", "direction", "division", "counterparty", "due",
                             "dueConfidence", "notes", "evidence", "sourceRef"],
                "additionalProperties": False,
            },
        },
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["changes", "questions"],
    "additionalProperties": False,
}


def run(conn: sqlite3.Connection, google: Google, client=None, since: datetime | None = None) -> dict:
    """Capture since the last run (default: last 24 hours) and apply the changes."""
    state = store.get_setting(conn, "capture", {})
    started = datetime.now(timezone.utc)
    since = since or _parse(state.get("lastCaptureAt")) or started - timedelta(days=1)
    days = max(1, (started - since).days + 1)  # Gmail's newer_than is day-granular

    messages = _gather(conn, google, days, since)
    if not messages:
        store.put_setting(conn, "capture", state | {"lastCaptureAt": now()}, actor="system")
        return {"messages": 0, "added": [], "updated": [], "closed": [], "questions": [], "skipped": []}

    divisions = list(store.get_setting(conn, "divisions", {}) or {"me": {}})
    system = SYSTEM.format(
        name=store.assistant_name(conn),
        divisions=", ".join(divisions),
        rules="\n".join(f"- {r['content']}" for r in store.list_rules(conn)) or "- (none)",
    )
    board = [{k: i.get(k) for k in ("id", "title", "status", "division", "due", "counterparty")}
             for i in store.list_items(conn)]
    user = json.dumps({"openBoardItems": board, "emails": messages}, ensure_ascii=False)
    result = llm.complete(conn, "triage", system, user, SCHEMA, client=client)

    applied = _apply(conn, result["changes"], {m["id"]: m for m in messages}, set(divisions))
    applied["questions"] = result["questions"]
    applied["messages"] = len(messages)
    store.put_setting(conn, "capture", state | {"lastCaptureAt": started.isoformat()}, actor="system")
    audit(conn, "assistant", "capture.run", **{k: len(v) if isinstance(v, list) else v for k, v in applied.items()})
    conn.commit()
    return applied


def _gather(conn: sqlite3.Connection, google: Google, days: int, since: datetime) -> list[dict]:
    blocked = _blocked_senders(conn)
    intake = store.get_setting(conn, "google", {}).get("intakeAddress")
    queries = [f"in:inbox newer_than:{days}d -category:promotions -category:social",
               f"in:sent newer_than:{days}d"]
    if intake:
        queries.append(f"to:{intake} newer_than:{days}d")
    seen, out = set(), []
    for q in queries:
        for m in google.search(q, MAX_MESSAGES):
            if m["id"] in seen or len(out) >= MAX_MESSAGES:
                continue
            seen.add(m["id"])
            sender = (m.get("from") or "").lower()
            if any(b in sender for b in blocked):
                continue
            out.append({
                "id": m["id"], "threadId": m["threadId"], "date": m["date"], "from": m["from"], "to": m["to"],
                "subject": m["subject"], "sent": "SENT" in m["labels"], "body": m["body"][:BODY_CHARS],
            })
    return out


def _blocked_senders(conn: sqlite3.Connection) -> set[str]:
    """Senders whose digest adapter says never read (sensitive) or skip (ignore)."""
    adapters = (store.get_setting(conn, "digests", {}) or {}).get("adapters", [])
    return {f.lower() for a in adapters if a.get("handling") in {"sensitive", "ignore"}
            for f in a.get("match", {}).get("from", [])}


def _apply(conn: sqlite3.Connection, changes: list[dict], messages: dict, divisions: set[str]) -> dict:
    added, updated, closed, skipped = [], [], [], []
    for ch in changes:
        msg = messages.get(ch["sourceRef"], {})
        division = ch["division"] if ch["division"] in divisions else "me"
        try:
            if ch["op"] == "add":
                if _duplicate(conn, msg.get("threadId"), ch["title"]):
                    skipped.append(ch["title"])
                    continue
                item = store.add_item(conn, {
                    "title": ch["title"], "direction": ch["direction"], "division": division,
                    "counterparty": ch["counterparty"], "due": ch["due"], "dueConfidence": ch["dueConfidence"],
                    "notes": ch["notes"],
                    "source": {"kind": "gmail", "ref": msg.get("threadId") or ch["sourceRef"], "url": msg.get("url")},
                })
                added.append({"id": item["id"], "title": item["title"]})
            elif ch["op"] == "update" and ch["itemId"]:
                store.update_item(conn, ch["itemId"], {k: ch[k] for k in ("due", "dueConfidence", "notes")}, actor="assistant")
                updated.append({"id": ch["itemId"], "title": ch["title"]})
            elif ch["op"] == "close" and ch["itemId"] and ch["evidence"]:
                store.update_item(conn, ch["itemId"], {"status": "done", "evidence": ch["evidence"]}, actor="assistant")
                closed.append({"id": ch["itemId"], "title": ch["title"], "evidence": ch["evidence"]})
            else:
                skipped.append(ch["title"])
        except (KeyError, ValueError):
            skipped.append(ch["title"])  # unknown item id or invalid change: never guess
    return {"added": added, "updated": updated, "closed": closed, "skipped": skipped}


def _duplicate(conn: sqlite3.Connection, thread_id: str | None, title: str) -> bool:
    for item in store.list_items(conn):
        if thread_id and item.get("source", {}).get("ref") == thread_id:
            return True
        if item["title"].strip().lower() == title.strip().lower():
            return True
    return False


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))
