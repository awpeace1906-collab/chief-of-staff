"""Two-way sync with Brain (the owner's second-brain PWA), following its brain/v1 contract.

Pull: entries tagged with the assistant's name become rules (never ones listed in `deleted`).
Push: the assistant's own rules that Brain doesn't have yet are appended. The whole file is
read, changed and PATCHed back in one step, keeping every entry the assistant didn't write.
Needs BRAIN_GIST_TOKEN (a classic token with only the gist scope).
"""

import json
import os
import sqlite3

import httpx

from . import store
from .db import audit, now

API = "https://api.github.com"
FILE = "brain-data.json"


class BrainUnavailable(RuntimeError):
    pass


def _headers() -> dict:
    token = os.environ.get("BRAIN_GIST_TOKEN")
    if not token:
        raise BrainUnavailable("set BRAIN_GIST_TOKEN to sync with Brain")
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def _gist_id(conn: sqlite3.Connection, http: httpx.Client) -> str:
    cfg = store.get_setting(conn, "brain", {}) or {}
    if cfg.get("gistId"):
        return cfg["gistId"]
    for page in range(1, 6):
        r = http.get(f"{API}/gists", params={"per_page": 100, "page": page}, headers=_headers())
        r.raise_for_status()
        gists = r.json()
        for g in gists:
            if FILE in g.get("files", {}):
                store.put_setting(conn, "brain", cfg | {"gistId": g["id"]}, actor="system")
                return g["id"]
        if len(gists) < 100:
            break
    raise BrainUnavailable(f"no gist with {FILE} found for this token")


def _read(http: httpx.Client, gist_id: str) -> dict:
    r = http.get(f"{API}/gists/{gist_id}", headers=_headers())
    r.raise_for_status()
    f = r.json()["files"][FILE]
    content = f.get("content")
    if f.get("truncated") or content is None:
        raw = http.get(f["raw_url"], headers=_headers())
        raw.raise_for_status()
        content = raw.text
    return json.loads(content)


def sync(conn: sqlite3.Connection, http: httpx.Client | None = None) -> dict:
    http = http or httpx.Client(timeout=30)
    gist_id = _gist_id(conn, http)
    data = _read(http, gist_id)
    tag = store.assistant_id(conn)
    deleted = set(data.get("deleted", []))
    entries = data.setdefault("entries", [])
    in_brain = {e.get("id") for e in entries}

    pulled = 0
    for e in entries:
        tags = e.get("tags", [])
        if tag not in tags or e.get("id") in deleted:
            continue
        kind = next((t for t in tags if t in {"rule", "preference", "context"}), "context")
        store.upsert_rule(conn, {"id": e["id"], "kind": kind, "content": e.get("content", ""),
                                 "summary": e.get("summary", ""), "archived": int(bool(e.get("archived"))),
                                 "source": "brain", "updated_at": e.get("timestamp") or now()})
        pulled += 1

    pushed = []
    for r in store.list_rules(conn):
        if r["source"] == "brain" or r["id"] in in_brain or r["id"] in deleted:
            continue
        entries.append({"id": r["id"], "content": r["content"], "type": "text", "tags": [tag, r["kind"]],
                        "summary": (r["summary"] or r["content"])[:90], "pinned": False, "archived": False,
                        "timestamp": r["updated_at"], "source": tag})
        pushed.append(r["id"])
    if pushed:
        data["syncedAt"] = now()
        p = http.patch(f"{API}/gists/{gist_id}", headers=_headers(),
                       json={"files": {FILE: {"content": json.dumps(data, ensure_ascii=False, indent=2)}}})
        p.raise_for_status()
        for rid in pushed:  # now they live in Brain; future edits come back from there
            conn.execute("UPDATE rules SET source = 'brain' WHERE id = ?", (rid,))
    store.put_setting(conn, "brain", (store.get_setting(conn, "brain", {}) or {}) | {"lastSync": now()}, actor="system")
    audit(conn, "system", "brain.sync", pulled=pulled, pushed=len(pushed))
    conn.commit()
    return {"pulled": pulled, "pushed": len(pushed)}
