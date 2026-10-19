"""Command line: `cos serve`, `cos import`, `cos export`, `cos google`, `cos agenda`, `cos mail`."""

import argparse
import json
import os
import sys

import httpx

from . import db
from .google import oauth
from .google.api import Google
from .importer import export_all, import_board, import_brain, import_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cos", description="Chief of Staff")
    parser.add_argument("--db", help="database file (default: $COS_DATA_DIR/cos.db)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="run the server")
    serve.add_argument("--host", default=os.environ.get("COS_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("COS_PORT", "8700")))

    imp = sub.add_parser("import", help="import existing setup")
    imp.add_argument("--config", help="directory with the assistant config and digests.json")
    imp.add_argument("--brain", help="brain-data.json export")
    imp.add_argument("--brain-tag", default="tower", help="Brain tag that marks the assistant's entries")
    imp.add_argument("--board", help="cos-board/v1 export")

    sub.add_parser("export", help="print everything as portable JSON")

    g = sub.add_parser("google", help="Google connection status")
    g.add_argument("action", choices=["status", "disconnect"])

    ag = sub.add_parser("agenda", help="calendar by division")
    ag.add_argument("--days", type=int, default=7)

    m = sub.add_parser("mail", help="read Gmail")
    m.add_argument("action", choices=["search", "intake"])
    m.add_argument("query", nargs="?", help="Gmail search query (for search)")
    m.add_argument("--limit", type=int, default=10)

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        from .main import create_app

        uvicorn.run(create_app(args.db), host=args.host, port=args.port)
        return 0

    conn = db.connect(args.db)
    if args.cmd == "import":
        if not (args.config or args.brain or args.board):
            parser.error("import needs --config, --brain and/or --board")
        if args.config:
            print("config:", import_config(conn, args.config))
        if args.brain:
            print("brain entries:", import_brain(conn, args.brain, args.brain_tag))
        if args.board:
            print("board items:", import_board(conn, args.board))
    elif args.cmd == "export":
        _print(export_all(conn))
    elif args.cmd == "google":
        if args.action == "disconnect":
            oauth.disconnect(conn)
        _print(oauth.status(conn))
    elif args.cmd == "agenda":
        _print(Google(conn).agenda(args.days))
    elif args.cmd == "mail":
        g = Google(conn)
        if args.action == "search":
            if not args.query:
                parser.error("mail search needs a query")
            msgs = g.search(args.query, args.limit)
        else:
            msgs = g.intake(limit=args.limit)
        _print([{k: m[k] for k in ("date", "from", "subject", "snippet", "url")} for m in msgs])
    return 0


def _print(data) -> None:
    json.dump(data, sys.stdout, indent=2)
    print()


def run() -> int:
    """Entry point: friendly one-line errors instead of tracebacks."""
    try:
        return main()
    except (oauth.GoogleNotConnected, RuntimeError) as e:
        print(f"cos: {e}", file=sys.stderr)
    except httpx.HTTPError as e:
        print(f"cos: Google request failed ({e.__class__.__name__}: {e})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(run())
