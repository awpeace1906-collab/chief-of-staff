"""Accountability: keep every open commitment in front of the principal until it's resolved.

No model calls. Each morning, `review` sorts the board into what needs attention:
- overdue: past due, still open
- dueSoon: due in the next two days
- undatedPromises: something the principal promised (from sent mail) with no date after three days
- waitingLate: something owed to the principal that's past due (time to nudge them)
- stuck: anything surfaced in three or more briefs without resolution, so the brief asks
  "do it, move it, or drop it?"
- renewals: licenses, certifications and the like (`kind: "renewal"`) expiring within 60 days;
  `alert` is true on the 60-, 30- and 7-day marks and once it's 7 days or less
- top: the principal's top 3 for this week (`top` = this week's Monday)

`mark_surfaced` counts how many briefs have shown each item. Nothing here closes an item.
Only evidence closes it (capture), or the principal does.
"""

import sqlite3
from datetime import date, timedelta

from . import store
from .db import audit

DUE_SOON_DAYS = 2
UNDATED_AFTER_DAYS = 3
STUCK_AFTER = 3  # briefs that surfaced the item
RENEWAL_WINDOW = 60
RENEWAL_MARKS = (60, 30, 7)


def review(conn: sqlite3.Connection, today: date) -> dict:
    """What needs attention today, after waking snoozed items that are due back."""
    woke = _wake_snoozed(conn, today)
    soon = today + timedelta(days=DUE_SOON_DAYS)
    out = {"overdue": [], "dueSoon": [], "undatedPromises": [], "waitingLate": [], "stuck": [], "renewals": [],
           "top": [], "woke": woke}
    monday = (today - timedelta(days=today.weekday())).isoformat()
    for item in store.list_items(conn):
        if item.get("top") == monday:
            out["top"].append(_brief(item, today))
        expires = _day(item.get("expires"))
        if item.get("kind") == "renewal" and expires and (expires - today).days <= RENEWAL_WINDOW:
            left = (expires - today).days
            out["renewals"].append(_brief(item, today) | {"expires": item["expires"], "daysLeft": left,
                                                          "alert": left in RENEWAL_MARKS or left <= 7})
        due = _day(item.get("due"))
        waiting = item["direction"] == "owed-to-me" or item["status"] == "waiting"
        if waiting:
            if due and due < today:
                out["waitingLate"].append(_brief(item, today))
        elif due and due < today:
            out["overdue"].append(_brief(item, today))
        elif due and due <= soon:
            out["dueSoon"].append(_brief(item, today))
        elif not due and item.get("promise") and _age(item, today) >= UNDATED_AFTER_DAYS:
            out["undatedPromises"].append(_brief(item, today))
        if item.get("nudges", 0) >= STUCK_AFTER and (not due or due <= soon):
            out["stuck"].append(_brief(item, today))
    return out


def surfaced_ids(r: dict) -> set[str]:
    return {i["id"] for k in ("overdue", "dueSoon", "undatedPromises", "waitingLate") for i in r[k]}


def mark_surfaced(conn: sqlite3.Connection, r: dict, today: date) -> int:
    """Count one more brief for each item the review surfaced (at most once per day)."""
    n = 0
    for item_id in surfaced_ids(r):
        item = store.get_item(conn, item_id)
        if item is None or item.get("lastSurfaced") == today.isoformat():
            continue
        store.update_item(conn, item_id, {"nudges": item.get("nudges", 0) + 1,
                                          "lastSurfaced": today.isoformat()}, actor="assistant")
        n += 1
    return n


def _wake_snoozed(conn: sqlite3.Connection, today: date) -> list[str]:
    woke = []
    for item in store.list_items(conn, ("snoozed",)):
        until = _day(item.get("snoozedUntil"))
        if until is None or until <= today:
            store.update_item(conn, item["id"], {"status": "open", "snoozedUntil": None}, actor="assistant")
            woke.append(item["id"])
    if woke:
        audit(conn, "assistant", "board.wake", ids=woke)
        conn.commit()
    return woke


def _brief(item: dict, today: date) -> dict:
    due = _day(item.get("due"))
    return {"id": item["id"], "title": item["title"], "direction": item["direction"],
            "division": item["division"], "counterparty": item.get("counterparty"), "due": item.get("due"),
            "daysLate": (today - due).days if due and due < today else 0,
            "promise": bool(item.get("promise")), "nudges": item.get("nudges", 0)}


def _age(item: dict, today: date) -> int:
    made = _day(item.get("createdAt"))
    return (today - made).days if made else 0


def _day(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
