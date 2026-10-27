# People: who the agent tracks, and noticing someone new

**Status:** in the app (`app/cos/people.py`) and in the daily brief's instructions.

The agent plans around the people in memory's `people` list (`[{name, role, division?}]`): the principal, a partner, children, caregivers, anyone else in the household. A coverage person (a nanny) is also named in their division's `coverage`. The core never holds these names; they come from memory ([memory.md](../memory.md)).

## Adding someone

- **Ask for it.** Tell the agent in Talk, by text or by email ("We had a daughter, Ellie; track her under Kids"). Your own message is the go-ahead: it adds her straight away (`add_person`).
- **Or edit memory.** Add the person to `people` in `<agent>-memory/memory.json` (and to a division's `coverage` for a caregiver), then load memory again.
- **API:** `POST /api/people {name, role, division}`; `GET /api/people` lists the people tracked and the names noticed.

## Noticing someone new

1. Capture (mail) and the daily brief (calendar events) report names that seem to belong to the household or its care but aren't in `people` (`newPeople`). Patients, colleagues, classmates and senders never count; evidence is one line with no health details.
2. Each mention is kept (`peopleCandidates`). A known first name, a full name or a coverage person is never a candidate.
3. Once a name has come up **3 times on at least 2 different days**, the brief asks in the **Situation Room**: "Is Ellie new to the household? Track them?", with the suggested division, one other, and **No**.
4. **Yes** adds them to `people` under that division (a caregiver or nanny also joins its `coverage`). When the memory directory is on the same machine, its `memory.json` is updated too; commit it to the memory repo to keep it. **No** is remembered: that name is never suggested again.

Nobody is added to the household on a guess: the principal's answer or message is the only way in.
