"""The daily brief (the `plan` route): capture, then plan the day, then deliver.

Besides the brief itself, the run files what the principal decides or approves on the Today tab: decisions
for the Situation Room, and proposals, including reply drafts ("Send: …") ready to approve."""

import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import re

from . import accountability, accounts, capture, llm, location, people, schedule, store
from .db import audit, now
from .google.api import Google

SYSTEM = """You are {name}, the principal's chief of staff. Write their daily brief.

The principal reads it on a phone in about 60 seconds. Lead with what matters today.
Sections, in this order, leaving out any that are empty:
0. **Situation Room**: choices only the principal can make, nearest deadline first: the open ones in
   `openDecisions`, plus any new ones you file in `decisions`. One line each, with the deadline and your
   recommendation.
1. **You owe**: overdue first, then due today, then the next 7 days, then things others owe
   the principal that are past due. One line each, with the due date. Mark promises the principal made
   ("you said you'd…") and how many days late anything is.
2. **Today**: by division ({divisions}), times in {tz} (if the principal is traveling, give local
   and {tz}).
3. **Coverage**: windows in the next 7 days when every adult in the household is busy or away
   and no coverage person (e.g. the nanny) is scheduled. Account for travel and drive time.
   Say "Covered all week" when there are none.
4. **Next 7 days**: only what needs preparation or a decision.
5. **Proposals**: concrete actions (a calendar block, a draft reply, a reschedule), numbered
   so the principal can reply "approve 1, 3". Never claim an action was taken. For each, fill the
   proposal fields too: title starts with a verb ("Add: …", "Fix: …", "Move: …", "Send: …"),
   when (times in {tz}), where, calendar (by name), division, change ("old → new" for edits),
   summary (one line: why); use "" for fields that don't apply. Don't repeat anything already
   in pendingProposals, and never propose adding an event that's already on a calendar.
   Accountability: every item in `accountability.overdue`, `dueSoon`, `undatedPromises` and
   `waitingLate` gets a proposal unless a pending one already covers it: a time block for the
   work (use the matching `suggestedBlocks` entry, already fitted into free time; otherwise a
   window from `freeSlots`), a drafted reply, a new date, or for waitingLate a nudge
   to the other person. For `undatedPromises`, propose a date. For each item in
   `accountability.stuck`, ask plainly: do it (with a slot), move it (to a date), or drop it.
   Reply drafts: for every item that's a reply owed, and every owed-to-me item more than 2 days past due,
   propose the email itself (kind "email", title "Send: …") with a draft: to, subject, body (short, in the
   principal's voice, signed with their first name), threadId (the item's source ref, or ""). It goes out
   only once approved. For proposals that aren't emails, every draft field is "".
   Advance: for each interview or important meeting in the next 14 days with no prep block yet, propose
   one the day before, in free time. Set itemId to the to-do a proposal serves, or "".
6. **Closed since yesterday**: items the capture step marked done, with the evidence. Only
   evidence or the principal closes an item: never drop one silently.
7. **Questions**: anything the capture step was unsure about.

Decisions: anything that needs the principal's choice, rather than a task, goes in `decisions`: a short slug
id, title (a question), deadline (YYYY-MM-DD), context (1–2 lines), 2–3 options (id, label, and detail: its
trade-off in one line), recommendation (an option id, or "" when it's purely their call), itemId (or "").
Never file one that's already in `openDecisions` or `decidedDecisions`.

{people}

Rules:
- Never assume where the principal is. Start every drive time, leave-by time and coverage call from
  `whereabouts` (the phone's latest location, else the trip they're on, else home), and name the
  starting point ("from home in …"). If its source is "home" or "unknown", say it's assumed.
- Vernacular: travel is a movement, prep before an event is the advance, the principal's
  location is their position, and the people covering the household are the detail (a coverage
  gap is a hole in the detail).
- Apply the principal's standing rules before flagging conflicts.
- Propose; never act. Nothing is sent or changed without the principal's approval.
- No clinical, patient or health details.
- Plain markdown, no tables. Short lines.

Standing rules from the principal:
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
                    "division": {"type": "string"},
                    "calendar": {"type": "string"},
                    "title": {"type": "string"},
                    "when": {"type": "string"},
                    "where": {"type": "string"},
                    "change": {"type": "string"},
                    "summary": {"type": "string"},
                    "itemId": {"type": "string"},
                    "draft": {
                        "type": "object",
                        "properties": {k: {"type": "string"} for k in ("to", "subject", "body", "threadId")},
                        "required": ["to", "subject", "body", "threadId"],
                        "additionalProperties": False,
                    },
                },
                "required": ["n", "kind", "division", "calendar", "title", "when", "where", "change", "summary",
                             "itemId", "draft"],
                "additionalProperties": False,
            },
        },
        "newPeople": people.SCHEMA,
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "deadline": {"type": "string"},
                    "context": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {k: {"type": "string"} for k in ("id", "label", "detail")},
                            "required": ["id", "label", "detail"],
                            "additionalProperties": False,
                        },
                    },
                    "recommendation": {"type": "string"},
                    "itemId": {"type": "string"},
                },
                "required": ["id", "title", "deadline", "context", "options", "recommendation", "itemId"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["subject", "markdown", "proposals", "decisions", "newPeople"],
    "additionalProperties": False,
}


def run(conn: sqlite3.Connection, google: Google, client=None, send: bool = False,
        today: datetime | None = None, microsoft=None) -> dict:
    """Capture, write the brief, store it, post its proposals, and optionally email it to the principal.
    `microsoft` adds Outlook mail, the Outlook calendar and Microsoft To Do."""
    tz = ZoneInfo(store.get_setting(conn, "timezone", "UTC"))
    today = today or datetime.now(tz)
    name = store.assistant_name(conn)

    changes = capture.run(conn, google, client=client, microsoft=microsoft)
    agenda = accounts.merge_calendars(conn, google.agenda(7, today=today.date()), google.http, today.date(), 7)
    extra = {}
    clients = microsoft if isinstance(microsoft, list) else [microsoft] if microsoft is not None else []
    if clients:
        extra["outlookAgenda"] = accounts.outlook_agenda(clients, 7, today.date())
        todo = []
        for ms in clients:
            try:
                todo += ms.todo()
            except Exception:  # To Do is optional; one account failing doesn't stop the brief
                pass
        extra["microsoftToDo"] = todo
    divisions = store.get_setting(conn, "divisions", {})
    acct = accountability.review(conn, today.date())
    cfg = schedule.settings(conn)
    slots = schedule.free_slots(agenda, today.date(), cfg, now=today)

    system = SYSTEM.format(
        name=name,
        tz=tz.key,
        divisions=", ".join(d.get("label", k) for k, d in divisions.items()) or "me",
        rules="\n".join(f"- {r['content']}" for r in store.list_rules(conn)) or "- (none)",
        people=people.PROMPT.format(where="calendar events (`agenda`)"),
    )
    user = json.dumps({
        "now": today.isoformat(),
        "whereabouts": location.whereabouts(conn, today.date(), now=today),
        "board": store.list_items(conn),
        "accountability": acct,
        "freeSlots": slots[:40],
        "suggestedBlocks": schedule.suggest_blocks(acct, slots, cfg),
        "capture": changes,
        "agenda": agenda,
        "openItems": store.get_setting(conn, "openItems", []),
        "divisionNotes": {k: d.get("notes") for k, d in divisions.items() if d.get("notes")},
        "coveragePeople": {k: d.get("coverage") for k, d in divisions.items() if d.get("coverage")},
        "pendingProposals": store.list_proposals(conn, ("pending", "approved")),
        **people.context(conn),
        "openDecisions": [{k: d.get(k) for k in ("id", "title", "deadline", "recommendation")}
                          for d in store.list_records(conn, "decision") if d.get("status") == "open"],
        "decidedDecisions": [d["id"] for d in store.list_records(conn, "decision") if d.get("status") != "open"],
        "trips": [{k: t.get(k) for k in ("id", "title", "start", "end", "base", "legs", "note")}
                  for t in store.list_records(conn, "trip") if (t.get("end") or "9999") >= today.date().isoformat()],
        **extra,
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
    accountability.mark_surfaced(conn, acct, today.date())
    for p in result["proposals"]:
        draft = p.pop("draft", None) or {}
        if p["kind"] == "email" and draft.get("to") and draft.get("body"):
            p["draft"] = draft
        try:
            store.add_proposal(conn, p | {"day": today.date().isoformat()})
        except ValueError:
            pass  # an empty proposal, or that number was already decided today
    decisions = file_decisions(conn, result.get("decisions") or [])
    people.note(conn, result.get("newPeople") or [], "calendar", today.date())
    decisions += people.ask(conn, today.date())

    sent, send_error = False, None
    if send:
        try:
            google.send_to_owner(subject, result["markdown"])
            conn.execute("UPDATE briefs SET sent = 1 WHERE id = ?", (brief_id,))
            sent = True
        except Exception as e:  # a delivery problem must not trigger a re-run of the whole brief
            send_error = f"{e.__class__.__name__}: {e}"
    audit(conn, "assistant", "brief.run", id=brief_id, sent=sent, sendError=send_error,
          proposals=len(result["proposals"]), decisions=len(decisions))
    conn.commit()
    return {"id": brief_id, "day": today.date().isoformat(), "subject": subject, "markdown": result["markdown"],
            "proposals": result["proposals"], "decisions": decisions, "capture": changes, "sent": sent,
            "sendError": send_error}


SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


def file_decisions(conn: sqlite3.Connection, decisions: list[dict]) -> list[str]:
    """Put new decisions in the Situation Room. One that's already there (open or decided) is left alone:
    the principal may be partway through it. Returns the ids filed."""
    out = []
    for d in decisions:
        options = [o for o in d.get("options") or [] if o.get("id") and o.get("label")]
        if not (SLUG.match(d.get("id") or "") and d.get("title") and len(options) >= 2):
            continue
        if store.get_record(conn, "decision", d["id"]):
            continue
        rec = {"title": d["title"], "deadline": d.get("deadline") or "", "context": d.get("context") or "",
               "options": options, "recommendation": d.get("recommendation") or "", "status": "open"}
        if d.get("itemId"):
            rec["itemId"] = d["itemId"]
        store.put_record(conn, "decision", d["id"], rec)
        out.append(d["id"])
    return out


def latest(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM briefs ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return None
    return dict(row) | {"proposals": json.loads(row["proposals"]), "capture": json.loads(row["capture"]),
                        "sent": bool(row["sent"])}
