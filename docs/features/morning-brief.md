# Morning brief

**Status:** live. Claude Code scheduled task "Chief of Staff · Tower morning brief", daily at 8:25am America/Denver. Exact instructions: [prompts/morning-brief.md](../../prompts/morning-brief.md).

## When

8:25am Mountain, after readywhen's brief normally arrives (~8:17am) so the parity check can use it. Once readywhen is dropped, the time can move.

## Inputs

1. Tower's rules from Brain (entries tagged `tower`), falling back to [config/tower.json](../../config/tower.json).
2. The board, freshly updated by the capture step ([commitments.md](commitments.md)).
3. All division calendars, today + 7 days.
4. Flight emails for travel changes.
5. Digests from siloed systems (Microsoft 365, residency platforms, call schedules, …), via Gmail or the Tower inbox.
6. Optional: today's readywhen brief, as a cross-check only.

## Output

Emailed to Andrew (subject starts `Tower:`) and posted in the Claude session. Sections:

1. **You owe**, from the board: overdue, today, next 7 days, waiting-on past due
2. **Today**, by division (Me / Stephanie / Kids & coverage)
3. **Coverage** (see [coverage-check.md](coverage-check.md))
4. **Next 7 days**, only what matters
5. **Proposals**, numbered (see [approvals.md](approvals.md))
6. **Roundup**: one line per digest source, only when it matters ([digests.md](digests.md))
7. **Closed since yesterday**, with the evidence
8. Parity line while readywhen runs in parallel; `Brain offline: <reason>` if memory couldn't load

## Rules

- Works without readywhen. If readywhen's brief exists, it's only a cross-check for capture misses.
- Times in Mountain unless Andrew is traveling; then show local and Mountain.
- Apply standing agreements before flagging conflicts (e.g. Jason → remote during rotations).
