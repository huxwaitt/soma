# Transcript reference — pasted transcripts in `/administrator:notes`

`/administrator:notes` takes raw notes. Sometimes what the user pastes is not notes but a transcript: the speaker-by-speaker record from `references/copilot-transcript-prompt.md`, a Teams transcript export, or something typed by hand in the same shape. This page says how to tell, and what to do differently. Everything not mentioned here works exactly as "Half 2 — notes" in `SKILL.md` describes (finding the meeting, status `held`, `last_contact`, the minutes email, the report). The note layout is still `references/meeting-note.md`.

## 1. Is it a transcript?

Treat the pasted text (or the file the user named) as a transcript when either holds:

- at least 5 lines match `^\[?\d{0,2}:?\d{0,2}\]?\s*[A-Z][^:]{1,40}: ` (a clock in square brackets or nothing, then a name, a colon and a space: `[13:02] Jane Doe: …`, `Jane Doe: …`), or at least 5 lines match `^\d{1,3}[.)]\s+[A-Z][^:]{1,40}: ` (Copilot sometimes numbers the turns: `12. Jane Doe: …`);
- or one line is exactly `END OF TRANSCRIPT`.

The user's own words win over the rule: "here is the transcript" means transcript even with four turns; "these are my notes" means notes even if every line starts with a name. Say which one you took in the report.

Plain notes go through the normal steps and this page does not apply.

## 2. Clean the text

Work on a copy; the meeting note gets the cleaned text, never the raw paste.

1. Drop lines that are only scaffolding from the Copilot prompt: `PART x of N` (any numbers), `continue`, `continue from the last turn you gave`, `END OF TRANSCRIPT`, and a trailing `Speakers:` block (the line `Speakers:` and the names under it — keep those names for step 3).
2. Anything **above the first turn line** is the user's own text (an intro like "from today's sync:"). Treat it as raw notes: it goes to `## Notes` as "Half 2, step 2" describes. Nothing else goes to `## Notes` (see step 6).
3. Everything from the first turn line to the end is the transcript. A line that does not match the turn pattern (a wrapped sentence, `[unclear]`, a blank line) stays where it is; do not join or split lines.
4. Do not change a word inside a turn: no fixing names, no replacing names with wikilinks, no trimming small talk. Count **turns** = lines matching the turn pattern, **speakers** = distinct names before the colon (trimmed, case-insensitive).

## 3. Speakers → person notes

Build one list of speaker names: the `Speakers:` block when Copilot gave one, else the distinct names from the turn lines. Then, for each name, in this order:

1. The user's own name (`outlook_whoami` display name, or the local part of their address) → `me`.
2. An attendee of the event (`attendees[].name`, organizer included) whose name equals the speaker name, case-insensitive, after collapsing spaces and ignoring a `Dr.`/`Mr`/`Ms` prefix.
3. An attendee whose surname equals the speaker's last word and whose first name starts with the speaker's first word (`Tom L.` → `Tom Lee`).
4. An attendee whose first name equals the speaker name and is the only attendee with that first name (`Jane` → `Jane Doe`).
5. Otherwise: not matched.

For every matched attendee call `vault_find(type="person", identity=<attendees[].address>)`; the note exists because `prep` / `schedule` / "Half 2, step 1" create person stubs for all attendees before this point. Use the returned path for the link (`[[People/<filename minus .md>]]`). A speaker that matched no attendee is written as plain text with `(not an attendee)` — never create a person note from a transcript, the address is unknown. If one speaker could be two attendees (two people called Jane), treat them as not matched and say so in the report.

## 4. Write the `## Transcript` section

When the meeting note is created in this run ("Half 2, step 1" found nothing), the section sits after `## Related emails` and before `## Minutes draft` and is part of the body passed to `vault_write(..., mode="upsert")`. When the note already exists (the usual case — `prep` or `schedule` wrote it), the same layout goes into this run's `vault_write(..., mode="append")` body as a `### Transcript` sub-heading, placed after `### Notes` (if any) and before `### Action items`; the server puts the whole body under `## Update <ISO>`. Never insert a heading into the existing text with the host's file tools — the server is the only writer, and it only appends.

Layout:

```markdown
## Transcript

**Speakers:** [[People/Jane Doe]], [[People/Tom Lee]], me (Hux Waitt), Priya (not an attendee)
**Decisions:**
- Net 45 stays in the contract ([13:04])
- First September delivery moves to 8 Sep ([13:11])

> [!note]- Transcript (9 turns, 3 speakers)
> [13:02] Jane Doe: …
> [13:03] Hux Waitt: …
```

- The callout line is exactly `> [!note]- Transcript (N turns, M speakers)` — the `-` after `]` makes Obsidian show it collapsed. Every transcript line, blank lines included, is prefixed with `> `. A line that already starts with `>` gets `> ` in front of it anyway.
- `**Decisions:**` is left out (line and list) when step 5 found none; write `**Decisions:** none found` instead so a reader knows the transcript was checked.
- The Update body's first line is `Transcript added via /administrator:notes.` (instead of `Notes added via …`). A second transcript for the same meeting goes the same way, under its own `## Update <ISO>`; nothing already in the note is edited.

