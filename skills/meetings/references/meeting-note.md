# Meeting note reference — template and rules

A meeting note is the vault record for one calendar event occurrence. It lives at `<vault>/Administrator/Meetings/YYYY-MM-DD HHmm <slug>.md`. The `meetings` skill writes it; `/administrator:prep` fills `## Prep`, `/administrator:notes` fills `## Notes`, `## Action items`, `## Waiting on` and (on request) `## Minutes draft`. The `schedule` skill writes the same note, with the same template, when it books a meeting (see "Note written by `schedule`" at the end). This file is the one template for meeting notes; no skill keeps its own. The general conventions in `skills/administrator/references/vault.md` apply (ISO dates with offset, quoted ids and wikilinks, block lists, vanilla Obsidian).

## Filename

| Part | Rule |
| --- | --- |
| `YYYY-MM-DD HHmm` | Local date and time of `start` as Outlook returned it (`2026-08-25T13:00:00+02:00` → `2026-08-25 1300`). Never convert time zones. |
| `<slug>` | The email slug rule from `vault.md` applied to `subject`: strip leading `Re:`/`FW:`/`AW:`/`WG:`/`TR:`/`SV:` and also `Canceled:`, `Abgesagt:`, `Updated:`, `Aktualisiert:`; replace `\ / : * ? " < > |` and control characters with `_`; collapse whitespace; trim spaces and trailing dots; cut to 60 characters; empty → `(no subject)`. |
| Collision | Same filename, different `occurrence_key` (two events at the same minute with the same subject): append ` (2)`, ` (3)` before `.md`. Same `occurrence_key`: this is an update, never a second file. |

## Identity

- The identity of a meeting note is `occurrence_key` (`global_id|<start ISO>`, returned on every event by `outlook_list_events`, `outlook_get_event`, `outlook_get_event_by_key`). One occurrence of a recurring meeting = one note.
- If `occurrence_key` is empty, build it yourself as `<global_id>|<start>` (the `start` exactly as Outlook returned it, offset included) and say so in `## Prep`. If `global_id` is also empty (rare, some shared calendars), use `entry_id` in its place and write `global_id: ""`.
- Before creating a note, `vault_find("meeting", {"occurrence_key": <key>, "global_id": <id>})`. `found: true` is the existing note: `vault_write(..., mode="append")`, never a second file (`mode="upsert"` makes that choice for you).
- `global_id` is shared by every occurrence of a recurring meeting. `vault_find("meeting", {"global_id": <id>})` lists earlier occurrences in `matches`, newest first; the one with the latest `start` before this one is "the previous meeting".

## Template

```markdown
---
type: meeting
source: outlook
entry_id: "<entry_id of the event as last seen; optional, see rules>"
global_id: "<global_id verbatim>"
occurrence_key: "<occurrence_key verbatim>"
subject: "<subject as Outlook returned it>"
start: 2026-08-25T13:00:00+02:00
end: 2026-08-25T14:00:00+02:00
location: "Room 4"
organizer: jane.doe@acme-parts.com
organizer_link: "[[Wiki/People/Jane Doe]]"
attendees:
  - jane.doe@acme-parts.com
  - tom.lee@acme-parts.com
attendee_links:
  - "[[Wiki/People/Jane Doe]]"
  - "[[Wiki/People/Tom Lee]]"
is_recurring: false
status: upcoming
created_by: administrator/0.4.1
---

# <Subject as Outlook returned it>

**When:** 2026-08-25 13:00–14:00
**Where:** Room 4
**Organizer:** [[Wiki/People/Jane Doe]] <jane.doe@acme-parts.com>
**Attendees:** [[Wiki/People/Jane Doe]] (required, accepted), [[Wiki/People/Tom Lee]] (optional, no reply)

## Prep

<Written by /administrator:prep. See "Prep section" below.>

## Notes

<Human text. Raw notes go here verbatim only when /administrator:notes creates the note; on an existing note they go under "## Update <ISO>" as "### Notes". The plugin never edits this section once written.>

## Action items

- [ ] <verb + object + by when> — owner: me | <name>

## Waiting on

- [[Wiki/People/Tom Lee]] — <what, ten words or fewer> (since 2026-08-25)

## Related emails

- 2026-08-21 — [[Emails/2026-08-21 Q3 supplier contract – signature needed]] — Jane asks for the signed contract by 29 Aug
- 2026-08-19 — RE: Delivery schedule September (Tom Lee) — not saved <!-- entry_id: 00000000B3… -->

## Minutes draft

<Only present when /administrator:notes created this note and saved a minutes email in the same run. Otherwise the draft text sits under "## Update <ISO>" as "### Minutes draft".>
```

