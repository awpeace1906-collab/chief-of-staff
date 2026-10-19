# Integrations

| System | Role | How Tower connects today | Read / write |
|---|---|---|---|
| Google Calendar | Every division's schedule | Claude connector | Read; write after approval |
| Gmail | Inbox scan, readywhen briefs, flights, sending the brief | Claude connector | Read; send to Andrew; drafts |
| Brain | Long-term memory (rules, preferences, context) | Private gist `brain-data.json`, `brain/v1`, via `BRAIN_GIST_TOKEN` | Read + write |
| readywhen | Commitment tracking and its own morning brief | Reads its brief email (no public API) | Read |
| readywhen WhatsApp | Interim voice: call, voice-note or message | Separate; capture lands on readywhen's board, which Tower reads via the brief | — |
| Granola | Meeting notes | Claude connector (not used yet) | Read |
| AgentMail | Possible dedicated inbox for Tower | Claude connector (not set up) | — |

## Brain contract

Full contract: [awpeace1906-collab/Brain INTEGRATION.md](https://github.com/awpeace1906-collab/Brain/blob/main/INTEGRATION.md).

- Find the gist: `GET https://api.github.com/gists`, pick the one with `brain-data.json`.
- Read, change and `PATCH` the whole file back in one step. Keep everything Tower didn't write.
- Tower's entries: id `tower-<ms>-<rand4>`, `"source": "tower"`, tags `["tower", rule|preference|context]`, summary ≤ 12 words.
- Never re-add an id listed in `deleted`.
- Helper: [tools/tower_brain.py](../tools/tower_brain.py).

## Environment needs (Claude Code cloud)

- Secret `BRAIN_GIST_TOKEN` (classic PAT, `gist` scope only)
- Network: `api.github.com` in Allowed domains
