# Self-contained Chief of Staff

Goal: one Chief of Staff app that does everything itself (Andrew's assistant inside it is Tower). The only outside resources are the ones that can't sensibly be owned:

| Allowed outside resource | Why it stays outside |
|---|---|
| **Hosting** (cloud server now, home box later) | Something has to be always on |
| **Telephony** (VoIP.ms / Telnyx number, SMS, call audio) | Only carriers can connect to the phone network |
| **AI processing** (Claude API) | Reasoning quality; local models aren't good enough for Tower's job |
| **Google** (Calendar, Gmail) | Not a dependency so much as where Andrew's data lives; Tower talks to it directly |

Everything else moves inside the app.

## Dependency inventory: today → self-contained

| Job | Today | Self-contained | Outside? |
|---|---|---|---|
| Run the brief every morning | Claude Code scheduled task | Built-in scheduler | No |
| Read/write Calendar and Gmail | Claude connectors | Direct Google APIs with Tower's own OAuth | Google only |
| Meeting notes | Granola connector | Optional connector; off by default | Optional |
| Commitments board | Gist (`cos-board.json`) | Local database (SQLite) | No |
| Rules, preferences, context | Brain gist | Local database; **Brain sync** as an optional two-way connector so the Brain app still shows Tower's memory | Optional |
| Digest intake | Gmail + AgentMail inbox | Gmail label via plus-address (`awpeace1906+tower@gmail.com` → label `Tower/Intake`), read through the Gmail API. Self-hosted companies can point Tower at any IMAP mailbox instead | No (uses Gmail) |
| Commitment tracking | readywhen | Built-in capture + board | No |
| Voice and texting | readywhen WhatsApp | Built-in: carrier webhooks into Tower | Carrier only |
| Speech-to-text / text-to-speech | — | Local Whisper (faster-whisper) and Piper, inside the app | No |
| Approvals | Reply in a Claude chat | Tower's own web app (installable PWA) + "approve 2" by text | No |
| Notifications | Email from Claude session | Email via Gmail API, SMS via carrier, Web Push from the PWA | Carrier for SMS |
| Spec and config | GitHub repo | Repo stays the source; the app reads config from its database, editable in Settings | No |

Removed entirely: readywhen, AgentMail, Claude Code scheduled tasks, Claude connectors, the board gist.

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
| AI | Anthropic Python SDK, tool use | Tower's tools map directly to Calendar, Gmail, board, rules |
| Speech | faster-whisper, Piper | Runs on a CPU server for voice notes; live calls use the carrier's speech until hardware allows |
| UI | Small PWA served by the app | Brief, board, proposals with one-tap approve, settings |
| Packaging | Docker image + `docker compose up` | Same image on a cloud server, a Mac mini or an office server |

## Data and migration

- Import from the current setup on first run: `config/tower.json`, `config/digests.json`, Tower entries from Brain, and any board items.
- Export at any time: one JSON file in `brain/v1` + `cos-board/v1` formats, so nothing is locked in.
- Backups: nightly copy of the SQLite file to wherever the user chooses (local disk, S3-compatible bucket).

## Transition plan

1. Build v0 alongside the current Claude Code setup; both run.
2. Switch the brief to the app once a week of briefs matches.
3. Switch approvals to the PWA and SMS.
4. Turn off the scheduled task, AgentMail inbox and readywhen.