A transcript never sits in the body `notes` creates: `vault_save(kind="transcript")` appends it as `### Transcript` (speakers line, collapsed callout or a file link) under its own `## Update` heading, and the decisions go into a separate append under `### Decisions`; see `references/transcript.md`.

## Frontmatter rules

| Key | Value |
| --- | --- |
| `entry_id` | Optional. The event's `entry_id` at the time the note was written, quoted. `schedule` always writes it (it is what `outlook_update_event` needs); `prep` writes it when it has one. Not an identity: an occurrence's `entry_id` is not stable, so never search by it when `occurrence_key` or `global_id` is known. |
| `global_id`, `occurrence_key` | Verbatim, always quoted. Never edited after creation. |
| `subject` | Verbatim, quoted. `Canceled:` prefix kept if Outlook has it. |
| `start`, `end` | ISO with offset, verbatim. All-day events: `start` at 00:00 and `end` the next day 00:00 as Outlook returns them, plus `all_day: true`. |
| `location` | Quoted; `""` when empty. Teams links go here unchanged. |
| `organizer` | `organizer_address` (SMTP). If it still starts with `/O=`, store it as is and say so in `## Prep`. |
| `organizer_link` | `"[[Wiki/People/<Display Name>]]"` — the organizer's name from `attendees[]` (the entry whose `address` equals `organizer_address`), else from `outlook_search_contacts`, else the local part of the address. `""` when the organizer is the user (no person note for yourself). |
| `attendees` | SMTP addresses from `attendees[].address`, in the order Outlook gives them, the user's own address (from `outlook_whoami`) left out. Empty list `[]` for a private appointment with no one invited. |
| `attendee_links` | One `"[[Wiki/People/<Display Name>]]"` per entry in `attendees`, same order. |
| `is_recurring` | `true` / `false` from the event. |
| `status` | `upcoming` on creation by `prep` or `schedule`; `held` set by `notes`; `cancelled` set by `prep` when `outlook_get_event_by_key` no longer finds the occurrence or the subject starts with `Canceled:` / `Abgesagt:`. This is the only frontmatter key edited in place. |
| `created_by` | `administrator/0.4.1`. |

Header lines under the `# Subject`: `**When:**` is `YYYY-MM-DD HH:MM–HH:MM` (one date; if `end` is on another day write both dates). `**Organizer:**` is `me <address>` when the user organised it. `**Attendees:**` lists every attendee as a wikilink with `(required|optional|resource, <response>)` where `<response>` is the event's `attendees[].response` in plain words: `accepted`, `tentative`, `declined`, `no reply` (for `none` and `notresponded`), `organizer`.

## Body sections: who writes what

| Section | Written by | Edited later? |
| --- | --- | --- |
| `## Prep` | `prep` on creation; `schedule` writes a placeholder (see below) | No. A second `prep` run — or the first `prep` run on a note `schedule` wrote — appends `## Update <ISO>` at the end of the file with a fresh `### Prep` inside it. |
| `## Notes` | `prep` / `schedule` write the placeholder `_(none yet)_`; `notes` writes it only when it creates the note in the same run | Never. The placeholder is not replaced; every drop of notes lands under `## Update <ISO>` as `### Notes`. |
| `## Action items` | `prep` / `schedule` write `- none`; `notes` fills it only on creation | Never. New `- [ ]` lines go under `## Update <ISO>` as `### Action items`. Boxes are never ticked by the plugin; a closed item is named under `### Closed` in the same Update. The unchecked action items of a meeting = all `- [ ]` lines in the note, in any section. |
| `## Waiting on` | same as `## Action items` | Never; later items go under `## Update` as `### Waiting on`. |
| `## Related emails` | `prep` | Never; a second `prep` run puts new lines under `## Update` as `### Related emails`. Skip a line whose `[[Emails/…]]` link or `entry_id` comment is already in the note. |
| `### Transcript` (under `## Update`) | `vault_save(kind="transcript")`, called by `notes` after the transcript file was written once (`references/transcript.md`) | Never; every transcript lands under its own `## Update` heading, never in the created body. |
| `## Minutes draft` | `notes`, only when it creates the note and a draft was saved in the same run | Never; the draft text is appended under `## Update` as `### Minutes draft` (not replaced — the newest one mirrors the Drafts item). |

