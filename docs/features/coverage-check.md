# Coverage check

**Status:** live, inside the morning brief.

## Question it answers

Is there any window, today through +7 days, where nobody has the kids?

## Logic

Flag a window when all three are true:

1. **The partner is busy:** working, on call, or in a meeting (the partner's division calendars).
2. **The owner is busy or away:** working, traveling, or on rotation (the owner's division calendars, flight emails).
3. **Childcare is not scheduled** (the coverage people in the kids division, e.g. the nanny's schedule calendar).

Which divisions and people these are comes from memory (`divisions`, `coverage`). Account for real travel: flight landing times plus the drive home from the airport.

## Example

The nanny leaves at 6:00pm; the partner's meeting runs to 6:30pm. The owner lands at 3:00pm and is home within an hour, so the owner covers. If the flight slips, the agent raises it.

## Output

A short list of gaps with a proposed fix for each (ask the nanny to stay late, move a block, etc.), or "Covered all week."

## App notes

- Which divisions count as "busy" and who counts as coverage are configured in memory.
- Needs travel awareness: parse flight confirmation emails into an itinerary; the app also watches flights live.
