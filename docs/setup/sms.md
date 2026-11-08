# Text Chief of Staff (one-time setup)

Text your assistant from your phone. Approve proposals by replying with their numbers, and get the daily brief by text. You need the app hosted first (see [../deployment.md](../deployment.md)), because the phone company has to be able to reach it. **Telnyx is the recommended provider** ([why](../features/agent-number-approvals-vault.md#1-the-agents-own-number)); the go-live runbook at the end takes you from nothing to a working number.

## 1. Rent a number

Pick one:
- **Telnyx** (recommended): about $1/month per number plus a fraction of a cent per text. Messaging → buy a local number → create a **Messaging Profile** → API Keys → create a key.
- **VoIP.ms**: about $1/month (DID) plus per-text fees. Buy a DID, enable SMS on it, and turn on the API (Main Menu → SOAP and REST/JSON API) with your server's IP allowed.

**US texting rules.** Business texting from a local number needs **A2P 10DLC registration** (sole proprietor brand + one campaign; small one-time and monthly fees). Telnyx walks you through it in the portal (**Messaging → Compliance**). Until it's approved, texts may be filtered. Start it first: it's the slow step.

**Lock the number down:** turn on two-factor sign-in for the Telnyx account, set a port-out PIN on the number, and turn on auto-recharge so the balance never lapses.

## 2. Tell the app

Environment (never in the repo):

```bash
COS_HOOK_SECRET=<a long random string>     # part of the webhook URL; keeps strangers out
TELNYX_API_KEY=...                          # Telnyx
TELNYX_PUBLIC_KEY=...                       # Telnyx: Portal → Keys & Credentials → Public Key; the app then rejects unsigned or replayed webhooks
# or
VOIPMS_USER=... VOIPMS_PASSWORD=...         # VoIP.ms API user and API password
```

Settings (memory's `memory.json` → `sms`, or `PUT /api/settings/sms`):

```json
"sms": {
  "provider": "telnyx",
  "number": "+15555550199",
  "ownerNumber": "+1XXXXXXXXXX",
  "briefByText": true
}
```

Only `ownerNumber` is ever answered or texted. Texts from anyone else are ignored and logged.

## 3. Point the number at the app

- **Telnyx:** Messaging Profile → Inbound → webhook URL `https://<your app>/hooks/sms/telnyx/<COS_HOOK_SECRET>`.
- **VoIP.ms:** DID settings → SMS → "SMS URL Callback" `https://<your app>/hooks/sms/voipms/<COS_HOOK_SECRET>?from={FROM}&to={TO}&message={MESSAGE}`.

## 4. Try it

| You text | What happens |
|---|---|
| `list` | The proposals waiting for your OK, numbered |
| `approve 1, 3` · `approve all` | Approves those and carries them out right away, then texts what it did |
| `decline 2` | Declines it |
| anything else | A message to your assistant. It answers by text, and the exchange also shows in the app's Talk tab |

With `briefByText` on, the daily brief also arrives as a short text: the subject, the numbered proposals and how to approve. Set `appUrl` in settings to include a link to the app.

## Not yet

Voice notes and calls (v0.6) need speech-to-text, either on the server (faster-whisper) or through the carrier. The texting pieces above don't depend on them.

## Go live (Telnyx on the hosted app)

The app already supports all of this; going live is configuration. On Fly.io:

1. **Register (start now, it's the slow part):** Telnyx portal → Messaging → Compliance → a **sole proprietor** brand, then one campaign. Describe it plainly: "Household assistant that texts the account owner and family members who opted in: schedules, reminders and approvals." Sample messages: a brief summary, and "Waiting for your OK: 1. Add: … Reply approve 1".
2. **Buy a local number** and create a **messaging profile**. Put the number in the profile, and attach the profile to the 10DLC campaign once it's approved.
3. **Secrets** (the deploy script asks for them, or set them by hand):
   ```bash
   fly secrets set -a <app> TELNYX_API_KEY=... TELNYX_PUBLIC_KEY=... COS_HOOK_SECRET=$(openssl rand -hex 16)
   ```
4. **Settings** (memory's `memory.json`, then `cos import --memory`, or `PUT /api/settings/sms` and `/api/settings/appUrl`):
   ```json
   "sms": {"provider": "telnyx", "number": "+1…", "ownerNumber": "+1…", "briefByText": false},
   "appUrl": "https://<app>.fly.dev"
   ```
5. **Webhook:** `fly ssh console -a <app> -C "cos sms status --show-webhook"` prints the URL. Paste it into the messaging profile as the **inbound webhook** (API v2).
6. **Check:** `cos sms status --live` must end with **READY**. It checks the provider, number, keys, webhook secret and https address, and that Telnyx has the number in a messaging profile pointed at this app. Settings → Texting shows the next unfinished step.
7. **Test:** `cos sms test` (or `POST /api/sms/test`) texts you a hello. Reply `list`.
8. **Turn on the brief by text** if you want it: `"briefByText": true`.

Until the registration is approved, carriers may delay or drop texts: the checklist marks that step "can't be checked from here". If registration is refused or filtering continues, the fallback is a SIM in an Android gateway ([design](../features/agent-number-approvals-vault.md)).

