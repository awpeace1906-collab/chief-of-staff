# Integrations

| System | Role | How Tower connects today | Read / write |
|---|---|---|---|
| Google Calendar | Every division's schedule | Claude connector today; the app reads it directly since v0.2 ([setup](setup/google.md)) | Read; write after approval |
| Gmail | Inbox scan, readywhen briefs, flights, sending the brief | Claude connector today; the app reads it directly since v0.2 | Read; send to Andrew; drafts |
| Brain | Long-term memory (rules, preferences, context) | Private gist `brain-data.json`, `brain/v1`, via `BRAIN_GIST_TOKEN` | Read + write |
| Board | Commitments (replaces readywhen's board) | Private gist `cos-board.json` (`{ chief of staff } board`), same token | Read + write |
| readywhen | Optional cross-check during transition | Reads its brief email (no public API) | Read |
| readywhen WhatsApp | Interim voice until Tower's own line is live | Separate; capture lands on readywhen's board, which Tower reads via the brief | — |
| Phone number (VoIP.ms / Telnyx) | Tower's own text, voice-note and call line | Webhooks to the Chief of Staff server ([features/voice-and-messaging.md](features/voice-and-messaging.md)) | Read + write |
| Granola | Meeting notes → commitments | Claude connector | Read |
| Flights | Travel for coverage check | Airline / Expedia emails, TripIt forwards | Read |
| Tower inbox `tower-andrew@agentmail.to` | Intake for digests forwarded from siloed accounts | AgentMail connector | Read; mark handled messages read |
| Microsoft 365, personal (awpeace1906@gmail.com) | Outlook mail and calendar, To Do, OneDrive | The app connects directly through Microsoft Graph (v0.4, [setup](setup/microsoft.md)); Claude's Microsoft 365 connector only supports work or school accounts | Read |
| Siloed systems (Microsoft 365 at burrell.edu, MedHub, Amion, Canvas, …) | Commitments, schedule changes, FYIs | Their digest emails, via adapters in `config/digests.json` | Read |

## Brain contract

Full contract: [awpeace1906-collab/Brain INTEGRATION.md](https://github.com/awpeace1906-collab/Brain/blob/main/INTEGRATION.md).

- Find the gist: `GET https://api.github.com/gists`, pick the one with `brain-data.json`.
- Read, change and `PATCH` the whole file back in one step. Keep everything Tower didn't write.
- Tower's entries: id `tower-<ms>-<rand4>`, `"source": "tower"`, tags `["tower", rule|preference|context]`, summary ≤ 12 words.
- Never re-add an id listed in `deleted`.
- Helper: [tools/brain_sync.py](../tools/brain_sync.py).

## Where Brain works

- **Chief of Staff app (hosted):** yes. Set `BRAIN_GIST_TOKEN` (classic PAT, `gist` scope only) in the app's environment.
- **Claude Code cloud sessions:** no. Their GitHub API access is limited to the session's attached repositories, and `api.github.com/gists` is refused ("sessions are bound to their configured repositories") even with a network secret. In those sessions Tower's memory is this repo: `config/tower.json` (rules, standing agreements, open items). Don't store the gist token as a Claude Code environment secret; nothing there can use it.
