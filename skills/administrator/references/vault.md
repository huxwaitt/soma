# Vault reference — note templates and rules

Everything the plugin writes goes under `<vault>/Administrator/` where `<vault>` = `ADMINISTRATOR_VAULT`. Notes are plain markdown with YAML frontmatter and must render in vanilla Obsidian.

Conventions used in every template:

- Dates in frontmatter are ISO-8601 with the offset Outlook returned (`2026-08-22T09:14:00+02:00`). Never convert time zones.
- Strings that may contain `:`, `#`, `[`, or quotes are double-quoted. `entry_id`, `internet_message_id`, `conversation_id` are always quoted.
- Lists are YAML block lists, one item per line.
- Wikilinks in frontmatter are quoted: `from_link: "[[People/Jane Doe]]"`.
- `created_by: administrator/0.0.1` on every note.

## Filenames

| Note | Path | Rule |
| --- | --- | --- |
| Email | `Emails/YYYY-MM-DD <slug>.md` | Date = `received` date (local). Slug from subject, see below. |
| Daily | `Daily/YYYY-MM-DD.md` | Local date of the run. |
| Person | `People/<Display Name>.md` | Display name as Outlook gives it (`from` / `recipients[].name`), illegal characters replaced by `_`, trimmed. If no display name, use the part of the SMTP address before `@`. |
| Attachments | `Attachments/<YYYY-MM-DD slug>/<filename>` | One subfolder per email note, same name as the note minus `.md`. |
| Follow-ups | `Follow-ups.md` | Fixed. |

### Slug rules (email notes)

1. Start with the subject. Empty subject → `(no subject)`.
2. Strip leading reply/forward prefixes, repeatedly, case-insensitive: `Re:`, `RE:`, `Fwd:`, `FW:`, `AW:`, `WG:`, `TR:`, `SV:` followed by optional spaces. `Re: Re: FW: Budget` → `Budget`.
3. Replace every character in `\ / : * ? " < > |` and control characters with `_`. Collapse runs of whitespace to one space.
4. Trim spaces and trailing dots (Windows does not allow a trailing `.`).
5. Cut to 60 characters, then trim again.
6. Result `""` → `(no subject)`.

### Filename collision

Same filename already present but with a different identity (different `internet_message_id` / `entry_id`): append ` (2)`, ` (3)` before `.md`. Same identity: this is an update, not a new file — see "Append on existing".

## Email note template

```markdown
---
type: email
source: outlook
entry_id: "<exact EntryID from outlook_get_mail>"
internet_message_id: "<internet_message_id from outlook_get_mail, e.g. <abc123@mail.example.com>; empty string when Outlook has none>"
conversation_id: "<conversation_id from outlook_get_mail>"
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
created_by: administrator/0.0.1
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

<Body as plain text, trimmed: stop before the first quoted reply
("From: ...", "-----Original Message-----", "On ... wrote:", "> ").
Drop the signature block when it is obvious. Keep line breaks.
For a thread note: one `### 2026-08-21 16:42 — Jane Doe` subsection per message, oldest first.>

## Attachments

- [[Administrator/Attachments/2026-08-22 Budget Q3/Budget Q3.msg|Budget Q3.msg]] (original message)
- [[Administrator/Attachments/2026-08-22 Budget Q3/Budget_Q3.xlsx|Budget_Q3.xlsx]] (180 KB)
- image001.png (4 KB, inline image, not exported)
```

Rules:

- `status`: `todo` = user must do something; `waiting` = user is waiting on someone; `done` = nothing left; `fyi` = read only. Default for a freshly saved mail with an action item is `todo`, without one `fyi`; `waiting` when the mail is from the user's own address (`outlook_whoami`) and asks someone else for something.
- `cc`, `has_attachments`, `attachments`, `msg_file` are optional — omit the key when empty. `has_attachments: true` whenever `get_mail` lists attachments, exported or not.
- `to` / `cc` list SMTP addresses from `recipients[]` where `type == "to"` / `"cc"`. Use the raw `to` / `cc` strings only when `recipients` is empty.
- The `**Cc:**` line and the `## Attachments` section are only present when there is something to list. Attachments that were not exported appear as plain text with "(not exported)".
- Only the sender gets a person note and a wikilink. Other recipients are plain text on the `**To:**` / `**Cc:**` lines.
- The `## Body` section is the record. Never edit it after the note exists; add updates below it.

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
created_by: administrator/0.0.1
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
| 09:30 | 10:00 | Stand-up | Teams | Bob Lee |
| 13:00 | 14:00 | Budget review with Jane | Room 4 | Jane Doe |

