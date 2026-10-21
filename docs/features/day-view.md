# Day view (Schedule)

**Status:** live on the Chief of Staff page (Day tab) and in the self-hosted app (Day tab, `GET /api/day`, `POST /api/schedule/block`, `app/cos/schedule.py`). Both use the same rules.

A calendar-style day view with hours down the side. The open to-dos that most need doing are suggested in the free time.

## What it shows

- **Hours down the side**, from 6am to 10pm. The range stretches when an event falls outside it. Times are in the phone's time zone, so it follows the owner when traveling, with home time noted alongside.
- **Events** from the calendars in the page's `settings/schedule` doc, read live through the viewer's Google Calendar connector (`list_events` only).
  - The owner's division always shows. The other divisions can be toggled on or off.
  - Other people's events sit in a side column so they never hide the owner's free time.
  - All-day markers (such as "Away") sit above the grid.
- **Free time:** gaps of at least 30 minutes between 7am and 9pm in the owner's own busy events. On today's view, free time starts from now. Free/transparent events don't block.
- **Suggestions in each gap:** up to 3 per gap, one for each half hour. They're the most urgent open to-dos in this order: overdue, stuck (3+ briefs), due today, due within 2 days, promises, due this week, later, undated. Items in a division marked `"suggest": false` in the divisions setting are left out. Each suggestion appears in only one gap.

## What you can do

- **Tick a suggestion** to mark the to-do done. The suggestions update straight away, because they come live from the to-do list.
- **Block** a suggestion at the start of its gap. The owner's tap is the approval. The page writes an approved calendar proposal (`source: "schedule"`, with exact `start`/`end`/`timeZone` and the `itemId`) and wakes the agent, which adds it to the block calendar (`blockCalendar`) with no invitations. Until then the block shows on the grid as "Planned". A block doesn't close the to-do.

## Settings (`settings/schedule` on the page)

`calendars` (id, name, division), `blockCalendar`, `dayStart`, `dayEnd`, `minMinutes`.

Calendar IDs are personal: they live in the page's data and the agent's memory, never in the page code.

## In the app

- `GET /api/day?date=YYYY-MM-DD&tz=Area/City` returns the day's events in the viewer's zone, the owner's free windows (minus blocks on their way) and the planned blocks. Without Google it returns 409, and the page assumes an empty day.
- `POST /api/schedule/block {itemId, start, end, timeZone}` stores an approved calendar proposal (`source: "schedule"`). If Google is connected, it puts the block on the calendar right away. Exact blocks need no model call: `agent._add_block` creates the event at exactly that time with no invites, and the to-do stays open.
- The schedule setting `blockCalendar` picks the calendar. It defaults to the first calendar in the owner's division.
- **No names in the code:** division keys, labels and colors come from the `divisions` setting (imported from the agent's memory). The owner's division is `schedule.division` (default `me`). The Day tab shows the owner's calendars plus every division without `"suggest": false`.
- `schedule.protect` holds protected windows, in the page's shape. They're never offered as free time, and `/api/day` returns them as `protected`.
- **Re-plan:** `POST /api/replan {day, at, timeZone, what}` stores a `replan` message and handles it straight away. The agent reads the day (`find_events`, `free_time`), files **Move:** proposals with `propose_move` (event id and exact times; fixed commitments never move), and replies with what changed.
- **Move:** an approved proposal with `eventId`, `start` and `end` moves that event to exactly those times, with no model call and nobody notified.
