---
description: Save one email (or a thread) from Outlook as a note in the vault, with a person stub for the sender and optional .msg and attachment exports.
argument-hint: "<entry_id | search terms>"
---

# /administrator:save

Argument (required): either an exact Outlook `entry_id` or free-text search terms (subject words, sender name).

Argument given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `save` skill. Load the `outlook` skill if it is not already loaded.
2. Check `ADMINISTRATOR_VAULT` is set; create `Administrator/Emails/`, `Administrator/People/`, and `Administrator/Attachments/` if missing.
3. Find the mail:
   - If the argument looks like an `entry_id` (long hex string with no spaces), call `outlook_get_mail(entry_id, response_format="json")`.
   - Otherwise call `outlook_search_mails(query=<terms>, folder="inbox", limit=5, response_format="json")`. If nothing matches, retry with `scope="from"`. Show up to 5 candidates (date, sender, subject) and ask the user to pick one. Then call `outlook_get_mail` on the chosen `entry_id`.
   - If the user asked for the whole thread, also call `outlook_get_conversation(entry_id, include_body=true, max_body_chars=0, limit=20)` as the `save` skill describes.
4. Build the note as the `save` skill describes: identity is `internet_message_id` (fall back to `entry_id`), filename `Emails/YYYY-MM-DD <slug>.md`, frontmatter with the exact keys from the `administrator` skill, one-line summary, action items, recipients, cleaned body with quoted history removed, and a `from_link` wikilink to `People/<Display Name>`.
5. Before writing, search `Administrator/Emails/` for a note whose frontmatter already has this identity. If found, append a `## Update <ISO timestamp>` section to that file instead of creating a new one.
6. Create or update `Administrator/People/<Display Name>.md` for the sender (first grep `People/` for the SMTP address in `email:` / `aliases:` so one person never gets two notes): set `last_contact` to this mail's `received` if newer, add a new display name or address to `aliases`, and add a line for the email note under `## Emails`.
7. Ask the user whether to also export. If yes: `outlook_save_mail_as(entry_id, output_dir="<vault>\Administrator\Attachments\<YYYY-MM-DD slug>", fmt="msg", filename="<YYYY-MM-DD slug>")` and, when the mail has attachments, `outlook_save_attachments(entry_id, output_dir="<vault>\Administrator\Attachments\<YYYY-MM-DD slug>")`. Link the saved files from the note's `## Attachments` section and the `attachments` / `msg_file` frontmatter keys. Both tools only accept paths under the user profile; if the vault is elsewhere, say so and skip.
8. Report the note path, the person note path, and any files saved. Do not change the mail in Outlook (no mark, move, or category) unless the user asks and says yes.
