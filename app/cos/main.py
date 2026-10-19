"""HTTP API and status page."""

import html
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse

from . import __version__, ai, db, store
from .importer import export_all


def create_app(db_path: str | None = None) -> FastAPI:
    conn: sqlite3.Connection | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        nonlocal conn
        conn = db.connect(db_path)
        yield
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

    @app.get("/", response_class=HTMLResponse)
    def home(c=Depends(get_conn)):
        name = html.escape(store.assistant_name(c))
        open_items = len(store.list_items(c))
        rules_n = len(store.list_rules(c))
        return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Chief of Staff</title>
<style>body{{font:16px system-ui;margin:2rem auto;max-width:36rem;padding:0 1rem}}</style></head>
<body><h1>Chief of Staff</h1><p>Assistant: <b>{name}</b> · v{__version__}</p>
<p>{open_items} open board items · {rules_n} rules</p></body></html>"""

    return app


app = create_app()