## Watch out

- Clash: Budget review with Jane (13:00–14:00) overlaps Dentist (13:30–14:30)
- No prep note: Budget review with Jane

## Suggested Outlook actions (not done)

- Mark 2 fyi/noise as read
- Move "Weekly roundup" to Inbox/Newsletters

## Update 2026-08-22T15:41:00+02:00

<Rows and items that were new on a second run; never repeat an entry_id already in the file.>
```

Rules:

- Frontmatter: `date` = the note's date; `folder` = the folder read; `since` = the lower bound used on the first run; `inbox_checked` = the time of the most recent `outlook_list_mails` call (the next run's `since`); `mails_seen` = count of the first run. Only `inbox_checked` and `status` are ever changed on an existing daily note.
- Table sorted `act`, `reply`, `waiting`, `fyi`, `noise`, newest first within a label. `Received` is `HH:MM` for today's mail, `YYYY-MM-DD HH:MM` otherwise. `Why` is one short line (under 80 characters).
- Every row ends with `<!-- entry_id: … -->` inside the `Note` cell (hidden in Obsidian reading view). That is the dedupe key for a second run.
- The `Note` column links to the email note only when one exists (match on `internet_message_id`, else `entry_id`). No link = not saved.
- `## To do` holds `act` and `reply` items only. `## Waiting on` mirrors what went into `Follow-ups.md`.
- `## Calendar` and `## Watch out` are only written by `/administrator:daily`; `/administrator:inbox` leaves them out. Times from `outlook_list_events`, `HH:MM` local. All-day events show `all day` in both time columns. `## Watch out` lists clashes (overlapping ranges) and meetings with no prep note (no file under `Emails/` or `Daily/` mentions the subject, case-insensitive; all-day events exempt).
- `## Suggested Outlook actions (not done)` lists what was offered. When the user says yes and the action runs, append a line `Done <ISO timestamp>: marked 2 as read` under an `## Update` section.
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
created_by: administrator/0.0.1
---

# Jane Doe

jane.doe@example.com · Example GmbH

## Emails

- 2026-08-22 — [[Emails/2026-08-22 Budget Q3]] (todo)
```

Rules:

- `company` is optional: take it from `outlook_search_contacts` when the address matches a directory entry, otherwise omit the key. Do not guess it from the domain.
- `aliases` holds other display names and other SMTP addresses seen for the same person. Start with an empty list `aliases: []` when there are none.
- `last_contact` = the newest `received` among linked emails. This is the one frontmatter key on a person note the plugin updates in place.
- `## Emails` is a list; append one line per new email note, newest at the bottom. Never remove lines.
- Anything the user writes below `## Emails` (a `## Notes` section, for instance) is left alone.

## Follow-ups.md

```markdown
---
type: followups
source: outlook
created_by: administrator/0.0.1
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

- `Since` = date of the mail that started the wait. `Who` = wikilink to the person note when one exists, else the display name. `What` = ten words or fewer (usually the subject). `Email` = wikilink to the email note, empty if not saved. `Last checked` = date of the run that last saw the thread still open, followed by `<!-- entry_id: … -->` of the newest mail in the thread.
- A row is identified by the `entry_id` comment, else by the `Email` link, else by `Who` + `What`. Existing row → update `Last checked` only. New → append to the bottom of `## Open`.
- Closing a row (user says it is done, or a reply from `Who` on the same subject appears in the inbox): cut the row from `## Open`, paste into `## Done` with `Closed` = today. Never delete rows. Both `inbox` and `save` write rows; only `inbox` closes them.

## Append on existing

Applies to email notes, daily notes, and person notes alike:

1. Find the existing note by identity (email: `internet_message_id`, else `entry_id`; daily: date; person: filename, else `email`/`aliases`).
2. Read it. Do not change anything above the first `## Update` heading, except: `status` (email, daily), `inbox_checked` (daily) and `last_contact` (person) may be replaced in the frontmatter; `## Emails` (person) and `## Open` / `## Done` tables (follow-ups) may receive new rows; `aliases` (person) may receive new items.
3. Append at the end of the file:

```markdown
## Update 2026-08-23T10:05:00+02:00

- status: todo → waiting
- Saved attachment [[Administrator/Attachments/2026-08-22 Budget Q3/Budget_Q3_v2.xlsx|Budget_Q3_v2.xlsx]]
- Moved to Inbox/Projects/Budget (new entry_id 00000000AB...; old 00000000AA...)
```

4. Skip the update section entirely when nothing changed. A re-run that finds nothing new writes nothing.

## Worked example 1 — saving one email

User: `/administrator:save budget q3 jane`

1. `outlook_search_mails(query="budget q3 jane", response_format="json")` → one hit, `entry_id` `00000000AA…`.
2. `outlook_get_mail(entry_id="00000000AA…", response_format="json")` → `subject: "Re: Budget Q3"`, `from: "Jane Doe"`, `from_address: "jane.doe@example.com"`, `internet_message_id: "<7f3a9c@example.com>"`, `conversation_id: "CAE…"`, `received: "2026-08-22T09:14:00+02:00"`, `recipients: [{name:"Hux Waitt", address:"me@example.com", type:"to"}]`, one attachment `Budget_Q3.xlsx`, body ends with a quoted earlier mail.
3. Slug: `Re: Budget Q3` → `Budget Q3`. Filename `Emails/2026-08-22 Budget Q3.md`.
4. Grep `Administrator/Emails/` for `internet_message_id: "<7f3a9c@example.com>"` → no match. Filename free.
5. Write:

```markdown
---
type: email
source: outlook
entry_id: "00000000AA…"
internet_message_id: "<7f3a9c@example.com>"
conversation_id: "CAE…"
from: jane.doe@example.com
from_name: Jane Doe
from_link: "[[People/Jane Doe]]"
to:
  - me@example.com
received: 2026-08-22T09:14:00+02:00
status: todo
has_attachments: true
created_by: administrator/0.0.1
---

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

6. `People/Jane Doe.md` does not exist and no `People/` note has `jane.doe@example.com` → create from the person template with `aliases: []` and one line under `## Emails`.
7. Ask: "Save the .msg and Budget_Q3.xlsx to Administrator/Attachments/2026-08-22 Budget Q3/?" Only on yes: `outlook_save_mail_as` and `outlook_save_attachments`, then add `attachments` / `msg_file` keys — this is the one case where keys are added to existing frontmatter, because the note was created seconds earlier in the same run.
8. Report: "Saved Emails/2026-08-22 Budget Q3.md (todo) and created People/Jane Doe.md."

## Worked example 2 — running inbox twice on one day

First run at 08:30: `Daily/2026-08-22.md` does not exist. `since` = `inbox_checked` from `Daily/2026-08-21.md`. `outlook_list_mails(unread_only=true, since=<that>, limit=100, response_format="json")` returns 23 mails. Write the daily note from the template, 23 rows, `mails_seen: 23`, `inbox_checked` = the time of the call. Two `waiting` rows → two new rows in `Follow-ups.md` under `## Open`. Offer "Mark 9 fyi/noise as read?" — user does not answer; nothing runs.

Second run at 15:40: `Daily/2026-08-22.md` exists. Read it, collect the `entry_id`s already listed (the `<!-- entry_id: … -->` comments). Call `outlook_list_mails` again with `since` = the note's `inbox_checked`. 3 new results (a mail that was already listed and is still unread would also come back if the user widened `since`; skip anything whose `entry_id` is already in the file). Append:

```markdown
## Update 2026-08-22T15:40:00+02:00

### Inbox (since 2026-08-22T08:31:10+02:00)

| # | Label | From | Subject | Received | Why | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 24 | reply | Bob Lee | Re: offsite dates | 14:02 | Proposes week 36, asks if that works | <!-- entry_id: 00000000AF… --> |
| 25 | noise | Vendor | Webinar invite | 13:30 | Marketing | <!-- entry_id: 00000000B0… --> |
| 26 | fyi | Carol Ng | Re: Contract draft | 15:12 | Sent the draft; wait is over | <!-- entry_id: 00000000B1… --> |

- Carol Ng replied on "Contract draft" → Follow-ups row moved to Done.
- Offered: mark 1 noise as read — not done.
```

Then set `inbox_checked: 2026-08-22T15:40:00+02:00` in the frontmatter. `Follow-ups.md`: the Carol Ng row moves from `## Open` to `## Done` with `Closed: 2026-08-22`. Frontmatter `mails_seen` stays 23. No second daily file, no repeated rows.
