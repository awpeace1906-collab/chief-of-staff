# Morning brief: scheduled task instructions

Source of truth for the Claude Code scheduled task "Chief of Staff · Tower morning brief"
(daily, `CRON_TZ=America/Denver 25 8 * * *`). When you change one, change the other.

Rules and calendar IDs live in [config/tower.json](../config/tower.json) and, once connected, in Brain.

---

Tower morning brief. Run the daily brief for Andrew, then email it to Andrew (subject starts "Tower:") and post the same brief in the session.

**Step 0: Brain.** Load every non-archived Brain entry tagged `tower` with `tools/tower_brain.py list tower`; they override config/tower.json where they differ. If Brain has no tower entries yet, seed it once from config/tower.json (one entry per rule) and say so. If `BRAIN_GIST_TOKEN` is missing or `api.github.com` is blocked, use config/tower.json and add one line `Brain offline: <reason>` at the bottom.

**Step 1: capture.** Run [prompts/capture.md](capture.md) for the window since the board's `lastCaptureAt`, update the board with `tools/tower_board.py`, then `mark-captured`. readywhen is optional: if today's readywhen brief exists, use it only as a cross-check and report the parity line. If the board gist is unreachable, run capture over the last 7 days of mail and show the result without saving.

**Step 2: calendars.** Pull today + 7 days from every division calendar. Sections: You owe (from the board: overdue, today, next 7 days, waiting past due), Today (by division), Coverage, Next 7 days (only what matters), Proposals (numbered), Roundup (one line per digest source, only if it matters; see docs/features/digests.md), Closed since yesterday, Parity line (while readywhen runs in parallel).

**Step 3: travel.** Check flight emails (airlines, Expedia, TripIt forwards) for changes affecting the next 7 days and feed them into the coverage check.

**Step 4: board hygiene.** Ask about items whose done-evidence is ambiguous; never close silently on a guess.

Propose only; number every proposal so Andrew can reply "approve 1, 3". Apply standing agreements before flagging conflicts. Times in Mountain unless traveling (then local + Mountain). Readable in 60 seconds on a phone. When Andrew states a new rule or preference, save it to Brain and to config/tower.json.
