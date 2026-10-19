# Coverage check

**Status:** live, inside the morning brief.

## Question it answers

Is there any window, today through +7 days, where nobody has the kids?

## Logic

Flag a window when all three are true:

1. **Stephanie is busy:** working, on call, or in a meeting (Stephanie, LCDF, Call calendars).
2. **Andrew is busy or away:** working, traveling, or on rotation (Andrew's Calendar, Andrew Work, flight emails).
3. **Tiffany (nanny) is not scheduled** (Tiffany Schedule calendar).

Account for real travel: flight landing times plus the drive home (El Paso → Las Cruces about 1 hour).

## Example (Oct 20, 2026)

Tiffany leaves at 6:00pm; Stephanie's MMC meeting runs to 6:30pm. Andrew lands in El Paso at 2:58pm, so he covers. If the flight slips, Tower raises it.

## Output

A short list of gaps with a proposed fix for each (ask Tiffany to stay late, move a block, etc.), or "Covered all week."

## App notes

- Which divisions count as "busy" and who counts as coverage must be configurable.
- Needs travel awareness: parse flight confirmation emails into an itinerary.
