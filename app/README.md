# Chief of Staff app

v0.3: writes and emails the morning brief itself. One process, one SQLite file.

## What it does

- Stores settings, rules (the assistant's memory) and the commitments board in `$COS_DATA_DIR/cos.db`.
- Imports the current setup: `config/tower.json`, `config/digests.json`, a Brain export, a board export.
- Exports everything in portable formats (`brain/v1`, `cos-board/v1`), so nothing is locked in.
- Serves an HTTP API and a status page; every API call needs `COS_API_TOKEN` when it's set.
- Stores and validates AI routes ([docs/features/ai-providers.md](../docs/features/ai-providers.md)).
- **v0.3:** captures commitments from new mail with Claude (Haiku), writes the morning brief (Opus), saves it, emails it to the owner, and can run it on a schedule. Logs token use and estimated cost per route.
- **v0.2:** signs in to Google itself (OAuth with PKCE, read-only Calendar + Gmail), shows the agenda by division, searches Gmail, and reads the digest intake address. Setup: [docs/setup/google.md](../docs/setup/google.md).

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

Google (after [docs/setup/google.md](../docs/setup/google.md)):

```bash
export GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=...
cos serve    # then open http://127.0.0.1:8700/oauth/google/start?token=$COS_API_TOKEN
cos google status
cos agenda --days 7
cos mail search "newer_than:1d is:important"
cos mail intake
cos google disconnect
```

Brief (needs `ANTHROPIC_API_KEY`; reconnect Google once for the send permission):

```bash
export ANTHROPIC_API_KEY=...
cos capture           # new mail → board
cos brief             # capture + brief, printed
cos brief --send      # ... and emailed to you
cos usage             # tokens and estimated $ per route
COS_SCHEDULER=1 cos serve   # brief every day at brief.time
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
| GET | `/api/export` | Everything, portable (never includes tokens) |
| GET | `/oauth/google/start?token=…` | Begin Google sign-in (browser) |
| GET | `/oauth/google/callback` | Google redirects here |
| GET | `/api/google/status` | Connected, scopes |
| POST | `/api/google/disconnect` | Revoke and forget the token |
| GET | `/api/calendar/calendars` | Calendars the account can see |
| GET | `/api/calendar/agenda?days=7` | Events by division, sorted, with per-calendar errors |
| GET | `/api/mail/search?q=…&limit=25` | Gmail search, plain-text bodies |
| GET | `/api/mail/intake?days=2` | Mail sent to the intake plus-address |
| POST | `/api/capture/run` | New mail → board changes |
| POST | `/api/brief/run?send=false` | Capture + write the brief (and email it with `send=true`) |
| GET | `/api/brief/latest` | Most recent brief |
| GET | `/api/ai/usage?days=30` | Tokens and estimated cost per route |

## Tests

```bash
pytest
```

## Layout

| File | |
|---|---|
| `cos/db.py` | Schema, connection, audit log, secrets |
| `cos/store.py` | Settings, rules, board |
| `cos/ai.py` | AI providers and per-task routes |
| `cos/importer.py` | Import current setup; export everything |
| `cos/main.py` | HTTP API and status page |
| `cos/google/oauth.py` | Google sign-in, token refresh, revoke |
| `cos/google/api.py` | Calendar (agenda by division) and Gmail (search, message text, intake) |
| `cos/llm.py` | Model calls (structured output, caching, fallbacks), usage log and cost estimate |
| `cos/capture.py` | New mail → board changes |
| `cos/brief.py` | The morning brief |
| `cos/scheduler.py` | Daily brief at `brief.time` |
| `cos/cli.py` | `cos serve`, `import`, `export`, `google`, `agenda`, `mail`, `capture`, `brief`, `usage` |
