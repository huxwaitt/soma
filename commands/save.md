---
description: Save one email (or a thread) from Outlook as a note in the vault, with a person stub for the sender and optional .msg and attachment exports.
argument-hint: "<entry_id | search terms>"
---

# /administrator:save

Argument (required): either an exact Outlook `entry_id` or free-text search terms (subject words, sender name).

Argument given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `save` skill. Load the `outlook` skill if it is not already loaded.
2. Call `vault_status` if not done yet this session; if `administrator_dir_exists` or any folder or file flag is false, call `vault_init(created_by="administrator/0.0.4")` and mention `/administrator:setup`.
3. Find the mail:
   - If the argument looks like an `entry_id` (long hex string with no spaces), call `outlook_get_mail(entry_id, trim_quoted=true, response_format="json")`.
   - Otherwise call `outlook_search_mails(query=<terms>, folder="inbox", limit=5, response_format="json")`. If nothing matches, retry with `scope="from"`. Show up to 5 candidates (date, sender, subject) and ask the user to pick one. Then call `outlook_get_mail` on the chosen `entry_id`.
   - If the user asked for the whole thread, also call `outlook_get_conversation(entry_id, include_body=true, trim_quoted=true, max_body_chars=0, limit=20)` as the `save` skill describes.
4. `vault_find("email", {"internet_message_id": …, "entry_id": …})`. Found → the mail is already saved: append an update with `vault_write("email", <frontmatter as found>, "Saved again via /administrator:save. <what changed>", mode="append")` and skip to step 8. Not found → continue.
5. Build the note as the `save` skill describes: frontmatter with the exact keys from `administrator/references/vault.md` (`created_by: administrator/0.0.4`), one-line summary, action items, recipients, the body from `body_trimmed` when the tool returns it (else trimmed by the skill's own rules), and a `from_link` wikilink to `People/<Display Name>` — the name of the note `vault_find("person", {"email": <smtp>})` finds, or the sender's display name when there is none.
6. If the mail has attachments or the user asked to keep the original, ask first (one question, nothing else in that turn) whether to export. On a yes: `outlook_save_mail_as(entry_id, output_dir="<vault>\Administrator\Attachments\<YYYY-MM-DD slug>", fmt="msg", filename="<YYYY-MM-DD slug>")` and, when the mail has attachments, `outlook_save_attachments(entry_id, output_dir="<vault>\Administrator\Attachments\<YYYY-MM-DD slug>")`; put the returned files into the `attachments` / `msg_file` frontmatter keys and the note's `## Attachments` section. Both tools only accept paths under the user profile; if `vault_status.under_user_profile` is false, say so and skip.
7. Write: `vault_write("email", frontmatter, body, mode="upsert")` — the server picks the filename `Administrator/Emails/YYYY-MM-DD <slug>.md` and refuses a second note for the same mail. Then the sender's person note: `vault_write("person", …, mode="create")` when step 5 found none, else `mode="append"` with `last_contact` set to this mail's `received` if newer, a new display name or address added to `aliases`, and one `## Emails` line as the body. If `status` is `waiting`, `vault_append_row("Administrator/Follow-ups.md", "Open", [...], dedupe_key=<entry_id>)`.
8. Report the note path, the person note path, and any files saved, ending with `obsidian://open?vault=<vault_name>&file=<url-encoded path>` (`vault_name` from `vault_status`, `path` from `vault_write`). Do not change the mail in Outlook (no mark, move, or category) unless the user asks and says yes.
