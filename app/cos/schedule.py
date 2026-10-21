"""Schedule builder: find the owner's free time and slot open commitments into it.

No model calls. `free_slots` reads the agenda (busy events in the owner's division) and
returns open windows inside the working day. `suggest_blocks` gives each commitment the
accountability review surfaced its earliest window before it's due. The brief turns those
into numbered "Add: …" proposals, so nothing reaches a calendar without the owner's OK.

Settings (`schedule`): dayStart / dayEnd ("07:00" / "21:00"), minMinutes (30),
blockMinutes (30), division ("me").
"""

import sqlite3
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from . import store

DEFAULTS = {"dayStart": "07:00", "dayEnd": "21:00", "minMinutes": 30, "blockMinutes": 30, "division": "me"}


def settings(conn: sqlite3.Connection) -> dict:
    return DEFAULTS | (store.get_setting(conn, "schedule", {}) or {})


def free_slots(agenda: dict, today: date, cfg: dict, days: int = 7, now: datetime | None = None) -> list[dict]:
    """Open windows of at least cfg.minMinutes, day by day, in the agenda's timezone."""
    tz = ZoneInfo(agenda.get("timezone") or "UTC")
    busy = _busy(agenda.get("divisions", {}).get(cfg["division"], {}).get("events", []), tz)
    start_t, end_t = _hm(cfg["dayStart"]), _hm(cfg["dayEnd"])
    need = timedelta(minutes=int(cfg["minMinutes"]))
    slots = []
    for offset in range(days + 1):
        day = today + timedelta(days=offset)
        lo, hi = datetime.combine(day, start_t, tz), datetime.combine(day, end_t, tz)
        if now and now > lo:
            lo = _round_up(max(lo, now.astimezone(tz)))
        cursor = lo
        for b_start, b_end in busy:
            if b_end <= cursor or b_start >= hi:
                continue
            if b_start - cursor >= need:
                slots.append(_slot(cursor, b_start))
            cursor = max(cursor, b_end)
        if hi - cursor >= need:
            slots.append(_slot(cursor, hi))
    return slots


def suggest_blocks(review: dict, slots: list[dict], cfg: dict) -> list[dict]:
    """Earliest fitting window for each surfaced commitment, before its due date when possible."""
    length = timedelta(minutes=int(cfg["blockMinutes"]))
    left = [[datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"])] for s in slots]
    wanted = review["overdue"] + review["dueSoon"] + review["undatedPromises"]
    out = []
    for item in sorted(wanted, key=lambda i: i.get("due") or "9999"):
        due = date.fromisoformat(item["due"][:10]) if item.get("due") else None
        pick = None
        for window in left:
            if window[1] - window[0] < length:
                continue
            if due and window[0].date() > due and item["daysLate"] == 0:
                continue  # an on-time item stays on time; late items take the first window
            pick = window
            break
        if pick is None:
            continue
        start = pick[0]
        pick[0] = start + length
        out.append({"itemId": item["id"], "title": item["title"],
                    "start": start.isoformat(), "end": (start + length).isoformat()})
    return out


def _busy(events: list[dict], tz: ZoneInfo) -> list[tuple[datetime, datetime]]:
    spans = []
    for e in events:
        if not e.get("busy", True) or not e.get("start") or not e.get("end"):
            continue
        if e.get("allDay"):
            s = datetime.combine(date.fromisoformat(e["start"][:10]), time.min, tz)
            f = datetime.combine(date.fromisoformat(e["end"][:10]), time.min, tz)
        else:
            s, f = datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"])
        spans.append((s, f))
    return sorted(spans)


def _slot(a: datetime, b: datetime) -> dict:
    return {"start": a.isoformat(), "end": b.isoformat(), "minutes": int((b - a).total_seconds() // 60)}


def _hm(text: str) -> time:
    h, m = text.split(":")
    return time(int(h), int(m))


def _round_up(t: datetime) -> datetime:
    """Next quarter hour, so a slot never starts at 9:07."""
    extra = (-t.minute) % 15
    return (t + timedelta(minutes=extra)).replace(second=0, microsecond=0)
