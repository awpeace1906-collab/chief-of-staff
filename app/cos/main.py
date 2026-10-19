"""HTTP API and status page."""

import html
import os
import secrets
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from . import __version__, ai, brief, capture, db, llm, scheduler, store
from .google import oauth
from .google.api import Google
from .importer import export_all

OAUTH_PENDING_TTL = 600


def create_app(db_path: str | None = None, http: httpx.Client | None = None, client=None) -> FastAPI:
    """`http` overrides the Google HTTP client and `client` the Anthropic client (tests pass fakes)."""
    conn: sqlite3.Connection | None = None
    pending: dict[str, tuple[str, float]] = {}  # OAuth state -> (PKCE verifier, created)
    run_lock = threading.Lock()  # one capture/brief at a time, manual or scheduled

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        nonlocal conn
        conn = db.connect(db_path)
        stop = scheduler.start(conn, run_lock) if os.environ.get("COS_SCHEDULER") == "1" else None
        yield
        if stop:
            stop.set()
        conn.close()

    app = FastAPI(title="Chief of Staff", version=__version__, lifespan=lifespan)

    def get_conn() -> sqlite3.Connection:
        return conn

    def require_token(authorization: str | None = Header(default=None)) -> None:
        token = os.environ.get("COS_API_TOKEN")
        if not token:
            return
        sent = (authorization or "").removeprefix("Bearer ").strip()
        if not secrets.compare_digest(sent, token):
            raise HTTPException(401, "missing or wrong API token")

    api = [Depends(require_token)]

    def google_call(fn):
        try:
            return fn()
        except oauth.GoogleNotConnected as e:
            raise HTTPException(409, str(e))
        except llm.ModelError as e:
            raise HTTPException(502, str(e))
        except httpx.HTTPStatusError as e:
            raise HTTPException(502, f"Google returned {e.response.status_code}")
        except httpx.HTTPError as e:
            raise HTTPException(502, f"could not reach Google: {e.__class__.__name__}")

    @app.get("/health")
    def health():
        return {"ok": True, "version": __version__}

    @app.get("/api/settings", dependencies=api)
    def get_settings(c=Depends(get_conn)):
        return store.all_settings(c)

    @app.put("/api/settings/{key}", dependencies=api)
    def put_settings(key: str, value: Any = Body(...), c=Depends(get_conn)):
        if key == "ai":
            try:
                ai.validate(value)
            except ValueError as e:
                raise HTTPException(422, str(e))
        store.put_setting(c, key, value)
        return {"ok": True}

    @app.get("/api/ai/routes", dependencies=api)
    def ai_routes(c=Depends(get_conn)):
        out = {}
        for route, purpose in ai.ROUTES.items():
            try:
                r = ai.resolve(c, route)
                out[route] = {"purpose": purpose, "provider": r["provider"], "model": r["model"], "ready": True}
            except RuntimeError as e:
                out[route] = {"purpose": purpose, "ready": False, "error": str(e)}
        return out

    @app.get("/api/rules", dependencies=api)
    def rules(include_archived: bool = False, c=Depends(get_conn)):
        return store.list_rules(c, include_archived)

    @app.get("/api/board", dependencies=api)
    def board(status: str | None = None, c=Depends(get_conn)):
        statuses = tuple(status.split(",")) if status else store.ACTIVE_STATUSES
        return store.list_items(c, statuses)

    @app.post("/api/board", dependencies=api, status_code=201)
    def add_board_item(item: dict, c=Depends(get_conn)):
        try:
            return store.add_item(c, item, actor="user")
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.patch("/api/board/{item_id}", dependencies=api)
    def patch_board_item(item_id: str, patch: dict, c=Depends(get_conn)):
        try:
            return store.update_item(c, item_id, patch)
        except KeyError:
            raise HTTPException(404, "no such item")
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.get("/api/export", dependencies=api)
    def export(c=Depends(get_conn)):
        return export_all(c)

    # Google: connect, status, Calendar, Gmail

    @app.get("/oauth/google/start")
    def google_start(token: str | None = None, c=Depends(get_conn)):
        # Opened in a browser, so the API token comes as ?token= instead of a header.
        require_token(f"Bearer {token}" if token else None)
        url, state, verifier = google_call(lambda: oauth.start(c))
        now_ = time.time()
        for k in [k for k, (_, t) in pending.items() if now_ - t > OAUTH_PENDING_TTL]:
            del pending[k]
        pending[state] = (verifier, now_)
        return RedirectResponse(url)

    @app.get("/oauth/google/callback", response_class=HTMLResponse)
    def google_callback(state: str, code: str | None = None, error: str | None = None, c=Depends(get_conn)):
        entry = pending.pop(state, None)
        if entry is None or time.time() - entry[1] > OAUTH_PENDING_TTL:
            raise HTTPException(400, "unknown or expired sign-in attempt; start again")
        if error or not code:
            raise HTTPException(400, f"Google sign-in failed: {error or 'no code'}")
        google_call(lambda: oauth.finish(c, code, entry[0], http))
        return "<!doctype html><p>Google connected. You can close this tab.</p>"

    @app.get("/api/google/status", dependencies=api)
    def google_status(c=Depends(get_conn)):
        return oauth.status(c)

    @app.post("/api/google/disconnect", dependencies=api)
    def google_disconnect(c=Depends(get_conn)):
        google_call(lambda: oauth.disconnect(c, http))
        return {"ok": True}

    @app.get("/api/calendar/calendars", dependencies=api)
    def calendars(c=Depends(get_conn)):
        return google_call(lambda: Google(c, http).calendars())

    @app.get("/api/calendar/agenda", dependencies=api)
    def agenda(days: int = 7, c=Depends(get_conn)):
        return google_call(lambda: Google(c, http).agenda(max(0, min(days, 31))))

    @app.get("/api/mail/search", dependencies=api)
    def mail_search(q: str, limit: int = 25, c=Depends(get_conn)):
        return google_call(lambda: Google(c, http).search(q, max(1, min(limit, 100))))

    @app.get("/api/mail/intake", dependencies=api)
    def mail_intake(days: int = 2, c=Depends(get_conn)):
        try:
            return google_call(lambda: Google(c, http).intake(max(1, min(days, 30))))
        except RuntimeError as e:
            raise HTTPException(409, str(e))

    # Capture, brief, AI usage

    def exclusive(fn):
        if not run_lock.acquire(blocking=False):
            raise HTTPException(409, "a capture or brief is already running")
        try:
            return google_call(fn)
        finally:
            run_lock.release()

    @app.post("/api/capture/run", dependencies=api)
    def capture_run(c=Depends(get_conn)):
        return exclusive(lambda: capture.run(c, Google(c, http), client=client))

    @app.post("/api/brief/run", dependencies=api)
    def brief_run(send: bool = False, c=Depends(get_conn)):
        return exclusive(lambda: brief.run(c, Google(c, http), client=client, send=send))

    @app.get("/api/brief/latest", dependencies=api)
    def brief_latest(c=Depends(get_conn)):
        latest = brief.latest(c)
        if latest is None:
            raise HTTPException(404, "no brief yet")
        return latest

    @app.get("/api/ai/usage", dependencies=api)
    def ai_usage(days: int = 30, c=Depends(get_conn)):
        return llm.usage_summary(c, max(1, min(days, 365)))

    @app.get("/", response_class=HTMLResponse)
    def home(c=Depends(get_conn)):
        name = html.escape(store.assistant_name(c))
        open_items = len(store.list_items(c))
        rules_n = len(store.list_rules(c))
        google = "connected" if oauth.status(c)["connected"] else "not connected"
        return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Chief of Staff</title>
<style>body{{font:16px system-ui;margin:2rem auto;max-width:36rem;padding:0 1rem}}</style></head>
<body><h1>Chief of Staff</h1><p>Assistant: <b>{name}</b> · v{__version__}</p>
<p>{open_items} open board items · {rules_n} rules · Google {google}</p></body></html>"""

    return app


app = create_app()
