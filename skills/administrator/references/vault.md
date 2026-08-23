# Vault reference — note templates and rules

Everything the plugin writes goes under `<vault>/Administrator/` where `<vault>` = `ADMINISTRATOR_VAULT`. Notes are plain markdown with YAML frontmatter and must render in vanilla Obsidian. This page is the schema: what each note looks like and what each key means. The `vault` MCP server (`administrator-vault`) enforces it; skills pass a frontmatter object and a markdown body to `vault_write` and never touch files themselves.

Conventions the server applies:

- Dates in frontmatter are ISO-8601 with the offset Outlook returned (`2026-08-22T09:14:00+02:00`). Never convert time zones.
- Quoting is the server's job: `entry_id`, `internet_message_id`, `conversation_id`, `global_id`, `occurrence_key`, `subject`, `location`, `msg_file` are always quoted; plain SMTP addresses and `administrator/0.1.0` stay unquoted. Pass raw values.
- Lists are YAML block lists; pass arrays (`[]` when empty).
- Wikilinks in frontmatter are quoted: `from_link: "[[People/Jane Doe]]"`.
- `created_by: administrator/0.1.0` on every note (pass it; the server fills in only `type`).

## Writing notes: the `vault_*` tools

The rules on this page are enforced by the `vault` MCP server (`administrator-vault`); skills call its tools instead of writing files. Pass the frontmatter as an object and the body as markdown (no frontmatter fences); the server picks the filename, checks the required keys, quotes what must be quoted, and refuses a second note for an identity that exists.

| Need | Call |
| --- | --- |
| Is this mail / meeting / person already in the vault? | `vault_find(type, identity)` — identity `{"internet_message_id": …, "entry_id": …}`, `{"occurrence_key": …, "global_id": …}`, an SMTP address, a date, or a week |
| Write or update a note | `vault_write(type, frontmatter, body, mode="upsert")` — returns `action: created` or `appended` plus the path |
| A row in `Follow-ups.md` or a daily table | `vault_append_row(path, section, row, dedupe_key=<entry_id>)` (`key_label="occurrence_key"` for meeting rows) |
| Close a follow-up | `vault_move_row("Administrator/Follow-ups.md", "Open", "Done", <entry_id>, set_last_cell=<today>)` |
| Read a note, list notes | `vault_read(path)`, `vault_list(type, since)` |
| Which daily note was last written? | `vault_list("daily", limit=1, fields=["date", "inbox_checked"])` |
| Do the mechanical part of a workflow in code | `vault_rules`, `vault_inbox_prepare`, `vault_write_daily`, `vault_save_email`, `vault_prep_context`, `vault_weekly_facts`, `vault_attach_transcript` — see "Workflow helpers" below |

On `append` the server only changes `status`, `last_contact`, `inbox_checked`, `mails_seen` and adds new `aliases`; every other frontmatter key and all existing body text stay as they are. `append` still checks the required keys, so pass the frontmatter `vault_find` returned with just the intended key changed. Use `created_by: administrator/0.1.0` in every frontmatter you pass.

`dedupe_key` for meeting rows is `<occurrence_key> # <What>` (one meeting can create several rows); for proposed-times rows it is `<address> # pick a time — <subject>` with `key_label="proposal"`; for rows `followups` writes from the user's own sent mail it is the `internet_message_id` of that mail with `key_label="internet_message_id"` (`entry_id` when it is empty). The server treats a row as a duplicate when the key value appears in any hidden comment anywhere in the file, whatever the label.

A key or a cell may contain `|` (an `occurrence_key` always does); the server stores it as `\|` and gives it back unescaped, so pass raw values and compare against the raw key.

## Workflow helpers

These tools do the moving, comparing and formatting so the model only decides. They take the JSON the outlook tools returned and write through the same code as `vault_write` / `vault_append_row`, so every rule on this page still holds. Pass `created_by="administrator/0.1.0"` to the ones that write.

