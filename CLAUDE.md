# Chief of Staff: notes for Claude

- This repo is the Chief of Staff core: the redistributable app (`app/`), its docs, prompts, schemas and examples. It holds no owner's information.
- All owner data (people, divisions, calendars, rules, notes) lives in the agent's memory repo `<agent>-memory`, specified in `docs/memory.md`. Never write it into this repo; personal rule changes go to the memory repo.
- Before any push, `python tools/check_core.py --memory ../<agent>-memory` must report the core clean.
- Any change to a rule, workflow or integration updates the matching file in `docs/`, `prompts/` or `examples/memory/` (and `docs/memory.md` when the memory format changes) in the same change.
- The agent proposes; it acts only on explicit approval. See `docs/features/approvals.md`.
- Brain (`brain/v1` gist) holds the agent's rules. Follow `docs/integrations.md` exactly: read-modify-PATCH the whole file, keep others' entries, never re-add a deleted id.
- The agent's name is configurable; never hard-code an agent name in the core. Its permanent `id` and its alias `name` come from memory.
- No personal names in app code (`app/cos`): people, divisions and their labels reach the app as settings from memory.
