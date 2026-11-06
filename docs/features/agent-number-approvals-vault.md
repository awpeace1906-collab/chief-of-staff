# Agent's number, calls, standing approvals and the vault

**Status:** design sketch. Nothing here is built yet. It adapts patterns from consumer texting agents: an agent you text like a person, allow/always/deny approvals, and a vault the model never sees. Their hosting model is left out: the principal's data stays on the principal's own server, per principle 7 in [vision.md](../vision.md) ("Local first, server when needed").

```
 Household phones ──SMS / MMS──► Agent's own number (prepaid SIM in a spare Android phone)
                                   │  open-source SMS-gateway app
                                   │  private network (Tailscale) or the app's tunnel
                                   ▼
                                 Chief of Staff server
                                   │  1. who is this (member, or guest)
                                   │  2. Claude plans → proposals
                                   │  3. privacy ceiling: what may go back by text
                                   │  4. policy: standing rule? second factor? → run : ask
                                   ▼
                                 Tool runner ──vault ref──► Vault (model never sees)
                                   └─► Calendar / Gmail / AgentMail / …
```

## 1. The agent's own number

The agent gets its own phone number that the household texts and, later, calls like a person. No messaging app (Signal, Telegram, iMessage) is required of anyone.

### How it works

| Phase | What | How |
|---|---|---|
| **Texting** (first) | Texts to and from the agent | A prepaid talk-and-text SIM in a spare Android phone running an open-source SMS-gateway app. The gateway posts inbound texts to `/hooks/sms/gateway/{COS_HOOK_SECRET}` and sends replies through its local API, over Tailscale (or the app's existing tunnel). No open ports |
| **Voice notes** | Audio sent by text | Works if the gateway app passes MMS (pictures and audio) through: a setup test item. Audio is transcribed locally (Whisper) and handled as a text |
| **Calls** (later) | Ring the agent | Speech → text (Whisper) → Claude → speech (Piper), as in [voice-and-messaging.md](voice-and-messaging.md). Whether the call path runs through a voice provider or a cellular modem is decided when it's built |
| **Calls out** (with calls) | The agent rings a business for the principal | See "Calls the agent places" below |

Because it's a real personal line, its texts are ordinary person-to-person messages: no A2P 10DLC business registration, and the only cost is the prepaid plan. The Telnyx and VoIP.ms adapters in [../setup/sms.md](../setup/sms.md) stay as alternatives for a hosted app with no phone at home.

The gateway becomes a third provider in `sms.py` (`parse_inbound("gateway", payload)`, `send(...)`). Commands are unchanged: `list`, `approve 1, 3`, `decline 2`, plus the new answers in section 2.

### Calls the agent places

The agent can phone a business for the principal (a clinic, a restaurant, a hotel, an airline, a utility), wait through the phone menu until a person answers, do the one job it was given, and report back. It is a proposal like any other:

> **Call:** Hotel front desk, ask for early check-in on arrival day (arriving 10am). Accept anything before 1pm; a fee up to $40 is fine. Don't change the reservation.

- **Proposal kind `call`:** `to` (name and number, from the item, the email or a lookup the agent names), `goal`, `limits` (what it may agree to, what it may share), `fallback` (leave a voicemail or not, call back when).
- **Always tier 3:** it speaks for the principal to someone outside, so it always asks and needs the second factor when approved by text. The agent may *propose* a call on its own ("you land early; want me to call about early check-in?"); it never places one unasked.
- **Says who it is.** The opening line names it as an assistant calling for the principal, and that the call is transcribed. It never claims to be the principal.
- **Stays inside its limits.** Anything outside them (a different date, a higher fee, a question it can't answer from the proposal) gets "I'll check and call back", and comes back as a new proposal.
- **Never shares:** clinical or patient details, card or account numbers, SSN, passwords or codes. Anything that needs them is handed back to the principal.
- **Only businesses and people who expect it.** No calls to a third party's personal phone unless the principal says that person expects it (AI-voice calls fall under the TCPA in the US).
- **Afterwards:** a short summary and the full transcript are filed on the item, and the outcome closes it or opens a follow-up. The privacy ceiling applies: by text, a notice and a link. Transcripts stay on the principal's server.
- **Pipeline:** the same speech path as inbound calls (Whisper → Claude → Piper) on an outbound leg; the phone menu is handled by listening and sending keypad tones.

### Line hygiene (checklist)

- Prepaid talk-and-text line with **auto-renew**, a **carrier account PIN** and a **port-out lock**, so the number can't be stolen or lapse.
- A spare Android phone, kept on power and Wi-Fi, to test the gateway app (including MMS).
- An **approval PIN** for each adult (see "Second factor").

### Household members

A sender is matched to a person from memory. The core knows roles only, never names.

| Role | Can | Can't |
|---|---|---|
| `principal` | Everything: ask, approve, decline, set standing rules | (none) |
| `partner` | Ask about shared divisions; add items; approve proposals in shared divisions; set standing rules for themselves | Approve anything in the principal's work division |
| `caregiver` | See the coverage schedule for their days; confirm or flag a shift; send a note to the principal | Approve proposals; see email or other divisions |
| `guest` | Household-level info only (see the privacy ceiling); a message is passed to the principal | Approve anything; see anything personal |

**Unknown numbers get guest mode.** That includes someone texting "it's <partner>, new phone": a new number is bound to a member only by the principal, in the app, never by text. The agent tells the principal about the claim and does nothing else.

The binding lives in memory's `channels` setting (no secrets: which numbers belong to which member, and each member's opt-ins). `docs/memory.md` gets the new key in the same change that builds it:

```json
"channels": {
  "sms": {"provider": "gateway", "number": "+1…"},
  "members": [
    {"person": "<name from people>", "role": "principal", "numbers": ["+1…"], "fullByText": ["ownCalendar"]},
    {"person": "<name>", "role": "partner", "numbers": ["+1…"], "fullByText": []}
  ]
}
```

### Privacy ceiling

Texts and calls aren't end-to-end encrypted; the carrier can read them. So every reply is sorted before it goes out:

| Class | Examples | By text |
|---|---|---|
| **Household** | Grocery list, chores, who has pickup | In full |
| **Personal** | Schedules, email, travel, money, work, the brief | A content-free notice and a link that opens in the app after sign-in: "Your schedule is ready: <link>" |
| **Secret** | Passwords, codes, account numbers | Never. If someone texts one *to* the agent, it isn't echoed, stored in memory or sent to the model; the reply says to put it in Settings |

An adult can opt in to receiving specific personal categories in full (`fullByText`, e.g. their own calendar times). Opt-ins are per member and per category, and logged like standing approvals. Clinical or patient details are never sent by text, and no opt-in changes that. The ceiling is applied in code, after Claude writes the reply and before `send`.

## 2. Allow / Always / Deny

Today every proposal gets **Approve / Change… / Decline**. This adds a fourth answer: **Always**. It approves this proposal *and* creates a standing rule, so future proposals that match it run without asking.

### The answers

| Answer | Effect |
|---|---|
| **Allow** (Approve) | Runs this one proposal |
| **Always** | Runs it, then creates a standing approval: same kind, same scope, from now on |
| **Deny** (Decline) | Doesn't run it. Optionally **Never**: future matching proposals are dropped silently and listed in the brief |
| **Change…** | Unchanged: approve with edits (can't be combined with Always) |

By text they're words: `allow 2`, `always 2`, `deny 2`, `never 2`. In the app they're buttons.

### What "Always" may cover (tiers)

Not every action can become standing. Each proposal kind has a tier, set in the core and impossible to override from memory:

| Tier | Examples | Always allowed? |
|---|---|---|
| **0: read** | Read calendars and email, build the brief | Never asks (as today) |
| **1: own calendar** | Add a block to the principal's own calendar, a travel buffer, a day-view block | Yes |
| **2: shared** | Change a family or caregiver calendar, add a list item for someone else | Yes, but only the division owner can set it, and it expires (default 90 days) |
| **3: outward** | Send email to anyone but the principal, invite or notify others, place a call, pay, sign, cancel | **No.** Always asks, every time. The phone read-back guard from voice-and-messaging.md stays |

### Standing approvals are rules, traced to a person

An "Always" writes a rule into memory's `standingApprovals` (a branch and a PR, like every memory change), and the app keeps a copy in its database so it works offline:

```json
{
  "id": "sa-2026-11-06-1",
  "kind": "calendar.add",
  "scope": {"division": "<key>", "calendar": "<name>", "titlePrefix": "Travel buffer"},
  "tier": 1,
  "grantedBy": "<person>",
  "grantedVia": "sms",
  "fromProposal": "2026-11-06-1",
  "grantedAt": "2026-11-06T18:40:00-07:00",
  "expires": null,
  "uses": 0
}
```

- **Traced:** each one records who said it, where, when, and the proposal it came from. Only `principal` or `partner` members can grant one; a caregiver's "always" is refused.
- **Logged:** each auto-run writes an audit entry (`ran under sa-…`) and shows up in the next brief under **Ran on standing approval**, with a one-tap **Revoke**.
- **Narrow by default:** the scope is copied from the proposal (division, calendar, title prefix). The agent may suggest a wider scope ("all travel buffers?") as a separate proposal; it never widens one itself.
- **Revocable:** `rules` lists them by text or on the page; `revoke sa-…` deletes it. A deleted id is never re-added (same rule as Brain).
- **Brain:** a standing approval is also written to Brain as a rule, following [integrations.md](../integrations.md) exactly (read-modify-PATCH the whole file, keep others' entries).

### Learned rules

The agent watches how the principal answers and suggests rules from it, instead of waiting to be told:

- **Edits:** the same kind of change made twice on the same kind of proposal (a Change… that moves a gym block to 6am, a draft whose sign-off is always rewritten, a travel buffer always lengthened to 45 minutes).
- **Declines:** the same kind of proposal declined twice.
- **Always:** a scope the principal keeps widening by hand.

When it sees one, it proposes the rule (`kind: rule`, title "Rule: …", with the proposals it learned from). Approving writes it to memory's rules and to Brain, like a rule the principal stated, with `learnedFrom` (those proposal ids) and `grantedBy`. Nothing is learned silently: an unapproved pattern changes nothing. At most one rule suggestion per brief, a declined suggestion isn't offered again, and a learned rule can't reach past the tier caps above (no learned rule makes a tier-3 action run unasked).

### Second factor

Texts are easy to fake and numbers can be stolen (SIM swap, port-out). So the size of an approval decides what proof it needs:

| Approval | By text alone | Needs a second factor |
|---|---|---|
| Small: under $50, a draft (nothing sent), a tier-1 block on the sender's own calendar | Yes | No |
| Bigger: tier 2 and 3, $50 or more, anything outward, any **Always** | No | Yes |

The second factor is either the member's PIN with a code tied to the proposal (`ALLOW M3D 4417`: proposal code, then PIN), or a tap in the app. The code changes per proposal, so an old message can't be replayed. Three wrong PINs lock text approvals for that member until the principal clears them in the app. PINs are stored hashed in the vault, never in memory.

### Test scenarios

The approval tests (`app/tests`) get cases for:
1. A spoofed principal number approving a tier-3 send with no PIN → asks for the second factor; nothing runs.
2. "It's <partner>, new phone" from an unknown number → guest mode; the principal is told; no binding.
3. A correct PIN with a stale or other proposal's code → refused.
4. Three wrong PINs → text approvals locked; the app still works.
5. A personal-class reply to a member with no opt-in → notice and link only.
6. A secret texted to the agent → not echoed, not stored, not sent to the model.
7. A caregiver texting "always 2" → refused.
8. A $40 approval by text alone → runs; a $60 one → asks for the second factor.
9. A `call` proposal approved by text with no PIN → asks for the second factor; no call is placed.
10. During a call, the other side offers something outside the limits → the agent doesn't agree; a new proposal comes back.
11. A call where the other side asks for a card number or clinical details → refused; handed back to the principal.
12. The same edit made twice → one "Rule:" proposal; declined → not offered again; a learned rule for a tier-3 action → never proposed.

### Where the check runs

The policy check sits between Claude and the tool runner, in code, not in the prompt. Claude proposes; `policy.decide(proposal, member, proof)` returns `run`, `ask`, `ask-second-factor` or `drop`. The model can't grant itself an approval. A standing approval can only be created by a button press or command from a matched member.

## 3. A vault the model never sees

The secrets table exists today (`get_secret` / `put_secret` in `db.py`). Docs already say secrets live in the host's secret store and never in memory or the core. This makes the boundary explicit: secrets are attached when a tool runs, and the model only ever holds a reference.

### Rules

1. **References, not values.** Tools that need a credential take a reference like `vault:google.refresh` or `vault:telnyx.api_key`. The tool runner looks it up and attaches it to the outgoing request. The value never appears in a prompt, a tool result, a log line or an export.
2. **Scoped references.** Each reference lists the tools and hosts allowed to use it (`google.*` only goes to `*.googleapis.com`). Using one anywhere else is refused.
3. **Redaction on the way back.** Tool results pass through a filter that masks anything matching a stored secret before Claude sees it, in case an API echoes a token.
4. **No secret-reading tool.** There is no tool that returns a vault value. Adding or rotating a secret is done by the principal in Settings or with `cos secret set <ref>` on the host (input hidden), never by text message and never through the model.
5. **Storage stays local.** Backends, in order: the OS keychain (macOS Keychain, or libsecret on Linux) → the encrypted `secrets` table (file mode 0600, never exported) → the host's secret store when hosted (`fly secrets`). Memory may say *where* a secret is kept; it never holds one.

### Shape

```python
# cos/vault.py
def ref(name: str) -> VaultRef                 # what the model and tools pass around
def attach(req: Request, r: VaultRef) -> None  # tool runner only: checks host scope, sets the header
def redact(text: str) -> str                   # applied to every tool result
```

The existing callers of `get_secret` (Google, Microsoft, SMS, APNs) move behind `vault.attach`.

## Build order

1. **Vault first** (smallest; makes the rest safe): `vault.py`, move current secret callers, add redaction, tests that no secret reaches a prompt or log.
2. **Gateway provider:** the Android SMS gateway in `sms.py`, over Tailscale; line-hygiene checklist; MMS test.
3. **Privacy ceiling and guest mode:** classify replies, notice-plus-link, member matching from `channels`.
4. **Policy, tiers and second factor:** `policy.decide`, PINs, Always / Never, learned rules; `standingApprovals` and `channels` in memory (and `docs/memory.md`, `examples/memory/`); the test scenarios above.
5. **Household roles:** partner and caregiver permissions.
6. **Calls:** Whisper → Claude → Piper, inbound first, then calls the agent places; provider or modem decided then.

The **tally** in the brief ([morning-brief.md](morning-brief.md)) needs only the audit log, so it can ship any time, ahead of this order.

## Open questions

- Should a partner's standing approval in a shared division need the principal's confirmation once?
- Default expiry for tier-1 rules: none, or a yearly review in the brief?
- Which personal categories, if any, should the principal opt into by default?
- Should the agent leave voicemails on calls it places, or only call back?
