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
- Before creating a note, Grep `<vault>/Administrator/Meetings/*.md` for the line `occurrence_key: "<key>"` (exact string, quotes included). A hit is the existing note: append, never rewrite, never create a second file.
- `global_id` is shared by every occurrence of a recurring meeting. Grep for `global_id: "<id>"` to find earlier occurrences; the one with the latest `start` before this one is "the previous meeting".

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
organizer_link: "[[People/Jane Doe]]"
attendees:
  - jane.doe@acme-parts.com
  - tom.lee@acme-parts.com
attendee_links:
  - "[[People/Jane Doe]]"
  - "[[People/Tom Lee]]"
is_recurring: false
status: upcoming
created_by: administrator/0.0.3
---

# <Subject as Outlook returned it>

**When:** 2026-08-25 13:00–14:00
**Where:** Room 4
**Organizer:** [[People/Jane Doe]] <jane.doe@acme-parts.com>
**Attendees:** [[People/Jane Doe]] (required, accepted), [[People/Tom Lee]] (optional, no reply)

## Prep

<Written by /administrator:prep. See "Prep section" below.>

## Notes

<Human text. Raw notes pasted by the user go here, verbatim. The plugin never edits this section once written; a second drop of notes goes under its own "## Update <ISO>" heading at the end of the file.>

## Action items

- [ ] <verb + object + by when> — owner: me | <name>

## Waiting on

- [[People/Tom Lee]] — <what, ten words or fewer> (since 2026-08-25) → also in [[Follow-ups]]

## Related emails

- 2026-08-21 — [[Emails/2026-08-21 Q3 supplier contract – signature needed]] — Jane asks for the signed contract by 29 Aug
- 2026-08-19 — RE: Delivery schedule September (Tom Lee) — not saved <!-- entry_id: 00000000B3… -->

## Minutes draft

<Only present after /administrator:notes offered a minutes email. The exact text that went to Drafts, or "not sent" if the user said no.>
```

## Frontmatter rules

| Key | Value |
| --- | --- |
| `entry_id` | Optional. The event's `entry_id` at the time the note was written, quoted. `schedule` always writes it (it is what `outlook_update_event` needs); `prep` writes it when it has one. Not an identity: an occurrence's `entry_id` is not stable, so never search by it when `occurrence_key` or `global_id` is known. |
| `global_id`, `occurrence_key` | Verbatim, always quoted. Never edited after creation. |
| `subject` | Verbatim, quoted. `Canceled:` prefix kept if Outlook has it. |
| `start`, `end` | ISO with offset, verbatim. All-day events: `start` at 00:00 and `end` the next day 00:00 as Outlook returns them, plus `all_day: true`. |
| `location` | Quoted; `""` when empty. Teams links go here unchanged. |
| `organizer` | `organizer_address` (SMTP). If it still starts with `/O=`, store it as is and say so in `## Prep`. |
| `organizer_link` | `"[[People/<Display Name>]]"` — the organizer's name from `attendees[]` (the entry whose `address` equals `organizer_address`), else from `outlook_search_contacts`, else the local part of the address. `""` when the organizer is the user (no person note for yourself). |
| `attendees` | SMTP addresses from `attendees[].address`, in the order Outlook gives them, the user's own address (from `outlook_whoami`) left out. Empty list `[]` for a private appointment with no one invited. |
| `attendee_links` | One `"[[People/<Display Name>]]"` per entry in `attendees`, same order. |
| `is_recurring` | `true` / `false` from the event. |
| `status` | `upcoming` on creation by `prep` or `schedule`; `held` set by `notes`; `cancelled` set by `prep` when `outlook_get_event_by_key` no longer finds the occurrence or the subject starts with `Canceled:` / `Abgesagt:`. This is the only frontmatter key edited in place. |
| `created_by` | `administrator/0.0.3`. |

Header lines under the `# Subject`: `**When:**` is `YYYY-MM-DD HH:MM–HH:MM` (one date; if `end` is on another day write both dates). `**Organizer:**` is `me <address>` when the user organised it. `**Attendees:**` lists every attendee as a wikilink with `(required|optional|resource, <response>)` where `<response>` is the event's `attendees[].response` in plain words: `accepted`, `tentative`, `declined`, `no reply` (for `none` and `notresponded`), `organizer`.

## Body sections: who writes what

| Section | Written by | Edited later? |
| --- | --- | --- |
| `## Prep` | `prep` on creation; `schedule` writes a placeholder (see below) | No. A second `prep` run — or the first `prep` run on a note `schedule` wrote — appends `## Update <ISO>` at the end of the file with a fresh `### Prep` inside it. |
| `## Notes` | `notes` (first drop) or left as a placeholder line `_(none yet)_` by `prep` | The placeholder line is replaced by the first drop. After that never touched; later drops go under `## Update <ISO>`. |
| `## Action items` | `notes` | New `- [ ]` lines may be appended at the bottom. Existing lines (checked or unchecked) are never changed or removed. |
| `## Waiting on` | `notes` | Append only. |
| `## Related emails` | `prep` | Append only; a second `prep` run adds new lines here and not a second heading. Skip a line whose `[[Emails/…]]` link or `entry_id` comment is already present. |
| `## Minutes draft` | `notes`, only if a minutes email was offered | Replaced wholesale when a new draft is written, because it mirrors the Drafts item. |

The section order above is fixed. `prep` writes every heading even when a section is empty (with the single line `- none` for lists, `_(none yet)_` for `## Notes`), so `notes` can find them later. `## Minutes draft` is the exception: not present until `notes` writes it.

## Prep section

Written once by `/administrator:prep`, in this order; leave out a sub-heading only when there is nothing for it **and** say so in one line.

