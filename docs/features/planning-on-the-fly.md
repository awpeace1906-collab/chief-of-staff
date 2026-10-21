# Planning on the fly

**Status:** live on the Chief of Staff page and in the scheduled tasks. It follows the assistant role: when plans change, adjust and say what moved.

## Re-plan this day (Day tab)

- **Asking:** Andrew taps **Plans changed?**. He picks Running late, Ran long, Free early or Flight delayed, or types what happened, then taps **Re-plan this day**.
- **What's sent:** a `messages` doc with `kind: "replan"`, the day, the local time and the time zone. Sending it wakes Tower straight away.
- **What Tower does** (on-demand run, step 3):
  - Reads that day's calendars and Day-tab blocks, and applies the change.
  - Files a pending **Move:** proposal for each block or flexible event that no longer fits, to the next free window that day or the next. Fixed commitments (shifts, interviews, flights, appointments) are never moved.
  - Flags any coverage break, and proposes a new date or a quick reply for any promise due that day.
  - Replies in one message: what changed, what's proposed, and what's still fine.
- **Approving:** an approved Move: changes the calendar event (no notifications).

## Flight watches

- **Scheduling:** the evening setup schedules one-shot checks for tomorrow's flights: 3 hours before the first leg, and 1 hour before each connection. Names start "Tower · flight watch"; they're never duplicated.
- **The check:** each one reads airline and TripIt mail for delays, cancellations, gate changes or a missed connection. If nothing changed, it's silent.
- **If something changed:** it updates the trip card and posts a message. It proposes the fix for what's affected, such as tomorrow's first-day logistics, with any note to a coordinator drafted for approval.
- **Urgent changes:** only a cancellation or an overnight delay also emails Andrew a 3-line alert, because those need action within hours.
- **First use:** St. Louis, Sun Oct 25. AA 690 is watched at 2:36pm MT, AA 1445 at 7:55pm MT.

## The app

The app's `schedule.py` already finds free windows. A `replan` endpoint and Move: execution in `agent.py` come with the app catch-up.
