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
- [ ] Choose home hardware for the Tower server
- [ ] Rent a number (VoIP.ms or Telnyx); start A2P 10DLC registration
- [ ] Tower server v0: inbound SMS → Claude with Tower's tools → reply; approvals by text
- [ ] Voice notes with local Whisper
- [ ] Calls via provider real-time speech; later local speech
- [ ] Retire readywhen's WhatsApp
- [ ] Tiffany contract review: pull her scheduled hours from the calendar as a starting point
- [x] Digest framework: adapters registry, routing, Roundup section
- [x] Create the Tower inbox: `tower-andrew@agentmail.to`
- [ ] burrell.edu Outlook rules: forward Microsoft 365 digests (Viva briefing, Teams, Planner, SharePoint) to the Tower inbox; confirm IT allows external forwarding
- [ ] Confirm real sender addresses for each adapter from the first digest received

## The app (later)

- [ ] Configurable assistant name, divisions, coverage people, standing agreements
- [ ] Google OAuth for Calendar and Gmail; Microsoft Graph as an optional direct source
- [ ] Per-user Tower inbox and a digest adapter library users can extend
- [ ] Brain (`brain/v1` gist) as the memory store
- [ ] Scheduler for the brief and re-plan triggers
- [ ] One-tap approvals (push / email)
- [ ] Voice line
- [ ] Settings → Advanced → Hosting: cloud / hybrid / self-hosted, with telephony, speech, AI endpoint, storage and intake options
- [ ] Docker image (self-hosted) and one-line installer (hybrid)
- [ ] Company installs: SSO, per-user assistants, audit log, retention, integration API
