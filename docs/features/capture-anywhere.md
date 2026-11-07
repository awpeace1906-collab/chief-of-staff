# Capture anywhere: files, brain dumps, Markdown export

**Status:** design. Nothing here is built yet. It builds on what exists: capture ([commitments.md](commitments.md)), the expense log, trips and binders ([evening-and-week.md](evening-and-week.md)), the Talk tab's mic button and `POST /api/voice/transcribe` (`app/cos/voice.py`), and `GET /api/export`.

Three ways to get things in and out of the agent with less effort. Everything still follows [approvals.md](approvals.md): what the agent captures becomes items, notes and proposals; nothing lands on a calendar or goes to anyone without approval.

## Files and photos

Send the agent a photo, screenshot or PDF; it reads it, files it, keeps the original, and turns dates into proposals.

### Ways in

| Way in | How |
|---|---|
| **iPhone share sheet** | A share extension in the iOS shell: "Send to <agent>" from Photos, Files, Mail or Safari. Posts to `POST /api/intake` |
| **The web app** | A paperclip in Talk: pick a file or take a photo |
| **Email** | Attach it to a message to the agent's address (the `+<agent>` address or the agent's inbox); capture already reads these |
| **Text** | MMS to the agent's number, once the gateway passes MMS ([agent-number-approvals-vault.md](agent-number-approvals-vault.md)) |

Accepted: images (JPEG, PNG, HEIC), PDF, plain text, Markdown, CSV. Up to 20 MB each.

### What happens

1. **Read.** Text is pulled from the file: the PDF's own text, or OCR for images and scans. OCR runs locally where it can (Apple Vision on the phone, Tesseract on the server); Claude reads the result, with the image itself only when the text isn't enough.
2. **Sort.** Claude decides what it is and where it goes:

   | It looks like | It becomes |
   |---|---|
   | A receipt (ride, hotel, parking, meal while away) | An expense on the right trip or rotation |
   | A schedule, rotation letter, orientation packet | A binder, or an update to one, plus items for what's owed |
   | An appointment card, invitation, flyer | A calendar **proposal** ("Add: …") |
   | A form or letter with a deadline | An item with the due date |
   | Anything else | A note, filed by division |

3. **Keep the original.** The file is stored with the record it made (`attachments` table, on the principal's server; never in memory or the core) and linked from it, so the source is one tap away.
4. **Say what it did.** One line back: "Filed: hotel receipt, $52.82 → the conference trip. Proposed: Add: Orientation Mon 7:45am."

### Guards

- **No clinical or patient details.** If the text looks clinical (a patient list, a note, a lab result), nothing is extracted or kept; the agent says it skipped it. Health-data digests are never opened, as now.
- **No secrets.** A photo of a card, an ID, a password or a code is not filed; the agent says to put it in Settings or keep it elsewhere ([agent-number-approvals-vault.md](agent-number-approvals-vault.md), the vault).
- **Duplicates:** a file whose hash or contents match one already filed links to the existing record instead of making a new one.
- **Who can send:** only signed-in members (app, share sheet) or matched members (text, email), with their role's rights.

## Brain dump

Hold the mic in Talk and say everything on your mind, up to 2 minutes, the way it comes out, including corrections ("Thursday… no, Friday").

1. Audio goes to `POST /api/voice/transcribe` (local Whisper when available).
2. Claude splits the transcript into pieces and applies corrections, keeping the last version of anything said twice.
3. Each piece goes where capture would send it: an item (with owner and due date), a calendar **proposal**, a note, or a message for someone else (a **Send:** draft, never sent unasked).
4. The agent reads back what it captured as a short list, each line with an undo: "3 items, 1 proposal, 1 note."

The same flow handles a voice memo shared from another app and a voice note sent by text. The audio is kept only until it's transcribed, unless the principal turns on keeping it.

## Markdown export

**Settings → Export → Markdown (.zip)**, or `cos export --markdown`, or `GET /api/export?format=markdown`.

A zip of plain Markdown files that opens as-is in Obsidian, Notion, VS Code or any editor:

```
<agent>-export-<date>/
  README.md              what's here, when it was exported
  board/
    open/<item>.md       one file per item: title, owner, due, status, history, evidence
    done/<item>.md
  trips/<trip>.md        legs, lodging, notes
  binders/<binder>.md
  expenses.csv           and expenses.md (a table by trip)
  decisions/<id>.md
  notes/<division>/<note>.md
  attachments/           originals of shared files, linked from the files above
```

- Front matter (YAML) carries the fields, so the files can be re-imported and Obsidian can query them.
- It's a one-time export the principal runs, not a live sync.
- It holds no secrets (tokens, keys, device tokens are never exported, as now) and the audit log isn't in it unless asked for.
- The JSON export stays as the full backup; Markdown is the readable copy.

## Build order

1. **Markdown export** (smallest): a writer over `export_all`, the Settings button, a test that a round-trip keeps every field.
2. **Files and photos:** `POST /api/intake`, local OCR, the sort step, `attachments`, the paperclip in Talk; then the iOS share extension; then email attachments in capture.
3. **Brain dump:** the 2-minute recorder in Talk, the split-and-correct step, the read-back with undo.

## Test scenarios

1. A hotel receipt photo → one expense on the right trip, original attached; sent again → no duplicate.
2. A PDF schedule with three dates → three "Add:" proposals, nothing on the calendar until approved.
3. A photo of a patient list → nothing extracted or stored; the agent says it skipped it.
4. A photo of a credit card → not filed; the agent says why.
5. A brain dump with "Thursday… no, Friday" → one item, dated Friday.
6. A brain dump asking to "tell the nanny I'm running late" → a Send: draft, not sent.
7. Markdown export → re-import → every item, trip and expense matches.
