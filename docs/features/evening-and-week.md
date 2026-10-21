# Decide, Tomorrow, Week, Trips, Binders, Expenses

**Status:** live on the Chief of Staff page. They come from the chief-of-staff and assistant frameworks ([research](../research/role-frameworks.md)), built in the ranked order. The app (`app/`) has the engine for them (see [The app](#the-app)); its web app screens come next.

| # | Feature | Where it shows | Who fills it |
|---|---|---|---|
| 1 | **Decide**: choices with a deadline, options, trade-offs and an optional recommendation | Top of Today | Morning brief (`decisions/<slug>`). A tap records the choice and wakes Tower, which turns it into dated next steps the same day (`actions`). |
| 2 | **Tomorrow**: first commitment and when to leave, what to bring, what's due, coverage, flights | Today, from evening until noon | Evening setup, 6:47pm MT daily (`brief/tomorrow`) |
| 3 | **Weekly review**: last week, this week, promised vs free hours, suggested top 3 | Today, during the week | Evening setup on Sundays (`brief/week`). Andrew stars his top 3 in To-do (`items.top` = the week's Monday). |
| 4 | **Reply drafts**: "Send:" proposals with the email shown; Change… edits the text; Send sends it | Today, Needs your OK | Morning brief files them (`proposal.draft`); the on-demand run sends after approval (Gmail, on the thread) |
| 5 | **Interview kit**: prep item, a prep block the day before, thank-you draft within 24 hours | To-do and Needs your OK | Morning brief |
| 6 | **Rotation binder**: dates, first day, shifts, phones, people, before-you-leave | Day tab, while the rotation is on | Morning brief, from intake mail (`binders/<slug>`); no passwords stored |
| 7 | **Next trip**: legs with times, what's missing | Today | Morning brief from flight, hotel and TripIt mail (`trips/<slug>`) |
| 8 | **Renewals**: certifications, licenses, immunizations | To-do (`kind: "renewal"`, `expires`) | Morning brief; surfaced at 60, 30 and 7 days |
| 9 | **Expenses** by trip or rotation, with totals | To-do, Expenses | Evening setup from receipts (`expenses/<slug>`) |
| 10 | **Protected time**: weekly windows that are never free time | Day tab, hatched | `settings/schedule.protect: [{label, start, end, days?}]`, set by Andrew |
| 11 | **Waiting on others**: things handed off, with the person and a check-in | To-do, own group | Morning brief; nudges drafted when late |
| 12 | **Monthly alignment**: "What should Tower start, stop or keep doing?" | The brief on the 1st | Morning brief; answers become config rules |

Sending email: an approved "Send:" proposal is Andrew's permission to send that one email, from his Gmail, to the recipient shown. Nothing else ever goes to anyone but Andrew.

## The app

The engine is in; the web app's screens and the runs that fill these come next.

| Page | App |
|---|---|
| `decisions/<slug>` | `records` kind `decision`. `PUT /api/records/decision/<slug>` files one; `POST /api/decisions/<slug>/choose {choice}` is the owner's tap, and the assistant writes `actions` straight away (`agent.act_on_decisions`, also in every check). Refiling a decided decision keeps the choice. |
| `brief/tomorrow`, `brief/week` | `records` kind `card`, ids `tomorrow` and `week` |
| `trips/`, `binders/`, `expenses/` | `records` kinds `trip`, `binder`, `expense`; `GET /api/records/<kind>` |
| Reply drafts | `proposal.draft {to, subject, body, threadId}`; the owner's edit is `draftBody`. An approved draft is sent exactly as shown, from the owner's Gmail, on the thread, only when the `email` setting has `sendApprovedDrafts: true` (off by default). |
| Renewals | `accountability.review(...)["renewals"]`: `kind: "renewal"` items expiring within 60 days, with `alert` at 60, 30 and 7 days and from 7 days on |
| Top 3 | `items.top` = this week's Monday; `review(...)["top"]` |
| Protected time | `schedule.protect` setting, same shape as the page; `free_slots` never offers it; `/api/day` returns `protected` |
| Waiting on others | items with `direction: "owed-to-me"` or status `waiting`; `review(...)["waitingLate"]` |

`POST /api/import/page` brings the page's decisions, trips, binders, expenses and cards over, with items' `promise`, `top`, `kind` and `expires`, and proposals' drafts.
