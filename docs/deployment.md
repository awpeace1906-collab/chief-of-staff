# Deployment modes

People and companies will want different trade-offs between convenience and control. The app supports three modes, chosen in **Settings → Advanced → Hosting**. Every feature works in every mode; only where things run changes.

| | **Cloud** (default) | **Hybrid** | **Self-hosted** (home or office) |
|---|---|---|---|
| Who it's for | Most people; zero setup | Privacy-minded individuals (Andrew's setup) | Practices, clinics, companies with their own IT |
| Tower server | Our cloud | Your machine | Your machine or your servers |
| Phone number | We provision it | You rent it (VoIP.ms, Telnyx, Twilio) | You rent it, or bring your own SIP trunk / PBX (Asterisk, FreeSWITCH, existing office phone system) |
| Speech (calls, voice notes) | Hosted | Voice notes local; calls hosted until hardware allows | Fully local (Whisper, Piper/Kokoro) |
| Memory (Brain) and board | Your private gist | Your private gist | Your gist, or a local database / your own storage |
| AI model | Claude API | Claude API | Claude API, a company account (Amazon Bedrock, Google Vertex), or bring your own endpoint |
| Data leaves your premises | Yes | Text to Claude only | Text to the configured AI endpoint only |
| Setup | Sign in | Installer + tunnel | Installer, Docker image, or deployment guide |
| Upkeep | None | Low | Yours |

## Advanced settings (self-hosted and hybrid)

| Setting | Options |
|---|---|
| Hosting | Cloud / Hybrid / Self-hosted |
| Server address | Tunnel URL or internal hostname |
| Telephony | Provider (VoIP.ms, Telnyx, Twilio) or SIP trunk details |
| Speech-to-text | Hosted / Local Whisper (model size) |
| Text-to-speech | Hosted / Local Piper or Kokoro (voice) |
| AI endpoint | Anthropic API / Bedrock / Vertex / custom |
| Storage | Gist / local database / S3-compatible bucket |
| Email intake | Tower inbox (AgentMail) / your own IMAP mailbox / Microsoft Graph / Google API |
| Allowed users and numbers | Per person, with permissions (e.g. Stephanie can view, not approve) |
| Data retention | How long transcripts, briefs and closed board items are kept |
| Audit log | On/off; every action Tower took and who approved it |

## Company and practice installs

Things organizations will ask for, to design in from the start:
- **Integrate on their own:** documented webhooks and an API so their IT can connect internal systems (scheduling, EHR-adjacent tools that are allowed, ticketing).
- **Single sign-on** and per-user assistants under one install.
- **Audit log and retention controls.**
- **Health data:** a self-hosted install inside a covered entity's network, with a business associate agreement for any outside AI endpoint, is the only setup where PHI could be in scope. Default for every mode: Tower does not handle patient information.

## Packaging

- One codebase, configured by mode, never forked per mode.
- Docker image for self-hosted; a one-line installer for hybrid on macOS and Linux.
- The assistant name, divisions, adapters and rules are settings in every mode (see [vision.md](vision.md)).
