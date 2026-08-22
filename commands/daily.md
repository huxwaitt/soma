---
description: Build today's daily note from the inbox and today's calendar, pointing out clashes and meetings with no prep note.
argument-hint: "[date]"
---

# /administrator:daily

Argument (optional): `date` as `YYYY-MM-DD`. Default: today in the user's local timezone.

Argument given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `inbox` skill. Load the `outlook` skill if it is not already loaded.
2. Call `vault_status` if not done yet this session; if `administrator_dir_exists` or any folder or file flag is false, call `vault_init(created_by="administrator/0.0.4")` and mention `/administrator:setup`.
3. Run the inbox workflow exactly as `/administrator:inbox` does (steps 3 to 5 of that command) for `Administrator/Daily/<date>.md`, but hold the `vault_write` call until step 5 so the note is written once. Skip the batch-action offer for now; collect it for step 7.
4. Call `outlook_list_events(start="<date>T00:00:00", end="<date>T23:59:59", include_recurrences=true, limit=50, response_format="json")`. For every event that is not all-day, `vault_find("meeting", {"occurrence_key": <occurrence_key>, "global_id": <global_id>})` tells you whether a prep note exists.
5. Write the daily note with one `vault_write("daily", frontmatter, body, mode="upsert")`:
   - **No note yet** (`vault_find("daily", {"date": <date>})` says `found: false`): the inbox body from step 3 followed by `## Calendar` and `## Watch out`, laid out as in the daily note template in `administrator/references/vault.md`: a table `| Start | End | Subject | Location | Organizer |` (all-day events show `all day` in both time columns; each row ends with `<!-- occurrence_key: … -->` inside the last cell), then a `## Watch out` list with clashes (events whose time ranges overlap) and meetings with no prep note (`found: false` in step 4, not all-day), with an offer of `/administrator:prep` for those. Put `## Suggested Outlook actions (not done)` last, as the template does.
   - **Note exists** (`/administrator:inbox` ran earlier, or this is a second run): `vault_read(path)` first; the body is the inbox update material from step 3 plus `### Calendar` with only the rows whose `occurrence_key` comment is not yet in the file, and `### Watch out` with only items not already listed. The server puts all of it under one `## Update <ISO>` heading. Frontmatter: the one `vault_find` returned with `inbox_checked` set to now.
6. Show the user a short brief: inbox counts, action list, agenda, and the watch-out items, ending with `obsidian://open?vault=<vault_name>&file=<url-encoded path>` (`vault_name` from `vault_status`, `path` from `vault_write`).
7. Offer the batch Outlook changes from the inbox workflow as a numbered list with counts and subjects. Run nothing until the user gives an explicit yes to a specific option. Nothing in this command creates, updates, or responds to calendar events.
