# Chief of Staff app

v0.1: the skeleton. One process, one SQLite file. No AI calls yet.

## What v0.1 does

- Stores settings, rules (the assistant's memory) and the commitments board in `$COS_DATA_DIR/cos.db`.
- Imports the current setup: `config/tower.json`, `config/digests.json`, a Brain export, a board export.
- Exports everything in portable formats (`brain/v1`, `cos-board/v1`), so nothing is locked in.
- Serves an HTTP API and a status page; every API call needs `COS_API_TOKEN` when it's set.
- Stores and validates AI routes ([docs/features/ai-providers.md](../docs/features/ai-providers.md)).

## Run it

```bash
cd app
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

export COS_DATA_DIR=./data COS_API_TOKEN=change-me
cos import --config ../config            # settings, standing agreements, digest adapters
cos serve                                 # http://127.0.0.1:8700
```

Optional imports:

```bash
cos import --brain brain-data.json --brain-tag tower   # the assistant's entries from Brain
cos import --board cos-board.json                       # an existing board
cos export > backup.json
```

With Docker:

```bash
cd app
echo "COS_API_TOKEN=change-me" > .env
docker compose up -d --build
docker compose exec cos cos import --config /config
```

## API

| Method | Path | |
|---|---|---|
| GET | `/health` | No token needed |
| GET | `/api/settings` | All settings |
| PUT | `/api/settings/{key}` | Replace one setting (`ai` is validated) |
| GET | `/api/ai/routes` | Each route's provider, model and whether it can run |
| GET | `/api/rules` | The assistant's rules and preferences |
| GET | `/api/board?status=open,waiting` | Board items (default: open, proposed, waiting) |
| POST | `/api/board` | Add an item |
| PATCH | `/api/board/{id}` | Update an item |
| GET | `/api/export` | Everything, portable |

## Tests

```bash
pytest
```

## Layout

| File | |
|---|---|
| `cos/db.py` | Schema, connection, audit log |
| `cos/store.py` | Settings, rules, board |
| `cos/ai.py` | AI providers and per-task routes |
| `cos/importer.py` | Import current setup; export everything |
| `cos/main.py` | HTTP API and status page |
| `cos/cli.py` | `cos serve`, `cos import`, `cos export` |
