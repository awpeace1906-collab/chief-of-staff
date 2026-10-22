# Roadmap

The principal's own setup steps (accounts, keys, numbers) are tracked in their memory repo, not here.

## Now (live)

- [x] Morning brief, daily, email + Claude session
- [x] Calendar divisions (e.g. me / partner / kids & coverage), configured in memory
- [x] Coverage check
- [x] Propose → approve flow
- [x] Standing agreements as rules the planner applies

## Next

- [ ] Connect Brain (needs `BRAIN_GIST_TOKEN` + `api.github.com` access); seed the agent's rules into it
- [x] Planning on the fly: Re-plan this day on the Day tab, plus flight watches on travel days
- [x] Commitment framework: architecture, board schema, capture prompt, board helper
- [ ] Capture parity check against any brief service the principal already runs; log misses
- [x] Voice and messaging spec; deployment modes (cloud / hybrid / self-hosted)
- [ ] Chief of Staff server v0: inbound SMS → Claude with the agent's tools → reply; approvals by text
- [ ] Voice notes with local Whisper
- [ ] Calls via provider real-time speech; later local speech
- [x] Digest framework: adapters registry, routing, Roundup section
- [x] The agent's own inbox for forwarded digests
- [ ] Confirm real sender addresses for each adapter from the first digest received

## Toward the end goal (see [docs/vision.md](docs/vision.md))

- [x] One front end for everything: Today (brief + approvals), Day, To-do, Talk, all driven by the agent
- [ ] Every source connected: Gmail, Outlook/Microsoft 365, calendars, to-do lists, digests
- [x] Commitment ledger: every promise or sign-up becomes a tracked item with an owner, a due date and evidence of closure
- [x] Accountability loop: overdue and at-risk commitments surface daily, propose a time block or a reply, and escalate until resolved
- [x] Schedule builder (v1): turn open commitments into proposed calendar blocks around fixed events (shifts, call, coverage)

## From the role frameworks (see [docs/research/role-frameworks.md](docs/research/role-frameworks.md))

Live on the page and in the scheduled tasks ([docs/features/evening-and-week.md](docs/features/evening-and-week.md)); in the app's engine and web app too.

- [x] Decisions first: a Decide section with options, a deadline and a recommendation, turned into dated actions once decided
- [x] Tomorrow, tonight: an evening card with tomorrow's first commitment, what to bring, what's due, and coverage
- [x] Weekly review (Sunday): look back and ahead, pick the top 3, check promised hours against free hours
- [x] Reply drafting for "reply owed" and "waiting on" items (Send proposals)
- [x] Interview and meeting kit: prep packet, prep block, thank-you within 24 hours
- [x] Binder: one card per rotation or program, built from intake email
- [x] Travel desk, renewals tracker, expense log, protected time, delegation tracking, monthly alignment

## The app: self-contained Chief of Staff

See [docs/self-contained.md](docs/self-contained.md).

- [x] v0.1 Skeleton: FastAPI app, SQLite store, settings, AI routes, Docker image; import memory, Brain and board; portable export ([app/](app/))
- [x] v0.2 Google: own OAuth (PKCE); Calendar agenda by division; Gmail search and plus-address intake ([docs/setup/google.md](docs/setup/google.md))
- [x] v0.3 Core: capture → board → plan with Claude (structured output); morning brief by email to the principal; built-in scheduler; token usage and cost per route
- [ ] Brief parity with the Claude Code version: flight-email parsing, Brain sync
- [x] v0.4 Own web app (installable PWA): Today (brief, proposals with approve / change / decline), To-do (filters, snooze, swipe to finish), Talk (Ask answers instantly; Send queues for the agent); sign-in by access key; audit log; import from the Claude-hosted page
- [x] App catch-up, part 1 (engine): decisions → next steps, records (trips, binders, expenses, tomorrow and week cards), approved email drafts (off until `email.sendApprovedDrafts`), Move: execution, re-plan endpoint, protected time, renewals and the week's top 3; page import brings them over
- [x] App catch-up, part 2: web app UI for the above (Decide, cards, trips, binders, expenses, Waiting on others, top-3 stars, drafts, Plans changed?, hatched protected time)
- [x] Flight watch in the app: live flight status (AeroDataBox, optional key) + FAA NAS Status airport events; changes re-plan the day
- [ ] App catch-up, part 3: the brief and an evening run file decisions, drafts, trips, binders, expenses and cards themselves
- [x] v0.4 Microsoft 365 via Graph (personal or work accounts, read-only): Outlook mail into capture, Outlook calendar and To Do into the brief ([docs/setup/microsoft.md](docs/setup/microsoft.md))
- [x] v0.4.1 The app's own hourly check (silent unless something fails; then an email to the principal): carries out approved calendar proposals (Calendar write scope; never invites anyone), answers Send messages with tools (list changes directly, everything else as a proposal), turns email to the `+<agent>` address into messages and replies by email, captures new mail
- [x] Optional local AI provider (OpenAI-compatible: Ollama, llama.cpp) for structured routes (triage, plan); tool-using routes stay on Claude
- [x] Brain two-way sync in the app (`BRAIN_GIST_TOKEN`), daily with the first check
- [x] v0.5 Channels: carrier webhooks for SMS (Telnyx, VoIP.ms); approvals by text; brief by text ([docs/setup/sms.md](docs/setup/sms.md))
- [x] Settings screen in the web app: connections (Google, Microsoft, Claude, Brain, texting, scheduler) with connect buttons, agent name, brief time and check hours, "run the check now"
- [x] Two silos: the core holds no principal data; memory is `<agent>-memory` with a permanent agent id, and a rename moves it ([docs/memory.md](docs/memory.md))
- [ ] v0.6 Voice notes (faster-whisper); calls via carrier speech; Piper for replies
- [x] v0.7 Brain sync (two-way, optional); export/backup (moved up into v0.4.1)
- [ ] Cut over from the Claude Code scheduled tasks and the page to the hosted app

## The app: later

- [x] Configurable agent name, divisions, coverage people, standing agreements (from memory)
- [x] Google OAuth for Calendar and Gmail; Microsoft Graph as an optional direct source
- [ ] Per-user agent inbox and a digest adapter library principals can extend
- [ ] Brain (`brain/v1` gist) as the memory store
- [ ] Scheduler for the brief and re-plan triggers
- [ ] One-tap approvals (push / email)
- [ ] Voice line
- [ ] Settings → Advanced → Hosting: cloud / hybrid / self-hosted, with telephony, speech, AI endpoint, storage and intake options
- [ ] Docker image (self-hosted) and one-line installer (hybrid)
- [ ] Company installs: SSO, per-user agents, audit log, retention, integration API
