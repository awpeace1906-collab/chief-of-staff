"""The people the agent tracks, and noticing new ones.

`people` (from memory: `[{name, role, division?}]`) lists the principal and the household: partner, children,
caregivers, and anyone else the agent plans around. Capture (mail) and the brief (calendars) report names that
keep coming up as part of the household but aren't listed (`newPeople`). They collect here as candidates in the
`peopleCandidates` setting. Once a name has come up enough (3 mentions on 2 different days, by default), the
brief asks in the Situation Room: track them, under which division, or not. Only the principal's answer, or
their own message asking for it, adds someone; a "no" is remembered and never asked again.

Adding someone updates the app's `people` (and a caregiver joins their division's coverage). When the memory
directory is on this machine, its memory.json is updated too, so the change can be committed to the memory repo.
"""

import json
import os
import re
import sqlite3
from datetime import date, timedelta

from . import memory, store
from .db import audit, now

ASK_AFTER = {"mentions": 3, "days": 2}
ROLES = {"partner", "child", "caregiver", "nanny", "relative", "other"}
COVERAGE_ROLES = {"caregiver", "nanny"}
MAX_MENTIONS = 10


def known(conn: sqlite3.Connection) -> list[dict]:
    return store.get_setting(conn, "people", []) or []


def key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def is_known(conn: sqlite3.Connection, name: str) -> bool:
    """A full name or a first name already in `people` or a division's coverage list counts as known."""
    k = key(name)
    if not k:
        return True
    names = [p.get("name", "") for p in known(conn)]
    names += [c for d in store.divisions(conn).values() for c in d.get("coverage") or []]
    for n in names:
        nk = key(n)
        if k == nk or k == nk.split(" ")[0] or nk == k.split(" ")[0]:
            return True
    return False


def context(conn: sqlite3.Connection) -> dict:
    """What the capture and brief models need: who's already tracked, and names not to suggest again."""
    cands = store.get_setting(conn, "peopleCandidates", {}) or {}
    return {"knownPeople": [{k: p.get(k) for k in ("name", "role", "division")} for p in known(conn)],
            "notPeopleToTrack": sorted(c["name"] for c in cands.values() if c.get("status") == "dismissed")}


def note(conn: sqlite3.Connection, found: list[dict], source: str, day: date) -> list[str]:
    """Record mentions of possible new household members. Returns the names noted."""
    cands = store.get_setting(conn, "peopleCandidates", {}) or {}
    divisions = set(store.divisions(conn))
    noted = []
    for f in found or []:
        name = re.sub(r"\s+", " ", str(f.get("name") or "")).strip()[:60]
        if not name or is_known(conn, name):
            continue
        k = key(name)
        c = cands.get(k) or {"name": name, "status": "new", "mentions": [], "firstSeen": day.isoformat()}
        if c["status"] in {"dismissed", "added"}:
            continue
        if f.get("relation") in ROLES:
            c["relation"] = f["relation"]
        if f.get("division") in divisions:
            c["division"] = f["division"]
        c["mentions"] = (c["mentions"] + [{"day": day.isoformat(), "source": source,
                                           "evidence": str(f.get("evidence") or "")[:160]}])[-MAX_MENTIONS:]
        c["count"] = c.get("count", 0) + 1
        c["lastSeen"] = day.isoformat()
        cands[k] = c
        noted.append(name)
    if noted:
        store.put_setting(conn, "peopleCandidates", cands, actor="assistant")
    return noted


def ask(conn: sqlite3.Connection, today: date) -> list[str]:
    """File a Situation Room decision for each candidate that has come up enough. Returns decision ids."""
    cands = store.get_setting(conn, "peopleCandidates", {}) or {}
    labels = {k: d.get("label", k) for k, d in store.divisions(conn).items()} or {store.owner_division(conn): "Me"}
    filed = []
    for k, c in cands.items():
        days = {m["day"] for m in c.get("mentions", [])}
        if c.get("status") != "new" or c.get("count", 0) < ASK_AFTER["mentions"] or len(days) < ASK_AFTER["days"]:
            continue
        suggested = c.get("division") if c.get("division") in labels else store.owner_division(conn)
        order = [suggested] + [d for d in labels if d != suggested]
        options = [{"id": f"track-{d}", "label": f"Yes, track under {labels.get(d, d)}",
                    "detail": "Added to the people the agent plans around" + (
                        f", as {c['relation']}" if c.get("relation") else "")} for d in order[:2]]
        options.append({"id": "no", "label": "No, don't track", "detail": "Won't be asked about again"})
        where = "; ".join(f"{m['source']}: {m['evidence']}" for m in c["mentions"][-3:] if m.get("evidence"))
        decision_id = "person-" + memory.slug(c["name"])
        if store.get_record(conn, "decision", decision_id):
            c["status"] = "asked"
            continue
        store.put_record(conn, "decision", decision_id, {
            "title": f"Is {c['name']} new to the household? Track them?",
            "deadline": (today + timedelta(days=7)).isoformat(),
            "context": f"Came up {c['count']} times since {c['firstSeen']}" + (f" ({where})" if where else "") + ".",
            "options": options, "recommendation": "", "status": "open",
            "person": {"key": k, "name": c["name"], "relation": c.get("relation") or "other"},
        })
        c["status"] = "asked"
        filed.append(decision_id)
    if filed:
        store.put_setting(conn, "peopleCandidates", cands, actor="assistant")
    return filed