- `vault_inbox_prepare(items, date)` — pass the `items[]` from `outlook_list_mails`. Back come only the mails not yet in any daily note of that ISO week and not matched by a never-save rule; each has `label` / `rule` filled when a rule decided. Read the `preview` only of the ones with `label: null`, then call `vault_write_daily(date, labels=[{entry_id, label, reason}], since, inbox_checked, events)` with your labels — items come from the cached list (`Attachments/_cache/inbox-<date>.json`), so do not pass them back. Pass `events` from `outlook_list_events` in `daily`; clashes and missing prep notes are worked out in code, `watch_out` is for anything else. A second run on the same day appends only new rows; `action: unchanged` means nothing was written. Items with no label from the model or a rule come back in `unlabelled` and are left out of the note.
- `vault_save_email(mail, summary, action_items, attachments_saved, msg_file, self_addresses, company)` — `mail` is the `outlook_get_mail(trim_quoted=true)` JSON. The note, the person note and the Follow-ups row (for `waiting`) are written in one call; `status` defaults to `todo` with action items, `fyi` without, `waiting` when the mail is from one of `self_addresses` and has action items.
- `vault_prep_context(occurrence_key, global_id, attendees)` replaces the `vault_find` / `vault_read` round trips of `prep` and `notes`; `vault_weekly_facts(week)` replaces those of `weekly`. Both are read-only.
- `vault_attach_transcript(meeting_path, transcript_path)` — write the transcript under `Attachments/<meeting>/` with the host's Write tool once, then call this; never paste the text back through `vault_write`.
- `Administrator/Rules.md` (`type: rules`, created by `vault_init`, never overwritten) holds the user's rules: `## Labels` table `| Match | Field | Label |`, `## Never save` table `| Match | Field |`, `## Fyi senders` list. `Field` is `from`, `domain`, `name` or `subject`; `Match` is a case-insensitive part of the value or a `*` / `?` pattern. Built-in rules (List-Unsubscribe, auto-replies, meeting responses, no-reply senders, people with `status: fyi`) run first. `vault_rules(action="get")` shows them; the plugin writes a line only through `vault_append_row("Administrator/Rules.md", "Labels", [match, field, label])` after the user said yes to a proposal.
- `fields=[...]` on `vault_find` and `vault_list` returns only those frontmatter keys.

## Filenames

The server builds these; listed so you can predict the path and the `Attachments/` folder name.

| Note | Path | Rule |
| --- | --- | --- |
| Email | `Emails/YYYY-MM-DD <slug>.md` | Date = `received` date (local). Slug from subject, see below. |
| Meeting | `Meetings/YYYY-MM-DD HHmm <slug>.md` | Date and time = `start` (local). Slug from `subject` with the email rule plus `Canceled:` / `Cancelled:` / `Abgesagt:` / `Updated:` / `Aktualisiert:` prefixes stripped. Full template in `skills/meetings/references/meeting-note.md`. |
| Preferences | `Preferences.md` | Fixed. |
| Daily | `Daily/YYYY-MM-DD.md` | Local date of the run. |
| Weekly | `Weekly/YYYY-Www.md` | ISO week (Monday–Sunday) of the review. Written by `/administrator:weekly`. |
| Person | `People/<Display Name>.md` | Display name as Outlook gives it (`from` / `recipients[].name`), illegal characters replaced by `_`, trimmed. If no display name, the part of the SMTP address before `@`. |
| Attachments | `Attachments/<YYYY-MM-DD slug>/<filename>` | One subfolder per email note, same name as the note minus `.md`. |
| Follow-ups | `Follow-ups.md` | Fixed. |

### Slug rules (email notes)

What the server does with the subject:

1. Start with the subject. Empty subject → `(no subject)`.
2. Strip leading reply/forward prefixes, repeatedly, case-insensitive: `Re:`, `RE:`, `Fwd:`, `FW:`, `AW:`, `WG:`, `TR:`, `SV:` followed by optional spaces. `Re: Re: FW: Budget` → `Budget`.
3. Replace every character in `\ / : * ? " < > |` and control characters with `_`. Collapse runs of whitespace to one space.
4. Trim spaces and trailing dots (Windows does not allow a trailing `.`).
5. Cut to 60 characters, then trim again.
6. Result `""` → `(no subject)`.

