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
- [ ] v0.2 Google: own OAuth; Calendar + Gmail read; plus-address intake label
- [ ] v0.3 Core: capture → board → plan with Claude tool use; morning brief by email; token usage logged per route
- [ ] Optional local AI provider (Ollama / llama.cpp) for any route ([docs/features/ai-providers.md](docs/features/ai-providers.md))
- [ ] v0.4 Approvals: PWA (brief, board, one-tap approve) + audit log
- [ ] v0.5 Channels: carrier webhooks for SMS; approvals by text
- [ ] v0.6 Voice notes (faster-whisper); calls via carrier speech; Piper for replies
- [ ] v0.7 Brain sync (two-way, optional); export/backup
- [ ] Cut over from Claude Code scheduled task, AgentMail and readywhen

## The app: later

- [ ] Configurable assistant name, divisions, coverage people, standing agreements
- [ ] Google OAuth for Calendar and Gmail; Microsoft Graph as an optional direct source
- [ ] Per-user assistant inbox and a digest adapter library users can extend
- [ ] Brain (`brain/v1` gist) as the memory store
- [ ] Scheduler for the brief and re-plan triggers
- [ ] One-tap approvals (push / email)
- [ ] Voice line
- [ ] Settings → Advanced → Hosting: cloud / hybrid / self-hosted, with telephony, speech, AI endpoint, storage and intake options
- [ ] Docker image (self-hosted) and one-line installer (hybrid)
- [ ] Company installs: SSO, per-user assistants, audit log, retention, integration API
