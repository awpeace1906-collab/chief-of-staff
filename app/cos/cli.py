"""Command line: `cos serve`, `cos import ...`, `cos export`."""

import argparse
import json
import os
import sys

from . import db
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
        json.dump(export_all(conn), sys.stdout, indent=2)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
