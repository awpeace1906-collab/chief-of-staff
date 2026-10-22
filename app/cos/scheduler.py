"""In-process scheduler: the daily brief once a day at `brief.time`, and the hourly check
(approved proposals, new messages, new mail) at :45 from 6:45am to 9:45pm by default (`check` setting),
and the flight watch for legs near departure (flights.py).
The check stays silent unless something fails; then it emails the principal, at most every 3 hours.

Enabled with COS_SCHEDULER=1. Checks every 30 seconds; if the server was down
at brief time, it runs as soon as it's back the same day. A failed run is
recorded and retried at most every 15 minutes, and at most 3 times a day, so a
persistent error can't run up model costs. A brief that was written but could
not be emailed counts as done for the day.
"""

import logging
import os
import sqlite3
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import agent, brain, brief, flights, sms, store
from .db import audit
from .google.api import Google
from .microsoft import oauth as ms_oauth
from .microsoft.api import Microsoft

log = logging.getLogger("cos.scheduler")
CHECK_SECONDS = 30
RETRY_SECONDS = 15 * 60
MAX_ATTEMPTS_PER_DAY = 3


def due(conn: sqlite3.Connection, now: datetime | None = None) -> bool:
    tz = ZoneInfo(store.get_setting(conn, "timezone", "UTC"))
    now = (now or datetime.now(tz)).astimezone(tz)
    cfg = store.get_setting(conn, "brief", {})
    hh, mm = (int(x) for x in (cfg.get("time") or "08:25").split(":"))
    state = store.get_setting(conn, "scheduler", {})
    today = now.date().isoformat()
    if state.get("lastBriefDay") == today:
        return False
    if state.get("attemptsDay") == today and state.get("attempts", 0) >= MAX_ATTEMPTS_PER_DAY:
        return False
    if (now.hour, now.minute) < (hh, mm):
        return False
    return time.time() - state.get("lastAttempt", 0) >= RETRY_SECONDS


def tick(conn: sqlite3.Connection, lock: threading.Lock, http=None, client=None) -> None:
    with lock:
        if not due(conn):
            return
        state = store.get_setting(conn, "scheduler", {})
        tz = ZoneInfo(store.get_setting(conn, "timezone", "UTC"))
        today = datetime.now(tz).date().isoformat()
        attempts = state.get("attempts", 0) + 1 if state.get("attemptsDay") == today else 1
        store.put_setting(conn, "scheduler", state | {"lastAttempt": time.time(), "attemptsDay": today,
                                                      "attempts": attempts}, actor="system")
        try:
            ms = Microsoft(conn, http) if ms_oauth.status(conn)["connected"] else None
            result = brief.run(conn, Google(conn, http), client=client, send=True, microsoft=ms)
            text_error = None
            if sms.configured(conn) and sms.settings(conn).get("briefByText"):
                try:
                    sms.send(conn, sms.brief_text(result, store.get_setting(conn, "appUrl")), http)
                except Exception as e:
                    text_error = f"brief text: {e.__class__.__name__}: {e}"
            store.put_setting(conn, "scheduler", store.get_setting(conn, "scheduler", {})
                              | {"lastBriefDay": result["day"], "lastError": result["sendError"] or text_error}, actor="system")
        except Exception as e:  # record and retry later; never kill the server
            log.exception("scheduled brief failed")
            store.put_setting(conn, "scheduler", store.get_setting(conn, "scheduler", {})
                              | {"lastError": f"{e.__class__.__name__}: {e}"}, actor="system")
            audit(conn, "system", "brief.failed", error=str(e))
            conn.commit()


CHECK_DEFAULT = {"enabled": True, "minute": 45, "firstHour": 6, "lastHour": 21}
ERROR_NOTICE_SECONDS = 3 * 3600