### Filename collision

Same filename already present but with a different identity (different `internet_message_id` / `entry_id`): the server appends ` (2)`, ` (3)` before `.md`. Same identity: this is an update, not a new file — see "Append on existing".

## Email note template

```markdown
---
type: email
source: outlook
entry_id: "<exact EntryID from outlook_get_mail>"
internet_message_id: "<internet_message_id from outlook_get_mail, e.g. <abc123@mail.example.com>; empty string when Outlook has none>"
conversation_id: "<conversation_id from outlook_get_mail>"
subject: "<subject as received>"
from: jane.doe@example.com
from_name: Jane Doe
from_link: "[[People/Jane Doe]]"
to:
  - me@example.com
  - bob@example.com
cc:
  - carol@example.com
received: 2026-08-22T09:14:00+02:00
status: todo
has_attachments: true
attachments:
  - "[[Administrator/Attachments/2026-08-22 Budget Q3/Budget_Q3.xlsx|Budget_Q3.xlsx]]"
msg_file: "[[Administrator/Attachments/2026-08-22 Budget Q3/Budget Q3.msg|Budget Q3.msg]]"
created_by: administrator/0.1.0
---

# <Subject as received, untouched>

**From:** [[People/Jane Doe]] <jane.doe@example.com>
**To:** Hux Waitt <me@example.com>, Bob Lee <bob@example.com>
**Cc:** Carol Ng <carol@example.com>
**Received:** 2026-08-22 09:14

## Summary

<One line, 25 words or fewer. What the sender wants or tells, in plain words.>

## Action items

- [ ] <verb + object + by when, only if the email actually asks for it> — owner: me
- none            <- use this single line when the mail asks for nothing

## Body

<Body as plain text, trimmed: `body_trimmed` from outlook_get_mail(trim_quoted=true),
which stops before the first quoted reply and drops the signature. Keep line breaks.
For a thread note: one `### 2026-08-21 16:42 — Jane Doe` subsection per message, oldest first.>

## Attachments

- [[Administrator/Attachments/2026-08-22 Budget Q3/Budget Q3.msg|Budget Q3.msg]] (original message)
- [[Administrator/Attachments/2026-08-22 Budget Q3/Budget_Q3.xlsx|Budget_Q3.xlsx]] (180 KB)
- image001.png (4 KB, inline image, not exported)
```

Rules:

- Required keys (the server refuses the write without them): `type`, `source`, `internet_message_id`, `entry_id`, `conversation_id`, `subject`, `from`, `from_name`, `from_link`, `to`, `cc`, `received`, `status`, `created_by`. Pass `cc: []` when there is no Cc.
- `status`: `todo` = user must do something; `waiting` = user is waiting on someone; `done` = nothing left; `fyi` = read only. Default for a freshly saved mail with an action item is `todo`, without one `fyi`; `waiting` when the mail is from the user's own address (`outlook_whoami`) and asks someone else for something.
- `has_attachments`, `attachments`, `msg_file` are optional — omit the key when empty. `has_attachments: true` whenever `get_mail` lists attachments, exported or not. `attachments` and `msg_file` are present only when the export happened before the note was written (the save skill asks first); exports done later are linked in an `## Update` section.
- `to` / `cc` list SMTP addresses from `recipients[]` where `type == "to"` / `"cc"`. Use the raw `to` / `cc` strings only when `recipients` is empty.
- The `**Cc:**` line and the `## Attachments` section are only present when there is something to list. Attachments that were not exported appear as plain text with "(not exported)".
- Only the sender gets a person note and a wikilink. Other recipients are plain text on the `**To:**` / `**Cc:**` lines.
- The `## Body` section is the record. Never edit it after the note exists; updates go below it.

## Daily note template