def resolve(conn: sqlite3.Connection, decision: dict) -> str:
    """Carry out the principal's answer to a person decision. Returns the one-line `actions`."""
    p, choice = decision["person"], decision.get("choice") or ""
    cands = store.get_setting(conn, "peopleCandidates", {}) or {}
    cand = cands.get(p["key"], {"name": p["name"], "mentions": []})
    if not choice.startswith("track-"):
        cands[p["key"]] = cand | {"status": "dismissed", "decidedAt": now()}
        store.put_setting(conn, "peopleCandidates", cands, actor="user")
        return f"Not tracking {p['name']}; won't ask again."
    cands[p["key"]] = cand | {"status": "added", "decidedAt": now()}
    store.put_setting(conn, "peopleCandidates", cands, actor="user")
    return add(conn, p["name"], p.get("relation") or "other", choice.removeprefix("track-"))


def add(conn: sqlite3.Connection, name: str, role: str, division: str, actor: str = "user") -> str:
    """Add someone to `people` (a caregiver also joins the division's coverage), and to memory.json when the
    memory directory is here. Returns a one-line result."""
    name = re.sub(r"\s+", " ", (name or "").strip())[:60]
    if not name:
        raise ValueError("a person needs a name")
    role = role if role in ROLES else "other"
    divisions = store.divisions(conn)
    division = division if division in divisions else store.owner_division(conn)
    label = (divisions.get(division) or {}).get("label", division)
    if any(key(x.get("name", "")) == key(name) for x in known(conn)):
        return f"{name} is already tracked."
    person = {"name": name, "role": role, "division": division}
    store.put_setting(conn, "people", known(conn) + [person], actor=actor)
    coverage = role in COVERAGE_ROLES and division in divisions
    if coverage:
        divisions[division] = divisions[division] | {"coverage": (divisions[division].get("coverage") or []) + [name]}
        store.put_setting(conn, "divisions", divisions, actor=actor)
    audit(conn, actor, "people.add", name=name, division=division)
    conn.commit()
    result = f"Now tracking {name} under {label}" + (" (coverage)" if coverage else "") + "."
    try:  # COS_MEMORY_DIR, else <alias>-memory beside the core; never a guess at some other *-memory
        path = memory.locate() if os.environ.get("COS_MEMORY_DIR") else memory.locate(store.assistant_name(conn))
    except (FileNotFoundError, ValueError):
        return result + " Add them to people in the memory repo too; it isn't on this machine."
    _write_memory(path, person, coverage)
    return result + f" Updated {path.name}/memory.json; commit it to the memory repo to keep it."


def _write_memory(path, person: dict, coverage: bool) -> None:
    file = path / memory.FILE
    cfg = json.loads(file.read_text())
    if not any(key(p.get("name", "")) == key(person["name"]) for p in cfg.get("people", [])):
        cfg.setdefault("people", []).append(person)
    div = (cfg.get("divisions") or {}).get(person["division"])
    if coverage and isinstance(div, dict) and person["name"] not in (div.get("coverage") or []):
        div["coverage"] = (div.get("coverage") or []) + [person["name"]]
    file.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")


SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "relation": {"type": "string", "enum": sorted(ROLES)},
            "division": {"type": "string"},
            "evidence": {"type": "string"},
        },
        "required": ["name", "relation", "division", "evidence"],
        "additionalProperties": False,
    },
}

PROMPT = """- newPeople: people who seem to belong in the principal's household or its care (a new child, partner,
  caregiver or nanny, a relative moving in), named in the {where} but not in `knownPeople` and not in
  `notPeopleToTrack`. Never patients, colleagues, classmates, senders, or anyone named only in a clinical or
  work context. relation: partner, child, caregiver, nanny, relative or other. division: the best-fitting key
  from the divisions. evidence: one short line on where they came up, with no health or clinical details.
  Leave it empty when there's no one; most days there isn't."""