```markdown
## Prep

**Previous meeting:** [[Meetings/2026-08-18 1300 Weekly supplier sync]] (2026-08-18)

### Carried over

- [ ] Send revised forecast to Jane — owner: me (from 2026-08-18)
- [ ] Confirm Leipzig delivery address — owner: Tom Lee (from 2026-08-18)

### People

- [[People/Jane Doe]] — ACME Parts GmbH — last contact 2026-08-21
- [[People/Tom Lee]] — ACME Parts GmbH — last contact 2026-08-19

### Open follow-ups with them

| Since | Who | What | Email | Last checked |
| --- | --- | --- | --- | --- |
| 2026-08-21 | [[People/Jane Doe]] | Contract draft | [[Emails/2026-08-21 Contract draft]] | 2026-08-22 <!-- entry_id: 00000000AC… --> |

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

- **Previous meeting**: only for recurring meetings (`is_recurring: true`) or when another note shares the `global_id`. Link the most recent earlier occurrence. Copy its unchecked `- [ ]` lines from `## Action items` into `### Carried over`, each suffixed `(from <that note's date>)`. Do not copy checked lines, and do not tick anything in the old note.
- **People**: one line per attendee, from the person note's `company` and `last_contact` (blank `last_contact` → "no email on record").
- **Open follow-ups with them**: the rows from `Follow-ups.md` `## Open` whose `Who` links to any attendee's person note (or shows their display name). Copied verbatim, same table header. No rows → the line `- none`.
- **Recent threads**: up to 5, newest first, each one line: bold subject, `(sender, date)`, a summary of 25 words or fewer from the preview (items 3–5) or from the whole conversation (items 1–2, fetched with `outlook_get_conversation`), then a `[[Emails/…]]` link when a note exists for that `internet_message_id` / `entry_id`, otherwise `<!-- entry_id: … -->` of the newest mail in the thread. The same lines (link or comment only, no summary) also go into `## Related emails`.
- **Suggested points**: 2–5 bullets, each pointing at the thread number or carried-over item it comes from. Nothing invented; if there is nothing to point at, write `- nothing open`.

## Status lines and the Update section

A second `prep` run on an existing note (same `occurrence_key`) appends:

```markdown
## Update 2026-08-25T08:40:00+02:00

Prep re-run via /administrator:prep.

### Prep

<the same sub-headings as above, but only lines that are new since the last prep: new threads, new follow-up rows, new carried-over items. Nothing new → the single line "Nothing new since the last prep.">
```

and adds any new thread lines to `## Related emails`. The frontmatter is unchanged except `status` (if the event turned out to be cancelled).

A second `notes` drop on a note whose `## Notes` already holds text appends:

```markdown
## Update 2026-08-25T15:12:00+02:00

Notes added via /administrator:notes.

### Notes

<the new raw notes, verbatim>
```

and appends any new `- [ ]` lines to `## Action items` and new lines to `## Waiting on` in their original sections (so there is one checklist per meeting, not one per drop).

## Person note: meetings list

Attendee person notes (created or updated by `prep` and `notes`) get a `## Meetings` section after `## Emails`:

```markdown
## Meetings

- 2026-08-25 — [[Meetings/2026-08-25 1300 Supplier sync]] (upcoming)
```

One line per meeting note, newest at the bottom, added by `prep` on creation. `notes` does not rewrite the line when the status changes to `held`; the meeting note's frontmatter is the source of truth. A person stub created by `prep` has `last_contact: ""` (no email on record yet) and `aliases: []`; `notes` sets `last_contact` to the meeting `start` if that is later than the stored value, because a held meeting counts as contact.

## Follow-ups rows from a meeting

Same table and same `Who`/`What` rules as `vault.md`. Differences for rows that come from a meeting:

```markdown
| 2026-08-25 | [[People/Tom Lee]] | Confirm Leipzig delivery address | [[Meetings/2026-08-25 1300 Supplier sync]] | 2026-08-25 <!-- occurrence_key: 0400…|2026-08-25T13:00:00+02:00 --> |
```

- `Since` = the meeting date. `Email` column holds the meeting note link. The trailing comment is `occurrence_key: …` instead of `entry_id: …`.
- Row identity: the `occurrence_key` comment **plus** the `What` text (one meeting can create several rows). Existing row with both → leave it. `inbox` closes rows as before when a reply from `Who` on the same subject words shows up; `notes` closes a row only when the user's notes say it is done ("Tom confirmed the address") — then the row moves to `## Done` with `Closed` = the meeting date.

## Note written by `schedule`

When `/administrator:schedule` books a meeting it writes the same note from the same template, so `prep` and `notes` find it later by `occurrence_key`. Differences from a note written by `prep`:

- `entry_id` is always present (from `outlook_create_event`); `global_id` and `occurrence_key` come from `outlook_get_event(entry_id=…, response_format="json")`, called once right after the create. `organizer` is the user's own address, `organizer_link: ""`, `is_recurring: false`, `status: upcoming`.
- `attendees` / `attendee_links`: same rule as `prep` — one person note per attendee, found or created exactly as `prep` step 3 does (grep `email:` / `aliases:` first; stub with `last_contact: ""`, `aliases: []`; a `## Meetings` line on each).
- `## Prep` holds the single line `_(booked by /administrator:schedule on <YYYY-MM-DD>; no prep was run)_` followed by the user's agenda text as bullets if they gave any. `## Notes` holds `_(none yet)_`, `## Action items` and `## Waiting on` hold `- none`, `## Related emails` holds `- none`.
- A move (`outlook_update_event`) never renames the file or edits `start` / `end`; it appends `## Update <ISO>` with the old and new time. The `occurrence_key` keeps the original start, so `prep` run after a move will not find the note by the event's new key; it then falls back to the `global_id` grep (same id after a move) and treats that note as the existing one.
