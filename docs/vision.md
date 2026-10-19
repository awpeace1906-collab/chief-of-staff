# Vision

## End goal

A self-contained application that does everything Tower does today: briefs, coverage checks, planning on the fly, commitment tracking, voice, and memory. It should run without Claude Code, readywhen, or any one vendor's assistant.

## Principles

1. **Propose, then act.** Tower proposes every action, numbered. It creates events, sends email or changes calendars only after explicit approval. Approval can be partial ("approve 1, 3").
2. **Build on, don't repeat.** If another tool already reported something (readywhen's brief), Tower verifies it and turns it into an action instead of restating it.
3. **Households, not just people.** Calendars are grouped into divisions (me, partner, kids/coverage) so Tower can reason about who is where and who has the kids.
4. **Memory lives with the user.** Rules and preferences live in Brain (the user's own gist), not inside the assistant.
5. **Readable in 60 seconds on a phone.**

## Product requirements

- **Assistant name is configurable.** "Tower" is Andrew's name for his assistant. In the public app each user names their own. The name drives email subjects (`<name>:`), the voice wake phrase and how drafts are signed. Never hard-code it.
- **Divisions are configurable.** Users map any calendars to any divisions and say which division's events count as "working".
- **Standing agreements are first-class.** Example: "when I'm out of town on rotation, Jason appointments go remote." Store these as rules the planner applies, not as one-off notes.
- **Hosting is the user's choice.** Cloud (default), hybrid, or fully self-hosted at home or in an office, set in Settings → Advanced → Hosting. People and companies can run Tower on their own hardware and integrate it with their own systems. See [deployment.md](deployment.md).
- **Talk, text or call.** Voice and messaging are core, not add-ons. See [features/voice-and-messaging.md](features/voice-and-messaging.md).
- **Every rule is portable.** Rules live as structured entries (Brain `brain/v1`) so the app can load the same memory.
