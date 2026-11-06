# Messaging channels, standing approvals and the vault

**Status:** design sketch. Nothing here is built yet. It adapts three patterns from consumer texting agents (an agent you text, allow/always/deny approvals, a vault the model never sees). Their hosting model is left out: the principal's data stays on the principal's own server, per principle 7 in [vision.md](../vision.md) ("Local first, server when needed").

The three pieces fit together:

```
 Phone ──Telegram / Signal / SMS / (iMessage via Mac bridge)──► Channel adapter
                                                                  │  sender → household member
                                                                  ▼
                                                        Chief of Staff server
                                                          │  1. who is this, what may they do
                                                          │  2. Claude plans → proposals
                                                          │  3. policy: standing rule? → run : ask
                                                          ▼
                                                        Tool runner ──vault ref──► Vault (secrets)
                                                          │                         (model never sees)
                                                          └─► Calendar / Gmail / AgentMail / …
```

## 1. Texting as the interface

Texting already works over SMS (v0.5, see [voice-and-messaging.md](voice-and-messaging.md)). This adds more channels behind one interface and lets other household members text.

### Channels, in order

| Order | Channel | How | Why this order |
|---|---|---|---|
| 1 | **Telegram** | Bot API, webhook to `/hooks/msg/telegram/{secret}` | Free, official bot API, rich buttons (inline Allow / Always / Deny), no phone number to rent |
| 2 | **Signal** | `signal-cli` (or signal-cli-rest-api) on the home server, linked to a dedicated number | End-to-end encrypted; the household may prefer it. No official bot API, so it runs as a linked device |
| 3 | **SMS** | Existing Telnyx / VoIP.ms adapter (`sms.py`) | Already built; works with any phone |
| 4 | **iMessage** (later) | A bridge on an always-on Mac (e.g. BlueBubbles server, or AppleScript on Messages.app), posting to `/hooks/msg/imessage/{secret}` | Apple has no official iMessage bot API, so it needs a Mac signed in to an Apple ID. Most fragile, so it comes last |

### One adapter shape

Each channel becomes a small adapter with the same three functions, so the logic in `sms.py` (`handle_inbound`, `proposal_list`, `brief_text`) moves into a channel-neutral module:

```python
class Channel(Protocol):
    name: str                                     # "telegram", "signal", "sms", "imessage"
    def parse(self, payload) -> Inbound | None    # sender id, text, attachments, button press
    def send(self, to, text, buttons=None) -> None
    def configured(self) -> bool
```

- **`cos/channels/`** holds `telegram.py`, `signal.py`, `sms.py` (moved), `imessage.py`.
- **`cos/messaging.py`** holds the shared logic: resolve the sender, run commands, ask Claude, render proposals and buttons, split long replies.
- **Routes:** `/hooks/msg/{channel}/{COS_HOOK_SECRET}`. The `/hooks/sms/...` routes stay as aliases.

### Household members

A sender is matched to a person from memory. The core knows roles only, never names.

| Role | Can | Can't |
|---|---|---|
| `principal` | Everything: ask, approve, decline, set standing rules | (none) |
| `partner` | Ask about shared divisions; add items; approve proposals in shared divisions; set standing rules for themselves | Approve anything in the principal's work division |
| `caregiver` | See the coverage schedule for their days; confirm or flag a shift; send a note to the principal | Approve proposals; see email or other divisions |
| `guest` | Nothing until the principal adds them | (none) |

Unknown senders get no reply (or one canned "not set up" line, set in settings) and are logged.

The binding from a member's phone number or handle to their role lives in memory's `channels` setting (no secrets: just which identifiers belong to which member). `docs/memory.md` gets the new key in the same change that builds it:

```json
"channels": {
  "telegram": {"enabled": true},
  "members": [
    {"person": "<name from people>", "role": "principal", "ids": {"telegram": "<user id>", "sms": "+1…"}},
    {"person": "<name>", "role": "partner", "ids": {"signal": "+1…"}}
  ]
}
```

The `/api/...` routes and `require_token` don't change; channel hooks authenticate with the hook secret plus the sender match.

## 2. Allow / Always / Deny

Today every proposal gets **Approve / Change… / Decline**. This adds a fourth answer: **Always**. It approves this proposal *and* creates a standing rule, so future proposals that match it run without asking.

### The answers

| Answer | Effect |
|---|---|
| **Allow** (Approve) | Runs this one proposal |
| **Always** | Runs it, then creates a standing approval: same kind, same scope, from now on |
| **Deny** (Decline) | Doesn't run it. Optionally **Never**: future matching proposals are dropped silently and listed in the brief |
| **Change…** | Unchanged: approve with edits (can't be combined with Always) |

On Telegram these are inline buttons. On SMS they're words: `allow 2`, `always 2`, `deny 2`, `never 2`.

### What "Always" may cover (tiers)

Not every action can become standing. Each proposal kind has a tier, set in the core and impossible to override from memory:

| Tier | Examples | Always allowed? |
|---|---|---|
| **0: read** | Read calendars and email, build the brief | Never asks (as today) |
| **1: own calendar** | Add a block to the principal's own calendar, a travel buffer, a day-view block | Yes |
| **2: shared** | Change a family or caregiver calendar, add a list item for someone else | Yes, but only the division owner can set it, and it expires (default 90 days) |
| **3: outward** | Send email to anyone but the principal, invite or notify others, pay, sign, cancel | **No.** Always asks, every time. The phone read-back guard from voice-and-messaging.md stays |

### Standing approvals are rules, traced to a person

An "Always" writes a rule into memory's `standingApprovals` (a branch and a PR, like every memory change), and the app keeps a copy in its database so it works offline:

```json
{
  "id": "sa-2026-11-06-1",
  "kind": "calendar.add",
  "scope": {"division": "<key>", "calendar": "<name>", "titlePrefix": "Travel buffer"},
  "tier": 1,
  "grantedBy": "<person>",
  "grantedVia": "telegram",
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

### Where the check runs

The policy check sits between Claude and the tool runner, in code, not in the prompt. Claude proposes; `policy.decide(proposal, member)` returns `run`, `ask` or `drop`. The model can't grant itself an approval. A standing approval can only be created by a button press or command from a matched member.

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

1. **Vault first** (smallest; makes the next two safe): `vault.py`, move current secret callers, add redaction, tests that no secret reaches a prompt or log.
2. **Policy and tiers:** `policy.decide`, tier table, audit log; Always / Never on the page and in SMS; `standingApprovals` in memory (and `docs/memory.md`, `examples/memory/`).
3. **Channel refactor:** move `sms.py` logic into `messaging.py` behind the `Channel` interface; no behavior change.
4. **Telegram:** adapter, inline buttons, member matching.
5. **Household roles:** partner and caregiver permissions.
6. **Signal**, then **iMessage** via a Mac bridge once a Mac is always on.

## Open questions

- Should a partner's standing approval in a shared division need the principal's confirmation once?
- Default expiry for tier-1 rules: none, or a yearly review in the brief?
- Should Signal replace SMS as the default once it works?
