"""The memory connector: the agent's memory over MCP, for AI apps the principal connects.

Phase 1 (docs/features/memory-connector.md): a stateless MCP server over Streamable HTTP with JSON responses,
at POST /mcp, behind the app's API token. Reads are plain lookups; writes never act: `remember` hands text to
the agent as a message and `propose` files a pending proposal for the principal to approve in the app.

Off until the `connector` setting turns it on: {"enabled": true, "scope": "read" | "propose"}.
"""

import json
import sqlite3

from . import __version__, brief, store
from .db import audit, now

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")  # newest first
SCOPES = ("read", "propose")
PROPOSE_KINDS = ("board", "calendar", "list")
SEARCH_KINDS = ("item", "trip", "binder", "decision", "expense", "rule")
MAX_RESULTS = 20
MAX_TEXT = 4000


class ConnectorError(Exception):
    """A JSON-RPC error: `code` per JSON-RPC 2.0."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def settings(conn: sqlite3.Connection) -> dict:
    cfg = store.get_setting(conn, "connector", {}) or {}
    scope = cfg.get("scope") if cfg.get("scope") in SCOPES else "read"
    return {"enabled": bool(cfg.get("enabled")), "scope": scope}


# Tools

def _tools(scope: str) -> list[dict]:
    read = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
    tools = [
        {"name": "today",
         "description": "The principal's latest daily brief, the pending proposals waiting for approval, and "
                        "open items that are due today or overdue.",
         "inputSchema": {"type": "object", "properties": {}},
         "annotations": read | {"title": "Today"}},
        {"name": "week",
         "description": "Tomorrow's card (the Book) and the week card, plus open items due in the next 7 days.",
         "inputSchema": {"type": "object", "properties": {}},
         "annotations": read | {"title": "This week"}},
        {"name": "recall",
         "description": "Search the agent's memory: board items (open and closed), trips, binders, decisions, "
                        "expenses and rules. Every word in the query must appear. Returns up to 20 matches.",
         "inputSchema": {"type": "object", "properties": {
             "query": {"type": "string", "description": "Words to look for, e.g. 'tucson housing'."},
             "kinds": {"type": "array", "items": {"type": "string", "enum": list(SEARCH_KINDS)},
                       "description": "Limit the search to these kinds. Default: all."}},
             "required": ["query"]},
         "annotations": read | {"title": "Recall"}},
    ]
    if scope == "propose":
        tools += [
            {"name": "remember",
             "description": "Hand something to the agent, as if the principal had texted it: a fact, a change, a "
                            "to-do. The agent files it on its next run; anything that would act becomes a proposal "
                            "the principal approves in the app. Nothing happens immediately.",
             "inputSchema": {"type": "object", "properties": {
                 "text": {"type": "string", "description": "What to remember, in the principal's words."}},
                 "required": ["text"]},
             "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False,
                             "openWorldHint": False, "title": "Remember"}},
            {"name": "propose",
             "description": "Ask the agent to do something. It becomes a numbered, pending proposal; nothing "
                            "happens until the principal approves it in the app.",
             "inputSchema": {"type": "object", "properties": {
                 "kind": {"type": "string", "enum": list(PROPOSE_KINDS),
                          "description": "calendar: add or move an event; board: a to-do change; list: a list "
                                         "change. Default: board. Email can't be proposed here."},
                 "title": {"type": "string", "description": "Starts with a verb: 'Add: …', 'Move: …'."},
                 "summary": {"type": "string", "description": "One line: why."},
                 "when": {"type": "string", "description": "When, if it has a time."},
                 "division": {"type": "string", "description": "A division key, if known."}},
                 "required": ["title"]},
             "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False,
                             "openWorldHint": False, "title": "Propose"}},
        ]
    return tools


def _item_line(i: dict) -> str:
    due = f" (due {i['due']})" if i.get("due") else ""
    who = f" [{i['direction']}]" if i.get("direction") else ""
    return f"- {i['title']}{due}{who} · {i['status']} · {i['id']}"


def _today(conn: sqlite3.Connection, args: dict) -> str:
    day = now()[:10]
    latest = brief.latest(conn)
    parts = [f"# Brief for {latest['day']}\n\n{latest['markdown']}" if latest else "No brief yet."]
    pending = store.list_proposals(conn, statuses=("pending",))
    if pending:
        parts.append("## Waiting for approval\n" + "\n".join(
            f"- {p['id']}: {p.get('title') or p.get('summary')}" + (f" ({p['when']})" if p.get("when") else "")
            for p in pending))
    due = [i for i in store.list_items(conn) if i.get("due") and i["due"] <= day]
    if due:
        parts.append("## Due today or overdue\n" + "\n".join(_item_line(i) for i in due))
    return "\n\n".join(parts)


def _week(conn: sqlite3.Connection, args: dict) -> str:
    from datetime import date, timedelta
    parts = []
    for card, label in (("tomorrow", "Tomorrow"), ("week", "This week")):
        rec = store.get_record(conn, "card", card)
        if rec and rec.get("markdown"):
            when = rec.get("day") or rec.get("weekOf") or ""
            parts.append(f"# {label}{' (' + when + ')' if when else ''}\n\n{rec['markdown']}")
    horizon = (date.fromisoformat(now()[:10]) + timedelta(days=7)).isoformat()
    due = [i for i in store.list_items(conn) if i.get("due") and i["due"] <= horizon]
    if due:
        parts.append("## Due in the next 7 days\n" + "\n".join(_item_line(i) for i in due))
    return "\n\n".join(parts) or "Nothing for this week yet."


def _matches(doc, words: list[str]) -> bool:
    text = json.dumps(doc, ensure_ascii=False).lower()
    return all(w in text for w in words)


def _recall(conn: sqlite3.Connection, args: dict) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ConnectorError(-32602, "recall needs a query")
    kinds = args.get("kinds") or list(SEARCH_KINDS)
    if not isinstance(kinds, list) or any(k not in SEARCH_KINDS for k in kinds):
        raise ConnectorError(-32602, f"kinds must be some of {', '.join(SEARCH_KINDS)}")
    words = query.lower().split()
    hits: list[str] = []
    if "item" in kinds:
        hits += [_item_line(i) for i in store.list_items(conn, statuses=tuple(store.BOARD_STATUSES))
                 if _matches(i, words)]
    for kind in ("trip", "binder", "decision", "expense"):
        if kind in kinds:
            for r in store.list_records(conn, kind):
                if _matches(r, words):
                    label = r.get("title") or r.get("vendor") or r["id"]
                    extra = {"trip": f"{r.get('start', '')}–{r.get('end', '')}",
                             "expense": f"{r.get('date', '')} ${r.get('amount', '')}",
                             "decision": r.get("status", ""), "binder": r.get("status", "")}[kind]
                    hits.append(f"- [{kind}] {label} · {extra} · {r['id']}")
    if "rule" in kinds:
        hits += [f"- [rule] {r.get('summary') or r.get('content', '')[:120]} · {r['id']}"
                 for r in store.list_rules(conn) if _matches(r, words)]
    if not hits:
        return f"Nothing matches “{query}”."
    more = f"\n…and {len(hits) - MAX_RESULTS} more; narrow the query." if len(hits) > MAX_RESULTS else ""
    return f"{min(len(hits), MAX_RESULTS)} match(es) for “{query}”:\n" + "\n".join(hits[:MAX_RESULTS]) + more


def _remember(conn: sqlite3.Connection, args: dict, client: str) -> str:
    text = str(args.get("text") or "").strip()
    if not text:
        raise ConnectorError(-32602, "remember needs text")
    m = store.add_message(conn, "owner", text[:MAX_TEXT], channel="connector", ref=client[:80] or None)
    return f"Handed to the agent ({m['id']}). It files it on its next run; anything that acts comes back as a proposal."


def _propose(conn: sqlite3.Connection, args: dict, client: str) -> str:
    title = str(args.get("title") or "").strip()
    if not title:
        raise ConnectorError(-32602, "propose needs a title")
    kind = args.get("kind") or "board"
    if kind not in PROPOSE_KINDS:
        raise ConnectorError(-32602, f"kind must be one of {', '.join(PROPOSE_KINDS)}")
    divisions = store.divisions(conn)
    division = args.get("division") if args.get("division") in divisions else store.owner_division(conn)
    p = store.add_proposal(conn, {
        "kind": kind, "title": title[:300], "summary": str(args.get("summary") or "")[:500],
        "when": str(args.get("when") or "")[:120], "division": division,
        "source": f"connector:{client[:60]}" if client else "connector"}, actor="connector")
    return f"Proposal {p['id']} is waiting for the principal's approval in the app."


READ_TOOLS = {"today": _today, "week": _week, "recall": _recall}
WRITE_TOOLS = {"remember": _remember, "propose": _propose}


# JSON-RPC

def _negotiate(requested) -> str:
    return requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]


def handle(conn: sqlite3.Connection, message: dict, client: str = "") -> dict | None:
    """One JSON-RPC message in, its response out (None for a notification)."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return _error(message.get("id") if isinstance(message, dict) else None, -32600, "invalid request")
    if "id" not in message:
        return None  # notifications (initialized, cancelled) need no answer
    mid, method, params = message["id"], message["method"], message.get("params") or {}
    scope = settings(conn)["scope"]
    try:
        if method == "initialize":
            name = store.assistant_name(conn)
            return _result(mid, {
                "protocolVersion": _negotiate(params.get("protocolVersion")),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": f"{store.assistant_id(conn)}-memory", "title": f"{name}'s memory",
                               "version": __version__},
                "instructions": (
                    f"{name} is the principal's chief-of-staff agent. Use `today` and `week` for what's on their "
                    "plate and `recall` to look something up before answering from memory. "
                    + ("`remember` and `propose` hand things to the agent; nothing acts until the principal "
                       "approves it in the app." if scope == "propose" else "This connection is read-only."))})
        if method == "ping":
            return _result(mid, {})
        if method == "tools/list":
            return _result(mid, {"tools": _tools(scope)})
        if method == "tools/call":
            tool, args = params.get("name"), params.get("arguments") or {}
            if not isinstance(args, dict):
                raise ConnectorError(-32602, "arguments must be an object")
            if tool not in READ_TOOLS and not (tool in WRITE_TOOLS and scope == "propose"):
                return _error(mid, -32602, f"unknown tool '{tool}'")
            try:
                text = (READ_TOOLS[tool](conn, args) if tool in READ_TOOLS else WRITE_TOOLS[tool](conn, args, client))
            except (ConnectorError, ValueError) as e:  # the tool ran and refused: tell the model, not the client
                return _result(mid, {"content": [{"type": "text", "text": str(e)}], "isError": True})
            audit(conn, "connector", "connector.call", tool=tool, client=client[:80])
            conn.commit()
            return _result(mid, {"content": [{"type": "text", "text": text}], "isError": False})
        raise ConnectorError(-32601, f"method not found: {method}")
    except ConnectorError as e:
        return _error(mid, e.code, str(e))


def _result(mid, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}
