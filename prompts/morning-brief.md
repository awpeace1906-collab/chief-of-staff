# Morning brief: scheduled task instructions

Source of truth for the Claude Code scheduled task "Chief of Staff · Tower morning brief"
(daily, `CRON_TZ=America/Denver 25 8 * * *`). When you change one, change the other.

Rules and calendar IDs live in [config/tower.json](../config/tower.json) and, once connected, in Brain.

---

Tower morning brief. Run the daily brief for Andrew, then email it to Andrew (subject starts "Tower:") and post the same brief in the session.

**Step 0: Brain.** Load every non-archived Brain entry tagged `tower` with `tools/tower_brain.py list tower`; they override config/tower.json where they differ. If Brain has no tower entries yet, seed it once from config/tower.json (one entry per rule) and say so. If `BRAIN_GIST_TOKEN` is missing or `api.github.com` is blocked, use config/tower.json and add one line `Brain offline: <reason>` at the bottom.

**Step 1: readywhen.** Read today's readywhen brief (`from:noreply@readywhen.ai newer_than:1d`). Don't repeat it. Verify its flags against the calendars, turn each into a concrete proposed action, and note anything it got wrong.

**Step 2: calendars.** Pull today + 7 days from every division calendar. Sections: Today (by division), Coverage, Next 7 days (only what matters), Proposals (numbered), Open items.

**Step 3: Gmail.** Scan `newer_than:1d` primary/important for replies owed, interview invites, deadlines, flight changes.

**Step 4: open items.** Carry them until closed.

Propose only; number every proposal so Andrew can reply "approve 1, 3". Apply standing agreements before flagging conflicts. Times in Mountain unless traveling (then local + Mountain). Readable in 60 seconds on a phone. When Andrew states a new rule or preference, save it to Brain and to config/tower.json.
