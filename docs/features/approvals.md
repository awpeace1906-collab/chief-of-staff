# Propose → approve

**Status:** live.

## How it works

1. Tower lists every action it wants to take as a numbered proposal: a calendar block, a draft email, a reschedule.
2. Andrew answers on the Chief of Staff page's Today tab (**Approve**, **Change…** to approve with edits, or **Decline**), or in the Claude session: `approve 1, 3`, `approve all`, or edits ("approve 2 but make it 7pm").
3. Only then does Tower create the event, send the email or change the calendar, and confirm what it did.

## Never without approval

- Creating, moving or deleting calendar events
- Sending email to anyone other than Andrew
- Changing anything on someone else's calendar

## Allowed without approval

- Reading calendars and email
- Sending the brief to Andrew
- Saving rules Andrew states to Brain

## App notes

The app needs a one-tap approve on each proposal (push notification or the brief email itself), not just a chat reply.

## Proposal shape (page)

`proposals/<YYYY-MM-DD>-<n>`: `day`, `n`, `kind` (calendar | email | list | other), `division` (me | stephanie | kids), `calendar` (name), `title` (starts with a verb: "Add: …", "Fix: …", "Move: …", "Send: …"), `when` (Mountain time, plus local when traveling), `where`, `change` (for edits: "old → new"), `summary` (one line: why), `status` (pending | approved | declined | done | failed), `changes` (Andrew's edits when he approves with changes), `result`.

The page shows the agent's name from `settings/profile.agentName`. "Tower" is Andrew's choice, not hard-coded.
