#!/usr/bin/env python3
"""Tower board (tower-board/v1) in its own private gist.

  tower_board.py list [status ...]       print items (default: open proposed waiting)
  tower_board.py add < item.json         add one item (id/createdAt/updatedAt filled in)
  tower_board.py update <id> < patch.json  merge fields into an item
  tower_board.py mark-captured <iso>     set lastCaptureAt after a capture run

Uses BRAIN_GIST_TOKEN (gist scope). Creates the gist on first write if missing.
"""
import json, random, string, sys, time

from tower_brain import API, TOKEN, now, req

FILE = "tower-board.json"
DESCRIPTION = "{ tower } board"


def find_gist():
    for g in req(f"{API}/gists?per_page=100"):
        if FILE in g["files"]:
            return g["url"]
    return None


def load(url):
    if not url:
        return {"schema": "tower-board/v1", "lastCaptureAt": None, "updatedAt": now(), "items": []}
    return json.loads(req(url)["files"][FILE]["content"])


def save(url, board):
    board["updatedAt"] = now()
    files = {FILE: {"content": json.dumps(board, indent=2)}}
    if url:
        req(url, "PATCH", {"files": files})
    else:
        req(f"{API}/gists", "POST", {"description": DESCRIPTION, "public": False, "files": files})


def main():
    if not TOKEN:
        sys.exit("BRAIN_GIST_TOKEN is not set")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    url = find_gist()
    board = load(url)
    if cmd == "list":
        wanted = set(sys.argv[2:]) or {"open", "proposed", "waiting"}
        for i in sorted(board["items"], key=lambda i: i.get("due") or "9999"):
            if i["status"] in wanted:
                print(f"- [{i['id']}] {i['status']:<8} {i.get('due') or '—':<10} {i['division']:<9} {i['title']}")
        return
    if cmd == "add":
        item = json.load(sys.stdin)
        item["id"] = f"c-{int(time.time() * 1000)}-{''.join(random.choices(string.ascii_lowercase + string.digits, k=4))}"
        item["createdAt"] = item["updatedAt"] = now()
        item.setdefault("status", "open")
        board["items"].append(item)
        print(f"added {item['id']}")
    elif cmd == "update":
        item = next((i for i in board["items"] if i["id"] == sys.argv[2]), None)
        if not item:
            sys.exit(f"no item {sys.argv[2]}")
        item.update(json.load(sys.stdin))
        item["updatedAt"] = now()
        print(f"updated {item['id']}")
    elif cmd == "mark-captured":
        board["lastCaptureAt"] = sys.argv[2]
    else:
        sys.exit(__doc__)
    save(url, board)


if __name__ == "__main__":
    main()
