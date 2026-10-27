"""Capture: turn new mail into board changes and travel records (the `triage` route).

Reads inbox, sent mail and the digest intake address since the last capture, from the main Google account
and every watched Google and Microsoft 365 account (cos/accounts.py). Drops senders the digest adapters mark
sensitive or ignored, asks the model for board changes plus the trips, rotation binders and expenses the
mail describes, and applies them. Health-data senders are never opened.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import re

from . import accounts, llm, store
from .db import audit, now
from .google.api import Google

MAX_MESSAGES = 60        # from the main Google account
MAX_PER_ACCOUNT = 25     # from each watched account
MAX_TOTAL = 150
BODY_CHARS = 2500
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")

SYSTEM = """You are the capture step of a personal chief-of-staff assistant named {name}.
You read the principal's recent email and keep a board of commitments: things the principal owes,
things owed to the principal, deadlines, and household tasks.

For each email decide whether it creates, updates or completes a commitment.
- A commitment needs an owner, a deliverable, and a reason to act. Newsletters, receipts,
  marketing, shipping notices and FYIs with no ask are not commitments: skip them.
- Digest emails (summaries from other systems) can hold several items; handle each.
- Sent mail ("sent": true) is the principal's own words. Any promise in it ("I'll send…",
  "I will complete the paperwork", "let me get back to you") is an i-owe commitment to the
  recipient (counterparty). Infer a due date from the wording ("asap" = 2 days, "this week"
  = Friday) and mark it "inferred". A sent reply can also close an open item it delivers.
- "add": a new commitment not already on the board. Title is imperative, under 12 words.
- "update": an open board item changed (new due date, new detail). Give its itemId.
- "close": an open board item is done, with evidence in the mail (the principal sent the
  deliverable, booked the meeting, or the other side confirmed). Give itemId and evidence.
  If the evidence is unclear, do not close; add a question instead.
- direction: i-owe, owed-to-me, deadline, or household.
- division: one of {divisions}. If the ask is really for someone else in the household and
  the principal is only copied, use that person's division.
- due: ISO date if stated (dueConfidence "explicit"), a best inference ("inferred"), or null ("none").
- notes: only what is needed to act. Never copy clinical, patient or health details; for a
  health question from a friend or relative write "Reply owed re: health question".
