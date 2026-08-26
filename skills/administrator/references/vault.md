# Vault reference — note templates and rules

Everything the plugin writes goes under `<vault>/Administrator/` where `<vault>` = `ADMINISTRATOR_VAULT`. Notes are plain markdown with YAML frontmatter and must render in vanilla Obsidian. This page is the schema: what each note looks like and what each key means. The `vault` MCP server (`administrator-vault`) enforces it; skills pass a frontmatter object and a markdown body to `vault_write` and never touch files themselves.

Conventions the server applies:

- Dates in frontmatter are ISO-8601 with the offset Outlook returned (`2026-08-22T09:14:00+02:00`). Never convert time zones.
- Quoting is the server's job: `entry_id`, `internet_message_id`, `conversation_id`, `global_id`, `occurrence_key`, `subject`, `location`, `msg_file` are always quoted; plain SMTP addresses and `administrator/0.4.0` stay unquoted. Pass raw values.
- Lists are YAML block lists; pass arrays (`[]` when empty).
- Wikilinks in frontmatter are quoted: `from_link: "[[Wiki/People/Jane Doe]]"`.
- `created_by: administrator/0.4.0` on every note (pass it; the server fills in only `type`).

## Writing notes: the `vault_*` tools

The rules on this page are enforced by the `vault` MCP server (`administrator-vault`); skills call its tools instead of writing files. Pass the frontmatter as an object and the body as markdown (no frontmatter fences); the server picks the filename, checks the required keys, quotes what must be quoted, and refuses a second note for an identity that exists.

| Need | Call |
| --- | --- |
| Is this mail / meeting / person already in the vault? | `vault_find(type, identity)` — identity `{"internet_message_id": …, "entry_id": …}`, `{"occurrence_key": …, "global_id": …}`, an SMTP address, a date, or a week |
| Write or update a note | `vault_write(type, frontmatter, body, mode="upsert")` — returns `action: created` or `appended` plus the path |
| A row in a daily table, `Rules.md` or a Time-blocks `## Held` table | `vault_row(action="append", path, section, row, dedupe_key=<entry_id>)` (`key_label="occurrence_key"` for calendar and held rows). `Follow-ups.md` is generated and refuses rows. |
| Something somebody owes: open it, move it, close it | `vault_wiki_write(pages=[{"path": <the page it is about>, "ops": [{"op": "open" \| "reschedule" \| "done", …}]}])` — see "Follow-ups.md" below |
| Read a note, list notes | `vault_read(path)`, `vault_find(type, since=…)` (no `identity` = list) |
| Which daily note was last written? | `vault_find("daily", limit=1, fields=["date", "inbox_checked"])` |
| Do the mechanical part of a workflow in code | `vault_rules`, `vault_inbox_prepare`, `vault_write_daily`, `vault_save`, `vault_prep_context`, `vault_weekly_facts` — see "Workflow helpers" below |
| Ask the wiki a question, read or change a page | `vault_wiki_search`, `vault_wiki_read`, `vault_wiki_write`, `vault_wiki_keep` — see "Wiki" below and `skills/wiki/SKILL.md` |
| Save a Teams chat as a day record, read or move the "last collected" stamps, list notes changed since a time | `vault_save(kind="chat", chat, messages, self_names)`, `vault_collect(action, source, at, payload, since)` (`read`, `advance`, `tokens` for what a run predicted against what it cost, and `changed` for the notes modified since a time) — see "Chat note" below and `skills/collect-information/SKILL.md` |
| Read the months before the "last collected" stamps into the wiki, one window of days at a time | `vault_load_history(action="status" \| "plan" \| "next" \| "done", since, batch, payload, reset)` — see "Loading the past" below and `skills/load-history/SKILL.md` |
| Plan the week's focus and admin blocks, write the plan note once the appointments exist, count where a week's hours went | `vault_time_block(action="plan" \| "write" \| "audit", week, events, today, blocks)`, `vault_priorities_write(action, lines)` (`candidates` for a suggestion, `write` only with lines the user confirmed) — see "Time-block note" and "Priorities.md" below and `skills/time-block/SKILL.md` |

