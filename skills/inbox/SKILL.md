---
name: inbox
description: Go through the user's new Outlook mail, label each message as act / reply / waiting / fyi / noise, write the result into today's daily note in the Obsidian vault, add "waiting" items to Follow-ups.md, and then offer (never run unasked) batch clean-up in Outlook. Trigger on /administrator:inbox, "go through my inbox", "what's new in my inbox", "anything urgent?", "what do I need to reply to", "what came in since yesterday", "sort my mail", "clear my inbox". Requires the outlook_* and vault_* tools and ADMINISTRATOR_VAULT.
---

# Inbox

Read new mail, decide what each message needs from the user, write that down in the vault, then offer to tidy Outlook. Reads are free. Nothing that changes Outlook runs without an explicit yes.

Vault conventions (paths, frontmatter, what a note looks like) live in the core `administrator` skill and `administrator/references/vault.md`; the notes themselves are written through the `vault_*` tools (`references/vault.md` has the table of which call does what). Outlook mechanics live in the `outlook` skill. This file only describes the inbox workflow.

## Inputs

- `folder` (optional, default `inbox`) — any folder reference the `outlook` skill accepts.
- `since` (optional) — ISO-8601 lower bound. If absent, work it out as described in "Finding the window".
- A working vault: `vault_status` once per session; if `administrator_dir_exists` or any folder or file flag is false, call `vault_init(created_by="administrator/0.0.4")` and mention `/administrator:setup`. If `vault_status` says the vault is unset or not a directory, stop and tell the user; do not guess a path.

## Steps

### 1. Find the window

1. `vault_list("daily", limit=1)` → the newest daily note, if any.
2. Use its frontmatter `inbox_checked` (ISO with offset) as `since`. If the note has no `inbox_checked`, use its `date` at `00:00` local time.
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

Use vault context when it is cheap: `vault_find("person", <from_address>)` with `found: true` means the sender is known and a message from them is less likely to be `noise`. Do this for senders you are unsure about, not for every sender.

### 4. Link to existing email notes

For each message, `vault_find("email", {"internet_message_id": <internet_message_id>, "entry_id": <entry_id>})`. If `found` is true, the `path` (without `Administrator/` and `.md`) becomes a wikilink for the `Note` column, e.g. `[[Emails/2026-08-22 Sign the NDA by Friday]]`; otherwise leave the link out. Do not create email notes from this skill — that is the `save` skill's job.

### 5. Write the daily note

One note per day, identity = the date. `vault_find("daily", {"date": <today>})` tells you whether it exists; `vault_write("daily", frontmatter, body, mode="upsert")` writes it and returns `action: created` or `appended` plus the `path`.

The exact layout is the daily note template in `administrator/references/vault.md`; follow it, do not improvise headings. In short:

**No note yet** — pass this frontmatter and body (the server adds nothing and checks the keys; `type` may be left out):

```yaml
type: daily
source: outlook
date: 2026-08-22
folder: inbox
since: 2026-08-21T17:05:00+02:00
inbox_checked: 2026-08-22T09:14:00+02:00
mails_seen: 5
status: todo
created_by: administrator/0.0.4
```

```markdown
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

**Note already exists** (second run today, or `/administrator:daily` already wrote it) — never rewrite it. First `vault_read(path)` and collect every `<!-- entry_id: … -->` in the body; drop any message whose `entry_id` is already there, so running twice never lists a mail twice. Then call `vault_write("daily", frontmatter, body, mode="append")` where:

- `frontmatter` is the one `vault_find` returned with `inbox_checked` set to the time you ran `outlook_list_mails` (the only key this skill changes on an existing note; the server keeps every other key as it was, `mails_seen` included).
- `body` is the new material only. The server puts it under a heading `## Update <ISO>` it adds itself (the heading text comes back as `update_heading`), so the body starts with the sub-heading and continues the row numbers:

```markdown
### Inbox (since 2026-08-22T09:14:00+02:00)

<table, continuing the row numbers, then the To do / Waiting on / Suggested lists as above, only for the new messages>
```

When nothing is new, the body is the one line "Inbox: nothing new since <since>." and `inbox_checked` is still set.

Set `inbox_checked` to the time you ran `outlook_list_mails`, not to the newest mail's `received`, so the next run picks up anything that arrived during the run.

