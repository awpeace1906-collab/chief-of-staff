# Digests from siloed systems

**Status:** live (Gmail digests and the agent's inbox); the app reads them in capture.

Many systems the agent can't log into still send email: Microsoft 365, residency and school platforms, scheduling tools. Their digest and notification emails are the integration point. The agent reads them, splits them into items, and routes each item to the right place.

## Intake

The agent reads digests from one of two places:

| Intake | How | Best for |
|---|---|---|
| **Gmail** | Digests already sent to the owner's Gmail | Personal services |
| **The agent's inbox** (e.g. an AgentMail address) | Rules in other accounts auto-forward digests here | Siloed work or school accounts (an organization's Microsoft 365) and anything kept out of Gmail |

A dedicated inbox is the portable choice: the public app gives every user one, and any system that can send or forward email can feed the agent.

### Read state

Once the agent has handled a message in its inbox (captured to the board, routed to the plan or Roundup, or ignored per its adapter), it marks it read. Anything unhandled, failed or waiting on the owner stays unread, so unread means "the agent hasn't dealt with this". This applies to every agent inbox it reads. Gmail read state is left alone.

### Forwarding from a work or school Microsoft 365

Outlook → Settings → Mail → Rules → new rule: *From* contains the senders in `<agent>-memory/digests.json` → *Forward to* the agent's inbox.

- Many organizations block automatic forwarding to outside addresses. If the rule silently does nothing, IT has blocked it. Fallbacks: forward by hand, or have the agent read a weekly export.
- **Forward digests only, never all mail.** School and hospital accounts can contain protected health information. Only forward systems listed in the registry, and never patient-facing systems (Epic In Basket, secure messaging).

## Adapters

Each known sender has an adapter in `<agent>-memory/digests.json` (example: [examples/memory/digests.json](../../examples/memory/digests.json)):

| Field | Meaning |
|---|---|
| `match` | Sender and/or subject patterns |
| `silo` | Which system it speaks for (Microsoft 365, MedHub, …) |
| `yields` | What it can produce: `commitments`, `schedule`, `fyi`, `metrics` |
| `handling` | `itemize` (split into items), `summarize` (one line), `metrics` (numbers only), `ignore`, `sensitive` (never read content) |
| `division` | Default division for its items |

Unknown senders whose email looks like a digest (a list of items; subject has digest, summary, activity, briefing, recap, "you missed") are handled by the **generic adapter**: itemize, classify, and propose a new adapter in the brief so the owner can confirm it.

## Routing each item

| Item type | Goes to | Example |
|---|---|---|
| **Commitment** | Board ([commitments.md](commitments.md)) | Viva briefing: "You said you'd send the deck to Dr. X" · MedHub: "3 evaluations due" |
| **Schedule** | Plan + coverage check | Amion/QGenda: call swap · Teams invite moved |
| **FYI** | Roundup section of the brief, one line per source | Professional society digest: abstract deadline open |
| **Metrics** | Project line in the brief | Side project beta: 0 new sign-ups |

## Brief: Roundup section

After Proposals, at most one line per digest source, most important first. Silent when nothing matters:

```
Roundup
· Microsoft 365: 2 Teams mentions (Peds clerkship chat), 1 Planner task due Thu → board
· MedHub: 3 evaluations due Fri → board
· Society digest: abstract submissions open
· Side project beta: 0 new sign-ups, 0 feedback (3rd day flat)
```

## Privacy rules

- `sensitive` adapters (health data, e.g. a glucose-monitor report) are never read. The agent only notes that one arrived, if asked.
- No clinical or patient details on the board, in the brief, or in Brain.
- Work-account content stays in the brief and board. It never goes into Brain unless the owner turns it into a rule.
