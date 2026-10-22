# Propose → approve

**Status:** live. In the app (v0.4), proposals live in its own database and the web app's Today tab is where the principal approves them. The app's hourly check carries out approved calendar proposals itself. It applies the principal's Change… notes; "hold" means nothing changes. It never invites or notifies anyone. Email proposals ("Send:") show the full draft; Change… edits it and Send approves it. The approved text is sent exactly as shown from the principal's Gmail, on the thread.

**Until the app is hosted:** the Chief of Staff page (a Claude-hosted page) carries approvals. There's no hourly polling. Tapping **Approve** or sending a message wakes the agent straight away through an on-demand scheduled task. Taps close together share one run, with at most one more per 90 seconds. Anything that can't wake the agent (a declined connector permission, say) is picked up by the next morning brief.

## How it works

1. The agent lists every action it wants to take as a numbered proposal: a calendar block, a draft email, a reschedule.
2. The principal answers on the page's Today tab (**Approve**, **Change…** to approve with edits, or **Decline**), or in the Claude session: `approve 1, 3`, `approve all`, or edits ("approve 2 but make it 7pm").
3. Only then does the agent create the event, send the email or change the calendar, and confirm what it did.

## No duplicates

A proposal never adds an event that's already on a calendar. The agent checks all division calendars first; when the email and the existing event disagree, it proposes fixing the existing event (see `calendarRules` in memory).

## Never without approval

- Creating, moving or deleting calendar events
- Sending email to anyone other than the principal
- Changing anything on someone else's calendar

## Allowed without approval

- Reading calendars and email
- Sending the brief to the principal
- Saving rules the principal states to Brain and memory

## App notes

- Exact proposals run without a model call: a day-view block (`start`, `end`), a **Move:** (`eventId`, `start`, `end`) and an email draft.
- An approved email draft is sent only when the `email` setting has `sendApprovedDrafts: true`. It's off until the principal turns it on; until then an approved draft fails with that reason.

The app needs a one-tap approve on each proposal (push notification or the brief email itself), not just a chat reply.

## Proposal shape (page)

`proposals/<YYYY-MM-DD>-<n>`: `day`, `n`, `kind` (calendar | email | list | other), `division` (a key from memory's divisions), `calendar` (name), `title` (starts with a verb: "Add: …", "Fix: …", "Move: …", "Send: …"), `when` (home time, plus local when traveling), `where`, `change` (for edits: "old → new"), `summary` (one line: why), `status` (pending | approved | declined | done | failed), `changes` (the principal's edits when approving with changes), `result`. Also `draft {to, subject, body, threadId}` and `draftBody` (the principal's edit) for Send:, and `eventId`, `start`, `end`, `timeZone` for Move: and day-view blocks.

The page shows the agent's name from `settings/profile.agentName`; it's the principal's choice, not hard-coded.