```markdown
---
type: daily
source: outlook
date: 2026-08-22
folder: inbox
since: 2026-08-21T18:02:00+02:00
inbox_checked: 2026-08-22T08:31:10+02:00
mails_seen: 23
status: todo
created_by: administrator/0.1.0
---

# 2026-08-22

## Inbox (since 2026-08-21T18:02:00+02:00)

| # | Label | From | Subject | Received | Why | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | act | Jane Doe | Budget Q3 | 09:14 | Asks for final Q3 numbers by Friday | [[Emails/2026-08-22 Budget Q3]] <!-- entry_id: 00000000AA… --> |
| 2 | reply | Bob Lee | Re: offsite dates | 08:40 | Asks which week works for you | <!-- entry_id: 00000000AB… --> |
| 3 | waiting | Carol Ng | Contract draft | 2026-08-21 17:55 | Will send the draft next week | <!-- entry_id: 00000000AC… --> |
| 4 | fyi | IT Service | Maintenance window Saturday | 07:10 | Announcement, nothing to do | <!-- entry_id: 00000000AD… --> |
| 5 | noise | Newsletter | Weekly roundup | 06:00 | Newsletter | <!-- entry_id: 00000000AE… --> |

Labels: **act** (do something), **reply** (answer), **waiting** (they owe me), **fyi** (read), **noise** (ignore).

## To do

- [ ] act — Budget Q3 (Jane Doe) — [[Emails/2026-08-22 Budget Q3]]
- [ ] reply — Re: offsite dates (Bob Lee)

## Waiting on

- Carol Ng — Contract draft (since 2026-08-21) → also in [[Follow-ups]]

## Calendar

| Start | End | Subject | Location | Organizer |
| --- | --- | --- | --- | --- |
| 09:30 | 10:00 | Stand-up | Teams | Bob Lee <!-- occurrence_key: 0400…|2026-08-22T09:30:00+02:00 --> |
| 13:00 | 14:00 | Budget review with Jane | Room 4 | Jane Doe <!-- occurrence_key: 0400…|2026-08-22T13:00:00+02:00 --> |

## Watch out

- Clash: Budget review with Jane (13:00–14:00) overlaps Dentist (13:30–14:30)
- No prep note: Budget review with Jane

## Update 2026-08-22T15:41:00+02:00

<Rows and items that were new on a second run; never repeat an entry_id already in the file.>
```

Rules:

- The whole note is rendered by `vault_write_daily`; the model passes labels, not rows. Required keys: `type`, `date`, `folder`, `since`, `inbox_checked`, `mails_seen`, `status`, `created_by` (`tokens_used` optional). `date` = the note's date; `folder` = the folder read; `since` = the lower bound used on the first run; `inbox_checked` = the time of the most recent `outlook_list_mails` call (the next run's `since`); `mails_seen` = count of the first run. The server replaces only `inbox_checked`, `mails_seen` and `status`.
- Table sorted `act`, `reply`, `waiting`, `fyi`, `noise`, newest first within a label. `Received` is `HH:MM` for today's mail, `YYYY-MM-DD HH:MM` otherwise. `Why` is one short line (under 80 characters).
- Every row ends with `<!-- entry_id: … -->` inside the `Note` cell (hidden in Obsidian reading view). That is the dedupe key for a second run.
- The `Note` column links to the email note only when one exists (match on `internet_message_id`, else `entry_id`). No link = not saved.
- `## To do` holds `act` and `reply` items only. `## Waiting on` mirrors what went into `Follow-ups.md`.
- `## Calendar` and `## Watch out` are only written by `/administrator:daily` (from the `events` passed to `vault_write_daily`); `/administrator:inbox` leaves them out. Times from `outlook_list_events`, `HH:MM` local. All-day events show `all day` in both time columns. Calendar rows end with `<!-- occurrence_key: … -->` inside the last cell (written by `daily`, or by `schedule` through `vault_append_row`). `## Watch out` lists clashes (overlapping ranges) and meetings with no prep note (worked out in code; all-day events exempt), then any `watch_out` bullets the model passed. Offer `/administrator:prep` for those.
- Batch actions are offered in the chat, not written to the note. When the user says yes and the action runs, a one-line `vault_write(mode="append")` records it: `Done <ISO timestamp>: marked 2 as read`.
- When the folder is not the inbox, the heading reads `## Inbox (Inbox/Invoices, since …)`.

