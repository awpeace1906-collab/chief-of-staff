"""In-process scheduler: runs the morning brief once a day at `brief.time`.

Enabled with COS_SCHEDULER=1. Checks every 30 seconds; if the server was down
at brief time, it runs as soon as it's back the same day. A failed run is
recorded and retried at most every 15 minutes, and at most 3 times a day, so a
persistent error can't run up model costs. A brief that was written but could
not be emailed counts as done for the day.
"""

import logging
import sqlite3
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import brief, store
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
            store.put_setting(conn, "scheduler", store.get_setting(conn, "scheduler", {})
                              | {"lastBriefDay": result["day"], "lastError": result["sendError"]}, actor="system")
        except Exception as e:  # record and retry later; never kill the server
            log.exception("scheduled brief failed")
            store.put_setting(conn, "scheduler", store.get_setting(conn, "scheduler", {})
                              | {"lastError": f"{e.__class__.__name__}: {e}"}, actor="system")
            audit(conn, "system", "brief.failed", error=str(e))
            conn.commit()


def start(conn: sqlite3.Connection, lock: threading.Lock) -> threading.Event:
    stop = threading.Event()

    def loop():
        while not stop.wait(CHECK_SECONDS):
            tick(conn, lock)

    threading.Thread(target=loop, name="cos-scheduler", daemon=True).start()
    return stop
