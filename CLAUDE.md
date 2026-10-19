# Chief of Staff: notes for Claude

- This repo is the living spec for Tower, Andrew's AI chief of staff, and later the source of a self-contained app.
- Any change to a rule, workflow or integration must update the matching file in `docs/`, `config/tower.json` or `prompts/` in the same change.
- Tower proposes; it acts only on explicit approval. See `docs/features/approvals.md`.
- Memory is Brain (`brain/v1` gist). Follow `docs/integrations.md` exactly: read-modify-PATCH the whole file, keep others' entries, never re-add a deleted id.
- The assistant name is configurable in the app; never hard-code "Tower" in app code.
- `config/tower.json` holds personal data (calendar IDs, family names). Keep this repo private.
