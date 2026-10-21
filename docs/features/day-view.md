# Day view (Schedule)

**Status:** live on the Chief of Staff page (Day tab) and in the self-hosted app (Day tab, `GET /api/day`, `POST /api/schedule/block`, `app/cos/schedule.py`). Both use the same rules.

A calendar-style day view with hours down the side. The open to-dos that most need doing are suggested in the free time.

## What it shows

- **Hours down the side**, from 6am to 10pm. The range stretches when an event falls outside it. Times are in the phone's time zone, so it follows Andrew when he travels, with Mountain time noted alongside.
- **Events** from the calendars in the page's `settings/schedule` doc, read live through the viewer's Google Calendar connector (`list_events` only).
  - Andrew's division always shows. Home & kids and Stephanie can be toggled on or off.
  - Other people's events sit in a side column so they never hide Andrew's free time.
  - All-day markers (such as "Away") sit above the grid.
- **Free time:** gaps of at least 30 minutes between 7am and 9pm in Andrew's own busy events. On today's view, free time starts from now. Free/transparent events don't block.
- **Suggestions in each gap:** up to 3 per gap, one for each half hour. They're the most urgent open to-dos in this order: overdue, stuck (3+ briefs), due today, due within 2 days, promises, due this week, later, undated. Stephanie's items are left out. Each suggestion appears in only one gap.

## What you can do

- **Tick a suggestion** to mark the to-do done. The suggestions update straight away, because they come live from the to-do list.
- **Block** a suggestion at the start of its gap. Andrew's tap is the approval. The page writes an approved calendar proposal (`source: "schedule"`, with exact `start`/`end`/`timeZone` and the `itemId`) and wakes Tower, which adds it to the block calendar (`blockCalendar`, default Andrew Work) with no invitations. Until then the block shows on the grid as "Planned". A block doesn't close the to-do.

## Settings (`settings/schedule` on the page)

`calendars` (id, name, division), `blockCalendar`, `dayStart`, `dayEnd`, `minMinutes`.

Calendar IDs are personal: they live in the page's data and config/tower.json, never in the page code.

## In the app

- `GET /api/day?date=YYYY-MM-DD&tz=Area/City` returns the day's events in the viewer's zone, the owner's free windows (minus blocks on their way) and the planned blocks. Without Google it returns 409, and the page assumes an empty day.
- `POST /api/schedule/block {itemId, start, end, timeZone}` stores an approved calendar proposal (`source: "schedule"`). If Google is connected, it puts the block on the calendar right away. Exact blocks need no model call: `agent._add_block` creates the event at exactly that time with no invites, and the to-do stays open.
- The schedule setting `blockCalendar` picks the calendar. It defaults to the first calendar in the owner's division.