## Person note template

```markdown
---
type: person
source: outlook
name: Jane Doe
email: jane.doe@example.com
company: Example GmbH
last_contact: 2026-08-22T09:14:00+02:00
aliases:
  - Doe, Jane
  - jdoe@example.com
created_by: administrator/0.1.0
---

# Jane Doe

jane.doe@example.com · Example GmbH

## Emails

- 2026-08-22 — [[Emails/2026-08-22 Budget Q3]] (todo)

## Meetings

- 2026-08-25 — [[Meetings/2026-08-25 1300 Supplier sync]] (upcoming)
```

Rules:

- Required keys: `type`, `name`, `email`, `aliases`, `last_contact`, `created_by`.
- `company` is optional: take it from `outlook_search_contacts` when the address matches a directory entry, otherwise omit the key. Do not guess it from the domain.
- `aliases` holds other display names and other SMTP addresses seen for the same person. Start with an empty list `aliases: []` when there are none. `vault_find("person", <address>)` matches `email` and `aliases`, so one person never gets two notes.
- `last_contact` = the newest `received` among linked emails or the `start` of the newest held meeting, whichever is later. A stub created by `prep` or `schedule` with no email yet has `last_contact: ""`.
- `## Emails` and `## Meetings` are written at creation. Later email and meeting lines land under the `## Update <ISO>` headings the server adds (one line per append), because the server never edits existing text. `last_contact` is replaced and `aliases` merged on append; nothing else changes.
- Anything the user writes below these lists (a `## Notes` section, for instance) is left alone.
- A `Voice with this person:` block (six bullets, `skills/draft/references/voice.md`) written by the user, or by an earlier plugin version, is honoured by `draft`; the plugin no longer writes it. `draft` never creates a person note.

## Meeting note

One note per calendar event occurrence, written by the `meetings` skill (`/administrator:prep`, `/administrator:notes`) or by the `schedule` skill when it books a meeting — all three use the one template in `skills/meetings/references/meeting-note.md`. Identity = `occurrence_key`. Frontmatter: `type: meeting`, `source: outlook`, `entry_id` (optional), `global_id`, `occurrence_key`, `subject`, `start`, `end`, `location`, `organizer` (SMTP), `organizer_link`, `attendees` (SMTP list), `attendee_links`, `is_recurring`, `status: upcoming | held | cancelled`, `created_by`. Body sections in fixed order: `## Prep` (written by `prep`, or a one-line placeholder by `schedule` / `notes`), `## Notes`, `## Action items`, `## Waiting on`, `## Related emails`, `## Transcript` (only when a transcript was pasted), `## Minutes draft` (optional). Placeholders are never replaced; later prep runs, note drops, action items and the minutes draft live under `## Update` headings with `###` sub-headings. A moved meeting keeps its filename and frontmatter; the move is an `## Update` line. Template, Prep layout, and append rules: `skills/meetings/references/meeting-note.md`.

## Weekly note

One note per ISO week, written by `/administrator:weekly` (`skills/review/SKILL.md`). Identity = `week`. Frontmatter:

```markdown
---
type: weekly
source: administrator
week: 2026-W34
start: 2026-08-17
end: 2026-08-23
generated: 2026-08-22T10:20:00+02:00
created_by: administrator/0.1.0
---
```

Required keys: `type`, `week`, `start`, `end`, `created_by`. Body sections in fixed order: `## Still open from inbox`, `## Waiting on`, `## Meetings held`, `## Next week`, `## People going quiet`, and optionally `## Notes` (3–6 bullets written by the model; the other five are laid out from `vault_weekly_facts` and `outlook_list_events`). A second run on the same week appends `## Update <ISO>` with a fresh set of sections; the earlier text stays. Nothing in a weekly note is edited in place.