On `append` the server only changes `status`, `last_contact`, `inbox_checked`, `mails_seen` and adds new `aliases` (and `vault_wiki_write` replaces `wiki`); every other frontmatter key and all existing body text stay as they are. `append` still checks the required keys, so pass the frontmatter `vault_find` returned with just the intended key changed. Use `created_by: administrator/0.4.0` in every frontmatter you pass.

`dedupe_key` for a daily calendar row and a Time-blocks `## Held` row is the `occurrence_key` with `key_label="occurrence_key"`; `Rules.md` lines take none. The server treats a row as a duplicate when the key value appears in any hidden comment anywhere in the file, whatever the label. (Open items are not rows: they carry their own `src` — an `internet_message_id`, an `entry_id`, `proposal:<address>` or `user` — and the same record twice on one page is refused as `duplicate`.)

A key or a cell may contain `|` (an `occurrence_key` always does); the server stores it as `\|` and gives it back unescaped, so pass raw values and compare against the raw key.

## Workflow helpers

These tools do the moving, comparing and formatting so the model only decides. They take the JSON the outlook tools returned and write through the same code as `vault_write` / `vault_row` / `vault_wiki_write`, so every rule on this page still holds. Pass `created_by="administrator/0.4.0"` to the ones that write.

- `vault_inbox_prepare(items, date)` — pass the `items[]` from `outlook_list_mails`. Back come only the mails not yet in any daily note of that ISO week and not matched by a never-save rule; each has `label` / `rule` filled when a rule decided. Read the `preview` only of the ones with `label: null`, then call `vault_write_daily(date, labels=[{entry_id, label, reason}], since, inbox_checked, events)` with your labels — items come from the cached list (`Attachments/_cache/inbox-<date>.json`), so do not pass them back. Pass `events` from `outlook_list_events` in `daily`; clashes and missing prep notes are worked out in code, `watch_out` is for anything else. A second run on the same day appends only new rows; `action: unchanged` means nothing was written. Items with no label from the model or a rule come back in `unlabelled` and are left out of the note.
- `vault_save(kind="email", mail, summary, action_items, attachments_saved, msg_file, self_addresses, company)` — `mail` is the `outlook_get_mail(trim_quoted=true)` JSON. The note, the person page and (for `waiting`) one open item owned by the counterpart — the first recipient of the user's own mail, else the sender — are written in one call; `status` defaults to `todo` with action items, `fyi` without, `waiting` when the mail is from one of `self_addresses` and has action items.
- `vault_prep_context(occurrence_key, global_id, attendees, subject)` replaces the `vault_find` / `vault_read` round trips of `prep` and `notes` and returns `wiki[]` (`path, type, title, status, lead, open[], facts[]`, at most 8 facts) for the attendees' pages and up to 3 topic pages matched on `subject` (taken from the existing note when empty); `vault_weekly_facts(week)` replaces those of `weekly`. Both are read-only.
- `vault_save(kind="transcript", meeting_path, transcript_path)` — write the transcript under `Attachments/<meeting>/` with the host's Write tool once, then call this; never paste the text back through `vault_write`.
- `Administrator/Rules.md` (`type: rules`, created by `vault_init`, never overwritten) holds the user's rules: `## Labels` table `| Match | Field | Label |`, `## Never save` table `| Match | Field |`, `## Fyi senders` list. `Field` is `from`, `domain`, `name` or `subject`; `Match` is a case-insensitive part of the value or a `*` / `?` pattern. Built-in rules (List-Unsubscribe, auto-replies, meeting responses, no-reply senders, people with `status: fyi`) run first. `vault_rules(action="get")` shows them; `vault_rules(action="match", items=<a mail listing>)` applies them and answers `results` per item plus `kept` (the mails left to read), `dropped: [{entry_id, why}]` for bulk mail and never-save rows, and `counts: {bulk, never_save, kept}` — `collect-information` and `load-history` call it before they read a preview. The plugin writes a line only through `vault_row(action="append", path="Administrator/Rules.md", section="Labels", row=[match, field, label])` after the user said yes to a proposal.
- `fields=[...]` on `vault_find` returns only those frontmatter keys.

