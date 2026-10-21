# Commitments (the board)

**Status:** framework drafted. Replaces readywhen's core feature.

## What counts as a commitment

Something with an owner, a deliverable, and (ideally) a deadline.

| Direction | Example | Source |
|---|---|---|
| **I owe** (inbound ask) | "Upload your flu shot to My Clinical Exchange by Oct 14" | Email from a rotation coordinator |
| **I owe** (my promise) | "I'll send you the slides Friday" | Andrew's sent mail, meeting notes |
| **Owed to me** | "Veronica will send interview details a week before" | Email to Andrew |
| **Deadline** | "Mid-point eval due Sun 23:59" | Calendar, school email |
| **Household** | "Re-evaluate Tiffany's contract and pay" | Andrew tells Tower |

Not commitments: newsletters, receipts, automated summaries (e.g. AnesCalc daily summary), FYI forwards with no ask.

## Lifecycle

```
open ──► proposed (Tower drafted an action) ──► done
  │                                              ▲
  ├──► waiting (owed to me; nudge if late) ──────┤
  ├──► snoozed (until date) ──► open             │
  └──► dropped (Andrew says no)                  │
                         evidence of completion ─┘
```

**Done evidence** Tower looks for on every capture run:
- A sent reply on the source thread, or an email containing the deliverable
- A calendar event created for it (e.g. "financial review" booked)
- The requester confirms receipt
- Andrew says "done"

When evidence is found, Tower marks it `done` and says so in the next brief ("Closed: Tucson upload, you sent it Oct 14"). If evidence is ambiguous, it asks instead of closing.

## Capture rules

1. **Scope per run:** mail since the last run (default 24h), Granola notes since last run, calendar changes.
2. **Dedupe** against open items by source thread id first, then by meaning (same person + same deliverable).
3. **Due dates:** use an explicit date if there is one; otherwise infer and mark `dueConfidence: "inferred"` so the brief says "inferred, check it".
4. **Division:** tag each item `me`, `stephanie` or `kids` so it lands in the right part of the brief. If Andrew is just CC'd on Stephanie's ask, it's hers (e.g. Ryan's financial review may be mainly Stephanie's).
5. **Link back:** every item keeps its source URL so one tap opens the original.
6. **Sensitive mail:** medical questions from friends or family (e.g. a forwarded health question) are captured as "reply owed" only, with no clinical content copied into the board.

## Accountability loop

**Status:** live in the morning brief and in the app (`app/cos/accountability.py`). The goal: nothing Andrew signed up for or promised quietly drops.

- **Promises are first-class.** When Andrew's sent mail promises something ("I'll…", "I will…", "let me get back to you"), it becomes an `i-owe` item with `promise: true` and `counterparty` set to the recipient. With no date, the due date is inferred ("asap" = 2 days, "this week" = Friday) and marked as inferred.
- **Every brief reviews the board:**
  - **overdue:** past due and still open.
  - **dueSoon:** due within 2 days.
  - **undatedPromises:** a promise with no date after 3 days.
  - **waitingLate:** something owed to Andrew that's past due.
  - **Snoozes:** snoozed items wake on their `snoozedUntil` date.
- **Each one gets a proposal** unless a pending one already covers it: a time block in a real free slot, a drafted reply, a new date, or a nudge to the other person.
- **Nudges are counted.** Each brief that surfaces an item adds one to `nudges` (at most once a day; `lastSurfaced`).
- **Escalation:** after 3 briefs, the item is "stuck" and the brief asks plainly: do it (slot), move it (date), or drop it?
- **Closure needs evidence** (below) or Andrew's say-so. The loop never closes or drops anything by itself.
- **Schedule builder** (`app/cos/schedule.py`): finds free windows in Andrew's division, around busy events (shifts, interviews; free/"Away" markers don't block), 7am–9pm in his home timezone. Each surfaced item gets the earliest 30-minute window before its due date (late items take the first window). The brief proposes these as "Add: …" blocks, so nothing reaches the calendar without approval. Settings: `schedule.dayStart`, `dayEnd`, `minMinutes`, `blockMinutes`, `division`.
- **Day view:** the page's Day tab shows the day hour by hour, with surfaced to-dos suggested in the free time (see [day-view.md](day-view.md)).
- **On the page:** the To-do tab shows "You promised <person>", "date guessed", how many briefs have brought an item up, and the do/move/drop question once an item is stuck. **Drop it** closes an item on purpose. Rescheduling resets the count.

## Brief integration

The brief's **You owe** section comes from the board: overdue, due today, due within 7 days, then waiting-on items past their expected date. Each one gets a proposal where useful (draft the reply, block time, book the call).

## Parity with readywhen (transition)

During the parallel run, each brief ends with a one-line scorecard:
`Parity: Tower 5 / readywhen 5 · missed by Tower: 0 · missed by readywhen: 1`
Misses get written to `docs/capture-misses.md` to tune [prompts/capture.md](../../prompts/capture.md).
