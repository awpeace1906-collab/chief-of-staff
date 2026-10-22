# The agent's memory

The Chief of Staff core (this repo) holds no one's information. Everything about the principal lives in the agent's memory, which the core reads. Nothing personal is ever written back into the core.

| Silo | What it holds | Where it lives |
|---|---|---|
| **Core** | The app, generic prompts, docs, schemas, an example memory | This repo; redistributable |
| **Memory** | People, divisions, calendars, rules, standing agreements, digest setup, personal notes | `<agent>-memory`, a private repo or folder per principal; plus the app's database and Brain |
| **Secrets** | API keys, OAuth tokens, access keys | The host's secret store or environment; never in memory or core |

## Layout

```
<agent>-memory/          e.g. juno-memory: the agent's alias, lowercased, spaces as hyphens
  memory.json            required: the agent config (below)
  digests.json           optional: where digests arrive and how each source is read
  notes/                 optional: personal context in markdown (rotations, travel, setup tasks)
  README.md
```

A starting point is in [`examples/memory/`](../examples/memory/), with a fictional principal.

## memory.json

| Key | What it is |
|---|---|
| `assistant` | `id` (permanent, see below), `name` (the alias), `owner`, `email`, `inbox`, `formerNames` |
| `people` | `[{name, role, division?}]`: the principal and everyone the agent deals with |
| `timezone` | IANA zone, e.g. `America/Denver` |
| `divisions` | `{key: {label, calendars: {name: id}, coverage?, notes?, suggest?}}`. `suggest: false` leaves a division out of Day-view suggestions (e.g. the partner's) |
| `brief`, `approvals`, `checkCadence`, `protectedTime` | When and how the agent runs and asks |
| `standingAgreements` | `[{who, rule}]`: imported as rules |
| `mailRules`, `calendarRules`, `notificationRules`, `emailRules` | Imported as rules |
| `home` | `{label, lat?, lon?, airport?}`: the fallback starting point when the phone's location isn't fresh ([location](features/location.md)) |
| `location` | `{freshHours?, homeRadiusKm?}`: how long a phone report counts, and how near home reads as home |
| `google`, `microsoft`, `hosting`, `sms`, `appUrl`, `check` | Connection and hosting settings (no secrets) |
| `openItems` | Seed to-dos for a first import |

The app imports these as settings and rules (`cos import --memory`). Unknown keys are kept in the file and ignored by the app, so the agent can store more context there.

## Identity and renaming

- `assistant.id` is set once, from the first name, and never changes. Brain tags, rule ids (`<id>-…`) and the agent's history key off it.
- `assistant.name` is the alias the principal sees. It can change any time.
- **Renaming** (the app's Settings, or `cos rename <name>`) is the same agent under a new name:
  - `assistant.name` becomes the new alias, and the old one is added to `formerNames`.
  - The folder moves from `<old>-memory` to `<new>-memory`. The id stays.
  - If memory is a GitHub repo, rename the repo to match. GitHub redirects the old name, so existing clones keep working.

## How the core finds memory

1. `COS_MEMORY_DIR`, if set (the folder itself; Docker mounts it at `/memory`).
2. Otherwise `<base>/<alias>-memory`, where `<base>` is `COS_MEMORY_BASE` or the folder that holds this repo.
3. Otherwise the only `*-memory` folder in `<base>`.

## Keeping the core clean

`python tools/check_core.py --memory ../<agent>-memory` reads memory for what counts as personal: the agent's names, the principal, people, agreement contacts, and every address and calendar id. It then searches the core for any of them, and must report clean before any push. `app/tests/test_divisions.py` runs it over the app's code with the example memory, and over the whole repo when `COS_MEMORY_DIR` is set.
