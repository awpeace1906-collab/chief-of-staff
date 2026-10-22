# Self-contained Chief of Staff

Goal: one Chief of Staff app that does everything itself, with the principal's agent inside it. The only outside resources are the ones that can't sensibly be owned:

| Allowed outside resource | Why it stays outside |
|---|---|
| **Hosting** (cloud server now, home box later) | Something has to be always on |
| **Telephony** (VoIP.ms / Telnyx number, SMS, call audio) | Only carriers can connect to the phone network |
| **AI processing** (Claude API) | Reasoning quality; local models aren't good enough for the agent's job |
| **Google** (Calendar, Gmail) | Not a dependency so much as where the principal's data lives; the agent talks to it directly |

Everything else moves inside the app.

## Dependency inventory: today → self-contained

| Job | Today | Self-contained | Outside? |
|---|---|---|---|
| Run the brief every morning | Claude Code scheduled task | Built-in scheduler | No |
| Read/write Calendar and Gmail | Claude connectors | Direct Google APIs with the app's own OAuth | Google only |
| Meeting notes | Granola connector | Optional connector; off by default | Optional |
| Commitments board | Gist (`cos-board.json`) | Local database (SQLite) | No |
| Rules, preferences, context | Brain gist | Local database; **Brain sync** as an optional two-way connector so the Brain app still shows the agent's memory | Optional |
| Digest intake | Gmail + AgentMail inbox | Gmail label via plus-address (`you+<agent>@gmail.com` → label `<Agent>/Intake`), read through the Gmail API. Self-hosted companies can point the agent at any IMAP mailbox instead | No (uses Gmail) |
| Commitment tracking | A brief service, if any | Built-in capture + board | No |
| Voice and texting | A third-party voice beta, if any | Built-in: carrier webhooks into the app | Carrier only |
| Speech-to-text / text-to-speech | — | Local Whisper (faster-whisper) and Piper, inside the app | No |
| Approvals | The page, or a reply in a Claude chat | The app's own web app (installable PWA) + "approve 2" by text | No |
| Notifications | Email from Claude session | Email via Gmail API, SMS via carrier, Web Push from the PWA | Carrier for SMS |
| Spec and config | Core repo + the principal's memory repo | The core repo stays the source of the app; memory (`<agent>-memory`) is imported into the app's database and editable in Settings | No |

Removed entirely: AgentMail, Claude Code scheduled tasks, Claude connectors, the board gist, and any third-party brief service.

## Local first, server when needed

The app is the interface between the principal and their agent: the phone (and computer) app is where they talk, approve and see the plan. It works on the device whenever it can, and calls the server only when it must.

| On the device (default) | On the server (only when needed) |
|---|---|
| The interface: Today, Day, To-do, Talk, approvals | Scheduled runs while the phone is asleep: the morning brief, evening setup, capture sweeps, flight watches |
| Location, from the phone's own location services, used on the device | Inbound channels: the agent's phone number (SMS, calls), its email inbox, webhooks |
| Speech in and out, reminders, notifications | The AI model, until a local one is good enough for the job ([AI providers](features/ai-providers.md)) |
| A local copy of the board, plan and memory, usable offline | Sync between the principal's devices, and backups |

- The server is the same app in server mode (below). A household can run it on its own hardware ([deployment.md](deployment.md)).
- Data goes to the server only when a server task needs it. For example, a scheduled run gets the starting point for drive times, not a location history ([features/location.md](features/location.md)).
- Today the device side is the installable web app (PWA). A native iPhone app comes later, for location, notifications and offline use.

## Shape of the app

One process, one Docker image, one database file.

```
                        ┌──────────────────────── Chief of Staff app ────────────────────────┐
 Carrier (SMS/calls) ──►│ Channels: SMS · calls · voice notes · web/PWA · email     │
                        │      │                                                     │
                        │ Speech: Whisper (in) · Piper (out)                         │
                        │      │                                                     │
 Google APIs ◄─────────►│ Connectors: Calendar · Gmail · (Brain sync) · (Granola)    │
                        │      │                                                     │
                        │ Core: capture → board → plan → propose → approve → act     │──► Claude API
                        │      │                                                     │
                        │ Scheduler: morning brief · capture sweeps · re-plan        │
                        │ Store: SQLite (board, rules, audit log, settings)          │
                        └────────────────────────────────────────────────────────────┘
```

