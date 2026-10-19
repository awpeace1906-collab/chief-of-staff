# Architecture

Tower runs on its own. readywhen is an optional extra input, never a dependency. This page describes the pipeline; [self-contained.md](self-contained.md) describes how it's packaged into one app.

```
 Sources ──► Capture ──► Board ──► Plan ──► Propose ──► Approve ──► Act ──► Close
 Gmail         extract    commitments  today+7    numbered     Andrew     calendar   detect done,
 Calendar      dedupe     (gist)       coverage   actions                 email      drop from board
 Granola       link       Brain rules  re-plan                            drafts
 Digests (M365,
  GME, call…)
 TripIt/flights                                                                        ▲
 Voice (later)                                                                         │
     └───────────────────────────── evidence (sent reply, event created) ─────────────┘
```

## Stages

| Stage | Job | Today | In the app |
|---|---|---|---|
| **Sources** | Raw signal | Gmail, Google Calendar, Granola connectors; flight emails (Expedia, airlines, TripIt forwards); digests from siloed systems via Gmail or the Tower inbox ([features/digests.md](features/digests.md)) | OAuth to the same services + a per-user Tower inbox |
| **Capture** | Turn signal into commitments | LLM pass over the last 24h of mail and meeting notes ([prompts/capture.md](../prompts/capture.md)) | Same prompt, run on new mail via push/webhook |
| **Board** | The single list of what's owed, by whom, by when | `cos-board.json` in a private gist ([schemas/board.schema.json](../schemas/board.schema.json)) | Same file or a local DB synced to it |
| **Plan** | Fit commitments into real time | Morning brief: calendars by division + coverage check | Brief + event-driven re-plan |
| **Propose** | Concrete numbered actions | In the brief | Brief + push notification |
| **Approve** | Human says yes | Reply in the Claude session | One-tap approve |
| **Act** | Do the approved thing | Calendar/Gmail connectors | Same APIs |
| **Close** | Notice it's done | Each capture run checks open items for evidence | Same |

## Stores

| Store | Holds | Why separate |
|---|---|---|
| **Brain** (`brain-data.json`) | Rules, preferences, context, standing agreements | Andrew's long-term memory; human-browsable in the Brain app |
| **Board** (`cos-board.json`, own gist, description `{ chief of staff } board`) | Commitments with status and due dates | High-churn operational data; keeps Brain clean |
| **config/tower.json** | Divisions, calendars, people | Static setup; fallback when Brain is offline |

Both gists use the same `gist`-scope token (`BRAIN_GIST_TOKEN`).

## readywhen's role now

Optional cross-check. If its brief is in the inbox, Tower compares: anything readywhen caught that Tower missed is logged as a capture miss (see [ROADMAP.md](../ROADMAP.md) parity scorecard). Once Tower matches it for two weeks, readywhen can be dropped.

## What replaces each readywhen feature

| readywhen | Tower |
|---|---|
| Commitment capture from email/meetings/docs | Capture stage over Gmail + Granola (+ Drive comments later) |
| Board / inbox | `cos-board.json` |
| Morning brief | Tower morning brief (already richer: divisions, coverage) |
| Drafts the next deliverable | Proposals with drafted emails/docs, sent only on approval |
| WhatsApp voice | Later: Tower's own voice line (see ROADMAP) |
