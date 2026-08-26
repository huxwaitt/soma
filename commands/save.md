---
description: Save one email (or a thread) from Outlook as a note in the vault, with a person note for the sender and optional .msg and attachment exports.
argument-hint: "<entry_id | search terms>"
---

# /administrator:save

Argument (required): either an exact Outlook `entry_id` or free-text search terms (subject words, sender name). Add "the thread" / "whole conversation" to save every mail of the thread into one note; add "without wiki" to skip the wiki ingest at the end.

Argument given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `save` skill and its `skills/save/references/examples.md`. Load the `outlook` skill if it is not already loaded.
2. Once per session: `vault_status` (if `administrator_dir_exists` or any folder or file flag is false, `vault_init(created_by="administrator/0.4.0")` and mention `/administrator:setup`) and `outlook_whoami(response_format="json")` for the user's own addresses.
3. Find the mail:
   - `entry_id` given (long hex string, no spaces) → use it.
   - Otherwise `outlook_search_mails(query=<terms>, folder="inbox", limit=5, fields=["entry_id","from","subject","received","preview"], preview_chars=80, response_format="json")` (`scope="from"` for a sender name; then `folder="sent"`). One hit → take it and say so; more → show date, sender, subject, preview and ask the user to pick.
4. `outlook_get_mail(entry_id, trim_quoted=true, response_format="json", fields=["entry_id","internet_message_id","conversation_id","subject","from","from_address","to","cc","recipients","received","attachments","body_trimmed","body_truncated"])`. For a thread also `outlook_get_conversation(entry_id, include_body=true, trim_quoted=true, max_body_chars=0, limit=20, preview_chars=0, fields=["entry_id","from","received","folder","body_trimmed"])` and replace `body_trimmed` of the newest mail with one `### <date time> — <from>` section per item, as the `save` skill describes.
5. `vault_find("email", {"internet_message_id": …, "entry_id": …}, fields=["status","msg_file","attachments"])` — found means the helper will append an update, and exports are only offered when the user asked for them now and they are not yet linked. `vault_find("person", {"email": <from_address>}, fields=["name"])`; not found → one `outlook_search_contacts(query=<from_address>, include_directory=true, limit=5)` for `company` (only when an item's `email` equals the sender's address).
6. If the mail has attachments or the user asked to keep the original, ask first (one question, nothing else in that turn) whether to export. On a yes: `outlook_save_mail_as(entry_id, output_dir="<vault>\Administrator\Attachments\<YYYY-MM-DD slug>", fmt="msg", filename="<YYYY-MM-DD slug>")` and `outlook_save_attachments(entry_id, output_dir=<same>)`. Both only accept paths under the user profile; if `vault_status.under_user_profile` is false, say so and skip.
7. Write a summary (at most 2 sentences) and the action items from `body_trimmed`, then one call: `vault_save_email(mail=<step 4 JSON>, summary, action_items, attachments_saved=[<paths>], msg_file=<path>, self_addresses=<whoami addresses>, company=<step 5>, created_by="administrator/0.4.0")`. It writes the email note (`Administrator/Emails/YYYY-MM-DD <slug>.md`, or an `## Update` on an existing one), the sender's person note and the `Follow-ups.md` row for `waiting`. No `vault_write`, `vault_append_row` or hand-written frontmatter.
8. Wiki ingest, unless the argument or the user said "save without wiki": load the `wiki` skill, `vault_wiki_match(text=<subject + first 300 chars>, people=[<from_address>], domains=[<sender domain>])`, `vault_wiki_read(path, sections=["lead","facts"])` on at most 3 hits, one `vault_wiki_ingest(record_path=<step 7 path>, pages=[...], created_by="administrator/0.4.0")` with ops only for what the mail adds, changes or confirms (`skills/wiki/SKILL.md`). The sender's person page gets a `lead` when it is still `draft`. Nothing matched → `pages=[]`. A topic candidate over the threshold → propose, create only on a yes.
9. Report the note path and `action`, status and action-item count, the person note (`person_action`), any files saved, one `Wiki:` line (pages and changes, Review items, or "skipped"), ending with `obsidian://open?vault=<vault_name>&file=<url-encoded path>` (`vault_name` from `vault_status`, `path` from `vault_save_email`). Do not change the mail in Outlook (no mark, move, or category) unless the user asks and says yes.
10. If the host shows the token count of this turn, add it as the last line of the report; otherwise say nothing about it. (`save` does not write a daily note, so there is no `vault_write_daily(tokens_used=…)` call here.)

## Example

```
/administrator:save supplier contract jane
/administrator:save 00000000AC1F2B3C…
/administrator:save the thread with Jane about the supplier contract
```

> Saved `Emails/2026-08-21 Q3 supplier contract – signature needed.md` (todo, 2 action items). New person note `Wiki/People/Jane Doe.md`. Exported the .msg and `Q3-supplier-contract-v3.pdf` to `Administrator/Attachments/2026-08-21 Q3 supplier contract – signature needed/`. Wiki: `Topics/acme-supplier-contract` (net 30 → net 45 superseded, 1 open item), `People/Jane Doe` (lead written).
> obsidian://open?vault=Vault&file=Administrator%2FEmails%2F2026-08-21%20Q3%20supplier%20contract%20%E2%80%93%20signature%20needed.md

The full worked examples (one mail, a re-run, a thread) are in `skills/save/references/examples.md`.