## Filenames

The server builds these; listed so you can predict the path and the `Attachments/` folder name.

| Note | Path | Rule |
| --- | --- | --- |
| Email | `Emails/YYYY-MM-DD <slug>.md` | Date = `received` date (local). Slug from subject, see below. |
| Meeting | `Meetings/YYYY-MM-DD HHmm <slug>.md` | Date and time = `start` (local). Slug from `subject` with the email rule plus `Canceled:` / `Cancelled:` / `Abgesagt:` / `Updated:` / `Aktualisiert:` prefixes stripped. Full template in `skills/meetings/references/meeting-note.md`. |
| Chat | `Teams/YYYY-MM-DD <slug>.md` | One per Teams chat per day. Date = the messages' local date; slug from `chat_title` with the email rule (the chat id when the title is empty). Written by `vault_save(kind="chat")`. |
| Preferences | `Preferences.md` | Fixed. |
| Priorities | `Priorities.md` | Fixed. |
| Daily | `Daily/YYYY-MM-DD.md` | Local date of the run. |
| Weekly | `Weekly/YYYY-Www.md` | ISO week (Monday–Sunday) of the review. Written by `/administrator:weekly`. |
| Time-block | `Time-blocks/YYYY-Www.md` | ISO week of the plan. Written by `vault_time_block(action="write")` (`/administrator:time-block`); `## Held` rows added by `/administrator:collect-information`. |
| Person | `Wiki/People/<Display Name>.md` | Display name as Outlook gives it (`from` / `recipients[].name`), illegal characters replaced by `_`, trimmed. If no display name, the part of the SMTP address before `@`. |
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
from_link: "[[Wiki/People/Jane Doe]]"
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
created_by: administrator/0.4.0
---

# <Subject as received, untouched>

**From:** [[Wiki/People/Jane Doe]] <jane.doe@example.com>
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
- `wiki` (list of page links) is added by `vault_wiki_write` after the note exists; never pass it.
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
created_by: administrator/0.4.0
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

- Carol Ng — Contract draft (since 2026-08-21) → open item on their page

## Promised

- Send the signed contract — due 2026-08-26 — [[Wiki/Topics/acme-supplier-contract]]

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
- `## To do` holds `act` and `reply` items only. `## Waiting on` names the open item each `waiting` mail opened on the sender's page. `## Promised` is written on the first run of the day: the user's own open items due within seven days, `- <what> — due <date> — [[<page>]]`, or `- none`.
- `## Calendar` and `## Watch out` are only written by `/administrator:daily` (from the `events` passed to `vault_write_daily`); `/administrator:inbox` leaves them out. Times from `outlook_list_events`, `HH:MM` local. All-day events show `all day` in both time columns. Calendar rows end with `<!-- occurrence_key: … -->` inside the last cell (written by `daily`, or by `schedule` through `vault_row`). `## Watch out` lists clashes (overlapping ranges) and meetings with no prep note (worked out in code; all-day events exempt), then any `watch_out` bullets the model passed. Offer `/administrator:prep` for those.
- Batch actions are offered in the chat, not written to the note. When the user says yes and the action runs, a one-line `vault_write(mode="append")` records it: `Done <ISO timestamp>: marked 2 as read`.
- When the folder is not the inbox, the heading reads `## Inbox (Inbox/Invoices, since …)`.

## Person note (a wiki page)

People live in the wiki: `Wiki/People/<Display Name>.md`, `type: person`, following the page contract in `skills/wiki/references/wiki.md` (lead, `## Facts`, `## Topics`, `## Open`, `## Records`, `## Related`, `## History`, `## Notes`). Identity = `email`; `vault_find("person", <address>)` matches `email` and `aliases`, so one person never gets two pages. Extra frontmatter for this type: `name`, `email`, `org` (text; from `outlook_search_contacts` when the address matches a directory entry, never guessed from the domain), `last_contact` (code: newest `received` among linked emails or `start` of the newest held meeting; `""` on a stub from `prep` / `schedule`), `aliases` (other display names and addresses, merged by code, never removed).