## Stack

| Piece | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Whisper, Google and Anthropic libraries are first-class; the existing tools are Python |
| Web/API | FastAPI | Webhooks, PWA backend and settings API in one |
| Store | SQLite (one file) | Zero setup, easy backup; swap for Postgres in company installs |
| Scheduler | In-process (APScheduler) | No outside cron |
| AI | Anthropic Python SDK, tool use; per-task routes with an optional local (OpenAI-compatible) provider | The assistant's tools map directly to Calendar, Gmail, board, rules; see [features/ai-providers.md](features/ai-providers.md) |
| Speech | faster-whisper, Piper | Runs on a CPU server for voice notes; live calls use the carrier's speech until hardware allows |
| UI | Small PWA served by the app | Brief, board, proposals with one-tap approve, settings |
| Packaging | Docker image + `docker compose up` | Same image on a cloud server, a Mac mini or an office server |

## Data and migration

- Import from the current setup on first run: the agent's memory (`cos import --memory`, which finds `<agent>-memory`), the agent's entries from Brain, and any board items.
- Export at any time: one JSON file in `brain/v1` + `cos-board/v1` formats, so nothing is locked in.
- Backups: nightly copy of the SQLite file to wherever the user chooses (local disk, S3-compatible bucket).

## Transition plan

The core never changes between stages. What moves is where memory lives, where secrets are kept and which AI each route calls. Each stage can be rolled back.

| Stage | Runs on | AI | Memory | Done when |
|---|---|---|---|---|
| 0. Today | Claude Code scheduled tasks + the Claude-hosted page; the app not yet hosted | Claude (Claude Code session) | `<agent>-memory` repo, read by the tasks; the page's database | — |
| 1. Host the app | A cloud server (docs/deployment.md) | Claude API (own key) | `<agent>-memory` cloned on the server, pulled on a schedule; the app's database is the working copy | Two weeks of matching briefs, side by side |
| 2. Memory writes back | Same | Same | Lasting changes the agent learns (a rule, a person, a renamed division) are committed back to `<agent>-memory` with a key scoped to that one repo; Brain keeps rules, keyed by the agent's id | The principal can read every memory change in its history |
| 3. AI of the principal's choice | Same | Routes switch one at a time to another provider or a local model; Claude stays the fallback | Same | Each route passes an eval built from real past briefs and approvals |
| 4. Own hardware and channels | A home or office server (Mac mini, mini PC) | Same | Same; only the hosting settings in memory change | Backups and remote access verified |

### Stage 1 checklist

1. Host the app, connect Google (with calendar write) and Microsoft, set the secrets (Anthropic key, access key, optional AERODATABOX_KEY).
2. Clone `<agent>-memory` beside the app (or set `COS_MEMORY_DIR`), `cos import --memory`, then `cos import --page` for the page's data.
3. Run both for two weeks. Compare each morning's brief, as the parity line does.
4. Switch approvals, messages and the flight watch to the app. The app's scheduler replaces the scheduled tasks.
5. Move what is Claude-specific:
   - The scheduled tasks' instructions become the app's prompts (generic) plus memory (personal).
   - The Gmail and Calendar connectors become the app's own Google sign-in.
   - The agent inbox becomes a forwarding address read by the app.
6. Turn off the scheduled tasks, the agent inbox, the Claude-hosted page and any third-party brief service.

### Before stage 3: gaps to close

- **Tool use beyond Claude:** `llm.run_tools` (approvals, re-plans, messages, decisions) only supports the Claude API today. A local or other provider needs OpenAI-compatible function calling in that loop before those routes can move.
- **Evals:** a fixed set of real past inputs per route (capture, plan, draft, chat) with the approved outcomes, so a new model is judged on the principal's actual work before it takes over.
- **Structured output:** routes that return JSON need a provider that can follow the schema, or a validate-and-retry step.

Later: SMS and voice (v0.5–v0.6) slot into stage 1 or 4.
