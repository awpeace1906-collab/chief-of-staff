# Roadmap

## Now (live)

- [x] Morning brief, 8:25am MT, email + Claude session
- [x] Calendar divisions: Me / Stephanie / Kids & coverage
- [x] Coverage check
- [x] Propose → approve flow
- [x] Standing agreement: Jason remote during rotations

## Next

- [ ] Connect Brain (needs `BRAIN_GIST_TOKEN` + `api.github.com` access); seed Tower's rules into it
- [ ] Planning on the fly: when something changes (delay, cancellation, new deadline), re-plan the day and propose the moves
- [x] Commitment framework drafted: architecture, board schema, capture prompt, board helper
- [ ] Run capture + board alongside readywhen for 2 weeks; log misses in `docs/capture-misses.md`
- [ ] Parity reached → drop readywhen from the brief; move brief time if wanted
- [x] Voice and messaging spec; deployment modes (cloud / hybrid / self-hosted)
- [ ] Choose home hardware for the Chief of Staff server
- [ ] Rent a number (VoIP.ms or Telnyx); start A2P 10DLC registration
- [ ] Chief of Staff server v0: inbound SMS → Claude with Tower's tools → reply; approvals by text
- [ ] Voice notes with local Whisper
- [ ] Calls via provider real-time speech; later local speech
- [ ] Retire readywhen's WhatsApp
- [ ] Tiffany contract review: pull her scheduled hours from the calendar as a starting point
- [x] Digest framework: adapters registry, routing, Roundup section
- [x] Create the Tower inbox: `tower-andrew@agentmail.to`
- [ ] burrell.edu Outlook rules: forward Microsoft 365 digests (Viva briefing, Teams, Planner, SharePoint) to the Tower inbox; confirm IT allows external forwarding
- [ ] Confirm real sender addresses for each adapter from the first digest received

## The app: self-contained Chief of Staff

See [docs/self-contained.md](docs/self-contained.md).

- [x] v0.1 Skeleton: FastAPI app, SQLite store, settings, AI routes, Docker image; import `config/*.json`, Brain and board; portable export ([app/](app/))
- [x] v0.2 Google: own OAuth (PKCE, read-only); Calendar agenda by division; Gmail search and plus-address intake ([docs/setup/google.md](docs/setup/google.md))
- [ ] Andrew: create the Google Cloud project and connect (one-time, [docs/setup/google.md](docs/setup/google.md))
- [x] v0.3 Core: capture → board → plan with Claude (structured output); morning brief by email to the owner; built-in scheduler; token usage and cost per route
- [ ] Andrew: Anthropic API key in the app's environment; reconnect Google for the send permission
- [ ] Brief parity with the Claude Code version: flight-email parsing, readywhen parity line, Brain sync
- [x] v0.4 Own web app (installable PWA): Today (brief, proposals with approve / change / decline), To-do (filters, snooze, swipe to finish), Talk (Ask answers instantly; Send queues for the assistant); sign-in by access key; audit log; import from the old Claude-hosted page
- [x] v0.4 Microsoft 365 via Graph (personal or work accounts, read-only): Outlook mail into capture, Outlook calendar and To Do into the brief ([docs/setup/microsoft.md](docs/setup/microsoft.md))
- [ ] Andrew: pick a host (Fly.io recommended) and deploy; register the Microsoft app and connect
- [x] v0.4.1 The app's own hourly check (silent unless something fails; then an email to the owner): carries out approved calendar proposals (Calendar write scope; never invites anyone), answers Send messages with tools (list changes directly, everything else as a proposal), turns email to the `+tower` address into messages and replies by email, captures new mail
- [x] Optional local AI provider (OpenAI-compatible: Ollama, llama.cpp) for structured routes (triage, plan); tool-using routes stay on Claude
- [x] Brain two-way sync in the app (`BRAIN_GIST_TOKEN`), daily with the first check
- [ ] v0.5 Channels: carrier webhooks for SMS; approvals by text
- [ ] v0.6 Voice notes (faster-whisper); calls via carrier speech; Piper for replies
- [x] v0.7 Brain sync (two-way, optional); export/backup (moved up into v0.4.1)
- [ ] Cut over from Claude Code scheduled task, AgentMail and readywhen

## The app: later

- [ ] Configurable assistant name, divisions, coverage people, standing agreements
- [x] Google OAuth for Calendar and Gmail; Microsoft Graph as an optional direct source
- [ ] Per-user assistant inbox and a digest adapter library users can extend
- [ ] Brain (`brain/v1` gist) as the memory store
- [ ] Scheduler for the brief and re-plan triggers
- [ ] One-tap approvals (push / email)
- [ ] Voice line
- [ ] Settings → Advanced → Hosting: cloud / hybrid / self-hosted, with telephony, speech, AI endpoint, storage and intake options
- [ ] Docker image (self-hosted) and one-line installer (hybrid)
- [ ] Company installs: SSO, per-user assistants, audit log, retention, integration API
