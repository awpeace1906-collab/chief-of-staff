# Evening setup: scheduled task instructions

Source of truth for the evening setup scheduled task (daily, early evening in the principal's time zone). When you change one, change the other. See [docs/features/evening-and-week.md](../docs/features/evening-and-week.md).

0. **Where the principal is.** Never assume it. Use the phone's latest location (the app's `lastLocation`, or the latest "Location" email in the agent's inbox), else the trip covering tomorrow, else home from memory, and name it on the card ("from home in …"). See [docs/features/location.md](../docs/features/location.md).
1. **Tomorrow card** (`brief/tomorrow`), about 6 lines:
   - First commitment and when to leave, with the drive time from the named starting point
   - What to bring
   - What's due
   - Coverage gaps
   - Flights or check-ins
   - Anything to prep tonight
   Use local time when traveling, with home time in parentheses.
2. **Sundays: weekly review** (`brief/week`):
   - Last week: done count and what slipped
   - This week: shifts, deadlines, interviews, travel, coverage
   - Promised hours vs free hours, saying plainly what should move
   - Suggested top 3
3. **Expenses**: travel and work-trip receipts from the last 2 days go to `expenses/<slug>`, with no duplicates.

4. **Flight watches** for tomorrow's flights (see [docs/features/planning-on-the-fly.md](../docs/features/planning-on-the-fly.md)).

Read only, except the page and the flight-watch tasks. Silent: reply "·" unless something failed.