def check_slot(conn: sqlite3.Connection, now: datetime | None = None) -> str | None:
    """The hour slot ('YYYY-MM-DDTHH') the check should run for now, or None."""
    cfg = CHECK_DEFAULT | (store.get_setting(conn, "check", {}) or {})
    if not cfg["enabled"]:
        return None
    tz = ZoneInfo(store.get_setting(conn, "timezone", "UTC"))
    now = (now or datetime.now(tz)).astimezone(tz)
    if not (cfg["firstHour"] <= now.hour <= cfg["lastHour"]) or now.minute < cfg["minute"]:
        return None
    slot = now.strftime("%Y-%m-%dT%H")
    return None if store.get_setting(conn, "scheduler", {}).get("lastCheckSlot") == slot else slot


def check_tick(conn: sqlite3.Connection, lock: threading.Lock, http=None, client=None) -> dict | None:
    with lock:
        slot = check_slot(conn)
        if slot is None:
            return None
        store.put_setting(conn, "scheduler", store.get_setting(conn, "scheduler", {}) | {"lastCheckSlot": slot}, actor="system")
        google = Google(conn, http)
        connected = google_connected(conn)
        ms = Microsoft(conn, http) if ms_oauth.status(conn)["connected"] else None
        try:
            report = agent.check(conn, google, client=client, microsoft=ms, capture_mail=connected) if connected \
                else {"errors": ["Google isn't connected, so approvals, messages and mail are waiting"]}
        except Exception as e:  # never kill the server
            log.exception("hourly check failed")
            report = {"errors": [f"{e.__class__.__name__}: {e}"]}
        today = slot[:10]
        if os.environ.get("BRAIN_GIST_TOKEN") and store.get_setting(conn, "brain", {}).get("lastSync", "")[:10] != today:
            try:
                report["brain"] = brain.sync(conn, http)
            except Exception as e:
                report["errors"].append(f"brain sync: {e.__class__.__name__}: {e}")
        if report["errors"]:
            notify_errors(conn, google, report["errors"])
        return report


def google_connected(conn) -> bool:
    from .google import oauth
    return oauth.status(conn)["connected"]


def notify_errors(conn: sqlite3.Connection, google: Google, errors: list[str]) -> bool:
    """Email the principal about failures, at most every 3 hours. Returns whether it sent."""
    state = store.get_setting(conn, "scheduler", {})
    if time.time() - state.get("lastErrorNotice", 0) < ERROR_NOTICE_SECONDS:
        return False
    name = store.assistant_name(conn)
    try:
        google.send_to_owner(f"{name}: something needs a look",
                             "The hourly check hit a problem:\n\n" + "\n".join(f"- {e}" for e in errors[:10]))
    except Exception:
        log.exception("couldn't email the error notice")
        return False
    store.put_setting(conn, "scheduler", store.get_setting(conn, "scheduler", {}) | {"lastErrorNotice": time.time()}, actor="system")
    return True


def flight_tick(conn: sqlite3.Connection, lock: threading.Lock, http=None, client=None) -> dict | None:
    """Watch flights in their window (see flights.py). A change that needs a re-plan is handled
    straight away when Google is connected, so the moves are proposed before the principal lands."""
    if not any(flights.due(leg, datetime.now(ZoneInfo("UTC")), flights.settings(conn)) for _, _, leg in flights.legs(conn)):
        return None
    with lock:
        google = Google(conn, http) if google_connected(conn) else None
        try:
            report = flights.check(conn, http, google=google)
            if report["replans"] and google is not None:
                agent.handle_messages(conn, google, client=client, only=set(report["replans"]), http=http)
        except Exception as e:  # never kill the server
            log.exception("flight watch failed")
            report = {"errors": [f"{e.__class__.__name__}: {e}"]}
        if report["errors"]:
            audit(conn, "system", "flights.errors", errors=report["errors"][:5])
            conn.commit()
        return report


def start(conn: sqlite3.Connection, lock: threading.Lock) -> threading.Event:
    stop = threading.Event()

    def loop():
        while not stop.wait(CHECK_SECONDS):
            tick(conn, lock)
            check_tick(conn, lock)
            flight_tick(conn, lock)

    threading.Thread(target=loop, name="cos-scheduler", daemon=True).start()
    return stop
