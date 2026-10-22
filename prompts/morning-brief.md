# Morning brief: scheduled task instructions

Source of truth for the morning brief scheduled task (daily, in the owner's time zone). When you change one, change the other.

Rules, people and calendar IDs live in the agent's memory, `<agent>-memory/memory.json` ([docs/memory.md](../docs/memory.md)), and, once connected, in Brain.

---

Morning brief. Run the daily brief for the owner, then email it to the owner (subject starts with the agent's name) and post the same brief in the session.

**Step 0: Brain.** Load every non-archived Brain entry tagged with the agent's id using `tools/brain_sync.py list <agent-id>`; they override memory.json where they differ. If Brain has no entries for the agent yet, seed it once from memory.json (one entry per rule) and say so. If `BRAIN_GIST_TOKEN` is missing or `api.github.com` is blocked, use memory.json and add one line `Brain offline: <reason>` at the bottom.

**Step 1: capture.** Run [prompts/capture.md](capture.md) for the window since the board's `lastCaptureAt`, update the board with `tools/board.py`, then `mark-captured`. If the board gist is unreachable, run capture over the last 7 days of mail and show the result without saving.

**Step 2: calendars.** Pull today + 7 days from every division calendar. Sections: You owe (from the board: overdue, today, next 7 days, waiting past due), Today (by division), Coverage, Next 7 days (only what matters), Proposals (numbered), Roundup (one line per digest source, only if it matters; see docs/features/digests.md), Closed since yesterday.

**Step 2b: accountability.** Follow the accountability loop in [docs/features/commitments.md](../docs/features/commitments.md#accountability-loop). Wake due snoozes. Give every overdue, due-soon, undated-promise and waiting-late item a proposal (time block, reply, new date or nudge), then count the nudge. For items surfaced 3 or more times, ask "do it, move it, or drop it?"

**Step 2c: chief-of-staff duties.** Follow [docs/features/evening-and-week.md](../docs/features/evening-and-week.md):
- Open decisions go first in the brief (Decide).
- Draft replies for "reply owed" items and late waiting-on items.
- For interviews and meetings in the next 14 days: prep item, prep block, then a thank-you draft.
- Keep binders and trips current. Each flight leg carries `flight` ("XY 123"), `date` (local departure date, YYYY-MM-DD), `from` and `to` (IATA), so the app can watch it live.
- Track renewals.
- Keep the waiting-on-others list.
- On the 1st of the month, ask the alignment question.

**Step 2d: location.** Never assume where the owner is. Start every drive, leave-by and coverage call from where they actually are: the phone's latest location, else the trip covering the day, else home (say it's assumed). Name the starting point. See [docs/features/location.md](../docs/features/location.md).

**Step 3: travel.** Check flight emails (airlines, booking sites, TripIt forwards) for changes affecting the next 7 days and feed them into the coverage check.

**Step 4: board hygiene.** Ask about items whose done-evidence is ambiguous; never close silently on a guess.

Propose only; number every proposal so the owner can reply "approve 1, 3". Apply standing agreements before flagging conflicts. Times in the owner's home time zone unless traveling (then local + home). Readable in 60 seconds on a phone. When the owner states a new rule or preference, save it to Brain and to the memory repo.
