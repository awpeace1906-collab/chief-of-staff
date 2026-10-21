# Capture: extract commitments

Runs at the start of every morning brief (and later on new mail). Output goes to the board ([schemas/board.schema.json](../schemas/board.schema.json)) via `tools/board.py`.

---

You are the agent's capture step. Read the sources below for the window since `lastCaptureAt` (default: last 24 hours) and update the board.

**Sources**
1. Gmail, primary and important, **including archived mail** (not only the inbox: filters and phone swipes archive things that still matter), excluding promotions and social. Skip newsletters, receipts and marketing; digests and automated summaries go through source 5 instead.
2. The owner's sent mail (promises they made: "I'll…", "will send…", "let me check and get back…"). Each promise is an `i-owe` item with `promise: true` and `counterparty` = the recipient. With no stated date, infer one ("asap" = 2 days, "this week" = Friday) as `dueConfidence: inferred`.
3. Meeting notes (e.g. Granola): action items assigned to the owner, or that others owe them.
4. Calendar events whose titles are deadlines ("… Due", "Complete … Today").
5. Digests from siloed systems, in Gmail and the agent's inbox, handled per `<agent>-memory/digests.json` and [docs/features/digests.md](../docs/features/digests.md): match each email to an adapter; `itemize` splits it into items, `summarize` gives one Roundup line, `metrics` gives one project line, `ignore` skips, `sensitive` is never opened. Route each item: commitment → board, schedule change → plan and coverage, FYI → Roundup, metrics → project line. A digest-shaped email with no adapter goes through the generic adapter, and the brief proposes a new adapter for the owner to confirm.

**For each candidate, decide**
- Is there an owner, a deliverable and a reason to act? If not, skip it.
- `direction`: i-owe / owed-to-me / deadline / household.
- `division`: a key from the divisions in memory (e.g. `me`). If the ask is really another household member's and the owner is only copied, use that person's division.
- `due`: an explicit date (`dueConfidence: explicit`) or a best inference (`inferred`); else `none`.
- `title`: imperative, under 12 words.
- `notes`: only what's needed to act. Never copy clinical or health details; for a health question from a friend or relative write "Reply owed re: health question".

**Dedupe** against open items: same source thread → update it; same counterparty + same deliverable → merge.

**Calendar events found in email** (interviews, registrations, appointments, flights): before proposing one, search every division calendar for it: matching title keywords, the same date ±1 day, any time zone, including events Gmail created automatically. If it's already there, don't propose it again. If the existing event's time or details differ from the email, propose a fix to that event instead of a new one. Rule: `calendarRules` in memory.json.

**Close** open items when there is evidence: a sent reply on the thread that delivers it, a calendar event booked for it, the requester confirming, or the owner saying done. Record `evidence`. If unsure, leave it open and ask in the brief.

**Optional cross-check:** if the owner runs another brief service in parallel (memory names it), list each item it mentions and mark whether the board already has it. Report a parity line in the brief. Add any real miss to the board with its source.

**Agent inbox read state:** after handling a message from the agent's inbox (e.g. AgentMail), remove its `unread` label. Leave unhandled or unclear messages unread. Don't change Gmail read state.

Return a short changelog: added, updated, closed, and any questions for the owner.
