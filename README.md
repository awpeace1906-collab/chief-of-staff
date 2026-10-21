# Chief of Staff

A personal AI chief of staff app.

## Naming

- **Chief of Staff** is the app: the product, the repo, the server, the database, the code (prefix `cos`).
- **The agent** is the owner's assistant. Every owner names their own (see [docs/vision.md](docs/vision.md)); the name and everything personal live in the agent's memory, `<agent>-memory` ([docs/memory.md](docs/memory.md)), never in this repo.

The agent runs the morning, watches every calendar in the household, spots conflicts before they happen and proposes fixes. Nothing is created or sent until the owner approves it.

The first deployment runs the agent as Claude Code scheduled tasks wired to Gmail, Google Calendar and Brain, with a Claude-hosted page as its front end. This repo is the spec for that setup and the source for the self-contained Chief of Staff app ([docs/self-contained.md](docs/self-contained.md)), whose only outside resources are hosting, the phone carrier, the AI service and the owner's own data sources.

## Two silos

| Silo | What it holds | Where |
|---|---|---|
| **Core** (this repo) | The app, docs, prompts, schemas, examples. No owner's information; redistributable. | `chief-of-staff` |
| **Memory** | The owner's agent: people, divisions, calendars, rules, digests, notes. | A private `<agent>-memory` repo ([docs/memory.md](docs/memory.md)) |

Secrets (API keys, tokens) are in neither: they live in the host's secret store. `python tools/check_core.py --memory ../<agent>-memory` checks that the core holds nothing from memory.

## What's here

| Path | What it is |
|---|---|
| [docs/self-contained.md](docs/self-contained.md) | **Target design:** one Chief of Staff app; only hosting, telephony, AI and the owner's data sources stay outside |
| [docs/memory.md](docs/memory.md) | The agent's memory: layout, identity and renaming, how the core reads it |
| [docs/architecture.md](docs/architecture.md) | How the agent works end to end |
| [docs/vision.md](docs/vision.md) | End goal, principles, product requirements |
| [docs/deployment.md](docs/deployment.md) | Cloud, hybrid and self-hosted (home/office) modes |
| [docs/features/](docs/features/) | One file per feature: what it does, its rules, its data |
| [docs/integrations.md](docs/integrations.md) | Every outside system the agent reads or writes, and how |
| [examples/memory/](examples/memory/) | A fictional memory (`memory.json`, `digests.json`) to start from |
| [prompts/](prompts/) | The exact instructions the agent runs: morning brief, capture, evening setup |
| [schemas/board.schema.json](schemas/board.schema.json) | The commitments board format |
| [app/](app/) | **The Chief of Staff app**: run instructions and API |
| [tools/](tools/) | Brain and board helpers, and the core check |
| [ROADMAP.md](ROADMAP.md) | What's live, what's next, what the app needs |

## Status

| Feature | Status |
|---|---|
| Morning brief (daily) | Live |
| Coverage check | Live (inside the brief) |
| Propose → approve flow | Live (approve on the page, in the session, or by text in the app) |
| Commitment capture + board | Live on the page; in the app since v0.3 |
| Digests from siloed systems (Microsoft 365 etc.) | Framework live; each siloed account needs forwarding to the agent's inbox |
| Brain as long-term memory | In the hosted app. Claude Code cloud sessions can't reach gists, so there the memory repo is the agent's memory |
| Voice and messaging (own number: text, voice notes, calls) | Texting in the app (v0.5); voice notes and calls specified |
| Self-contained app | v0.4+: its own installable web app (Today, Day, To-do, Talk, Settings), Microsoft 365 alongside Google ([app/](app/)); needs a host ([docs/deployment.md](docs/deployment.md#hosting-the-app-today-v04)) |
| Microsoft 365 (personal account) | Built into the app via Microsoft Graph, read-only ([docs/setup/microsoft.md](docs/setup/microsoft.md)) |
| AI providers | Claude by default, per-task routes; local models optional ([docs/features/ai-providers.md](docs/features/ai-providers.md)) |

## Rule for changes

When a rule, workflow or integration changes, update the matching doc here in the same change. If it isn't written here, the app won't have it. Changes to the owner's own rules go to their memory repo, not here.
