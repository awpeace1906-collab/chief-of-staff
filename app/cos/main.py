"""HTTP API and status page."""

import hashlib
import html
import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import Body, Cookie, Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, agent, ai, brain, brief, capture, db, llm, schedule, scheduler, sms, store
from .google import oauth
from .google.api import Google
from .importer import export_all, import_page
from .microsoft import oauth as ms_oauth
from .microsoft.api import Microsoft

OAUTH_PENDING_TTL = 600
WEB = Path(__file__).parent / "web"
SESSION_COOKIE = "cos_session"
SESSION_DAYS = 90


def _session_value(token: str) -> str:
    """What the sign-in cookie holds: a keyed hash of the API token, never the token itself."""
    return hashlib.sha256(f"cos-session:{token}".encode()).hexdigest()


def create_app(db_path: str | None = None, http: httpx.Client | None = None, client=None, runner=None) -> FastAPI:
    """`http` overrides the outbound HTTP client, `client` the Anthropic client, and `runner` how background
    work is started (default: a thread); tests pass fakes."""
    runner = runner or (lambda fn: threading.Thread(target=fn, daemon=True).start())
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

    def require_token(authorization: str | None = Header(default=None),
                      cos_session: str | None = Cookie(default=None)) -> None:
        """API calls carry the token (the scheduled assistant, scripts) or the web app's sign-in cookie."""
        token = os.environ.get("COS_API_TOKEN")
        if not token:
            return
        sent = (authorization or "").removeprefix("Bearer ").strip()
        if sent and secrets.compare_digest(sent, token):
            return
        if cos_session and secrets.compare_digest(cos_session, _session_value(token)):
            return
        raise HTTPException(401, "missing or wrong API token")

    def signed_in(cos_session: str | None) -> bool:
        token = os.environ.get("COS_API_TOKEN")
        return not token or bool(cos_session and secrets.compare_digest(cos_session, _session_value(token)))

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
    def google_start(token: str | None = None, cos_session: str | None = Cookie(default=None), c=Depends(get_conn)):
        # Opened in a browser: signed in to the web app, or the API token as ?token=.
        require_token(f"Bearer {token}" if token else None, cos_session)
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

    @app.get("/api/day", dependencies=api)
    def day_view(date: str | None = None, tz: str | None = None, c=Depends(get_conn)):
        """One day for the day view, in the viewer's time zone (it follows them when they travel)."""
        from datetime import date as Date
        try:
            zone = ZoneInfo(tz or store.get_setting(c, "timezone", "UTC"))
            now_here = datetime.now(zone)
            the_day = Date.fromisoformat(date) if date else now_here.date()
        except (ValueError, KeyError) as e:
            raise HTTPException(422, f"bad date or time zone: {e}")
        # a day in the viewer's zone can start the evening before in the owner's: read one day either side
        ag = google_call(lambda: Google(c, http).agenda(2, today=the_day - timedelta(days=1)))
        return schedule.day(ag, the_day, zone, schedule.settings(c), store.list_proposals(c, ("pending", "approved")), now=now_here)

    @app.post("/api/schedule/block", dependencies=api, status_code=201)
    def block(body: dict = Body(...), c=Depends(get_conn)):
        """The owner picked a free window for a to-do. Their tap is the approval: store it as an
        approved calendar proposal and put it on the calendar now if Google is connected."""
        item = store.get_item(c, str(body.get("itemId") or ""))
        if item is None:
            raise HTTPException(404, "unknown to-do")
        try:
            start = datetime.fromisoformat(str(body["start"]).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(body["end"]).replace("Z", "+00:00"))
            zone = ZoneInfo(body.get("timeZone") or store.get_setting(c, "timezone", "UTC"))
        except (KeyError, ValueError) as e:
            raise HTTPException(422, f"bad block: {e}")
        if not (start.tzinfo and end > start) or end - start > timedelta(hours=8):
            raise HTTPException(422, "a block needs a time zone and a sensible length")
        local = start.astimezone(zone)
        p = store.add_proposal(c, {
            "kind": "calendar", "division": item["division"], "calendar": schedule.settings(c).get("blockCalendar") or "",
            "title": "Add: " + item["title"], "summary": "Time to get it done, picked on the day view.",
            "when": local.strftime("%a %b %-d, %-I:%M %p ") + (local.tzname() or ""),
            "start": start.isoformat(), "end": end.isoformat(), "timeZone": zone.key, "itemId": item["id"], "source": "schedule",
        }, actor="user")
        p = store.update_proposal(c, p["id"], {"status": "approved"}, actor="user")
        if oauth.status(c).get("canWriteCalendar"):  # otherwise it waits, approved, for the next check
            try:
                agent.execute_approved(c, Google(c, http), only={p["id"]})
            except Exception:
                pass  # left approved: the next check carries it out
        return store.get_proposal(c, p["id"])

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

    def microsoft_if_connected(c):
        return Microsoft(c, http) if ms_oauth.status(c)["connected"] else None

    @app.post("/api/capture/run", dependencies=api)
    def capture_run(c=Depends(get_conn)):
        return exclusive(lambda: capture.run(c, Google(c, http), client=client, microsoft=microsoft_if_connected(c)))

    @app.post("/api/brief/run", dependencies=api)
    def brief_run(send: bool = False, c=Depends(get_conn)):
        return exclusive(lambda: brief.run(c, Google(c, http), client=client, send=send,
                                           microsoft=microsoft_if_connected(c)))

    @app.post("/api/check/run", dependencies=api)
    def check_run(c=Depends(get_conn)):
        """Run the hourly check now: approved proposals, new messages, new mail."""
        return exclusive(lambda: agent.check(c, Google(c, http), client=client, microsoft=microsoft_if_connected(c)))

    # Text messaging: inbound webhook, and what happens next

    def after_text(c, result: dict) -> None:
        """Runs in the background so the provider gets its 200 at once."""
        try:
            if result["reply"]:
                sms.send(c, result["reply"], http)
            if result["approved"]:
                with run_lock:
                    done = agent.execute_approved(c, Google(c, http), client=client, only=set(result["approved"]))
                lines = [f"{'✓' if r['status'] == 'done' else '·' if r['status'] == 'declined' else '✗'} "
                         f"{store.get_proposal(c, r['id']).get('title') or r['id']}: {r['result']}" for r in done]
                if lines:
                    sms.send(c, "\n".join(lines), http)
            if result["message"]:
                with run_lock:
                    agent.handle_messages(c, Google(c, http), client=client, only={result["message"]}, http=http)
        except Exception as e:  # never surface to the carrier; the hourly check retries messages
            db.audit(c, "system", "sms.followup_failed", error=f"{e.__class__.__name__}: {e}")
            c.commit()

    @app.api_route("/hooks/sms/{provider}/{secret}", methods=["GET", "POST"])
    async def sms_hook(provider: str, secret: str, request: Request, c=Depends(get_conn)):
        expected = os.environ.get("COS_HOOK_SECRET")
        if not expected or not secrets.compare_digest(secret, expected):
            raise HTTPException(404)
        if request.method == "POST" and request.headers.get("content-type", "").startswith("application/json"):
            payload = await request.json()
        elif request.method == "POST":
            payload = dict(await request.form())
        else:
            payload = dict(request.query_params)
        try:
            parsed = sms.parse_inbound(provider, payload)
        except ValueError:
            raise HTTPException(404)
        if parsed:
            result = sms.handle_inbound(c, *parsed)
            if result["reply"] or result["approved"] or result["message"]:
                runner(lambda: after_text(c, result))
        return {"ok": True}

    @app.get("/api/status", dependencies=api)
    def status_all(c=Depends(get_conn)):
        """Everything the Settings screen shows: connections, schedule, costs."""
        routes = {}
        for route in ai.ROUTES:
            try:
                r = ai.resolve(c, route)
                routes[route] = {"model": r["model"], "provider": r["provider"], "ready": True}
            except RuntimeError as e:
                routes[route] = {"ready": False, "error": str(e)}
        sched = store.get_setting(c, "scheduler", {}) or {}
        return {
            "version": __version__,
            "assistant": store.get_setting(c, "assistant", {}) or {},
            "google": oauth.status(c),
            "microsoft": ms_oauth.status(c),
            "anthropicKey": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "ai": routes,
            "brain": {"configured": bool(os.environ.get("BRAIN_GIST_TOKEN")),
                      "lastSync": (store.get_setting(c, "brain", {}) or {}).get("lastSync")},
            "sms": {"configured": sms.configured(c), "provider": sms.settings(c).get("provider"),
                    "briefByText": bool(sms.settings(c).get("briefByText"))},
            "scheduler": {"running": os.environ.get("COS_SCHEDULER") == "1", "lastBriefDay": sched.get("lastBriefDay"),
                          "lastCheckSlot": sched.get("lastCheckSlot"), "lastError": sched.get("lastError")},
            "brief": store.get_setting(c, "brief", {}) or {},
            "check": scheduler.CHECK_DEFAULT | (store.get_setting(c, "check", {}) or {}),
            "usage30d": llm.usage_summary(c, 30)["estimatedUsd"],
        }

    @app.post("/api/brain/sync", dependencies=api)
    def brain_sync(c=Depends(get_conn)):
        try:
            return brain.sync(c, http)
        except brain.BrainUnavailable as e:
            raise HTTPException(409, str(e))
        except httpx.HTTPStatusError as e:
            raise HTTPException(502, f"GitHub returned {e.response.status_code}")

    @app.get("/api/brief/latest", dependencies=api)
    def brief_latest(c=Depends(get_conn)):
        latest = brief.latest(c)
        if latest is None:
            raise HTTPException(404, "no brief yet")
        return latest

    @app.get("/api/ai/usage", dependencies=api)
    def ai_usage(days: int = 30, c=Depends(get_conn)):
        return llm.usage_summary(c, max(1, min(days, 365)))

    # Proposals, messages, Ask: the web app's data

    @app.get("/api/proposals", dependencies=api)
    def proposals(status: str | None = None, days: int = 3, c=Depends(get_conn)):
        since = (datetime.now(_tz(c)) - timedelta(days=max(0, min(days, 365)))).date().isoformat()
        active = store.list_proposals(c, ("pending", "approved", "failed"))
        if status:
            return store.list_proposals(c, tuple(status.split(",")))
        recent = store.list_proposals(c, ("done", "declined"), since_day=since)
        return active + recent

    @app.post("/api/proposals", dependencies=api, status_code=201)
    def add_proposal(proposal: dict, c=Depends(get_conn)):
        try:
            return store.add_proposal(c, proposal, actor="assistant")
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.patch("/api/proposals/{proposal_id}", dependencies=api)
    def patch_proposal(proposal_id: str, patch: dict, as_assistant: bool = False, c=Depends(get_conn)):
        """The web app approves/declines; the assistant (?as_assistant=1) records done/failed."""
        try:
            return store.update_proposal(c, proposal_id, patch, actor="assistant" if as_assistant else "user")
        except KeyError:
            raise HTTPException(404, "no such proposal")
        except ValueError as e:
            raise HTTPException(409, str(e))

    # Decisions, trips, binders, expenses, cards; re-planning a day

    def record_kind(kind: str) -> str:
        if kind not in store.RECORD_KINDS:
            raise HTTPException(404, f"unknown record kind '{kind}'")
        return kind

    @app.get("/api/records", dependencies=api)
    def all_records(c=Depends(get_conn)):
        return {kind: store.list_records(c, kind) for kind in sorted(store.RECORD_KINDS)}

    @app.get("/api/records/{kind}", dependencies=api)
    def records(kind: str, c=Depends(get_conn)):
        return store.list_records(c, record_kind(kind))

    @app.put("/api/records/{kind}/{record_id}", dependencies=api)
    def put_record(kind: str, record_id: str, data: dict = Body(...), c=Depends(get_conn)):
        """The assistant (or a script) files a record; the web app only reads them and makes decisions."""
        try:
            return store.put_record(c, record_kind(kind), record_id, data)
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.delete("/api/records/{kind}/{record_id}", dependencies=api)
    def delete_record(kind: str, record_id: str, c=Depends(get_conn)):
        try:
            store.delete_record(c, record_kind(kind), record_id)
        except KeyError:
            raise HTTPException(404, "no such record")
        return {"ok": True}

    def in_background(c, label: str, fn) -> None:
        """Do the follow-up now, off the request; on failure the next check picks it up."""
        def go():
            try:
                with run_lock:
                    fn()
            except Exception as e:
                db.audit(c, "system", f"{label}.failed", error=f"{e.__class__.__name__}: {e}")
                c.commit()
        runner(go)

    @app.post("/api/decisions/{decision_id}/choose", dependencies=api)
    def choose(decision_id: str, body: dict = Body(...), c=Depends(get_conn)):
        """The owner's tap is the decision. The assistant sets up the next steps straight away."""
        try:
            d = store.choose(c, decision_id, str(body.get("choice") or ""))
        except KeyError:
            raise HTTPException(404, "no such decision")
        except ValueError as e:
            raise HTTPException(409, str(e))
        in_background(c, "decision", lambda: agent.act_on_decisions(c, Google(c, http), client=client, only={decision_id}))
        return d

    @app.post("/api/replan", dependencies=api, status_code=201)
    def replan(body: dict = Body(...), c=Depends(get_conn)):
        """Plans changed: ask the assistant to re-plan a day. Moves come back as proposals."""
        what = str(body.get("what") or "").strip()[:500]
        try:
            day = datetime.fromisoformat(str(body.get("day") or "")).date().isoformat()
            zone = ZoneInfo(body.get("timeZone") or store.get_setting(c, "timezone", "UTC"))
        except (ValueError, KeyError) as e:
            raise HTTPException(422, f"bad day or time zone: {e}")
        if not what:
            raise HTTPException(422, "say what changed")
        at = str(body.get("at") or "")[:5]
        m = store.add_message(c, "owner", f"Re-plan {day}" + (f" (it's {at})" if at else "") + f": {what}",
                              kind="replan", data={"day": day, "at": at, "timeZone": zone.key})
        in_background(c, "replan", lambda: agent.handle_messages(c, Google(c, http), client=client, only={m["id"]}, http=http))
        return m

    @app.get("/api/messages", dependencies=api)
    def messages(limit: int = 40, status: str | None = None, c=Depends(get_conn)):
        return store.list_messages(c, max(1, min(limit, 200)), status)

    @app.post("/api/messages", dependencies=api, status_code=201)
    def add_message(body: dict, c=Depends(get_conn)):
        sender = body.get("from", "owner")
        try:
            return store.add_message(c, "assistant" if sender in {"assistant", "tower"} else "owner", body.get("text", ""))
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.patch("/api/messages/{message_id}", dependencies=api)
    def patch_message(message_id: str, body: dict, c=Depends(get_conn)):
        try:
            store.mark_message(c, message_id, body.get("status", "handled"))
        except KeyError:
            raise HTTPException(404, "no such message")
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {"ok": True}

    @app.post("/api/ask", dependencies=api)
    def ask(body: dict, c=Depends(get_conn)):
        """A quick answer from the board, proposals and latest brief (the `chat` route). Takes no actions."""
        question = (body.get("question") or "").strip()[:2000]
        if not question:
            raise HTTPException(422, "ask needs a question")
        history = [m for m in body.get("history", [])[-8:] if isinstance(m, dict)]
        latest = brief.latest(c)
        name = store.assistant_name(c)
        system = (f"You are {name}, the owner's chief of staff, answering inside the Chief of Staff app. "
                  f"Answer briefly and plainly from the data in the message only; if something isn't there, say "
                  f"you don't know. You can't take actions from here: for anything that needs doing (calendar, "
                  f"email, changes), tell the owner to tap \"Send to {name}\". Never include clinical or patient details.")
        user = json.dumps({
            "now": datetime.now(_tz(c)).isoformat(),
            "openItems": store.list_items(c),
            "proposals": store.list_proposals(c, ("pending", "approved")),
            "brief": {k: latest[k] for k in ("day", "subject", "markdown")} if latest else None,
            "conversation": [{"from": m.get("from"), "text": str(m.get("text", ""))[:2000]} for m in history],
            "question": question,
        }, ensure_ascii=False, default=str)
        schema = {"type": "object", "properties": {"answer": {"type": "string"}},
                  "required": ["answer"], "additionalProperties": False}
        try:
            return llm.complete(c, "chat", system, user, schema, max_tokens=2000, client=client)
        except llm.ModelError as e:
            raise HTTPException(502, str(e))
        except RuntimeError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/import/page", dependencies=api)
    def import_page_data(data: dict, c=Depends(get_conn)):
        """Move data over from the old Claude-hosted page (items, proposals, messages, brief)."""
        return import_page(c, data)

    # Microsoft 365: connect, status, Outlook calendar and mail, To Do

    def ms_call(fn):
        try:
            return fn()
        except ms_oauth.MicrosoftNotConnected as e:
            raise HTTPException(409, str(e))
        except httpx.HTTPStatusError as e:
            raise HTTPException(502, f"Microsoft returned {e.response.status_code}")
        except httpx.HTTPError as e:
            raise HTTPException(502, f"could not reach Microsoft: {e.__class__.__name__}")

    @app.get("/oauth/microsoft/start")
    def microsoft_start(token: str | None = None, cos_session: str | None = Cookie(default=None), c=Depends(get_conn)):
        require_token(f"Bearer {token}" if token else None, cos_session)
        url, state, verifier = ms_call(lambda: ms_oauth.start(c))
        now_ = time.time()
        for k in [k for k, (_, t) in pending.items() if now_ - t > OAUTH_PENDING_TTL]:
            del pending[k]
        pending[state] = (verifier, now_)
        return RedirectResponse(url)

    @app.get("/oauth/microsoft/callback", response_class=HTMLResponse)
    def microsoft_callback(state: str, code: str | None = None, error: str | None = None,
                           error_description: str | None = None, c=Depends(get_conn)):
        entry = pending.pop(state, None)
        if entry is None or time.time() - entry[1] > OAUTH_PENDING_TTL:
            raise HTTPException(400, "unknown or expired sign-in attempt; start again")
        if error or not code:
            raise HTTPException(400, f"Microsoft sign-in failed: {error_description or error or 'no code'}")
        ms_call(lambda: ms_oauth.finish(c, code, entry[0], http))
        account = ms_call(lambda: Microsoft(c, http).me())
        who = html.escape(account.get("mail") or account.get("userPrincipalName") or "your account")
        return f"<!doctype html><p>Microsoft 365 connected ({who}). You can close this tab.</p>"

    @app.get("/api/microsoft/status", dependencies=api)
    def microsoft_status(c=Depends(get_conn)):
        return ms_oauth.status(c)

    @app.post("/api/microsoft/disconnect", dependencies=api)
    def microsoft_disconnect(c=Depends(get_conn)):
        ms_oauth.disconnect(c)
        return {"ok": True}

    @app.get("/api/microsoft/calendars", dependencies=api)
    def microsoft_calendars(c=Depends(get_conn)):
        return ms_call(lambda: Microsoft(c, http).calendars())

    @app.get("/api/microsoft/agenda", dependencies=api)
    def microsoft_agenda(days: int = 7, c=Depends(get_conn)):
        return ms_call(lambda: Microsoft(c, http).agenda(max(0, min(days, 31))))

    @app.get("/api/microsoft/mail/search", dependencies=api)
    def microsoft_mail(q: str, limit: int = 25, c=Depends(get_conn)):
        return ms_call(lambda: Microsoft(c, http).search(q, max(1, min(limit, 50))))

    @app.get("/api/microsoft/todo", dependencies=api)
    def microsoft_todo(c=Depends(get_conn)):
        return ms_call(lambda: Microsoft(c, http).todo())

    # The web app (installable on a phone's home screen)

    @app.get("/login", response_class=HTMLResponse)
    def login_page(error: str | None = None):
        page = (WEB / "login.html").read_text()
        return page.replace("<!--error-->", '<p class="err">That key didn\'t match. Try again.</p>' if error else "")

    @app.post("/login")
    def login(key: str = Form(...)):
        token = os.environ.get("COS_API_TOKEN")
        if token and not secrets.compare_digest(key.strip(), token):
            return RedirectResponse("/login?error=1", status_code=303)
        resp = RedirectResponse("/", status_code=303)
        if token:
            resp.set_cookie(SESSION_COOKIE, _session_value(token), max_age=SESSION_DAYS * 86400, httponly=True,
                            samesite="lax", secure=os.environ.get("COS_SECURE_COOKIE", "1") == "1")
        return resp

    @app.post("/logout")
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(SESSION_COOKIE)
        return resp

    @app.get("/", response_class=HTMLResponse)
    def home(cos_session: str | None = Cookie(default=None)):
        if not signed_in(cos_session):
            return RedirectResponse("/login", status_code=303)
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/sw.js")
    def service_worker():
        # Served from the root so it can cover the whole app.
        return FileResponse(WEB / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")

    @app.get("/status", response_class=HTMLResponse, dependencies=api)
    def status_page(c=Depends(get_conn)):
        name = html.escape(store.assistant_name(c))
        open_items = len(store.list_items(c))
        rules_n = len(store.list_rules(c))
        google = "connected" if oauth.status(c)["connected"] else "not connected"
        microsoft = "connected" if ms_oauth.status(c)["connected"] else "not connected"
        return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Chief of Staff · status</title>
<style>body{{font:16px system-ui;margin:2rem auto;max-width:36rem;padding:0 1rem}}</style></head>
<body><h1>Chief of Staff</h1><p>Assistant: <b>{name}</b> · v{__version__}</p>
<p>{open_items} open board items · {rules_n} rules · Google {google} · Microsoft 365 {microsoft}</p></body></html>"""

    def _tz(c) -> ZoneInfo:
        return ZoneInfo(store.get_setting(c, "timezone", "UTC"))

    return app


app = create_app()
