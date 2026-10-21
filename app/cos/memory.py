"""The agent's memory: the owner's information, kept outside this code (docs/memory.md).

Memory is a directory named `<alias>-memory`, usually its own private git
repo, holding `memory.json` (the agent config: people, divisions, calendars, rules) and
optionally `digests.json` and `notes/`. The core reads it; it never writes personal data into
the core.

Identity: `assistant.id` never changes; `assistant.name` is the alias the owner sees. Renaming
the agent changes the name and moves the directory to `<new alias>-memory`; the id, and with it
Brain tags and rule ids, stays the same, so it is the same agent under a new name.

Where to look: `COS_MEMORY_DIR` (the directory itself), else `<base>/<alias>-memory` where base
is `COS_MEMORY_BASE` (default: beside the core checkout) and the alias comes from the
settings, else the only `*-memory` directory under base.
"""

import json
import os
import re
from pathlib import Path

SUFFIX = "-memory"
FILE = "memory.json"


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    if not s:
        raise ValueError("the agent needs a name with letters or digits")
    return s


def dir_name(alias: str) -> str:
    return slug(alias) + SUFFIX


def base_dir(base: str | Path | None = None) -> Path:
    """Where `<alias>-memory` sits: next to the core checkout (the folder holding this repo), unless
    COS_MEMORY_BASE says otherwise."""
    if base or os.environ.get("COS_MEMORY_BASE"):
        return Path(base or os.environ["COS_MEMORY_BASE"])
    here = Path(__file__).resolve()
    repo = here.parents[2] if len(here.parents) > 2 else Path.cwd()
    return repo.parent if (repo / "app" / "cos").is_dir() else Path.cwd()


def locate(alias: str | None = None, base: str | Path | None = None) -> Path:
    """The memory directory to read; raises FileNotFoundError when there isn't exactly one."""
    if os.environ.get("COS_MEMORY_DIR") and base is None and alias is None:
        return _checked(Path(os.environ["COS_MEMORY_DIR"]))
    root = base_dir(base)
    if alias:
        return _checked(root / dir_name(alias))
    found = sorted(p for p in root.glob("*" + SUFFIX) if (p / FILE).exists())
    if len(found) != 1:
        raise FileNotFoundError(f"expected one *{SUFFIX} directory with {FILE} under {root}, found {len(found)}")
    return found[0]


def read(path: str | Path) -> dict:
    return json.loads((_checked(Path(path)) / FILE).read_text())


def identity(cfg: dict) -> dict:
    """{"id", "name"}: the id defaults to the slug of the first name and never changes after."""
    a = cfg.get("assistant") or {}
    name = a.get("name") or "Assistant"
    return {"id": a.get("id") or slug(name), "name": name}


def rename(path: str | Path, new_alias: str) -> Path:
    """Give the agent a new alias: update memory.json (keeping the id, remembering the old name)
    and move the directory to `<new alias>-memory`. Returns the new path."""
    path = _checked(Path(path))
    cfg = json.loads((path / FILE).read_text())
    who = identity(cfg)
    if slug(new_alias) == slug(who["name"]) and new_alias == who["name"]:
        return path
    a = cfg.setdefault("assistant", {})
    a["id"] = who["id"]
    a["formerNames"] = [n for n in a.get("formerNames", []) if n != new_alias] + [who["name"]]
    a["name"] = new_alias
    (path / FILE).write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    target = path.with_name(dir_name(new_alias))
    if target != path:
        if target.exists():
            raise FileExistsError(f"{target} already exists")
        path.rename(target)
    return target


def _checked(path: Path) -> Path:
    if not (path / FILE).exists():
        raise FileNotFoundError(f"no {FILE} in {path}")
    return path
