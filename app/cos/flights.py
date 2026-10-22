"""Flight watch: live flight status and public air traffic control data, so a delay or cancellation
re-plans the day instead of surprising the principal.

Two sources:
- FAA NAS Status (nasstatus.faa.gov), public and keyless: ground stops, ground delay programs,
  departure/arrival delays and closures by airport. Checked for every watched leg's airports.
- A flight-status provider for the flight itself (revised times, gate, cancelled, diverted).
  AeroDataBox through RapidAPI (`AERODATABOX_KEY`); without a key only the FAA data is used.

What's watched: trip legs (records kind `trip`) that carry `flight` ("AA 690"), `date` (local
departure date) and, ideally, `from` / `to` (IATA). A leg is checked every `intervalMinutes` from
`watchHours` before its scheduled departure until 2 hours after its scheduled arrival.

On a change the leg's `live` field is updated and the principal gets one message. A delay of 30+
minutes, a cancellation or a diversion also files a `replan` message for the arrival day, so the
assistant proposes the moves. A cancellation, a diversion, or a delay that pushes the arrival past
midnight also emails the principal a 3-line alert. Nothing else is sent, and nothing is booked or moved
without approval. No model calls happen here unless a re-plan is filed.

Settings (`flights`): provider ("aerodatabox" | "none"), watchHours (6), intervalMinutes (20).
"""

import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from . import store
from .db import audit, now as db_now

FAA_URL = "https://nasstatus.faa.gov/api/airport-status-information"
ADB_HOST = "aerodatabox.p.rapidapi.com"
DEFAULTS = {"provider": "aerodatabox", "watchHours": 6, "intervalMinutes": 20}
REPLAN_DELAY = 30  # minutes of delay that's worth re-planning around
NOTE_DELAY = 15  # smaller changes in delay aren't worth a message
FLIGHT_RE = re.compile(r"\b([A-Z][A-Z0-9]|[A-Z0-9][A-Z])\s?(\d{1,4})\b")


def settings(conn: sqlite3.Connection) -> dict:
    return DEFAULTS | (store.get_setting(conn, "flights", {}) or {})


# What to watch

def legs(conn: sqlite3.Connection) -> list[tuple[dict, int, dict]]:
    """(trip, leg index, leg) for every leg with a flight number and date."""
    out = []
    for trip in store.list_records(conn, "trip"):
        for i, leg in enumerate(trip.get("legs") or []):
            flight = normalize(leg.get("flight") or "")
            if flight and leg.get("date"):
                out.append((trip, i, leg | {"flight": flight}))
    return out


def normalize(text: str) -> str:
    """'XY 123', 'xy123' or 'XY 123 Denver to Dallas' -> 'XY123'."""
    m = FLIGHT_RE.search(text.upper())
    return f"{m.group(1)}{m.group(2)}" if m else ""


def in_window(leg: dict, now: datetime, cfg: dict) -> bool:
    """From watchHours before the scheduled departure until 2 hours after the scheduled arrival.
    Without times yet, the whole departure date (UTC, padded a day either side) counts."""
    dep, arr = _when(leg.get("live", {}).get("scheduledDeparture")), _when(leg.get("live", {}).get("scheduledArrival"))
    if dep:
        return dep - timedelta(hours=cfg["watchHours"]) <= now <= (arr or dep + timedelta(hours=12)) + timedelta(hours=2)
    day = datetime.fromisoformat(leg["date"]).replace(tzinfo=timezone.utc)
    return day - timedelta(days=1) <= now <= day + timedelta(days=2)


def due(leg: dict, now: datetime, cfg: dict) -> bool:
    last = _when(leg.get("live", {}).get("checkedAt"))
    return in_window(leg, now, cfg) and (last is None or now - last >= timedelta(minutes=cfg["intervalMinutes"]))


# Sources

def faa_status(http: httpx.Client) -> dict[str, list[dict]]:
    """Active FAA events by airport: {"DFW": [{"kind": "ground stop", "reason": ..., ...}]}."""
    r = http.get(FAA_URL, headers={"Accept": "application/xml"}, timeout=20)
    r.raise_for_status()
    return parse_faa(r.text)


FAA_KINDS = {"Ground_Delay": "ground delay", "Program": "ground stop", "Delay": "delay", "Airport": "closure"}


