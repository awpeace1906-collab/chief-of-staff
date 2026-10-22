# Integrations

| System | Role | How the agent connects today | Read / write |
|---|---|---|---|
| Google Calendar | Every division's schedule | Claude connector; the app reads it directly since v0.2 ([setup](setup/google.md)) | Read; write after approval |
| Gmail | Inbox scan, flights, sending the brief | Claude connector; the app reads it directly since v0.2 | Read; send to the principal; approved drafts |
| Brain | Long-term memory (rules, preferences, context) | Private gist `brain-data.json`, `brain/v1`, via `BRAIN_GIST_TOKEN` | Read + write |
| Board | Commitments | Private gist `cos-board.json` (`{ chief of staff } board`), same token | Read + write |
| Another brief service (optional) | Cross-check during a transition | Reads its brief email | Read |
| Phone number (VoIP.ms / Telnyx) | The agent's own text, voice-note and call line | Webhooks to the Chief of Staff server ([features/voice-and-messaging.md](features/voice-and-messaging.md)) | Read + write |
| Granola | Meeting notes → commitments | Claude connector | Read |
| Flights | Travel for the coverage check | Airline and booking emails, TripIt forwards; live status in the app | Read |
| The agent's inbox (e.g. AgentMail) | Intake for digests forwarded from siloed accounts | AgentMail connector | Read; mark handled messages read |
| Microsoft 365, personal | Outlook mail and calendar, To Do, OneDrive | The app connects directly through Microsoft Graph (v0.4, [setup](setup/microsoft.md)); Claude's Microsoft 365 connector only supports work or school accounts | Read |
| Siloed systems (work Microsoft 365, MedHub, Amion, Canvas, …) | Commitments, schedule changes, FYIs | Their digest emails, via adapters in `<agent>-memory/digests.json` | Read |

The principal's own accounts and addresses for each row are in their memory, not here.

## Brain contract

Full contract: `INTEGRATION.md` in the Brain project.

- Find the gist: `GET https://api.github.com/gists`, pick the one with `brain-data.json`.
- Read, change and `PATCH` the whole file back in one step. Keep everything the agent didn't write.
- The agent's entries: id `<agent-id>-<ms>-<rand4>`, `"source": "<agent-id>"`, tags `["<agent-id>", rule|preference|context]`, summary ≤ 12 words. The agent id is permanent ([memory.md](memory.md)), so a rename keeps its entries.
- Never re-add an id listed in `deleted`.
- Helper: [tools/brain_sync.py](../tools/brain_sync.py).

## Where Brain works

- **Chief of Staff app (hosted):** yes. Set `BRAIN_GIST_TOKEN` (classic PAT, `gist` scope only) in the app's environment.
- **Claude Code cloud sessions:** no. Their GitHub API access is limited to the session's attached repositories, and `api.github.com/gists` is refused ("sessions are bound to their configured repositories") even with a network secret. In those sessions the agent's memory is the `<agent>-memory` repo (rules, standing agreements, open items). Don't store the gist token as a Claude Code environment secret; nothing there can use it.
