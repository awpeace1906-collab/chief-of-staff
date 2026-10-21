# Voice and messaging

**Status:** texting is built (v0.5, [setup](../setup/sms.md)): Telnyx or VoIP.ms, owner-only, "list", "approve 1, 3", "decline 2", messages answered by text, and the brief by text. Voice notes and calls are still spec.

Talk to the agent like a person: text it, send a voice note, or call it.

## What you can do

| Channel | Examples |
|---|---|
| **Text** | "What's today?" · "Who has the kids Thursday?" · "approve 1, 3" · "Remind me to review the nanny's contract Friday" |
| **Voice note** | Ramble a to-do list between meetings; the agent turns it into board items and reads back what it captured |
| **Call** | Ring the agent on the drive in and talk the day through; it proposes changes and you approve out loud |
| **Outbound** | Morning brief by text (short version, link to the full email); alerts when coverage breaks or a flight slips |

## Architecture (hybrid, recommended for one person)

```
 Phone ──SMS/call──► Carrier number ──webhook / SIP──► Chief of Staff server ──► Claude (brain)
 (owner)             (VoIP.ms or Telnyx)               (home mini PC,     │
                                                        Cloudflare Tunnel) ├─► Google Calendar / Gmail
                                                           │               ├─► Board gist, Brain gist
                                                           │               └─► Agent inbox (AgentMail)
                                                           ├─ Whisper (speech → text, local)
                                                           └─ Piper/Kokoro (text → speech, local)
```

| Piece | Choice | Why |
|---|---|---|
| Number + SMS | VoIP.ms or Telnyx | Cheapest; ~$1–1.50/mo per number |
| Live calls | Provider's real-time speech at first (e.g. Telnyx or Twilio ConversationRelay); move to local Whisper + Piper once hardware allows | Low latency now, privacy and savings later |
| Voice notes | Local Whisper | Not real-time, so any CPU works; audio never leaves home |
| Server | Small always-on machine at home, reached through Cloudflare Tunnel (no open ports) | Private, cheap, the owner owns it |
| Brain | Claude API with the agent's tools | Reasoning quality; the main running cost either way |

## Flows

**Inbound text**
1. Carrier posts the message to the Chief of Staff server.
2. Server checks the sender is an allowed number (the owner; later the partner with their own permissions).
3. Claude answers using the agent's tools and rules from memory and Brain.
4. Any action comes back as a numbered proposal; "approve 2" executes it.

**Call**
1. Carrier connects the call to the server's speech pipeline.
2. Speech → text → Claude → text → speech, turn by turn.
3. Approvals are spoken ("approve one and three"). The agent repeats them back before acting.
4. After hanging up, the agent texts a summary of what it did and what's still proposed.

**Voice note** (MMS audio or messaging app)
1. Transcribe locally, then treat it as a text message.
2. Reply with what was captured ("Added 3 items to the board: …").

## Approvals over text and voice

Same rules as [approvals.md](approvals.md). Extra guards for phone channels:
- Only allowed numbers can approve.
- Anything that sends email or changes someone else's calendar is read back for a "yes" before it runs.
- `undo` within 10 minutes reverses the last action where possible (delete the created event, recall a draft).

## Privacy

- Voice-note audio is transcribed locally and deleted after transcription; only the text is kept, and only as long as needed.
- Live-call audio passes through the carrier's speech service until speech moves in-house. Say so in settings.
- No clinical or patient details in texts, the board or Brain. The agent declines to read clinical content aloud.

## Setup steps

1. Pick hardware: spare mini PC, old Mac or Raspberry Pi 5 for text and voice notes; a machine with a GPU for local live-call speech.
2. Open a VoIP.ms or Telnyx account and buy one number.
3. Start A2P 10DLC registration (sole proprietor) for SMS. Takes days to weeks, so do it first.
4. Install the Chief of Staff server and Cloudflare Tunnel (installer to come).
5. Point the number's SMS and voice webhooks at the tunnel URL.
6. Add allowed numbers in settings.
7. Test: text "what's today?", send a voice note, place a call.
8. Once it works, turn off any third-party assistant line it replaces.

## Rough costs, personal volume

Ballpark; confirm current prices before buying. About 30 call minutes and a few hundred texts a month.

| | Managed cloud | Hybrid (home server) |
|---|---|---|
| Number + texts | ~$3–5/mo | ~$2–3/mo |
| Voice + speech | ~$5–15/mo | ~$1/mo carrier + local speech |
| Server | ~$0–5/mo | ~$2–5/mo electricity |
| Claude | same | same |
| Up front | $0 | ~$150–600 hardware |

Savings are modest at one-person scale; the stronger reasons for home hosting are privacy and control.
