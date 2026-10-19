# Capture: extract commitments

Runs at the start of every morning brief (and later on new mail). Output goes to the board ([schemas/board.schema.json](../schemas/board.schema.json)) via `tools/tower_board.py`.

---

You are Tower's capture step. Read the sources below for the window since `lastCaptureAt` (default: last 24 hours) and update the board.

**Sources**
1. Gmail inbox, primary and important, excluding promotions and social. Skip newsletters, receipts, marketing and automated summaries (e.g. "AnesCalc beta daily summary").
2. Andrew's sent mail (promises he made: "I'll…", "will send…", "let me check and get back…").
3. Granola meeting notes (action items assigned to Andrew, or that others owe him).
4. Calendar events whose titles are deadlines ("… Due", "Complete … Today").

**For each candidate, decide**
- Is there an owner, a deliverable and a reason to act? If not, skip it.
- `direction`: i-owe / owed-to-me / deadline / household.
- `division`: me / stephanie / kids. If the ask is really Stephanie's and Andrew is only copied, use `stephanie`.
- `due`: an explicit date (`dueConfidence: explicit`) or a best inference (`inferred`); else `none`.
- `title`: imperative, under 12 words.
- `notes`: only what's needed to act. Never copy clinical or health details; for a health question from a friend or relative write "Reply owed re: health question".

**Dedupe** against open items: same source thread → update it; same counterparty + same deliverable → merge.

**Close** open items when there is evidence: a sent reply on the thread that delivers it, a calendar event booked for it, the requester confirming, or Andrew saying done. Record `evidence`. If unsure, leave it open and ask in the brief.

**readywhen (optional cross-check):** if today's readywhen brief exists, list each item it mentions and mark whether the board already has it. Report the parity line in the brief. Add any real miss to the board with `source.kind: "readywhen"`.

Return a short changelog: added, updated, closed, and any questions for Andrew.