- sourceRef: the message id the change came from.
- "account" on an email names the mailbox it came from (the principal's other accounts); it's still the
  principal's mail.

Records (leave a list empty when the mail has nothing for it):
- trips: flight, hotel, car-rental and itinerary mail (airlines, Expedia, TripIt, rotation housing). Return the
  whole trip: an existing trip from `trips` with its id and every leg (kept, changed or added), or a new one with
  a short slug id ("stl-rotation-2026"). Flight legs need flight (carrier code and number, "AA 690"), date (local
  departure date, YYYY-MM-DD), from and to (IATA codes); when is the local departure time in words ("Sun Oct 25
  5:36pm MT"). Use "" for anything unknown. base is where the principal stays (hotel or apartment), or "". A
  delay or cancellation updates the leg's detail. Note what's still missing ("return flight not found").
- binders: intake mail for a new rotation or program (first-day instructions, contacts, rules). sections are
  short headed lists ({{h, lines}}). Never copy passwords or keys: say where they're kept.
- expenses: receipts for travel or rotation costs (flights, bags, seats, rides, hotels, parking, meals while
  away). id is a slug like "aa-bags-2026-10-24"; group is the trip or rotation title. Skip personal shopping and
  anything already in `recentExpenses`.

Standing rules from the principal:
{rules}"""

STR = {"type": "string"}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


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
        "trips": {"type": "array", "items": _obj({
            "id": STR, "title": STR, "start": STR, "end": STR, "status": STR, "note": STR, "base": STR,
            "legs": {"type": "array", "items": _obj({k: STR for k in ("when", "what", "detail", "flight", "date",
                                                                      "from", "to")})},
        })},
        "binders": {"type": "array", "items": _obj({
            "id": STR, "title": STR, "start": STR, "end": STR,
            "sections": {"type": "array", "items": _obj({"h": STR, "lines": {"type": "array", "items": STR}})},
        })},
        "expenses": {"type": "array", "items": _obj({
            "id": STR, "date": STR, "vendor": STR, "amount": {"type": "number"}, "group": STR,
        })},
    },
    "required": ["changes", "questions", "trips", "binders", "expenses"],
    "additionalProperties": False,
}


def run(conn: sqlite3.Connection, google: Google, client=None, since: datetime | None = None,
        microsoft=None) -> dict:
    """Capture since the last run (default: last 24 hours) and apply the changes.
    `microsoft` (a cos.microsoft.api.Microsoft) adds Outlook inbox and sent mail."""
    state = store.get_setting(conn, "capture", {})
    started = datetime.now(timezone.utc)
    since = since or _parse(state.get("lastCaptureAt")) or started - timedelta(days=1)
    days = max(1, (started - since).days + 1)  # Gmail's newer_than is day-granular

    messages, errors = _gather(conn, google, days, since), []
    for account, watcher in accounts.google_watchers(conn, getattr(google, "http", None)):
        if account.get("mail", True):
            try:
                messages += _gather_watched(conn, watcher, account, days)
            except Exception as e:  # one account failing never blocks the others
                errors.append(f"{account.get('email')}: {e.__class__.__name__}: {e}"[:300])
    clients = microsoft if isinstance(microsoft, list) else [microsoft] if microsoft is not None else []
    for ms in clients:
        if not getattr(ms, "account", {}).get("mail", True):
            continue
        try:
            messages += _gather_outlook(conn, ms, since, min(MAX_PER_ACCOUNT if clients[1:] else MAX_MESSAGES,
                                                             MAX_TOTAL - len(messages)))
        except Exception as e:
            errors.append(f"{getattr(ms, 'account', {}).get('email') or 'Microsoft 365'}: {e.__class__.__name__}: {e}"[:300])
    messages = messages[:MAX_TOTAL]
    if not messages:
        store.put_setting(conn, "capture", state | {"lastCaptureAt": now()}, actor="system")
        return {"messages": 0, "added": [], "updated": [], "closed": [], "questions": [], "skipped": [],
                "records": {"trips": [], "binders": [], "expenses": []}, "errors": errors}

    divisions = list(store.get_setting(conn, "divisions", {}) or {"me": {}})
    system = SYSTEM.format(
        name=store.assistant_name(conn),
        divisions=", ".join(divisions),
        rules="\n".join(f"- {r['content']}" for r in store.list_rules(conn)) or "- (none)",
    )
    board = [{k: i.get(k) for k in ("id", "title", "status", "division", "due", "counterparty")}
             for i in store.list_items(conn)]
    user = json.dumps({"openBoardItems": board, **_record_context(conn), "emails": messages}, ensure_ascii=False)
    result = llm.complete(conn, "triage", system, user, SCHEMA, client=client)

    applied = _apply(conn, result["changes"], {m["id"]: m for m in messages}, set(divisions))
    applied["records"] = apply_records(conn, result)
    applied["questions"] = result["questions"]
    applied["messages"] = len(messages)
    applied["errors"] = errors
    store.put_setting(conn, "capture", state | {"lastCaptureAt": started.isoformat()}, actor="system")
    audit(conn, "assistant", "capture.run", **{k: len(v) if isinstance(v, list) else v for k, v in applied.items()
                                               if k != "records"},
          records={k: len(v) for k, v in applied["records"].items()})
    conn.commit()
    return applied


def _gather(conn: sqlite3.Connection, google: Google, days: int, since: datetime) -> list[dict]:
    blocked = _blocked_senders(conn)
    intake = store.get_setting(conn, "google", {}).get("intakeAddress")
    queries = [f"newer_than:{days}d -in:sent -category:promotions -category:social",  # archived mail too
               f"in:sent newer_than:{days}d"]
    if intake:
        queries.append(f"to:{intake} newer_than:{days}d")
    owner = (store.get_setting(conn, "assistant", {}) or {}).get("email", "").lower()
    seen, out = set(), []
    for q in queries:
        for m in google.search(q, MAX_MESSAGES):
            if m["id"] in seen or len(out) >= MAX_MESSAGES:
                continue
            seen.add(m["id"])
            sender = (m.get("from") or "").lower()
            if any(b in sender for b in blocked):
                continue
            if intake and owner and owner in sender and intake.lower() in (m.get("to") or "").lower():
                continue  # the principal writing to the assistant: a message, handled by the check, not a commitment
            out.append({
                "id": m["id"], "threadId": m["threadId"], "date": m["date"], "from": m["from"], "to": m["to"],
                "subject": m["subject"], "sent": "SENT" in m["labels"], "body": m["body"][:BODY_CHARS],
            })
    return out


def _gather_watched(conn: sqlite3.Connection, google: Google, account: dict, days: int) -> list[dict]:
    """Inbox and sent mail from one of the principal's other Google accounts. Ids carry the account, so they
    can't collide with the main mailbox."""
    blocked, seen, out = _blocked_senders(conn), set(), []
    for q in (f"newer_than:{days}d -in:sent -category:promotions -category:social", f"in:sent newer_than:{days}d"):
        for m in google.search(q, MAX_PER_ACCOUNT):
            if m["id"] in seen or len(out) >= MAX_PER_ACCOUNT:
                continue
            seen.add(m["id"])
            if any(b in (m.get("from") or "").lower() for b in blocked):
                continue
            out.append({
                "id": f"{account['id']}:{m['id']}", "threadId": m["threadId"], "date": m["date"], "from": m["from"],
                "to": m["to"], "subject": m["subject"], "sent": "SENT" in m["labels"], "body": m["body"][:BODY_CHARS],
                "account": account.get("email"), "url": m.get("url"),
            })
    return out


def _gather_outlook(conn: sqlite3.Connection, microsoft, since: datetime, room: int) -> list[dict]:
    blocked, out = _blocked_senders(conn), []
    account = (getattr(microsoft, "account", None) or {}).get("email")
    for folder in ("inbox", "sentitems"):
        if room - len(out) <= 0:
            break
        for m in microsoft.search(folder=folder, since=since, limit=room - len(out)):
            if any(b in (m.get("from") or "").lower() for b in blocked):
                continue
            out.append({
                "id": m["id"], "threadId": m["threadId"], "date": m["date"], "from": m["from"], "to": m["to"],
                "subject": m["subject"], "sent": folder == "sentitems", "body": m["body"][:BODY_CHARS],
                "mailbox": "outlook", **({"account": account} if account else {}),
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
        division = ch["division"] if ch["division"] in divisions else store.owner_division(conn)
        try:
            if ch["op"] == "add":
                if _duplicate(conn, msg.get("threadId"), ch["title"]):
                    skipped.append(ch["title"])
                    continue
                item = store.add_item(conn, {
                    "title": ch["title"], "direction": ch["direction"], "division": division,
                    "counterparty": ch["counterparty"], "due": ch["due"], "dueConfidence": ch["dueConfidence"],
                    "notes": ch["notes"],
                    "promise": bool(msg.get("sent")) and ch["direction"] == "i-owe",
                    "source": {"kind": "outlook" if msg.get("mailbox") == "outlook" else "gmail",
                               "ref": msg.get("threadId") or ch["sourceRef"], "url": msg.get("url"),
                               **({"account": msg["account"]} if msg.get("account") else {})},
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


def _record_context(conn: sqlite3.Connection) -> dict:
    """What the model needs to update records instead of duplicating them."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=45)).date().isoformat()
    return {
        "trips": [{k: t.get(k) for k in ("id", "title", "start", "end", "status", "note", "legs")} | {
            "base": (t.get("base") or {}).get("label", "")} for t in store.list_records(conn, "trip")
            if (t.get("end") or "9999") >= cutoff],
        "binders": [{"id": b["id"], "title": b.get("title"), "start": b.get("start"), "end": b.get("end"),
                     "headings": [x.get("h") for x in b.get("sections") or []]}
                    for b in store.list_records(conn, "binder") if (b.get("end") or "9999") >= cutoff],
        "recentExpenses": [{k: e.get(k) for k in ("id", "date", "vendor", "amount")}
                           for e in store.list_records(conn, "expense") if (e.get("date") or "") >= cutoff],
    }


def apply_records(conn: sqlite3.Connection, result: dict) -> dict:
    """File the trips, binders and expenses the model found. Updates merge into what's there: a field left
    empty keeps its old value, binder sections replace only the same heading, and an expense already on
    file (same id, or same date, vendor and amount) is skipped. Returns the ids filed, by kind."""
    out = {"trips": [], "binders": [], "expenses": []}
    for t in result.get("trips") or []:
        if not (SLUG_RE.match(t.get("id") or "") and t.get("title")):
            continue
        old = store.get_record(conn, "trip", t["id"]) or {}
        rec = old | {k: t[k] for k in ("title", "start", "end", "status", "note") if t.get(k)}
        if t.get("base"):
            rec["base"] = (old.get("base") or {}) | {"label": t["base"]}
        if t.get("legs"):
            rec["legs"] = [_merge_leg(old.get("legs") or [], {k: v for k, v in leg.items() if v}) for leg in t["legs"]]
        rec.setdefault("status", "booked")
        store.put_record(conn, "trip", t["id"], rec)
        out["trips"].append(t["id"])
    for b in result.get("binders") or []:
        if not (SLUG_RE.match(b.get("id") or "") and b.get("title")):
            continue
        old = store.get_record(conn, "binder", b["id"]) or {}
        sections = {s.get("h"): s for s in old.get("sections") or []}
        for sec in b.get("sections") or []:
            if sec.get("h") and sec.get("lines"):
                sections[sec["h"]] = {"h": sec["h"], "lines": [str(x)[:300] for x in sec["lines"]][:30]}
        rec = old | {k: b[k] for k in ("title", "start", "end") if b.get(k)} | {"sections": list(sections.values())}
        store.put_record(conn, "binder", b["id"], rec)
        out["binders"].append(b["id"])
    existing = {(e.get("date"), (e.get("vendor") or "").lower(), round(float(e.get("amount") or 0), 2))
                for e in store.list_records(conn, "expense")}
    for e in result.get("expenses") or []:
        try:
            amount = round(float(e.get("amount")), 2)
        except (TypeError, ValueError):
            continue
        sig = (e.get("date"), (e.get("vendor") or "").lower(), amount)
        if not (SLUG_RE.match(e.get("id") or "") and e.get("vendor") and amount > 0) or sig in existing \
                or store.get_record(conn, "expense", e["id"]):
            continue
        store.put_record(conn, "expense", e["id"], {"date": e.get("date"), "vendor": e["vendor"], "amount": amount,
                                                    "group": e.get("group") or "", "source": "mail"})
        existing.add(sig)
        out["expenses"].append(e["id"])
    return out


def _merge_leg(old_legs: list[dict], leg: dict) -> dict:
    """A leg the model returned, over the same leg already on file (same flight and date), so fields the
    app filled in (live flight status) survive."""
    for o in old_legs:
        if leg.get("flight") and o.get("flight") == leg.get("flight") and o.get("date") == leg.get("date"):
            return o | leg
    return leg


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
