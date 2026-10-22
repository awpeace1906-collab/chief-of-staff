"""Where the owner is: the phone's latest location, else the trip they're on, else home. The assistant never
assumes a starting point for a drive or a leave-by time; it uses this, and says which source it used."""

import math
import sqlite3
from datetime import date, datetime, timedelta, timezone

from . import store
from .db import audit

DEFAULTS = {"freshHours": 6, "homeRadiusKm": 25}


def settings(conn: sqlite3.Connection) -> dict:
    return DEFAULTS | (store.get_setting(conn, "location", {}) or {})


def record(conn: sqlite3.Connection, lat: float, lon: float, at: str | None = None, accuracy: float | None = None,
           place: str = "", source: str = "phone") -> dict:
    """Store a location ping (from the owner's phone). Only the latest one is kept."""
    lat, lon = float(lat), float(lon)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("lat/lon out of range")
    when = _parse(at) if at else datetime.now(timezone.utc)
    if when is None:
        raise ValueError("at must be an ISO 8601 time")
    ping = {"lat": lat, "lon": lon, "at": when.isoformat(), "place": str(place or "")[:120], "source": source}
    if accuracy is not None:
        ping["accuracy"] = float(accuracy)
    store.put_setting(conn, "lastLocation", ping, actor="owner")
    audit(conn, "owner", "location.ping", source=source)
    conn.commit()
    return ping


def whereabouts(conn: sqlite3.Connection, day: date | None = None, now: datetime | None = None) -> dict:
    """The owner's starting point for `day` (default today): {label, source, lat?, lon?, asOf?, note}.
    source is "phone" (a fresh ping), "trip" (a trip covering that day) or "home" (the fallback)."""
    now = now or datetime.now(timezone.utc)
    day = day or now.date()
    cfg = settings(conn)
    home = store.get_setting(conn, "home", {}) or {}

    ping = store.get_setting(conn, "lastLocation")
    at = _parse(ping.get("at")) if ping else None
    # A fresh ping answers for today, and for tomorrow too when it's the evening before (where they'll sleep).
    if at and now - at <= timedelta(hours=cfg["freshHours"]) and (day - now.date()).days <= 1:
        near_home = _near(ping, home, cfg["homeRadiusKm"])
        label = f"home ({home.get('label')})" if near_home and home.get("label") else ping.get("place") or \
            f"{ping['lat']:.4f}, {ping['lon']:.4f}"
        return {"label": label, "source": "phone", "lat": ping["lat"], "lon": ping["lon"], "asOf": ping["at"],
                "note": "From the phone's latest location."}

    for trip in store.list_records(conn, "trip"):
        if trip.get("status") == "cancelled" or not trip.get("start") or not trip.get("end"):
            continue
        if trip["start"][:10] <= day.isoformat() <= trip["end"][:10]:
            base = trip.get("base") or {}
            label = base.get("label") or trip.get("title") or trip["id"]
            out = {"label": label, "source": "trip", "note": f"On the trip \"{trip.get('title') or trip['id']}\"; "
                                                             "no fresh phone location."}
            return out | {k: base[k] for k in ("lat", "lon") if k in base}

    if home.get("label"):
        return {"label": f"home ({home['label']})", "source": "home", **{k: home[k] for k in ("lat", "lon") if k in home},
                "note": "Assumed: no fresh phone location and no trip that day. Say so."}
    return {"label": "", "source": "unknown", "note": "Unknown: no phone location, trip or home is set. Ask the owner."}


def _near(a: dict, b: dict, km: float) -> bool:
    if not all(k in b for k in ("lat", "lon")):
        return False
    return _km(a["lat"], a["lon"], b["lat"], b["lon"]) <= km


def _km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _parse(ts: str | None) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