- `vault_save`, `prep` and `schedule` create the page as `status: draft` with a one-line lead `<name> (<email>) — <org>.` and the record's `## Records` line; the ingest step of `save` / `notes` writes the real lead and the role facts through `vault_wiki_write`. `vault_write("person", frontmatter, body, mode)` is handled by the wiki: `create` writes that draft page, `append` merges `aliases`, moves `last_contact` forward and replaces `status` when given; in both modes the body's `- <date> — [[record]]` lines become `## Records` lines (a trailing `(held)` / `(done)` status is dropped) and any other body text is dropped. No `## Update` heading is ever added to a person page.
- Everything under `## Notes` belongs to the user. A `Voice with this person:` block written by the user (or kept there by migration) is honoured by `draft`; the plugin never writes it. `draft` never creates a person page.
- A vault from 0.1.0 keeps its notes in `Administrator/People/` until `/administrator:setup` runs `vault_wiki_keep(action="migrate")` (dry run first, then on a yes): the files move, old `People/…` links in every record become `[[Wiki/People/…]]`, and the old `## Emails` / `## Meetings` lines become `## Records`.

## The `wiki` key on records

`vault_wiki_write` adds one replaceable list key to the email, meeting or chat note it ingested (`vault_save(kind="chat")` sets it too, for the person pages of the senders it matched): `wiki: ["[[Wiki/Topics/q3-budget]]", "[[Wiki/People/Jane Doe]]"]`. It is the only frontmatter key on a record the wiki writes, it is rewritten (not appended) on a second ingest, and it is what `prep`, `find`, the Bases views and lint check 11 ("records never ingested") read. Ask for it with `fields=["wiki"]` on `vault_find`; never set it through `vault_write`.

## Wiki

