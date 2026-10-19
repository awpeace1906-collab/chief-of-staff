# Morning brief

**Status:** live. Claude Code scheduled task "Chief of Staff · Tower morning brief", daily at 8:25am America/Denver. Exact instructions: [prompts/morning-brief.md](../../prompts/morning-brief.md).

## When

8:25am Mountain, about 8 minutes after readywhen's brief normally arrives (~8:17am).

## Inputs

1. Tower's rules from Brain (entries tagged `tower`), falling back to [config/tower.json](../../config/tower.json).
2. Today's readywhen brief from Gmail (`from:noreply@readywhen.ai newer_than:1d`).
3. All division calendars, today + 7 days.
4. Gmail, last 24 hours, primary/important: replies owed, interview invites, deadlines, flight changes.

## Output

Emailed to Andrew (subject starts `Tower:`) and posted in the Claude session. Sections:

1. **Today**, by division (Me / Stephanie / Kids & coverage)
2. **Coverage** (see [coverage-check.md](coverage-check.md))
3. **Next 7 days**, only what matters
4. **Proposals**, numbered (see [approvals.md](approvals.md))
5. **Open items**, carried until closed
6. `Brain offline: <reason>` line if memory couldn't load

## Rules

- Don't restate readywhen. Verify each of its flags against the calendars, turn each into a concrete action, and note anything it got wrong.
- Times in Mountain unless Andrew is traveling; then show local and Mountain.
- Apply standing agreements before flagging conflicts (e.g. Jason → remote during rotations).
