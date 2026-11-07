# Memory connector: the agent's memory in any AI chat

**Status:** phase 1 is built (`app/cos/connector.py`): the connector runs inside the app and works with Claude Code today, on the principal's own machine or network. Phase 2 (sign-in for claude.ai and ChatGPT, per-app privacy limits) waits until the app is hosted and the vault, policy and second factor from [agent-number-approvals-vault.md](agent-number-approvals-vault.md) are built.

## The idea

The principal talks to more than one AI: Claude on the phone, Claude Code, ChatGPT. Each forgets what the others were told. The agent's memory should be reachable from all of them: "remember the kids' dentist moved to Friday" said in any chat lands with the agent, and any chat can ask "what's on my plate this week?"

The app runs its own **MCP server** (the standard way AI apps connect to tools). The principal adds it once in each AI app and signs in.

## Phase 1 (built)

An MCP server at `POST /mcp` on the app: Streamable HTTP with JSON responses, stateless, no extra dependencies.

| Tool | Does | Scope |
|---|---|---|
| `today` | The latest brief, pending proposals, open items due today or overdue | read |
| `week` | Tomorrow's card (the Book), the week card, open items due in the next 7 days | read |
| `recall(query, kinds?)` | Search board items (open and closed), trips, binders, decisions, expenses and rules; every word must appear; up to 20 matches | read |
| `remember(text)` | Hands the text to the agent as a message from the principal (channel `connector`); the next run files it, and anything that acts comes back as a proposal | propose |
| `propose(title, kind?, summary?, when?, division?)` | Files a **pending** proposal (`board`, `calendar` or `list`; never email) for the principal to approve in the app | propose |

- **Off by default.** The `connector` setting turns it on: `{"enabled": true, "scope": "read"}` (only the three read tools are listed) or `"scope": "propose"` (all five). Set it in memory (`memory.json` → `connector`) or with `PUT /api/settings/connector`. While it's off, `/mcp` answers 404.
- **Sign-in:** the app's API token as a bearer token (`COS_API_TOKEN`). The web app's sign-in cookie is not accepted here, and a request carrying an `Origin` from another site is refused, so a web page can't reach it through the principal's browser. (Without `COS_API_TOKEN`, for local testing only, there is no sign-in, as for the rest of the API.)
- **Nothing acts.** Writes become a message or a pending proposal; approval stays in the app, as with every other channel ([approvals.md](approvals.md)).
- **Logged.** Every tool call is in the audit log (`connector.call`, with the tool and the client's name); proposals carry `source: connector:<client>`.
- **Never exposed:** secrets, the audit log, the raw database, or any way to approve.

### Connect Claude Code

With the app running (locally, or on the home server over Tailscale):

```bash
claude mcp add --transport http <agent>-memory http://localhost:8700/mcp \
  --header "Authorization: Bearer $COS_API_TOKEN"
claude mcp get <agent>-memory      # Status: Connected
```

Use `-s user` to have it in every project. Then ask Claude Code "what's on my plate this week?" or "remember that the dentist moved to Friday".

## Phase 2 (later): claude.ai and ChatGPT

Their apps only add connectors reachable on the internet over HTTPS, with an OAuth sign-in. That needs:

- **Local first.** The connector is served by the principal's own Chief of Staff server (over Tailscale, or the hosted app behind sign-in), never by a third-party memory service.
- **Sign-in per client** (OAuth, replacing the shared API token), with a scope per client: read-only, or read and propose. Revocable from Settings, each with a "last used" time.
- **Rules still go through memory.** A "remember this rule" from a chat becomes a Rule: proposal; approved rules go to `<agent>-memory` and Brain as today.
- **Privacy ceiling applies.** Each connected client is a channel with its own class limit, like texting; a client the principal doesn't fully trust gets household-level answers only.
- **Logged.** Every call is in the audit log with the client name, and counted in the brief's Handled tally.

## Open questions for phase 2

- Which clients first after Claude Code: claude.ai only, or ChatGPT too?
- Should reads be full by default for the principal's own Claude, or follow the privacy ceiling like texts?
- How does the agent tell which chat a request came from, for the audit log and for "undo"?
- Does Claude Code's own memory (CLAUDE.md, project notes) sync with it, or stay separate?