`Administrator/Wiki/` is the one place the plugin keeps *current* facts instead of records: `Index.md`, `Log.md`, `Review.md` (all generated), `Wiki.md` (the contract), `Questions.md` (the user's own list of questions), and pages of six kinds: `People/`, `Orgs/`, `Decisions/` (one choice that was made and now stands, added to and never rewritten), `Topics/` (a subject with a timeline; with an owner and a due date it is a project and the index groups it under Projects), `Howto/` and `Me.md`. Pages are read and written only through `vault_wiki_search` (ranked facts for a question, `brief=true` for one stitched answer, `pages=true` for the pages that match), `vault_wiki_read`, `vault_wiki_write` (ops, with or without a record) and `vault_wiki_keep` (`log`, `review`, `lint`, `merge`, `migrate`) — never through `vault_write`, which refuses a `Wiki/` path. The page contract, the op list, refusal meanings, size caps, the index, log and review files, and the lint checklist are in `skills/wiki/references/wiki.md` (the same text the vault holds as `Wiki/Wiki.md`); the workflow is `skills/wiki/SKILL.md`. A page you edit in Obsidian is read back by the next wiki call that writes, and that answer carries `adopted: [{page, changes}]` — say so in one line. A read tool writes nothing: it answers `hand_edits: n`, how many pages differ from what the code last wrote.

`Wiki/_cache/` holds what the tools remember between runs, never facts: `collect.json` (the "last collected" stamp per source), `history.json` (where the load-history pass got to), `lint-<date>.json` (the last lint report in full, items and all), `queries.log` (every question put to the wiki, which lint check 21 reads) and `tokens.json` — the last 20 runs per command of `vault_collect(action="tokens")`, each `{at, predicted_in, predicted_out, actual_in, actual_out}`. `action="read"` turns them into `tokens: {<command>: {runs, ratio_in, ratio_out}}`, the median actual over predicted, which `collect-information` and `load-history` multiply their estimate by once a command has three runs on file. Deleting anything in `_cache/` costs nothing but the memory.

### Loading the past

`vault_load_history` reads the months *before* the `vault_collect` stamps into the same pages, one window of days at a time. `action="plan"` fixes the start date (90 days back by default), the batch size and, per source (`outlook_inbox`, `outlook_sent`, `teams`), the day the pass stops at — that source's stamp, else now; the stamps themselves are only read and are never moved. `action="next"` hands out `{batch_no, source, since, until, expected, skip_ids, list_with, reissued, auto, cap, cost}`, where `list_with` is the exact `outlook_list_mails` / `teams_list_chats` call and `skip_ids` the ids of that window already read; a window that was never reported comes again unchanged. `action="done"` takes `payload={saved: [{id, path, received}], skipped_ids, listed, reached, exhausted, pages, calls}`, records the ids, moves the place (to `until` when the window was exhausted, else to `reached`), fits the window to the batch size (1 to 30 days) and answers `{batch, saved, skipped, listed, place, window_days, source_done, all_done, totals, next_hint, auto, cap, cost, note}`. `auto` is "yes to all" (the payload sets it, and every answer carries it back), `cap` the tokens the whole pass may spend and `cost` `{in, out, total}` what it has spent, so a run that is not asking after every batch knows when to ask again. `action="status"` reports where it stands, including each source's `listed` against its `saved`. The whole state — the place per source, the ids seen, the totals and the window that is open — is one file, `Administrator/Wiki/_cache/history.json`, written after `plan` and after every `done`; delete it and the pass simply starts again. A second `plan` after a finished pass keeps the ids that pass read (`kept_ids` in the answer), so the days it covered come back as `skip_ids`; `reset=true` forgets them. The workflow is `skills/load-history/SKILL.md`.

### Questions.md — how well the wiki answers

`Administrator/Wiki/Questions.md` (`type: wiki-questions`, created once by `vault_init` with an empty list and two examples above it, never overwritten) belongs to the user: one line per question the wiki should be able to answer, with the page that holds the answer — `- When are the Q3 numbers due? → [[Wiki/Topics/q3-budget]]`, optionally `f:<id>` after the link when one particular fact is the answer and nothing else will do. `→` and `->` both work, only lines under `## Questions` count, and anything else in the file is left alone. Every `/administrator:lint` run asks the wiki all of them and counts a question answered when its page (or the named fact) comes back in the first three hits; the score, the misses (with what came back instead) and the lines pointing at a page that does not exist yet come back in `checks["20"]`, and the score goes on the run's Log line (`questions 17/20`) so the trend is readable. The other side of it is `checks["21"]`: questions somebody actually asked the wiki that returned nothing at all, at least twice in the last 30 days, each written to Review as "no page answers … — create one?". The plugin only reads this file; the user writes it.

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
created_by: administrator/0.4.0
---
```

Required keys: `type`, `week`, `start`, `end`, `created_by`. Body sections in fixed order: `## Still open from inbox`, `## Waiting on`, `## Meetings held`, `## Next week`, `## People going quiet`, `## Time`, `## Wiki`, and optionally `## Notes` (3–6 bullets written by the model; the others are laid out from `vault_weekly_facts`, `outlook_list_events`, `vault_time_block(action="audit")` and the wiki tools). `## Time` holds its `lines` as bullets — the week's own events from one `outlook_list_events(start=<Monday>, end=<Sunday>, fields=["subject","start","end","all_day","attendee_count","is_meeting","occurrence_key","busy_status"])` call: hours per kind (meeting, focus, admin, other, unplanned) with shares of the work hours, blocks planned / held / moved / skipped / unanswered from the `Time-blocks/` note's `## Held` rows, and hours per priority planned and held. A second run on the same week appends `## Update <ISO>` with a fresh set of sections; the earlier text stays. Nothing in a weekly note is edited in place.

## Time-block note

One note per ISO week under `Time-blocks/`, written only by `vault_time_block(action="write")` after `/administrator:time-block` created the appointments; the model never types one. Identity = `week`. `source: administrator`. The appointments themselves live in Outlook (subjects `[Focus] <priority>` and `[Admin] Email and small tasks`, `show_as: busy`, category `Administrator`, no attendees); the note keeps what was planned and, row by row, how it went.

```markdown
---
type: time-block
source: administrator
week: 2026-W35
start: "2026-08-24"
end: "2026-08-30"
planned: 13
created_by: administrator/0.4.0
---

# Time blocks — 2026-W35

Week of Mon 24 Aug to Sun 30 Aug. Planned by /administrator:time-block; the appointments live in Outlook, this note keeps the plan and how it went.

## Plan

| Day | Start | End | Kind | Subject | Priority |
| --- | --- | --- | --- | --- | --- |
| Mon 24 Aug | 10:15 | 11:45 | focus | [Focus] ACME supplier contract | ACME supplier contract <!-- occurrence_key: 0400D01…\|2026-08-24T10:15:00+02:00 # plan --> |
| Mon 24 Aug | 12:00 | 12:45 | admin | [Admin] Email and small tasks | — <!-- occurrence_key: 0400D02…\|2026-08-24T12:00:00+02:00 # plan --> |

## Held

| Day | Block | Result | Note |
| --- | --- | --- | --- |
| Mon 24 Aug | [Focus] ACME supplier contract 10:15–11:45 | held | <!-- occurrence_key: 0400D01…\|2026-08-24T10:15:00+02:00 --> |

## Notes
```

Rules:

- Required keys: `type`, `source`, `week`, `start`, `end`, `planned`, `created_by`. `planned` counts every block row written so far (the server replaces it on a re-plan).
- `## Plan` rows come from the plan blocks plus the `entry_id` / `occurrence_key` of the create results; the hidden key carries a ` # plan` suffix so that the `## Held` row of the same block, keyed by the bare `occurrence_key`, is not refused as a duplicate. A re-plan of the same week appends a `### Plan` table under `## Update <ISO>`; nothing above it changes and no row is ever removed — an unwanted appointment is deleted in Outlook by the user.
- `## Held` rows are written only by `/administrator:collect-information` through `vault_row(action="append", path, section="Held", row=["<Tue 25 Aug>", "<subject HH:MM–HH:MM>", "<held | moved | skipped>", "<note>"], dedupe_key=<occurrence_key>, key_label="occurrence_key", header=["Day","Block","Result","Note"])`, one per answered block; `duplicate` means it was answered already. `vault_time_block(action="audit")` reads them: `skipped` moves the block's minutes to unplanned, `moved` keeps them, a block without a row is `unanswered`.
- `## Notes` belongs to the user.

## Chat note

One record per Teams chat per day under `Teams/`, written only by `vault_save(kind="chat")` (`/administrator:collect-information`); the model never types one. Identity = `{chat_id, date}`, also held as `record_id: "<chat_id>|<date>"`, which is the `src` the wiki writes on facts that came from the chat. `source: teams`.

```markdown
---
type: chat
source: teams
chat_id: "19:a1b2c3@thread.v2"
chat_title: Q3 budget
chat_type: group
date: 2026-08-24
account: "<tenantId>:<userObjectId>"
members:
  - Jane Doe
  - Tom Lee
  - Hux Waitt
record_id: "19:a1b2c3@thread.v2|2026-08-24"
messages: 2
first: 2026-08-24T09:15:03+02:00
last: 2026-08-24T09:17:20+02:00
created_by: administrator/0.4.0
---

# Q3 budget — 2026-08-24

**Members:** Jane Doe, Tom Lee, Hux Waitt

## Messages

- 09:15 **Jane Doe**: Morning — can we move the numbers deadline to Friday 29 Aug? <!-- id: 1756049703123 -->
- 09:17 **Hux Waitt**: Fine by me. <!-- id: 1756049840555 -->
```

Rules:

- Required keys: `type`, `source`, `chat_id`, `chat_title`, `date`, `account`, `members`, `record_id`, `messages`, `first`, `last`, `created_by`. `chat_type` is `chat` (1:1), `group`, `channel` or `meeting`, as `teams_list_chats` reported it. Values come from the `teams_list_chats` entry and its `messages[]`; the model passes them through unchanged.
- One line per message, oldest first, `HH:MM` local, the sender's display name in bold, the text on one line, and the hidden message id. That id is the dedupe key: a second call the same day appends `## Update <ISO>` with a `### Messages` list of the ids not yet in the file and moves `messages` and `last` forward; nothing else changes. Nothing new → `action: unchanged`, no write.
- Messages spanning several days give one record per day; `vault_save(kind="chat")` then returns a list with one result per day.
- Senders that match a person page by name or alias get a `## Records` line on it (`- 2026-08-24 — [[Teams/2026-08-24 Q3 budget]] — Q3 budget: <first line>`, one per record) and `last_contact` moves forward; those pages go into the record's `wiki:` key. Senders without a page come back in `unknown_people` and get none — a chat carries no address, and no person page is ever created without one. The user's own messages (`is_self`, or a sender in `self_names`) are recorded but never matched.
- Chat records are ingested like emails and meetings (`vault_wiki_write(record_path=<Teams/…>)`; `src` defaults to `record_id`, `since` to `date`); lint check 11 counts chat records never ingested.

## Follow-ups.md — generated from the wiki pages

```markdown
---
type: followups
source: wiki
generated: true
updated: 2026-08-25T09:12:04+02:00
open: 3
created_by: administrator/0.4.0
---

# Follow-ups

Generated from the Open items of the wiki pages — edit or tick the item on its page, or say 'done' in chat; changes here are overwritten.

## Open

| Since | Who | What | Email | Last checked |
| --- | --- | --- | --- | --- |
| 2026-08-21 | [[Wiki/People/Carol Ng]] | Contract draft | [[Emails/2026-08-21 Contract draft]] | 2026-08-25 <!-- o: 4m2t @ Wiki/People/Carol Ng --> |

## Done

| Since | Who | What | Email | Closed |
| --- | --- | --- | --- | --- |
| 2026-08-18 | [[Wiki/People/Tom Lee]] | Leipzig delivery address | [[Meetings/2026-08-25 1300 Supplier sync]] | 2026-08-25 |
```

Rules:

- The file is written by code from the `## Open` lines of every wiki page, after every wiki write. `## Open` holds what **other people** owe the user (an item with `owner: me` never appears); `## Done` the newest 50 `done` lines out of the pages' History. The five columns are the ones the file has always had, so the Bases view still works.
- `Since` = the item's `since`, `Who` = its owner, `What` = its text cut to 80 characters, `Email` = the record it came from, `Last checked` = the day the file was written, followed by `<!-- o: <item id> @ <page stem> -->`.
- `vault_row` **refuses** this file (`… is written from the wiki pages, so a row cannot be added here`). An item is opened, moved or ticked on its page: `{"op": "open", "text", "owner", "due", "since", "src"}`, `{"op": "reschedule", "id", "due"}`, `{"op": "done", "id"}` through `vault_wiki_write` (`skills/wiki/SKILL.md`). Ticking the box on the page in Obsidian does the same on the next wiki call.
- Reading them back: `vault_wiki_search(query="", open_items=true, owner="me" | "others", due_before=<ISO date>, page=<one page>, include_done=false)` → `[{page, stem, type, title, owner_name, id, text, owner, due, since, src, record, done}]`, oldest first, at most 200. `inbox`, `save`, `daily`, `notes`, `schedule`, `collect-information` and `followups` open items; `inbox`, `notes` and `followups` tick them.
- A `Follow-ups.md` from before 0.4.0 (rows kept by hand, no `generated: true`) is left exactly as it is until `vault_wiki_keep(action="migrate")` moves its rows onto the pages — `/administrator:setup` offers that with a dry run first.

## Preferences.md

`<vault>/Administrator/Preferences.md` — one file, owned by the user, read by the `schedule` skill once per session (again only when the user says they changed it). Created by `vault_init` (`/administrator:setup` asks for work hours and peak hours; other commands use the defaults 09:00–17:00, buffer 15, `peak_hours: ["09:00-12:00"]`, `no_meeting_blocks: ["Fri 13:00-<work_end>"]`). `vault_init(overwrite=true)` is the only thing that ever rewrites it. Frontmatter keys: `type: preferences`, `source: administrator`, `work_start`, `work_end` (`"HH:MM"`, quoted), `timezone` (a note only), `buffer_minutes`, `no_meeting_blocks` (list of `"Fri 13:00-17:00"`), `max_meetings_per_day`, `default_duration`, `default_location`, `preferred_days` (list of `Mon`…`Sun`), the time-block keys `peak_hours`, `focus_block_minutes`, `focus_blocks_per_day`, `admin_blocks_per_day`, `admin_block_minutes`, `slack_share`, and `collect_folders` (extra vault-relative folders `/administrator:collect-information` reads for changed notes; folders outside `Administrator/` are only ever read), `created_by`. A missing or malformed key falls back to the default for that key (`skills/schedule/references/preferences.md`). The body may hold a `## Voice` section — optional, plain bullets, written by the user only, read by the `draft` skill and by nudges and minutes (`skills/draft/references/voice.md`).

## Priorities.md

`<vault>/Administrator/Priorities.md` — `type: priorities`, `source: administrator`, created by `vault_init` once (also with `overwrite=true`); owned by the user. Body: a short explanation and one `## Priorities` section with a numbered list, three to five lines, each a wiki topic link (`[[Wiki/Topics/acme-supplier-contract]]`) or plain words, ranked. `/administrator:time-block` reads the numbered lines through `vault_read` and gives rank 1 every other focus block; the placeholder line `vault_init` writes counts as empty. The plugin writes this file only with lines the user confirmed: `vault_priorities_write(action="candidates")` returns the material for a suggestion — `topics` (active wiki topics with `owner`, `due`, `open_items`, `verified`, `summary`, soonest due first), `followups` (the open items other people owe, oldest first), `weekly_open` (open act / reply rows of the latest weekly), `current` (the numbered lines now in the file) — and writes nothing; after the user's yes to "Use these as your priorities?", `vault_priorities_write(action="write", lines=[…], note=…, created_by="administrator/0.4.0")` replaces the numbered list (and the plugin's own `<!-- suggested by administrator, confirmed <date> -->` comment) under `## Priorities` and nothing else — frontmatter, the text above the heading and every other line stay byte for byte; the old lines come back as `previous`. The user edits the file in Obsidian any time.

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
5. `vault_save(kind="email", mail=<the get_mail JSON>, summary="Jane asks for the final Q3 numbers by Friday so she can close the forecast.", action_items=["Send Q3 numbers to Jane by 2026-08-29 — owner: me"], attachments_saved=[…], msg_file=…, self_addresses=["me@example.com"], created_by="administrator/0.4.0")` → `{"path": "Administrator/Emails/2026-08-22 Budget Q3.md", "action": "created", "status": "todo", "person_path": "Administrator/Wiki/People/Jane Doe.md", "person_action": "created", "followup_added": false}`. The note and person note it wrote look like this (the model never types them):

