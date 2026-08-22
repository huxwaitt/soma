---
description: Go through the inbox, sort each mail into act / reply / waiting / fyi / noise, and write today's daily note. Offers (never runs) batch clean-up.
argument-hint: "[folder] [since]"
---

# /administrator:inbox

Arguments (both optional, in this order):

- `folder` — Outlook folder to read. Default `inbox`. Accepts a well-known name or a slash path (see the `outlook` skill).
- `since` — ISO-8601 date or datetime. Default: the `inbox_checked` value in the frontmatter of the most recent `Administrator/Daily/*.md` (that note's date at 00:00 if the key is missing); if there is no daily note, 24 hours ago.

Arguments given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill (vault rules, confirmation policy), then the `inbox` skill (the workflow). Load the `outlook` skill if it is not already loaded.
2. Check `ADMINISTRATOR_VAULT` is set and `<vault>/Administrator/` exists. If the env var is missing, stop and tell the user how to set it (see README). Create the `Daily/` subfolder and `Follow-ups.md` if missing.
3. Work out `since` as described above. Call `outlook_whoami` once to get the user's timezone, then `outlook_list_mails(folder=<folder>, unread_only=true, since=<since>, limit=100, response_format="json")`. Page with `next_offset` only if `has_more` is true and the user asked for more than 100.
4. Sort every mail into exactly one of **act / reply / waiting / fyi / noise** following the rules in the `inbox` skill. Use `outlook_get_mail(entry_id, max_body_chars=3000, response_format="json")` only for mails the preview cannot settle, at most 10 of them.
5. Write or append `Administrator/Daily/YYYY-MM-DD.md` (today, user's local date) using the daily note template in `administrator/references/vault.md`: frontmatter (`date`, `folder`, `since`, `inbox_checked`, `mails_seen`, `status`), a table of all mails with label and reason, `## To do` for act/reply, `## Waiting on`, and wikilinks to any existing `Emails/` notes with a matching `internet_message_id` or `entry_id`. If the file already exists, append a `## Update <ISO timestamp>` section and set `inbox_checked`; never rewrite earlier content. Add `waiting` items to the `## Open` table in `Administrator/Follow-ups.md` unless a row with that `entry_id` is already there.
6. Show the user a short summary: counts per group and the action list.
7. Offer, as a numbered list, the batch changes that would make sense — for example `outlook_bulk_mark_mails(entry_ids=[...], read=true)` for fyi/noise, `outlook_bulk_move_mails(entry_ids=[...], target_folder=<user-named folder>)`, or `outlook_bulk_mark_mails(entry_ids=[...], categories=[...])` using only names returned by `outlook_list_categories`. State the count and the subjects each option affects. Run nothing until the user answers with an explicit yes to a specific option. After running one, report `succeeded` / `failed` from the result.