### Transcripts over 400 lines

Count lines after cleaning. Over 400, the text does not go into the meeting note:

1. Write it with the host's Write tool (UTF-8, LF) to `<vault>\Administrator\Attachments\<meeting filename minus .md>\transcript.md` — the same folder rule email exports use, one folder per note. The file is plain markdown, no frontmatter (it is not a typed note and must stay out of the Bases views): first line `# Transcript — <subject> (<YYYY-MM-DD HH:MM>)`, second line `Meeting note: [[Meetings/<filename minus .md>]]`, then the speaker list, a blank line, then the transcript lines **without** the `> ` prefix. If `transcript.md` already exists in that folder, write `transcript (2).md`, `(3)`, …; never overwrite.
2. In the meeting note the `## Transcript` / `### Transcript` section keeps `**Speakers:**` and `**Decisions:**`, and instead of the callout holds one line: `Full text: [[Administrator/Attachments/<folder>/transcript|transcript.md]] (N turns, M speakers, L lines)`.

This is the one file the plugin writes with the host's Write tool instead of `vault_*`, because `vault_write` only writes typed notes and `Attachments/` is the export folder, not a note folder. It still lives under `Administrator/`; the "never write outside `<vault>/Administrator/`" rule holds, and the file is never edited afterwards. `vault_status.under_user_profile` does not matter here — the Write tool is not sandboxed the way Outlook exports are. `<vault>` is `vault` from `vault_status`.

## 5. Pull out decisions, action items, waiting items

Read only the transcript turns. Quote the turn's clock (`[13:04]`) when it has one, else the speaker name, so the reader can find the place.

**Decisions** — a turn that says the group settled something: `we agreed`, `agreed`, `decision`, `decided`, `let's go with`, `we'll go with`, `final answer`, `settled`, `wir einigen uns`, `beschlossen`. One bullet per decision, ten words or fewer plus the reference, in the order spoken. A later turn that overturns it ("actually, let's keep net 30") replaces the earlier bullet — keep the final state, mention the change in the report. Decisions go under `**Decisions:**` in `## Transcript` (step 4); they are not action items.

**Action items** — a turn where one person takes or is given a task: an imperative or promise with a name (`Tom, can you send the PO`, `I'll sign it tomorrow`, `Jane will send the draft`, `action for Priya: …`, `@Tom …`). Same rule as "Half 2, step 3": one line, the speaker's wording shortened, a date only when one was said (`tomorrow`, `Friday` → the real date from the meeting date), owner `me` for the user, else the matched attendee's display name, else the speaker name as spoken with `owner: ?`. Write `- [ ] <what> by <date> — owner: <owner> ([HH:MM])` under `### Action items` in the Update body (under `## Action items` only when the note is created in this run). Skip a line whose text already exists anywhere in the note, case-insensitive (`vault_read` first). Something that was only discussed ("we should look at packaging at some point") is not an action item.

**Waiting items** — action items whose owner is not `me`, plus turns like `I'll come back to you`, `we'll send it over`, `waiting on legal`. Each one → a `### Waiting on` line and a `Follow-ups.md` row exactly as "Half 2, step 3": `vault_append_row("Administrator/Follow-ups.md", "Open", [<meeting date>, <Who link>, <What>, "[[Meetings/<filename minus .md>]]", <meeting date>], dedupe_key="<occurrence_key> # <What>", key_label="occurrence_key")`. `Who` is the person note link from step 3; a speaker with no person note gets their plain name. The server answers `duplicate` for a repeat and the row is left alone.

**Closed items** — a turn that says a carried-over or open item is done (`Tom: the address is confirmed, Leipzig`, `I sent the forecast this morning`) is handled as "Half 2, step 3" does: a line under `### Closed` naming the item and the turn that closed it (the old box is not ticked — the server never edits existing text), and `vault_move_row` for a matching `Follow-ups.md` row.

## 6. `## Notes` stays the user's

A transcript does **not** fill `## Notes`. It keeps `_(none yet)_` (or whatever the user wrote) unless the user asked for a summary in the same message — "summarise", "summary", "sum it up", "give me the gist", "write the notes from this". Only then write 3–6 bullets, decisions first, then what was discussed, nothing that is not in the transcript, and put them where raw notes would go ("Half 2, step 2": `### Notes` in the Update body, or `## Notes` when the note is created in this run), with a first line `_(summary written from the transcript by /administrator:notes)_`. Say in the report that `## Notes` was left empty when it was, so the user knows the summary is theirs to write or to ask for.

The minutes email ("Half 2, step 5") is still offered. Its bullets come from the decisions and action items of step 5 when `## Notes` is empty; from the summary when one was written. Nothing from the transcript text itself is quoted in the email.

## 7. Report

Add to the usual lines: "transcript: N turns, M speakers (linked: …; not an attendee: …), stored in the note / in `Attachments/…/transcript.md`", the decision count, and "`## Notes` left for you" or "summary written".

