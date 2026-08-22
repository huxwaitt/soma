---
description: Go through the inbox, sort each mail into act / reply / waiting / fyi / noise, and write today's daily note. Offers (never runs) batch clean-up.
argument-hint: "[folder] [since]"
---

# /administrator:inbox

Arguments (both optional, in this order):

- `folder` — Outlook folder to read. Default `inbox`. Accepts a well-known name or a slash path (see the `outlook` skill).
- `since` — ISO-8601 date or datetime. Default: the `inbox_checked` value in the frontmatter of the most recent daily note (`vault_list("daily", limit=1)`; that note's date at 00:00 if the key is missing); if there is no daily note, 24 hours ago.

Arguments given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill (vault rules, confirmation policy), then the `inbox` skill (the workflow). Load the `outlook` skill if it is not already loaded.
2. Call `vault_status` if not done yet this session. If the vault is unset or not a directory, stop and tell the user how to set `ADMINISTRATOR_VAULT` (see README) or to run `/administrator:setup`. If `administrator_dir_exists` or any folder or file flag is false, call `vault_init(created_by="administrator/0.0.4")`.
3. Work out `since` as described above. Call `outlook_whoami` once to get the user's timezone, then `outlook_list_mails(folder=<folder>, unread_only=true, since=<since>, limit=100, response_format="json")`. Page with `next_offset` only if `has_more` is true and the user asked for more than 100.
4. Sort every mail into exactly one of **act / reply / waiting / fyi / noise** following the rules in the `inbox` skill. Use `outlook_get_mail(entry_id, max_body_chars=3000, response_format="json")` only for mails the preview cannot settle, at most 10 of them. For each mail, `vault_find("email", {"internet_message_id": …, "entry_id": …})` gives the wikilink for the `Note` column when a note exists.
5. Write the daily note with `vault_write("daily", frontmatter, body, mode="upsert")` as the `inbox` skill describes: frontmatter (`date`, `folder`, `since`, `inbox_checked`, `mails_seen`, `status`, `created_by: administrator/0.0.4`), body from the daily note template in `administrator/references/vault.md` (table of all mails with label, reason and `<!-- entry_id: … -->` comment, `## To do` for act/reply, `## Waiting on`). If `vault_find("daily", {"date": <today>})` says the note exists, `vault_read` it first, drop mails whose `entry_id` is already in it, and write with `mode="append"` — the body is the new material only and the frontmatter is the found one with `inbox_checked` set to now; the server adds the `## Update <ISO>` heading and never rewrites earlier content. Add `waiting` items with `vault_append_row("Administrator/Follow-ups.md", "Open", [...], dedupe_key=<entry_id>)`; a duplicate answer means the row is already there. Close a row whose reply arrived with `vault_move_row(..., "Open", "Done", <key>, set_last_cell=<today>)`.
6. Show the user a short summary: counts per group and the action list, ending with `obsidian://open?vault=<vault_name>&file=<url-encoded path>` (`vault_name` from `vault_status`, `path` from `vault_write`).
7. Offer, as a numbered list, the batch changes that would make sense — for example `outlook_bulk_mark_mails(entry_ids=[...], read=true)` for fyi/noise, `outlook_bulk_move_mails(entry_ids=[...], target_folder=<user-named folder>)`, or `outlook_bulk_mark_mails(entry_ids=[...], categories=[...])` using only names returned by `outlook_list_categories`. State the count and the subjects each option affects. Run nothing until the user answers with an explicit yes to a specific option. After running one, report `succeeded` / `failed` from the result and record it in the daily note with `vault_write("daily", <frontmatter as found>, "Done <ISO>: <what ran>", mode="append")`.
