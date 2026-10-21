# Vision

## End goal

A self-contained application with one front end, where the owner's agent (named by the owner) does the work of a chief of staff:

- **Watches everything the user is on the hook for.** Every email account, calendar, to-do list and digest the user connects.
- **Creates, summarizes and organizes.** It turns what it finds into a schedule and a task list: briefs, proposed calendar blocks, and to-dos with owners and due dates.
- **Keeps the user accountable.** Anything the user signed up for, promised or was asked to do becomes a tracked commitment. It stays visible, gets scheduled and gets followed up until it's done, declined or handed off. Nothing quietly drops.

It does everything the first deployment does (briefs, coverage checks, planning on the fly, commitment tracking, voice and memory) and runs without Claude Code or any one vendor's assistant.

## Principles

1. **Propose, then act.** The agent proposes every action, numbered. It creates events, sends email or changes calendars only after explicit approval. Approval can be partial ("approve 1, 3").
2. **Build on, don't repeat.** If another tool already reported something (another brief service), the agent verifies it and turns it into an action instead of restating it.
3. **Households, not just people.** Calendars are grouped into divisions (me, partner, kids/coverage) so the agent can reason about who is where and who has the kids.
4. **Memory lives with the owner.** People, rules and preferences live in the agent's memory (`<agent>-memory`, [memory.md](memory.md)) and Brain (the owner's own gist), never in the app's code.
5. **Readable in 60 seconds on a phone.**
6. **Accountability over reminders.** A commitment is closed only by evidence: a sent reply, a booked event, the user marking it done or declining it. Silence isn't closure. Overdue and at-risk commitments surface in the brief and the front end until they're resolved.

## Product requirements

- **The app is Chief of Staff; the agent's name is the owner's.** Each owner names their own. The name drives email subjects (`<name>:`), the voice wake phrase, how drafts are signed, and the memory folder (`<name>-memory`). A permanent id, set from the first name, is the `source`/id prefix of entries it writes to Brain, so a rename keeps the same agent. Never hard-code it; product code, schemas and files use `cos`.
- **Divisions are configurable.** Users map any calendars to any divisions and say which division's events count as "working".
- **Standing agreements are first-class.** Example: "when I'm out of town on rotation, my Monday sessions go remote." Store these as rules the planner applies, not as one-off notes.
- **Self-contained.** One app, one database. Outside resources are limited to hosting, the phone carrier, the AI service and the user's own data sources (Google). See [self-contained.md](self-contained.md).
- **Hosting is the user's choice.** Cloud (default), hybrid, or fully self-hosted at home or in an office, set in Settings → Advanced → Hosting. People and companies can run the agent on their own hardware and integrate it with their own systems. See [deployment.md](deployment.md).
- **Talk, text or call.** Voice and messaging are core, not add-ons. See [features/voice-and-messaging.md](features/voice-and-messaging.md).
- **Every rule is portable.** Rules live as structured entries (Brain `brain/v1`) so the app can load the same memory.
