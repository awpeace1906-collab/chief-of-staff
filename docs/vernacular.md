# Vernacular

Chief of Staff borrows the language of a head of state's staff and protective detail. These terms are used across the docs, prompts, app text and the agent's own writing. Code identifiers and stored data keys don't change (`owner`, `brief/tomorrow`, `decisions`, `whereabouts`, `coverage`), so renaming a term never breaks a memory repo or a database.

| Term | Means | Was | Where it shows |
|---|---|---|---|
| **Principal** | The person the agent serves: the app's user. Everything is planned around the principal's day, position and commitments. | owner, user | Everywhere |
| **Chief of Staff** | The app: the interface between the principal and their agent. | | App name |
| **Callsign** | The agent's name, which the principal chooses (the alias). It can be changed; the agent's permanent id never does ([memory.md](memory.md)). | alias | Settings, email subjects |
| **Daily brief** | The morning briefing, as in the President's Daily Brief. | Morning brief | Email, Today tab |
| **The Book** | The evening package for tomorrow: first movement and when to leave, what to bring, what's due, the detail, prep for tonight. A President's staff hands over "the Book" each night. | Tomorrow card | Today tab (evening until noon) |
| **Situation Room** | Choices only the principal can make, with options, a recommendation and a deadline. | Decide | Top of the daily brief and the Today tab |
| **Movement** | Any time the principal travels: a drive, a flight leg, a transfer. "Wheels up" and "arrived" are a movement's status. | Trip legs, drive times | Next movement card, the Book, flight watches |
| **Advance** | Prep for an event or trip, done before the day: route, timing, parking, badge, contacts. | Prep items, binders | Proposals, binders |
| **Position** | Where the principal is: phone, then trip, then home ([location](features/location.md)). | Whereabouts, location | Drive times, re-plans |
| **Detail** | Everyone covering the household at a given time: partner, nanny, family. A coverage gap is a hole in the detail. | Coverage | The daily brief, the Book |

## Not used

- **Codenames** and **protectees**: the principal's household goes by its own names.
