# Location: where the principal is

**Status:** in the app (`app/cos/location.py`) and in the scheduled tasks' instructions.

The agent never assumes where the principal is. Every leave-by time, drive time and coverage call starts from a known place, and the agent says which place it used, so the principal can correct a wrong one.

## Where it looks, in order

1. **The phone.** The principal's phone reports its location (below). A report counts while it's fresh, 6 hours by default (`location.freshHours`). It covers today, and tomorrow when the report comes the evening before, since that's where the principal will sleep. Within `location.homeRadiusKm` (25 km) of home, it reads as "home".
2. **A trip.** A trip in `trips/<slug>` whose `start`–`end` covers the day. The trip's optional `base` (`{label, lat?, lon?}`, e.g. the rotation's hotel or apartment) is the starting point; without one, the trip's title is used.
3. **Home.** The `home` setting from memory (`{label, lat?, lon?, airport?}`). This is a fallback, so the agent says it's assumed: "from home in …, assumed".
4. **Unknown.** If none of these is set, the agent asks rather than guessing.

The result (`whereabouts`) is `{label, source: phone|trip|home|unknown, lat?, lon?, asOf?, note}`. The daily brief, re-plans and message replies all get it, and their instructions require the starting point to be named.

## Getting the phone's location

- **In the native app (the target):** the Chief of Staff app reads the phone's own location services and works out the starting point on the device. Only that starting point goes to the server, and only when a server task (an overnight brief, a flight watch) needs it. The options below are the stopgap until then.
- **The app:** `POST /api/location {lat, lon, accuracy?, at?, place?}` with the API token. Only the latest report is kept (`lastLocation`); there's no history. `GET /api/location?date=YYYY-MM-DD` shows what the agent would use for that day, and why.
- **iPhone:** a Shortcuts personal automation ("Time of Day" before the daily brief and evening setup, plus "Arrive"/"Leave" for places that matter) runs: Get Current Location → Get Details of Locations (City) → Get Contents of URL (POST, JSON body `lat`, `lon`, `place`, header `Authorization: Bearer <token>`). Turn off "Ask Before Running".
- **Android:** the same with Tasker or an HTTP Shortcuts app.
- **Before the app is hosted:** the automation can instead email the agent's inbox (subject `Location`, body `lat, lon, place`). The scheduled tasks read the latest such email as the phone's report.

## Privacy

- Only the latest point is stored, in the principal's own database. It's never sent anywhere else and never written to the memory repo or the core.
- The token in the automation is the app's API token; keep it in the phone's Shortcuts, not in memory files.
