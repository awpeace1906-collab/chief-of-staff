# Chief of Staff

A personal AI chief of staff. The assistant is called **Tower** (the user picks the name; see [docs/vision.md](docs/vision.md)).

Tower runs the morning, watches every calendar in the household, spots conflicts before they happen and proposes fixes. Nothing is created or sent until you approve it.

Today Tower runs as a Claude Code scheduled task wired to Gmail, Google Calendar and Brain. This repo is the living spec for that setup and the source for the self-contained Tower app ([docs/self-contained.md](docs/self-contained.md)), whose only outside resources are hosting, the phone carrier, the AI service and Google.

## What's here

| Path | What it is |
|---|---|
| [docs/self-contained.md](docs/self-contained.md) | **Target design:** one Tower app; only hosting, telephony, AI and Google stay outside |
| [docs/architecture.md](docs/architecture.md) | How Tower works end to end, without readywhen |
| [docs/vision.md](docs/vision.md) | End goal, principles, product requirements |
| [docs/deployment.md](docs/deployment.md) | Cloud, hybrid and self-hosted (home/office) modes |
| [docs/features/](docs/features/) | One file per feature: what it does, its rules, its data |
| [docs/integrations.md](docs/integrations.md) | Every outside system Tower reads or writes, and how |
| [config/tower.json](config/tower.json) | Andrew's personal config: calendars, divisions, people, rules |
| [config/digests.json](config/digests.json) | Digest adapters: which systems Tower reads and how |
| [prompts/](prompts/) | The exact instructions Tower runs: morning brief, capture |
| [schemas/board.schema.json](schemas/board.schema.json) | The commitments board format |
| [tools/](tools/) | Brain (memory) and board (commitments) helpers |
| [ROADMAP.md](ROADMAP.md) | What's live, what's next, what the app needs |

## Status

| Feature | Status |
|---|---|
| Morning brief (8:25am MT daily) | Live |
| Coverage check | Live (inside the brief) |
| Propose → approve flow | Live (approve in the Claude session) |
| Commitment capture + board (replaces readywhen) | Framework drafted; runs once the gist is reachable |
| Digests from siloed systems (Microsoft 365 etc.) | Framework drafted; Gmail digests live, work account needs forwarding |
| Brain as long-term memory | Built; waiting on `BRAIN_GIST_TOKEN` and `api.github.com` access |
| Voice and messaging (own number: text, voice notes, calls) | Spec written; interim is readywhen's WhatsApp beta |
| Self-contained app | Later |

## Rule for changes

When a rule, workflow or integration changes, update the matching doc here in the same change. If it isn't written here, the app won't have it.