## Follow-ups.md

```markdown
---
type: followups
source: outlook
created_by: administrator/0.1.0
---

# Follow-ups

Things I am waiting on. One row per thread. Move a row to Done when it is closed.

## Open

| Since | Who | What | Email | Last checked |
| --- | --- | --- | --- | --- |
| 2026-08-21 | [[People/Carol Ng]] | Contract draft | [[Emails/2026-08-21 Contract draft]] | 2026-08-22 <!-- entry_id: 00000000AC… --> |

## Done

| Since | Who | What | Email | Closed |
| --- | --- | --- | --- | --- |
```

Row rules:

- `Since` = date of the mail that started the wait. `Who` = wikilink to the person note when one exists, else the display name. `What` = ten words or fewer (usually the subject). `Email` = wikilink to the email note, empty if not saved. `Last checked` = date of the run that wrote the row, followed by the hidden key comment `vault_append_row` adds.
- A row is identified by the hidden key comment (`entry_id`, `internet_message_id` for rows written by `followups` from the user's own sent mail, or `occurrence_key`), else by the `Email` link, else by `Who` + `What`. Existing row (same key) → left as it is (`vault_append_row` answers `duplicate`). New → append to the bottom of `## Open`.
- Closing a row (user says it is done, or a reply from `Who` on the same subject appears): `vault_move_row(..., "Open", "Done", key, set_last_cell=<date>)` cuts the row and sets `Closed`. Never delete rows. `inbox`, `save`, `notes`, `schedule` and `followups` write rows; `inbox` and `followups` close them (`notes` closes a meeting row when the user's notes say it is done).
- Rows created from a meeting (`/administrator:notes`): `Since` = meeting date, `Email` = `[[Meetings/…]]` link, key `<occurrence_key> # <What>` with `key_label="occurrence_key"` (one meeting can create several rows). Rows created by a proposed-times draft (`/administrator:schedule`): `What` = "pick a time — <subject>", `Email` empty, key `<address> # pick a time — <subject>` with `key_label="proposal"`.

## Preferences.md

`<vault>/Administrator/Preferences.md` — one file, owned by the user, read by the `schedule` skill once per session (again only when the user says they changed it). Created by `vault_init` (`/administrator:setup` asks for work hours; other commands use the defaults 09:00–17:00, buffer 15, `no_meeting_blocks: ["Fri 13:00-<work_end>"]`). `vault_init(overwrite=true)` is the only thing that ever rewrites it. Frontmatter keys: `type: preferences`, `source: administrator`, `work_start`, `work_end` (`"HH:MM"`, quoted), `timezone` (a note only), `buffer_minutes`, `no_meeting_blocks` (list of `"Fri 13:00-17:00"`), `max_meetings_per_day`, `default_duration`, `default_location`, `preferred_days` (list of `Mon`…`Sun`), `created_by`. A missing or malformed key falls back to the default for that key (`skills/schedule/references/preferences.md`). The body may hold a `## Voice` section — optional, plain bullets, written by the user only, read by the `draft` skill and by nudges and minutes (`skills/draft/references/voice.md`).

## Rules.md

`<vault>/Administrator/Rules.md` — `type: rules`, `source: administrator`, created by `vault_init`, never overwritten, edited by the user. Three sections: `## Labels` (`| Match | Field | Label |`), `## Never save` (`| Match | Field |`), `## Fyi senders` (a list of addresses). See "Workflow helpers" above for how `vault_rules` and `vault_inbox_prepare` apply it.

## Append on existing

A write for an identity that exists appends `## Update <ISO>` plus your body; nothing above it changes. Skip the call entirely when nothing changed — a re-run that finds nothing new writes nothing (`vault_write_daily` answers `action: unchanged` itself).

## Worked example 1 — saving one email

User: `/administrator:save budget q3 jane`

1. `outlook_search_mails(query="budget q3 jane", limit=5, fields=["entry_id","from","subject","received","preview"], preview_chars=80, response_format="json")` → one hit, `entry_id` `00000000AA…`.
2. `outlook_get_mail(entry_id="00000000AA…", trim_quoted=true, fields=["entry_id","internet_message_id","conversation_id","subject","from","from_address","to","cc","recipients","received","attachments","body_trimmed","body_truncated"], response_format="json")` → `subject: "Re: Budget Q3"`, `from: "Jane Doe"`, `from_address: "jane.doe@example.com"`, `internet_message_id: "<7f3a9c@example.com>"`, `conversation_id: "CAE…"`, `received: "2026-08-22T09:14:00+02:00"`, `recipients: [{name:"Hux Waitt", address:"me@example.com", type:"to"}]`, one attachment `Budget_Q3.xlsx`, `body_trimmed` without the quoted earlier mail.
3. `vault_find("email", {"internet_message_id": "<7f3a9c@example.com>", "entry_id": "00000000AA…"}, fields=["status","msg_file","attachments"])` → `found: false`; `vault_find("person", {"email": "jane.doe@example.com"}, fields=["name"])` → `found: false`.
4. Ask: "Export the original .msg and Budget_Q3.xlsx to Administrator/Attachments/2026-08-22 Budget Q3/?" Only on yes: `outlook_save_mail_as` and `outlook_save_attachments`.
5. `vault_save_email(mail=<the get_mail JSON>, summary="Jane asks for the final Q3 numbers by Friday so she can close the forecast.", action_items=["Send Q3 numbers to Jane by 2026-08-29 — owner: me"], attachments_saved=[…], msg_file=…, self_addresses=["me@example.com"], created_by="administrator/0.1.0")` → `{"path": "Administrator/Emails/2026-08-22 Budget Q3.md", "action": "created", "status": "todo", "person_path": "Administrator/People/Jane Doe.md", "person_action": "created", "followup_added": false}`. The note and person note it wrote look like this (the model never types them):

```yaml
type: email
source: outlook
entry_id: 00000000AA…
internet_message_id: <7f3a9c@example.com>
conversation_id: CAE…
subject: Re: Budget Q3
from: jane.doe@example.com
from_name: Jane Doe
from_link: "[[People/Jane Doe]]"
to:
  - me@example.com
cc: []
received: 2026-08-22T09:14:00+02:00
status: todo
has_attachments: true
created_by: administrator/0.1.0
```

```markdown
# Re: Budget Q3

**From:** [[People/Jane Doe]] <jane.doe@example.com>
**To:** Hux Waitt <me@example.com>
**Received:** 2026-08-22 09:14

## Summary

Jane asks for the final Q3 numbers by Friday so she can close the forecast.

## Action items

- [ ] Send Q3 numbers to Jane by 2026-08-29 — owner: me

## Body

Hi,

could you send me the final Q3 numbers by Friday? I need them to close the forecast.

Thanks
Jane
```

   The person note is the template above with `last_contact: 2026-08-22T09:14:00+02:00`, `aliases: []` and one `## Emails` line.

6. Report: "Saved Emails/2026-08-22 Budget Q3.md (todo) and created People/Jane Doe.md." plus the `obsidian://open` link.

## Worked example 2 — running inbox twice on one day

Both runs are one `vault_inbox_prepare` plus one `vault_write_daily` call; the model passes only `[{entry_id, label, reason}]`. The second run finds the earlier rows by their `<!-- entry_id: … -->` comments in code and appends only what is new under `## Update <ISO>`, replacing `inbox_checked` in the frontmatter. Nothing new → `action: unchanged`, nothing written. A reply from the `Who` of an open Follow-ups row is the one case the model still closes by hand: `vault_read("Administrator/Follow-ups.md")` once, then `vault_move_row("Administrator/Follow-ups.md", "Open", "Done", "00000000AC…", set_last_cell="2026-08-22")`. Call by call: `skills/inbox/references/examples.md`.
