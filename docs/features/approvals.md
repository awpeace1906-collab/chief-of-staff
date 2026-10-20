# Propose → approve

**Status:** live.

## How it works

1. Tower lists every action it wants to take as a numbered proposal: a calendar block, a draft email, a reschedule.
2. Andrew replies in the Claude session: `approve 1, 3`, `approve all`, or edits ("approve 2 but make it 7pm").
3. Only then does Tower create the event, send the email or change the calendar, and confirm what it did.

## No duplicates

A proposal never adds an event that's already on a calendar. Tower checks all division calendars first; when the email and the existing event disagree, it proposes fixing the existing event (see `calendarRules` in config/tower.json).

## Never without approval

- Creating, moving or deleting calendar events
- Sending email to anyone other than Andrew
- Changing anything on someone else's calendar

## Allowed without approval

- Reading calendars and email
- Sending the brief to Andrew
- Saving rules Andrew states to Brain

## App notes

The app needs a one-tap approve on each proposal (push notification or the brief email itself), not just a chat reply.
