"""The morning brief (the `plan` route): capture, then plan the day, then deliver."""

import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from . import capture, llm, store
from .db import audit, now
from .google.api import Google

SYSTEM = """You are {name}, the owner's chief of staff. Write their morning brief.

The owner reads it on a phone in about 60 seconds. Lead with what matters today.
Sections, in this order, leaving out any that are empty:
1. **You owe**: overdue first, then due today, then the next 7 days, then things others owe
   the owner that are past due. One line each, with the due date.
2. **Today**: by division ({divisions}), times in {tz} (if the owner is traveling, give local
   and {tz}).
3. **Coverage**: windows in the next 7 days when every adult in the household is busy or away
   and no coverage person (e.g. the nanny) is scheduled. Account for travel and drive time.
   Say "Covered all week" when there are none.
4. **Next 7 days**: only what needs preparation or a decision.
5. **Proposals**: concrete actions (a calendar block, a draft reply, a reschedule), numbered
   so the owner can reply "approve 1, 3". Never claim an action was taken.
6. **Closed since yesterday**: items the capture step marked done, with the evidence.
7. **Questions**: anything the capture step was unsure about.

Rules:
- Apply the owner's standing rules before flagging conflicts.
- Propose; never act. Nothing is sent or changed without the owner's approval.
- No clinical, patient or health details.
- Plain markdown, no tables. Short lines.

Standing rules from the owner:
{rules}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "markdown": {"type": "string"},
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "kind": {"type": "string", "enum": ["calendar", "email", "board", "other"]},
                    "summary": {"type": "string"},
                },
                "required": ["n", "kind", "summary"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["subject", "markdown", "proposals"],
    "additionalProperties": False,
}


def run(conn: sqlite3.Connection, google: Google, client=None, send: bool = False,
        today: datetime | None = None) -> dict:
    """Capture, write the brief, store it, and optionally email it to the owner."""
    tz = ZoneInfo(store.get_setting(conn, "timezone", "UTC"))
    today = today or datetime.now(tz)
    name = store.assistant_name(conn)

    changes = capture.run(conn, google, client=client)
    agenda = google.agenda(7, today=today.date())
    divisions = store.get_setting(conn, "divisions", {})

    system = SYSTEM.format(
        name=name,
        tz=tz.key,
        divisions=", ".join(d.get("label", k) for k, d in divisions.items()) or "me",
        rules="\n".join(f"- {r['content']}" for r in store.list_rules(conn)) or "- (none)",
    )
    user = json.dumps({
        "now": today.isoformat(),
        "board": store.list_items(conn),
        "capture": changes,
        "agenda": agenda,
        "openItems": store.get_setting(conn, "openItems", []),
        "divisionNotes": {k: d.get("notes") for k, d in divisions.items() if d.get("notes")},
        "coveragePeople": {k: d.get("coverage") for k, d in divisions.items() if d.get("coverage")},
    }, ensure_ascii=False, default=str)
    result = llm.complete(conn, "plan", system, user, SCHEMA, client=client)

    prefix = store.get_setting(conn, "brief", {}).get("subjectPrefix") or f"{name}:"
    subject = result["subject"] if result["subject"].startswith(prefix) else f"{prefix} {result['subject']}"
    cur = conn.execute(
        "INSERT INTO briefs (at, day, subject, markdown, proposals, capture) VALUES (?, ?, ?, ?, ?, ?)",
        (now(), today.date().isoformat(), subject, result["markdown"], json.dumps(result["proposals"]),
         json.dumps(changes)),
    )
    brief_id = cur.lastrowid
    conn.commit()  # the brief is kept even if emailing it fails

    sent, send_error = False, None
    if send:
        try:
            google.send_to_owner(subject, result["markdown"])
            conn.execute("UPDATE briefs SET sent = 1 WHERE id = ?", (brief_id,))
            sent = True
        except Exception as e:  # a delivery problem must not trigger a re-run of the whole brief
            send_error = f"{e.__class__.__name__}: {e}"
    audit(conn, "assistant", "brief.run", id=brief_id, sent=sent, sendError=send_error,
          proposals=len(result["proposals"]))
    conn.commit()
    return {"id": brief_id, "day": today.date().isoformat(), "subject": subject, "markdown": result["markdown"],
            "proposals": result["proposals"], "capture": changes, "sent": sent, "sendError": send_error}


def latest(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM briefs ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return None
    return dict(row) | {"proposals": json.loads(row["proposals"]), "capture": json.loads(row["capture"]),
                        "sent": bool(row["sent"])}
