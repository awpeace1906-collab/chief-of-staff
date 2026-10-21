# Deployment modes

People and companies will want different trade-offs between convenience and control. The app supports three modes, chosen in **Settings → Advanced → Hosting**. Every feature works in every mode; only where things run changes.

| | **Cloud** (default) | **Hybrid** | **Self-hosted** (home or office) |
|---|---|---|---|
| Who it's for | Most people; zero setup | Privacy-minded individuals (Andrew's setup) | Practices, clinics, companies with their own IT |
| Chief of Staff server | Our cloud | Your machine | Your machine or your servers |
| Phone number | We provision it | You rent it (VoIP.ms, Telnyx, Twilio) | You rent it, or bring your own SIP trunk / PBX (Asterisk, FreeSWITCH, existing office phone system) |
| Speech (calls, voice notes) | Hosted | Voice notes local; calls hosted until hardware allows | Fully local (Whisper, Piper/Kokoro) |
| Memory (Brain) and board | Your private gist | Your private gist | Your gist, or a local database / your own storage |
| AI model | Claude API | Claude API | Claude API, a company account (Amazon Bedrock, Google Vertex), or bring your own endpoint |
| Data leaves your premises | Yes | Text to Claude only | Text to the configured AI endpoint only |
| Setup | Sign in | Installer + tunnel | Installer, Docker image, or deployment guide |
| Upkeep | None | Low | Yours |

## Hosting the app today (v0.4)

The app is one small process with one SQLite file. Phones reach it over HTTPS, and Google and Microsoft sign-in also require HTTPS for anything other than localhost. Without a spare machine, the simplest home for it is a small cloud machine:

| Option | Cost | Notes |
|---|---|---|
| **Fly.io** (recommended to start) | about $3–5/month | `app/fly.toml` is ready: Denver region, a 1 GB volume for the database, HTTPS on `<name>.fly.dev`, the scheduler always on |
| Hetzner or DigitalOcean VPS | about $5–6/month | Docker Compose plus Caddy for HTTPS; more upkeep |
| Home machine + Cloudflare Tunnel | the hardware | Later, per the hardware guide below; the same Docker image |

Fly.io, from the repo root, the first time:

```bash
cd app
fly launch --no-deploy --copy-config          # pick a unique app name; update the two redirect URLs in fly.toml
fly volumes create cos_data --size 1 --region den
fly secrets set COS_API_TOKEN=$(openssl rand -hex 24) ANTHROPIC_API_KEY=... \
  GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... MS_CLIENT_ID=... MS_CLIENT_SECRET=...
# optional: live flight status (RapidAPI key for AeroDataBox); the FAA airport feed needs no key
fly secrets set AERODATABOX_KEY=...
fly deploy
# load the settings and the old page's data
fly ssh sftp shell        # put ../config/tower.json /data/tower.json; put ../config/digests.json /data/digests.json; put page.json /data/page.json
fly ssh console -C "cos import --config /data --page /data/page.json"
```

Then open `https://<name>.fly.dev`, sign in with the `COS_API_TOKEN` value, and on a phone use **Share → Add to Home Screen**. Connect Google at `/oauth/google/start` and Microsoft at `/oauth/microsoft/start`.

Back up the volume with `cos export` (JSON) or Fly's volume snapshots, which are on by default.

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
| Email intake | Gmail label via plus-address (default) / your own IMAP mailbox / Microsoft Graph |
| Allowed users and numbers | Per person, with permissions (e.g. Stephanie can view, not approve) |
| Data retention | How long transcripts, briefs and closed board items are kept |
| Audit log | On/off; every action Tower took and who approved it |

## Hardware guide (hybrid and self-hosted)

Ballpark prices; check before buying. Same software everywhere, so starting in the cloud and moving home later is one migration.

| Option | Up front | Power | Text + voice notes | Local live-call speech | Best for |
|---|---|---|---|---|---|
| Cloud server (Hetzner, DigitalOcean) | $0 | ~$5–7/mo rent | Yes | No (provider speech) | Starting out, no hardware |
| Raspberry Pi 5, 8GB + SSD | ~$120–150 | ~$0.50/mo | Yes, slower | No | Tightest budget |
| Mini PC, Intel N100/N150, 16GB | ~$150–250 | ~$1/mo | Yes | Borderline | Text-first users |
| Mac mini M4, 16GB | ~$600 | ~$1/mo | Yes | Yes | Fully local, one person or small office |
| PC with GPU (e.g. RTX 3060 12GB) | ~$500–800 | ~$5–10/mo | Yes | Yes | Several users or heavy call volume |

Add a small UPS (~$60) for any home box. Andrew's plan: cloud server now, Mac mini M4 (or N100 for text only) once usage is clear.

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
