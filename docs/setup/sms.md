# Text Chief of Staff (one-time setup)

Text your assistant from your phone. Approve proposals by replying with their numbers, and get the morning brief by text. You need the app hosted first (see [../deployment.md](../deployment.md)), because the phone company has to be able to reach it.

## 1. Rent a number

Pick one:
- **Telnyx** (recommended): about $1/month per number plus a fraction of a cent per text. Messaging → buy a local number → create a **Messaging Profile** → API Keys → create a key.
- **VoIP.ms**: about $1/month (DID) plus per-text fees. Buy a DID, enable SMS on it, and turn on the API (Main Menu → SOAP and REST/JSON API) with your server's IP allowed.

**US texting rules.** Business texting from a local number needs **A2P 10DLC registration** (sole proprietor brand + one campaign; small one-time and monthly fees). Telnyx walks you through it in the portal. Until it's approved, texts may be filtered.

## 2. Tell the app

Environment (never in the repo):

```bash
COS_HOOK_SECRET=<a long random string>     # part of the webhook URL; keeps strangers out
TELNYX_API_KEY=...                          # Telnyx
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

With `briefByText` on, the morning brief also arrives as a short text: the subject, the numbered proposals and how to approve. Set `appUrl` in settings to include a link to the app.

## Not yet

Voice notes and calls (v0.6) need speech-to-text, either on the server (faster-whisper) or through the carrier. The texting pieces above don't depend on them.
