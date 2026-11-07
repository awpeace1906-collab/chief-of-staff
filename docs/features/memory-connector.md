# Memory connector: the agent's memory in any AI chat (later)

**Status:** framed for later. Not designed in detail and not scheduled; it waits until the app is hosted and the vault, policy and second factor from [agent-number-approvals-vault.md](agent-number-approvals-vault.md) are built.

## The idea

The principal talks to more than one AI: Claude on the phone, Claude Code, ChatGPT. Each forgets what the others were told. The agent's memory should be reachable from all of them: "remember the kids' dentist moved to Friday" said in any chat lands with the agent, and any chat can ask "what's on my plate this week?"

The app would run its own **MCP server** (the standard way AI apps connect to tools). The principal adds it once in each AI app as a custom connector and signs in.

## Shape (to be designed)

| Tool | Does | Approval |
|---|---|---|
| `recall(query)` | Search items, trips, binders, notes, rules | Read only; filtered by the privacy ceiling for that client |
| `today()`, `week()` | The brief and week cards | Read only |
| `remember(text)` | Hand something to the agent, like a text or a brain dump | Becomes items, notes and **proposals**; nothing acts on its own |
| `propose(action)` | Ask the agent to do something | Becomes a numbered proposal; approved in the app as usual |

Things it would never expose: secrets (vault values), clinical details, other members' private data, the audit log's raw contents, or any tool that acts without a proposal.

## Constraints already decided

- **Local first.** The connector is served by the principal's own Chief of Staff server (over Tailscale, or the hosted app behind sign-in), never by a third-party memory service.
- **Sign-in per client** (OAuth), with a scope per client: read-only, or read and propose. Revocable from Settings, each with a "last used" time.
- **Rules still go through memory.** A "remember this rule" from a chat becomes a Rule: proposal; approved rules go to `<agent>-memory` and Brain as today.
- **Privacy ceiling applies.** Each connected client is a channel with its own class limit, like texting; a client the principal doesn't fully trust gets household-level answers only.
- **Logged.** Every call is in the audit log with the client name, and counted in the brief's Handled tally.

## Open questions for the design

- Which clients first: Claude (claude.ai and Claude Code) only, or ChatGPT too?
- Should reads be full by default for the principal's own Claude, or follow the privacy ceiling like texts?
- How does the agent tell which chat a request came from, for the audit log and for "undo"?
- Does Claude Code's own memory (CLAUDE.md, project notes) sync with it, or stay separate?
