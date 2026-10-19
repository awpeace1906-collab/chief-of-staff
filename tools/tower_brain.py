#!/usr/bin/env python3
"""Tower <-> Brain (brain/v1) gist helper.

  tower_brain.py list [tag]                     print entries (default: tag "tower")
  tower_brain.py add <tag> <summary> <content>  append a tower entry (tag: rule|preference|context)

Reads BRAIN_GIST_TOKEN. Read-modify-write in one step; keeps every entry and
field it didn't write; never re-adds an id listed in `deleted`.
"""
import json, os, random, string, sys, time, urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"
TOKEN = os.environ.get("BRAIN_GIST_TOKEN")


def req(url, method="GET", body=None):
    r = urllib.request.Request(url, method=method, data=body and json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(r) as resp:
        return json.load(resp)


def find_gist():
    for g in req(f"{API}/gists?per_page=100"):
        if "brain-data.json" in g["files"]:
            return g["url"]
    sys.exit("No brain gist: create one in Brain -> Settings -> Create sync gist")


def load(url):
    f = req(url)["files"]["brain-data.json"]
    if f.get("truncated"):
        with urllib.request.urlopen(f["raw_url"]) as resp:
            return json.load(resp)
    return json.loads(f["content"])


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def main():
    if not TOKEN:
        sys.exit("BRAIN_GIST_TOKEN is not set")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    url = find_gist()
    data = load(url)
    if cmd == "list":
        tag = sys.argv[2] if len(sys.argv) > 2 else "tower"
        for e in data.get("entries", []):
            if tag in e.get("tags", []) and not e.get("archived"):
                print(f"- [{e['id']}] {e['content']}")
    elif cmd == "add":
        tag, summary, content = sys.argv[2], sys.argv[3], sys.argv[4]
        eid = f"tower-{int(time.time() * 1000)}-{''.join(random.choices(string.ascii_lowercase + string.digits, k=4))}"
        if eid in data.get("deleted", []):
            sys.exit("id collides with a deleted id; retry")
        data.setdefault("entries", []).append({
            "id": eid, "content": content, "type": "text", "tags": ["tower", tag],
            "summary": " ".join(summary.split()[:12]), "pinned": False, "archived": False,
            "timestamp": now(), "source": "tower",
        })
        data["syncedAt"] = now()
        req(url, "PATCH", {"files": {"brain-data.json": {"content": json.dumps(data, indent=2)}}})
        print(f"saved {eid}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
