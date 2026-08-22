---
name: inbox
description: Go through the user's new Outlook mail, label each message as act / reply / waiting / fyi / noise, write the result into today's daily note in the Obsidian vault, add "waiting" items to Follow-ups.md, and then offer (never run unasked) batch clean-up in Outlook. Trigger on /administrator:inbox, "go through my inbox", "what's new in my inbox", "anything urgent?", "what do I need to reply to", "what came in since yesterday", "sort my mail", "clear my inbox". Requires the outlook_* tools and ADMINISTRATOR_VAULT.
---

# Inbox

Read new mail, decide what each message needs from the user, write that down in the vault, then offer to tidy Outlook. Reads are free. Nothing that changes Outlook runs without an explicit yes.

Vault conventions (paths, frontmatter, slug rules, append-vs-create) live in the core `administrator` skill and `administrator/references/vault.md`. Outlook mechanics live in the `outlook` skill. This file only describes the inbox workflow.

## Inputs

- `folder` (optional, default `inbox`) — any folder reference the `outlook` skill accepts.
- `since` (optional) — ISO-8601 lower bound. If absent, work it out as described in "Finding the window".
- `ADMINISTRATOR_VAULT` — absolute vault path. If it is unset, stop and tell the user to set it; do not guess a path.

## Steps

### 1. Find the window

1. Glob `<vault>/Administrator/Daily/*.md` and take the newest filename that matches `YYYY-MM-DD.md`.
2. Read its frontmatter. Use its `inbox_checked` value (ISO with offset) as `since`. If the note has no `inbox_checked`, use the file's date at `00:00` local time.
3. If there is no daily note at all, or the user gave a `since`, use that. Otherwise fall back to now minus 24 hours.
4. Call `outlook_whoami` once if you need the local time zone offset to write ISO timestamps; its `utc_offset` is the one to use.

Tell the user in one line which window you are using, e.g. "Checking mail since Thu 21 Aug 17:05."

### 2. List the mail

```
outlook_list_mails(folder=<folder>, unread_only=true, since=<since>, limit=100, response_format="json")
```

Use the `json` shape: you need `entry_id`, `internet_message_id`, `subject`, `from`, `from_address`, `to`, `received`, `importance`, `has_attachments`, `preview`. Remember the time you made this call; it becomes `inbox_checked`.

- **0 mails:** still write (or append to) today's daily note with a one-line "Inbox: nothing new since <since>." and set `inbox_checked`. Tell the user and stop. Do not offer batch actions.
- **`has_more` is true (more than 100):** do not page through everything. Label the 100 you have, and write a line at the top of the inbox section: "More than 100 unread since <since>; showed the newest 100. Run again with `since` set to <received of the oldest one shown> to see the rest." Then ask the user whether to continue with the next page before doing so.

### 3. Label each mail

Give every message exactly one label and a reason of one short sentence. The full decision rules are in `references/labels.md`; the short form:

| Label | Meaning | Typical signs |
|---|---|---|
| `act` | The user has to do something other than write back (pay, review, sign, fix, attend, decide). | Asks with a deadline, approvals, tickets assigned to the user, calendar invites needing a response, documents to review. |
| `reply` | The user is expected to write back, and a reply is the whole job. | Direct question to the user, the user is in To, sender is a real person, thread is waiting on the user. |
| `waiting` | The user asked for something and this message shows it is still pending, or it moves the ball to someone else. | "Will get back to you", acknowledgements, auto-replies to the user's own request, handoffs to a third party. |
| `fyi` | Worth knowing, nothing to do. | The user is in Cc, status updates, meeting changes already on the calendar, notifications from systems the user watches, finished threads. |
| `noise` | Safe to mark read and file without reading. | Newsletters, marketing, unsubscribe links, bulk senders, automated digests nobody acts on. |

Work from subject, sender, recipients, preview and importance. Only call `outlook_get_mail(entry_id, max_body_chars=3000)` when those are not enough to choose between two labels, and do that for at most 10 messages per run. Everything still ambiguous after that gets `reply` if the user is in To and the sender is a person, otherwise `fyi`, and the reason says "unsure".

Prefer the more demanding label when torn: `act` over `reply`, `reply` over `fyi`, `fyi` over `noise`. A wrong `noise` costs more than a wrong `fyi`.

Use vault context when it is cheap: if `<vault>/Administrator/People/<from_name>.md` exists, the sender is known and a message from them is less likely to be `noise`. Do not go hunting through the vault for every sender.

### 4. Link to existing email notes

For each message, check whether a note already exists: grep `<vault>/Administrator/Emails/` for `internet_message_id: "<internet_message_id>"` when the list item has one, otherwise for `entry_id: "<entry_id>"`. If a note exists, record its path as a wikilink for the `Note` column; otherwise leave the link out. Do not create email notes from this skill — that is the `save` skill's job.

### 5. Write the daily note

