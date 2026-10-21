# Evening setup: scheduled task instructions

Source of truth for the Claude Code scheduled task "Chief of Staff · Tower evening setup" (`CRON_TZ=America/Denver 47 18 * * *`). When you change one, change the other. See [docs/features/evening-and-week.md](../docs/features/evening-and-week.md).

1. **Tomorrow card** (`brief/tomorrow`), about 6 lines:
   - First commitment and when to leave
   - What to bring
   - What's due
   - Coverage gaps
   - Flights or check-ins
   - Anything to prep tonight
   Use local time when traveling, with Mountain in parentheses.
2. **Sundays: weekly review** (`brief/week`):
   - Last week: done count and what slipped
   - This week: shifts, deadlines, interviews, travel, coverage
   - Promised hours vs free hours, saying plainly what should move
   - Suggested top 3
3. **Expenses**: travel and rotation receipts from the last 2 days go to `expenses/<slug>`, with no duplicates.

4. **Flight watches** for tomorrow's flights (see [docs/features/planning-on-the-fly.md](../docs/features/planning-on-the-fly.md)).

Read only, except the page and the flight-watch tasks. Silent: reply "·" unless something failed.