```yaml
type: email
source: outlook
entry_id: 00000000AA…
internet_message_id: <7f3a9c@example.com>
conversation_id: CAE…
subject: Re: Budget Q3
from: jane.doe@example.com
from_name: Jane Doe
from_link: "[[Wiki/People/Jane Doe]]"
to:
  - me@example.com
cc: []
received: 2026-08-22T09:14:00+02:00
status: todo
has_attachments: true
created_by: administrator/0.4.0
```

```markdown
# Re: Budget Q3

**From:** [[Wiki/People/Jane Doe]] <jane.doe@example.com>
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

   The person page is a `draft` wiki page with `last_contact: 2026-08-22T09:14:00+02:00`, `aliases: []` and one `## Records` line.

6. Report: "Saved Emails/2026-08-22 Budget Q3.md (todo) and created People/Jane Doe.md." plus the `obsidian://open` link.

## Worked example 2 — running inbox twice on one day

Both runs are one `vault_inbox_prepare` plus one `vault_write_daily` call; the model passes only `[{entry_id, label, reason}]`. The second run finds the earlier rows by their `<!-- entry_id: … -->` comments in code and appends only what is new under `## Update <ISO>`, replacing `inbox_checked` in the frontmatter. Nothing new → `action: unchanged`, nothing written. A reply from someone who owes an open item is the one case the model still closes by hand: `vault_wiki_search(query="", open_items=true, owner="others", page="Wiki/People/Carol Ng")` once, then `vault_wiki_write(pages=[{"path": "Wiki/People/Carol Ng", "ops": [{"op": "done", "id": "4m2t", "src": "user"}]}])`. Call by call: `skills/inbox/references/examples.md`.