### 6. Add waiting items to Follow-ups.md

`Administrator/Follow-ups.md` exists once `vault_init` has run. For each `waiting` item, one call:

```
vault_append_row("Administrator/Follow-ups.md", "Open",
                 [<Since>, <Who>, <What>, <Email>, <today>],
                 dedupe_key=<entry_id>)
```

`Since` = the mail's date, `Who` = `[[People/<Name>]]` when `vault_find("person", <from_address>)` finds a note, else the display name, `What` = the subject (ten words or fewer), `Email` = the email-note wikilink if any, else empty. The server writes `<!-- entry_id: … -->` into the last cell and answers `appended: false, reason: "duplicate"` when that `entry_id` is already in the file; then leave the row alone (nothing else is edited on an existing row).

Closing: when a mail in this run is a reply from the `Who` of an open row on the same subject (a reply on the thread the user was waiting for), `vault_read("Administrator/Follow-ups.md")`, find the row in the `## Open` table by `Who` and `What`, take the key from its trailing comment, and call `vault_move_row("Administrator/Follow-ups.md", "Open", "Done", <key>, set_last_cell=<today>)`. Say so in the daily note ("Carol Ng replied on 'Contract draft' → Follow-ups row moved to Done."). Rows are never deleted; rows the user edited by hand are only ever moved, never rewritten.

### 7. Report, then offer batch actions

Tell the user in a few lines: counts per label, the `act` and `reply` subjects, and where the note went, ending with `obsidian://open?vault=<vault_name>&file=<url-encoded path>` (`vault_name` from `vault_status`, `path` from `vault_write`, every `/` and space encoded, e.g. `obsidian://open?vault=Vault&file=Administrator%2FDaily%2F2026-08-22.md`). Then offer, as a numbered list, only the actions that apply:

1. Mark `fyi` and `noise` as read — `outlook_bulk_mark_mails(entry_ids=[...], read=true)`. List the count and subjects (collapse to the first 10 plus "and N more" when long).
2. Move `noise` to a folder — `outlook_bulk_move_mails(entry_ids=[...], target_folder=<name>)`. Ask the user for the folder name; check it with `outlook_list_folders` and use the returned `path` verbatim. Do not create folders.
3. Tag by label — `outlook_bulk_mark_mails(entry_ids=[...], categories=[...])`. First call `outlook_list_categories`; only offer names that come back. Suggest a mapping (for example "To Respond" for `reply`, "FYI" for `fyi`) only from those names. If no matching categories exist, say so and skip this option rather than inventing one. Remember `categories` replaces the item's current list.
4. Flag `act` items for follow-up — `outlook_bulk_mark_mails(entry_ids=[...], flagged=true)`.

Run an action only after the user answers yes to that specific item. "Yes" to item 1 is not yes to item 2. After a bulk call, read the result: if `failed > 0`, say which subjects failed and why. Then record it: `vault_write("daily", <frontmatter as found>, "Done <ISO>: marked 2 as read", mode="append")`. Never call `outlook_bulk_delete_mails` or `outlook_delete_mail` from this skill, even if asked to "get rid of" noise — move it instead, and say so.

Nothing in this skill sends mail. If the user asks you to reply from here, point them to the reply as a separate request that will be confirmed on its own.

## Edge cases

- **`vault_status` reports no vault or a missing folder:** `vault_init` fixes missing folders and files; an unset or wrong `ADMINISTRATOR_VAULT` needs the user — stop before listing mail.
- **`vault_*` tools missing:** the vault server is not running; point the user to `/administrator:setup` and do not write notes by hand.
- **`outlook_*` tools missing:** follow the `outlook` skill's setup instructions; do not write a daily note.
- **A `since` in the future or unparsable:** say so and fall back to 24 hours.
- **Same message appears twice (duplicate delivery):** label once, list once; identical `entry_id`s collapse.
- **The user is the sender (mail from self):** `fyi` unless it is a note-to-self with a verb in it, then `act`.
- **Run on a folder other than the inbox:** same flow; name the folder in the section heading, e.g. `## Inbox (Inbox/Invoices, since ...)`, and in the `folder` frontmatter key.

## References

- `references/labels.md` — full decision rules per label, with the Fyxer eight-label mapping and the tie-break order.