## Worked example

User, on 2026-08-25 after the supplier sync: `/administrator:notes supplier sync` followed by:

```
PART 1 of 1
[13:02] Jane Doe: Let's start with the contract. Are you fine with net 45?
[13:03] Hux Waitt: Yes. I'll sign version 3 tomorrow and send it back.
[13:04] Jane Doe: Good, so we agreed on net 45, that stays in.
[13:05] Tom Lee: One thing from my side, the delivery address. I checked, it is still Leipzig, confirmed.
[13:06] Hux Waitt: Thanks, that closes that one.
[13:10] Tom Lee: About September. The first delivery on the first of September is too tight for us.
[13:11] Jane Doe: Let's go with 8 September then. Tom, can you send the updated schedule by Wednesday?
[13:12] Tom Lee: Will do.
[13:14] Priya: I'll send the packaging spec draft next week, once legal has seen it.
END OF TRANSCRIPT
Speakers:
Jane Doe
Hux Waitt
Tom Lee
Priya
```

1. Nine lines match the turn pattern and `END OF TRANSCRIPT` is present → transcript. The meeting is the 13:00 "Weekly supplier sync" (note from the prep example in `SKILL.md`, attendees Jane Doe, Tom Lee; user Hux Waitt).
2. Cleaned: `PART 1 of 1`, `END OF TRANSCRIPT` and the `Speakers:` block dropped; nothing above the first turn. 9 turns, 4 speakers, 9 lines (under 400).
3. Speakers: `Hux Waitt` → me. `Jane Doe` → `vault_find(type="person", identity="jane.doe@acme-parts.com")` → `Administrator/People/Jane Doe.md`. `Tom Lee` → `tom.lee@acme-parts.com` → `Administrator/People/Tom Lee.md`. `Priya` → no attendee → not an attendee.
4. The note exists, so everything goes into one `vault_write("meeting", <frontmatter as found, status: held>, body, mode="append")`; the body starts with `Transcript added via /administrator:notes.` and then:

```markdown
### Transcript

**Speakers:** [[People/Jane Doe]], [[People/Tom Lee]], me (Hux Waitt), Priya (not an attendee)
**Decisions:**
- Net 45 stays in the contract ([13:04])
- First September delivery moves to 8 September ([13:11])

> [!note]- Transcript (9 turns, 4 speakers)
> [13:02] Jane Doe: Let's start with the contract. Are you fine with net 45?
> [13:03] Hux Waitt: Yes. I'll sign version 3 tomorrow and send it back.
> [13:04] Jane Doe: Good, so we agreed on net 45, that stays in.
> [13:05] Tom Lee: One thing from my side, the delivery address. I checked, it is still Leipzig, confirmed.
> [13:06] Hux Waitt: Thanks, that closes that one.
> [13:10] Tom Lee: About September. The first delivery on the first of September is too tight for us.
> [13:11] Jane Doe: Let's go with 8 September then. Tom, can you send the updated schedule by Wednesday?
> [13:12] Tom Lee: Will do.
> [13:14] Priya: I'll send the packaging spec draft next week, once legal has seen it.
```

5. The same body continues:

```markdown
### Action items

- [ ] Sign contract v3 and send back by 2026-08-26 — owner: me ([13:03])
- [ ] Send updated September delivery schedule by 2026-08-27 — owner: Tom Lee ([13:11])
- [ ] Send packaging spec draft (next week) — owner: ? ([13:14])

### Waiting on

- [[People/Tom Lee]] — updated September delivery schedule (since 2026-08-25) → also in [[Follow-ups]]
- Priya — packaging spec draft (since 2026-08-25) → also in [[Follow-ups]]

### Closed

- Confirm Leipzig delivery address (carried over from 2026-08-18) — Tom confirmed it ([13:05])
```

   Two `vault_append_row` calls on `Administrator/Follow-ups.md`, section `Open`, `dedupe_key="<occurrence_key> # updated September delivery schedule"` and `"… # packaging spec draft"`, `key_label="occurrence_key"`; the second row's `Who` is the plain text `Priya`. No `Follow-ups.md` row existed for the Leipzig item, so nothing moves; the old box in `### Carried over` stays as it is.
6. The user did not ask for a summary → `## Notes` still holds `_(none yet)_`.
7. `status: held`, `last_contact` on Jane Doe and Tom Lee as usual. The minutes email is built from the two decisions and three action items, shown, and the question asked.

Report:

> Transcript stored in `Meetings/2026-08-25 1300 Weekly supplier sync.md` (9 turns, 4 speakers: Jane Doe, Tom Lee linked; Priya is not an attendee). 2 decisions, 3 action items (owner of "packaging spec draft" unknown — Priya is not on the invite), 2 waiting on → 2 rows in Follow-ups.md; carried-over "Leipzig address" closed. `## Notes` left for you — say "summarise" if you want 3–6 bullets from the transcript. Draft minutes shown above; save to Drafts?
