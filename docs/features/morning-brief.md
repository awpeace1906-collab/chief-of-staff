# Daily brief

**Status:** live as a Claude Code scheduled task; built into the Chief of Staff app in v0.3 (see below). Exact instructions: [prompts/morning-brief.md](../../prompts/morning-brief.md).

## When

Daily at the principal's chosen time (`brief.time` in memory), in their home time zone. If the principal runs another brief service, schedule it after that one arrives so the parity check can use it.

## Inputs

1. The agent's rules from Brain (entries tagged with the agent's id), falling back to `<agent>-memory/memory.json` ([memory.md](../memory.md)).
2. The board, freshly updated by the capture step ([commitments.md](commitments.md)).
3. All division calendars, today + 7 days.
4. Flight emails for travel changes.
5. Digests from siloed systems (Microsoft 365, residency platforms, call schedules, …), via Gmail or the agent's inbox.
6. Optional: another brief service's brief, as a cross-check only.

## Output

Emailed to the principal (subject starts with the agent's name) and posted in the Claude session. Sections:

1. **You owe**, from the board: overdue, today, next 7 days, waiting-on past due
2. **Today**, by division (e.g. Me / Partner / Kids & coverage)
3. **Coverage** (see [coverage-check.md](coverage-check.md))
4. **Next 7 days**, only what matters
5. **Proposals**, numbered (see [approvals.md](approvals.md))
6. **Roundup**: one line per digest source, only when it matters ([digests.md](digests.md))
7. **Closed since yesterday**, with the evidence
8. Parity line while another brief service runs in parallel; `Brain offline: <reason>` if memory couldn't load

## Rules

- Works on its own. Another service's brief, if any, is only a cross-check for capture misses.
- Times in home time unless the principal is traveling; then show local and home.
- Apply standing agreements before flagging conflicts (e.g. a weekly session goes remote during travel).

## In the Chief of Staff app (v0.3)

`cos brief --send`, `POST /api/brief/run?send=true`, or automatically with `COS_SCHEDULER=1`:

1. **Capture** (`triage` route, Claude Haiku 5.5): new inbox mail, sent mail and the intake address since the last run → board changes. Senders whose digest adapter is `sensitive` or `ignore` are dropped before anything reaches the model. Items close only with evidence; unknown item ids are never guessed.
2. **Plan** (`plan` route, Claude Opus 5.5, effort high): board + capture changelog + 7-day agenda by division + standing rules → brief markdown and numbered proposals (structured JSON).
3. **Deliver:** saved in the database (`/api/brief/latest`), and emailed to the principal only.

The scheduler runs once a day at `brief.time` in the configured timezone, catches up the same day if the server was down, and retries a failed run after 15 minutes, at most 3 times a day. A brief that was written but couldn't be emailed is kept and counts as done (the error shows in the scheduler state), so a delivery problem never re-runs the model. Token use and estimated cost per route: `cos usage` or `/api/ai/usage`.

Not in the app yet: the parity line, flight-email parsing for coverage.