Path: `<vault>/Administrator/Daily/YYYY-MM-DD.md` (today's local date).

The exact layout is the daily note template in `administrator/references/vault.md`; follow it, do not improvise headings. In short:

**New file** — write:

```markdown
---
type: daily
source: outlook
date: 2026-08-22
folder: inbox
since: 2026-08-21T17:05:00+02:00
inbox_checked: 2026-08-22T09:14:00+02:00
mails_seen: 5
status: todo
created_by: administrator/0.0.3
---

# 2026-08-22

## Inbox (since 2026-08-21T17:05:00+02:00)

| # | Label | From | Subject | Received | Why | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | act | Jane Doe | Sign the NDA by Friday | 08:52 | Deadline Friday, attachment to sign | [[Emails/2026-08-22 Sign the NDA by Friday]] <!-- entry_id: 00000000A1… --> |
| 2 | reply | Tom Lee | Re: Q3 numbers | 08:40 | Asks you directly for the revised figure | <!-- entry_id: 00000000A2… --> |
| 3 | waiting | Acme Support | Ticket 4411 received | 07:55 | Acknowledges your request, no answer yet | <!-- entry_id: 00000000A3… --> |
| 4 | fyi | Build Bot | Nightly build passed | 06:10 | Status only | <!-- entry_id: 00000000A4… --> |
| 5 | noise | Vendor News | August newsletter | 06:00 | Newsletter | <!-- entry_id: 00000000A5… --> |

Labels: **act** (do something), **reply** (answer), **waiting** (they owe me), **fyi** (read), **noise** (ignore).

## To do

- [ ] act — Sign the NDA by Friday (Jane Doe) — [[Emails/2026-08-22 Sign the NDA by Friday]]
- [ ] reply — Re: Q3 numbers (Tom Lee)

## Waiting on

- Acme Support — Ticket 4411 received (since 2026-08-22) → also in [[Follow-ups]]

## Suggested Outlook actions (not done)

- Mark 2 fyi/noise as read
```

Sort the table `act`, `reply`, `waiting`, `fyi`, `noise`, newest first within a label. Every row carries `<!-- entry_id: … -->` inside its last cell; that is how a later run knows the row is there. `## To do` holds `act` and `reply` items only. `## Waiting on` mirrors what goes into `Follow-ups.md`. `## Suggested Outlook actions (not done)` lists what step 7 offers. Leave `## Calendar` and `## Watch out` to `/administrator:daily`.

**File already exists** (second run today, or `/administrator:daily` already wrote it) — never rewrite it. Append:

```markdown
## Update 2026-08-22T14:02:00+02:00

### Inbox (since 2026-08-22T09:14:00+02:00)
<table, continuing the row numbers, and the To do / Waiting on / Suggested lists as above, only for the new messages>
```

and set `inbox_checked` in the existing frontmatter to now (the one frontmatter edit this skill makes; leave every other line alone, `mails_seen` included). Skip any message whose `entry_id` already appears in the file, so running twice never lists a mail twice. When nothing is new, append a one-line `## Update` saying "Inbox: nothing new since <since>." and still set `inbox_checked`.

Set `inbox_checked` to the time you ran `outlook_list_mails`, not to the newest mail's `received`, so the next run picks up anything that arrived during the run.

### 6. Add waiting items to Follow-ups.md

Path: `<vault>/Administrator/Follow-ups.md`. Create it from the template in `administrator/references/vault.md` if it does not exist (frontmatter `type: followups`, an `## Open` table and a `## Done` table, columns `Since | Who | What | Email | Last checked` / `Closed`).

For each `waiting` item, append one row to the bottom of `## Open`: `Since` = the mail's date, `Who` = `[[People/<Name>]]` if that note exists, else the display name, `What` = the subject (ten words or fewer), `Email` = the email-note wikilink if any, `Last checked` = today followed by `<!-- entry_id: … -->`. Before appending, grep the file for that `entry_id`; if the row is already there, only change its `Last checked` date.

Closing: when a mail in this run is a reply from the `Who` of an open row on the same subject (a reply on the thread the user was waiting for), move that row from `## Open` to `## Done` with `Closed` = today, and say so in the daily note. Never delete rows; never touch rows the user edited by hand beyond those two changes.

### 7. Report, then offer batch actions

Tell the user in a few lines: counts per label, the `act` and `reply` subjects, and where the note went. Then offer, as a numbered list, only the actions that apply:

1. Mark `fyi` and `noise` as read — `outlook_bulk_mark_mails(entry_ids=[...], read=true)`. List the count and subjects (collapse to the first 10 plus "and N more" when long).
2. Move `noise` to a folder — `outlook_bulk_move_mails(entry_ids=[...], target_folder=<name>)`. Ask the user for the folder name; check it with `outlook_list_folders` and use the returned `path` verbatim. Do not create folders.
3. Tag by label — `outlook_bulk_mark_mails(entry_ids=[...], categories=[...])`. First call `outlook_list_categories`; only offer names that come back. Suggest a mapping (for example "To Respond" for `reply`, "FYI" for `fyi`) only from those names. If no matching categories exist, say so and skip this option rather than inventing one. Remember `categories` replaces the item's current list.
4. Flag `act` items for follow-up — `outlook_bulk_mark_mails(entry_ids=[...], flagged=true)`.

Run an action only after the user answers yes to that specific item. "Yes" to item 1 is not yes to item 2. After a bulk call, read the result: if `failed > 0`, say which subjects failed and why. Never call `outlook_bulk_delete_mails` or `outlook_delete_mail` from this skill, even if asked to "get rid of" noise — move it instead, and say so.

Nothing in this skill sends mail. If the user asks you to reply from here, point them to the reply as a separate request that will be confirmed on its own.

## Edge cases

- **`ADMINISTRATOR_VAULT` unset or the folder does not exist:** stop before listing mail; ask the user to set it.
- **`outlook_*` tools missing:** follow the `outlook` skill's setup instructions; do not write a daily note.
- **A `since` in the future or unparsable:** say so and fall back to 24 hours.
- **Same message appears twice (duplicate delivery):** label once, list once; identical `entry_id`s collapse.
- **The user is the sender (mail from self):** `fyi` unless it is a note-to-self with a verb in it, then `act`.
- **Run on a folder other than the inbox:** same flow; name the folder in the section heading, e.g. `## Inbox (Inbox/Invoices, since ...)`, and in the `folder` frontmatter key.

## References

- `references/labels.md` — full decision rules per label, with the Fyxer eight-label mapping and the tie-break order.