The section order above is fixed. `prep` writes every heading even when a section is empty (with the single line `- none` for lists, `_(none yet)_` for `## Notes`). `## Minutes draft` is the exception: not present unless `notes` wrote it. The server (`vault_write`) never edits text that is already in the file, so everything a later run adds lives under its own `## Update <ISO>` heading with `###` sub-headings.

## Prep section

Written once by `/administrator:prep`, in this order; leave out a sub-heading only when there is nothing for it **and** say so in one line.

```markdown
## Prep

**Previous meeting:** [[Meetings/2026-08-18 1300 Weekly supplier sync]] (2026-08-18)

### Carried over

- [ ] Send revised forecast to Jane — owner: me (from 2026-08-18)
- [ ] Confirm Leipzig delivery address — owner: Tom Lee (from 2026-08-18)

### People

- [[Wiki/People/Jane Doe]] — ACME Parts GmbH — last contact 2026-08-21
- [[Wiki/People/Tom Lee]] — ACME Parts GmbH — last contact 2026-08-19

### Open follow-ups with them

- Jane Doe: Contract draft (since 2026-08-21) — [[Wiki/People/Jane Doe]]
- me: Send the signed contract (since 2026-08-22, due 2026-08-26) — [[Wiki/Topics/acme-supplier-contract]]

### Recent threads

1. **RE: Q3 supplier contract – signature needed** (Jane Doe, 2026-08-21) — Jane sent v3 with net-45 terms and wants it signed by 29 Aug; Tom handles the PO once it is back. [[Emails/2026-08-21 Q3 supplier contract – signature needed]]
2. **Delivery schedule September** (Tom Lee, 2026-08-19) — Tom proposes moving the first delivery to 8 Sep; no reply from me yet. <!-- entry_id: 00000000B3… -->
3. **Re: Supplier sync agenda** (Jane Doe, 2026-08-17) — one line <!-- entry_id: 00000000B1… -->

### Suggested points

- Confirm net-45 and sign the contract (item 1)
- Answer Tom on the 8 Sep delivery date (item 2)
- Carried over: Leipzig address still open
```

Rules:

- **Previous meeting**: only for recurring meetings (`is_recurring: true`) or when another note shares the `global_id`. Link the most recent earlier occurrence. Copy its unchecked `- [ ]` lines (from `## Action items` and from any `### Action items` under its `## Update` headings, skipping items named under a `### Closed` list) into `### Carried over`, each suffixed `(from <that note's date>)`. Do not copy checked lines, and do not tick anything in the old note.
- **People**: one line per attendee, from the person note's `company` and `last_contact` (blank `last_contact` → "no email on record").
- **Open follow-ups with them**: the `commitments[]` of `vault_prep_context` — the open items on the attendees' pages and the items anywhere they own, both directions. One line each: `- <owner_name>: <text> (since <since>[, due <due>]) — [[<page>]]`. None → the line `- none`.
- **Recent threads**: up to 5, newest first, each one line: bold subject, `(sender, date)`, a summary of 25 words or fewer from the preview (items 3–5) or from the whole conversation (items 1–2, fetched with `outlook_get_conversation`), then a `[[Emails/…]]` link when a note exists for that `internet_message_id` / `entry_id`, otherwise `<!-- entry_id: … -->` of the newest mail in the thread. The same lines (link or comment only, no summary) also go into `## Related emails`.
- **Suggested points**: 2–5 bullets, each pointing at the thread number or carried-over item it comes from. Nothing invented; if there is nothing to point at, write `- nothing open`.

## Status lines and the Update section

A second `prep` run on an existing note (same `occurrence_key`) appends:

```markdown
## Update 2026-08-25T08:40:00+02:00

Prep re-run via /administrator:prep.

### Prep

<the same sub-headings as above, but only lines that are new since the last prep: new threads, new open items with them, new carried-over items. Nothing new → the single line "Nothing new since the last prep.">
```

with new thread lines under `### Related emails` inside the same Update. The frontmatter is unchanged except `status` (if the event turned out to be cancelled).

Every `notes` drop (the first one included, unless `notes` created the note in the same run) appends:

```markdown
## Update 2026-08-25T15:12:00+02:00

Notes added via /administrator:notes.

### Notes

<the raw notes, verbatim>

### Action items

- [ ] <text> — owner: <owner>

### Waiting on

- [[Wiki/People/<Name>]] — <what> (since <meeting date>)

### Closed

- <the carried-over or follow-up item the notes say is done, and what closed it>
```

`### Waiting on` / `### Closed` are left out when empty. The `## Notes` placeholder, `- none` lines and existing boxes stay as they are; readers, `prep` (carried-over items) and `/administrator:weekly` collect the `- [ ]` lines from the whole note.

## Person page: the meeting's Records line

Attendee person pages (wiki pages under `Wiki/People/`, created or updated by `prep` and `notes`) get one line under `## Records`:

```markdown
## Records

- 2026-08-25 — [[Meetings/2026-08-25 1300 Supplier sync]]
```

The line is the body of the `vault_write("person", …)` call (`mode="create"` for a stub, `mode="append"` for an existing page); the server puts it under `## Records` (newest first, capped at 15) and never adds an `## Update` heading to a person page. The meeting note's frontmatter is the source of truth for the status; the line carries none. A person stub created by `prep` has `last_contact: ""` (no email on record yet), `aliases: []` and `status: draft`; `notes` sets `last_contact` to the meeting `start` if that is later than the stored value (the server replaces that key on append), because a held meeting counts as contact.

## Open items from a meeting

A waiting-on line of the notes becomes one open item on a wiki page, not a row in a file: `notes` sends it with the meeting's ingest as

```
{"op": "open", "text": "Confirm Leipzig delivery address", "owner": "[[Wiki/People/Tom Lee]]", "due": "2026-09-01", "since": "2026-08-25"}
```

on the topic or decision page the meeting matched, else on that person's page. `src` and `since` default to the meeting record, so the page's line ends `— [[Meetings/2026-08-25 1300 Supplier sync]]`.

- The same wording twice, or this meeting twice, is refused as `duplicate`; leave it.
- `notes` closes an item only when the user's notes say it is done ("Tom confirmed the address"): `{"op": "done", "id": <the id from `commitments[]`>}`. `inbox` and `followups` close their own items the same way. Old boxes in the meeting note are never ticked.
- `Administrator/Follow-ups.md` shows the items other people owe, written from the pages after every wiki change; `vault_row` refuses the file.

## Note written by `schedule`

When `/administrator:schedule` books a meeting it writes the same note from the same template, so `prep` and `notes` find it later by `occurrence_key`. Differences from a note written by `prep`:

- `entry_id` is always present (from `outlook_create_event`); `global_id` and `occurrence_key` come from `outlook_get_event(entry_id=…, response_format="json")`, called once right after the create. `organizer` is the user's own address, `organizer_link: ""`, `is_recurring: false`, `status: upcoming`.
- `attendees` / `attendee_links`: same rule as `prep` — one person note per attendee, found or created exactly as `prep` step 3 does (`vault_find("person", {"email": …})` first, which also matches `aliases`; stub with `last_contact: ""`, `aliases: []`; a `## Records` line on each).
- `## Prep` holds the single line `_(booked by /administrator:schedule on <YYYY-MM-DD>; no prep was run)_` followed by the user's agenda text as bullets if they gave any. `## Notes` holds `_(none yet)_`, `## Action items` and `## Waiting on` hold `- none`, `## Related emails` holds `- none`.
- A move (`outlook_update_event`) never renames the file or edits `start` / `end`; it appends `## Update <ISO>` with the old and new time. The `occurrence_key` keeps the original start, so `prep` run after a move will not find the note by the event's new key; it then falls back to `vault_find("meeting", {"global_id": <id>})` (same id after a move) and treats that note as the existing one.
