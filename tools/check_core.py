"""Check that the core holds none of the owner's information.

Reads the agent's memory (memory.json) for what counts as personal: the agent's names, the
owner and people, standing-agreement contacts, and every email address or calendar id in it.
Then searches the core repo's text files for any of them. Exit status 1 lists the hits.

    python tools/check_core.py --memory ../<alias>-memory [--core .]

The core keeps no list of names itself: that list is memory.
"""

import argparse
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "data"}
TEXT = {".py", ".js", ".html", ".css", ".md", ".json", ".toml", ".yml", ".yaml", ".txt", ".webmanifest", ".svg", ""}
ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def personal_terms(cfg: dict) -> set[str]:
    terms = set()
    a = cfg.get("assistant") or {}
    for n in [a.get("name"), a.get("id"), a.get("owner"), *a.get("formerNames", [])]:
        terms |= _words(n)
    for p in cfg.get("people") or []:
        terms |= _words(p.get("name") if isinstance(p, dict) else p)
    for ag in cfg.get("standingAgreements") or []:
        terms |= _words(ag.get("who"))
    for div in (cfg.get("divisions") or {}).values():
        for who in div.get("coverage") or []:
            terms |= _words(who)

    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(k)
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str):
            terms.update(m.lower() for m in ADDRESS.findall(v))
    walk(cfg)
    return terms


def _words(text) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", str(text or ""))}


def scan(core: Path, terms: set[str], skip: set[Path] = frozenset()) -> list[str]:
    if not terms:
        return []
    words = sorted(t for t in terms if "@" not in t)
    parts = [re.escape(t) for t in sorted(terms, key=len, reverse=True) if "@" in t] \
        + ([r"\b(?:" + "|".join(map(re.escape, words)) + r")\b"] if words else [])  # whole addresses first
    pattern = re.compile("|".join(parts), re.I)
    hits = []
    for path in sorted(core.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT or any(part in SKIP_DIRS for part in path.parts):
            continue
        if any(path.is_relative_to(s) for s in skip):
            continue
        try:
            lines = path.read_text().splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(lines, 1):
            m = pattern.search(line)
            if m:
                hits.append(f"{path.relative_to(core)}:{i}: {m.group(0)}")
    return hits


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--memory", required=True, help="the <alias>-memory directory")
    ap.add_argument("--core", default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args(argv)
    memory, core = Path(args.memory).resolve(), Path(args.core).resolve()
    hits = scan(core, personal_terms(json.loads((memory / "memory.json").read_text())), {memory})
    for h in hits:
        print(h)
    print(f"{len(hits)} personal reference(s) in the core" if hits else "core is clean")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
