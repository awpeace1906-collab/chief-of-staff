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

### Live flight status and public ATC data (the app)

The app watches flights itself, from live data rather than email (`app/cos/flights.py`):

- **Sources:**
  - The FAA's public NAS Status feed (`nasstatus.faa.gov`, no key): ground stops, ground delay programs, departure and arrival delays, and closures at each leg's airports.
  - Flight status from AeroDataBox (RapidAPI, `AERODATABOX_KEY`): status, revised departure and arrival, gate, cancelled, diverted. Without a key, only the FAA data is used.
- **What's watched:** trip legs that carry `flight` ("AA 690"), `date` (local departure date) and `from`/`to` (IATA). A leg is checked every 20 minutes from 6 hours before departure until 2 hours after arrival (`flights` setting: `watchHours`, `intervalMinutes`, `provider`).
- **On a change:** the leg's `live` field is updated (the trip card shows it), and the owner gets one message.
  - **Re-plan:** a delay of 30+ minutes, a cancellation, a diversion, or an FAA ground stop or closure files a `replan` message for the arrival day. When Google is connected it's handled straight away, so the **Move:** proposals are waiting when he lands.
  - **Email:** a cancellation, a diversion, or an arrival pushed past midnight also emails the owner a 3-line alert. Nothing else is sent, and nothing is rebooked.
- **API:** `GET /api/flights` (watched legs with live status); `POST /api/flights/check` (check now).
- **Not used:** live aircraft position (ADS-B, e.g. OpenSky). It says where the plane is, not whether the schedule changed; the status feed already reports departed, landed and diverted.

## The app

- **Re-plan:** `POST /api/replan {day, at, timeZone, what}`, or **Plans changed?** on the web app's Day tab, stores a `replan` message and handles it straight away. The assistant reads the day (`find_events`, `free_time`), files **Move:** proposals with `propose_move`, and replies with what changed. See [day-view.md](day-view.md#in-the-app).
- **Move:** an approved proposal with `eventId`, `start` and `end` moves that event to exactly those times, with no model call and nobody notified.
- **Flight watches:** the app's own watch uses live status and FAA data (above), so it needs no scheduled one-shot tasks.