def parse_faa(xml: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for parent in ET.fromstring(xml).iter():
        for el in parent:
            code = (el.findtext("ARPT") or "").strip().upper()
            if not code:
                continue
            kind = FAA_KINDS.get(el.tag, el.tag.replace("_", " ").lower())
            ev = {"kind": kind, "reason": (el.findtext("Reason") or "").strip()}
            for tag, key in (("Avg", "average"), ("Max", "max"), ("End_Time", "until"), ("Reopen", "until")):
                if el.findtext(tag):
                    ev[key] = el.findtext(tag).strip()
            for ad in el.findall("Arrival_Departure"):
                ev["direction"] = (ad.get("Type") or "").lower()
                ev["max"] = (ad.findtext("Max") or ev.get("max") or "").strip()
            out.setdefault(code, []).append(ev)
    return out


def flight_status(http: httpx.Client, flight: str, date: str, key: str) -> dict | None:
    """One leg from AeroDataBox, normalized; None if the provider doesn't know the flight."""
    r = http.get(f"https://{ADB_HOST}/flights/number/{flight}/{date}",
                 headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": ADB_HOST}, timeout=20)
    if r.status_code in (204, 404):
        return None
    r.raise_for_status()
    data = r.json()
    rows = data if isinstance(data, list) else [data]
    return normalize_adb(rows[0]) if rows else None


def normalize_adb(f: dict) -> dict:
    dep, arr = f.get("departure") or {}, f.get("arrival") or {}

    def t(side, key):
        return ((side.get(key) or {}).get("local") or "").replace(" ", "T") or None

    return {
        "status": f.get("status") or "Unknown",
        "from": (dep.get("airport") or {}).get("iata"), "to": (arr.get("airport") or {}).get("iata"),
        "scheduledDeparture": t(dep, "scheduledTime"), "departure": t(dep, "revisedTime") or t(dep, "runwayTime"),
        "scheduledArrival": t(arr, "scheduledTime"), "arrival": t(arr, "revisedTime") or t(arr, "runwayTime"),
        "gate": dep.get("gate"), "terminal": dep.get("terminal"),
        "arrivalAirport": (arr.get("airport") or {}).get("iata"),
    }


# The check

def check(conn: sqlite3.Connection, http: httpx.Client | None = None, now: datetime | None = None,
          google=None) -> dict:
    """Check every leg that's due. Returns {"checked": [...], "changes": [...], "errors": [...]}."""
    http = http or httpx.Client(timeout=20)
    now = now or datetime.now(timezone.utc)
    cfg = settings(conn)
    key = os.environ.get("AERODATABOX_KEY") if cfg["provider"] == "aerodatabox" else None
    report = {"checked": [], "changes": [], "replans": [], "errors": []}
    todo = [(t, i, leg) for t, i, leg in legs(conn) if due(leg, now, cfg)]
    if not todo:
        return report
    try:
        faa = faa_status(http)
    except Exception as e:
        faa = None
        report["errors"].append(f"FAA status: {e.__class__.__name__}: {e}")
    for trip, i, leg in todo:
        old = leg.get("live") or {}
        live = {k: old[k] for k in ("scheduledDeparture", "scheduledArrival", "from", "to") if old.get(k)}
        try:
            if key:
                live |= {k: v for k, v in (flight_status(http, leg["flight"], leg["date"], key) or {"status": "Unknown"}).items() if v}
        except Exception as e:
            report["errors"].append(f"{leg['flight']}: {e.__class__.__name__}: {e}")
        airports = [a for a in (live.get("from") or leg.get("from"), live.get("to") or leg.get("to")) if a]
        if faa is not None:
            live["airports"] = {a: faa.get(a.upper(), []) for a in airports}
        live["checkedAt"] = now.isoformat()
        changes = diff(old, live)
        _save(conn, trip, i, live)
        report["checked"].append(leg["flight"])
        if changes:
            report["changes"].append({"flight": leg["flight"], "date": leg["date"], "changes": changes})
            replan_id = _tell(conn, trip, leg, live, changes, google)
            if replan_id:
                report["replans"].append(replan_id)
    return report


def delay_minutes(live: dict, side: str = "departure") -> int:
    sched, actual = _when(live.get("scheduled" + side.title())), _when(live.get(side))
    return int((actual - sched).total_seconds() // 60) if sched and actual else 0


def diff(old: dict, new: dict) -> list[str]:
    """What changed that the principal should hear about, in plain words."""
    out = []
    status = new.get("status")
    if status and status != old.get("status") and status in {"Canceled", "CanceledUncertain", "Diverted", "Delayed"}:
        out.append({"Canceled": "cancelled", "CanceledUncertain": "may be cancelled", "Diverted": "diverted",
                    "Delayed": "delayed"}[status])
    was, now_ = delay_minutes(old), delay_minutes(new)
    if abs(now_ - was) >= NOTE_DELAY:
        out.append(f"departure now {_hm(new.get('departure'))} ({_late(now_)})")
    if new.get("gate") and old.get("gate") and new["gate"] != old["gate"]:
        out.append(f"gate {old['gate']} → {new['gate']}")
    for code, events in (new.get("airports") or {}).items():
        seen = {(e["kind"], e.get("reason")) for e in (old.get("airports") or {}).get(code, [])}
        for e in events:
            if (e["kind"], e.get("reason")) not in seen and e["kind"] in {"ground stop", "ground delay", "closure", "delay"}:
                out.append(f"FAA {e['kind']} at {code}" + (f" ({e['reason']})" if e.get("reason") else "")
                           + (f" until {e['until']}" if e.get("until") else "") + (f", up to {e['max']}" if e.get("max") else ""))
    return [c for i, c in enumerate(out) if c not in out[:i]]


def urgent(live: dict) -> bool:
    """A cancellation, a diversion, or an arrival pushed past midnight: worth an email now."""
    if live.get("status") in {"Canceled", "Diverted"}:
        return True
    sched, actual = _when(live.get("scheduledArrival")), _when(live.get("arrival"))
    return bool(sched and actual and actual.date() > sched.date())


def _tell(conn, trip: dict, leg: dict, live: dict, changes: list[str], google) -> str | None:
    """Message the principal; file a re-plan when the change matters. Returns the re-plan message id."""
    name = store.assistant_name(conn)
    text = f"{_pretty(leg['flight'])} on {leg['date']}: " + "; ".join(changes) + "."
    replan = live.get("status") in {"Canceled", "CanceledUncertain", "Diverted"} or delay_minutes(live) >= REPLAN_DELAY \
        or delay_minutes(live, "arrival") >= REPLAN_DELAY or any(c.startswith("FAA ground stop") or c.startswith("FAA closure") for c in changes)
    store.add_message(conn, "assistant", text + (" I'm re-planning around it; any moves will wait on the Today tab." if replan else ""))
    replan_id = None
    if replan:
        day = (live.get("arrival") or live.get("scheduledArrival") or leg["date"])[:10]
        replan_id = store.add_message(conn, "owner", f"Re-plan {day}: {text} ({trip.get('title') or 'trip'})", kind="replan",
                          data={"day": day, "timeZone": store.get_setting(conn, "timezone", "UTC"), "flight": leg["flight"],
                                "source": "flight watch"})["id"]
    if urgent(live) and google is not None:
        try:
            google.send_to_owner(f"{name}: {_pretty(leg['flight'])} {('cancelled' if live.get('status') == 'Canceled' else 'changed')}",
                                 f"{text}\nArrives {_hm(live.get('arrival') or live.get('scheduledArrival'))}.\n"
                                 f"Proposed fixes are on the Today tab.")
        except Exception as e:
            audit(conn, "assistant", "flights.alert_failed", flight=leg["flight"], error=str(e))
    audit(conn, "assistant", "flights.change", flight=leg["flight"], changes=changes)
    conn.commit()
    return replan_id


def _save(conn, trip: dict, i: int, live: dict) -> None:
    fresh = store.get_record(conn, "trip", trip["id"]) or trip
    legs_ = list(fresh.get("legs") or [])
    if i < len(legs_):
        legs_[i] = legs_[i] | {"live": live}
        store.put_record(conn, "trip", trip["id"], fresh | {"legs": legs_}, actor="assistant")


def _when(value) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _hm(value) -> str:
    d = _when(value)
    return d.strftime("%a %-I:%M%p").replace("AM", "am").replace("PM", "pm") + " local" if d else "unknown"


def _late(minutes: int) -> str:
    return "on time" if minutes <= 0 else f"{minutes} min late" if minutes < 60 else f"{minutes // 60}h {minutes % 60:02d}m late"


def _pretty(flight: str) -> str:
    m = re.match(r"([A-Z0-9]{2})(\d+)", flight)
    return f"{m.group(1)} {m.group(2)}" if m else flight
