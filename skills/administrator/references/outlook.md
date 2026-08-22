# Outlook reference — plugin needs → `outlook_*` tools

This is a map, not a manual. Exact parameter tables, return shapes, and quirks are in the `outlook` skill: `references/tools.md` (parameters) and `references/gotchas.md` (failure modes). Read those the first time you call a tool in a session. Server: outlook-classic-mcp 0.4.0 with `outlook_get_conversation` and `internet_message_id` (37 tools), classic Outlook only.

Always pass `response_format="json"` when you will use a field from the result (an `entry_id`, a `conversation_id`, a `received` time). Use the default markdown only when the result itself is the answer for the user.

## Map

| Plugin need | Tool | Parameters to use | What to take from the result |
| --- | --- | --- | --- |
| Inbox window (`inbox`, `daily`) | `outlook_list_mails` | `unread_only=true`, `since=<ISO>`, `limit=100`, `folder` (default `inbox`, or the one the user named), `response_format="json"` | `items[]`: `entry_id, internet_message_id, subject, from, from_address, to, received, unread, has_attachments, importance, preview`. `has_more` / `next_offset` → page once more if needed. |
| Find a mail by words (`save`) | `outlook_search_mails` | `query=<words>`, `scope` = `subject_body` (default) / `subject` / `from`, `limit=5`, `response_format="json"` | Same item shape as `list_mails`. Show the user up to 5 candidates and let them pick. |
| The whole thread (`save` with "the thread") | `outlook_get_conversation` | `entry_id=<any mail in the thread>`, `include_body=true`, `max_body_chars=0`, `limit=20` (always returns JSON) | `conversation_id`, `items[]` oldest first, each the `list_mails` item shape plus `conversation_id`, `folder`, `body`. `truncated=true` → thread longer than `limit`. One item only when Outlook has no conversation (IMAP/POP, drafts). |
| Full mail for a note (`save`, ambiguous classification in `inbox`) | `outlook_get_mail` | `entry_id`, `response_format="json"`, `max_body_chars=10000` (raise only if `body_truncated`) | `entry_id, internet_message_id, conversation_id, subject, from, from_address, to, cc, recipients[{name,address,type}], received, sent, categories, attachments[{index,filename,size_bytes}], body` |
| Many mails' metadata in one call, with `conversation_id` | `outlook_export_mails` | `entry_ids=[...]` or the same filters as `list_mails`, `fmt="json"`, `output_path=<vault>/Administrator/Attachments/_export/<date>.json`, `include_body=false` | File at `path`; columns `entry_id, subject, from, from_address, to, cc, received, sent, unread, flagged, has_attachments, importance, categories, conversation_id, internet_message_id`. Read the file, then delete it when done. |
| Export the mail itself (`save`, optional) | `outlook_save_mail_as` | `entry_id`, `output_dir=<vault>/Administrator/Attachments/<YYYY-MM-DD slug>`, `fmt="msg"` | `path` → `msg_file` in the note. Never overwrites; Outlook adds ` (1)`. |
| Export attachments (`save`, optional) | `outlook_save_attachments` | `entry_id`, `output_dir=<same folder>`, `attachment_index` (1-based) or omit for all | `files[]` → `attachments` list in the note. |
| Today's agenda (`daily`) | `outlook_list_events` | `start=<today 00:00>`, `end=<today 23:59:59>`, `include_recurrences=true`, `response_format="json"` | `items[]`: `entry_id, subject, start, end, location, organizer, all_day`. Clash = overlapping `start`/`end`. |
| Who is this person (`save` → person note `company`) | `outlook_search_contacts` | `query=<SMTP address or full name>`, `include_directory=true`, `limit=5` | `items[]`: `full_name, email, company, job_title`. Use `company` only when `email` equals the sender's SMTP. |
| Name → SMTP | `outlook_resolve_name` | `name` | `smtp_address` when `resolved=true`. |
| Folder path for a move offer | `outlook_list_folders` | `max_depth=4`, `response_format="json"` | `items[].path` — pass it verbatim as `target_folder`. |
| Category names for a category offer | `outlook_list_categories` | — | `items[].name`. Never use a name that is not in this list. |
| Which mailbox, which timezone | `outlook_whoami` | — | `accounts[].smtp_address` (the user's own address, to tell "from me" apart), `utc_offset`. |
| Mark read / flag / category in bulk (offered by `inbox`) | `outlook_bulk_mark_mails` | `entry_ids`, `read=true|false|null`, `flagged`, `categories=[...]` (replaces the list; `[]` clears) | `status`, `failed`, `failures[]`. Report failures by subject. |
| Move in bulk (offered by `inbox`) | `outlook_bulk_move_mails` | `entry_ids`, `target_folder=<path from list_folders>` | `results[].new_entry_id` — the old `entry_id` is dead after a cross-store move. |
| Single mark / move | `outlook_mark_mail`, `outlook_move_mail` | `entry_id` + the change | `unread` (not `read`) / `new_entry_id`. |

## Identity fields: where they come from

- `entry_id` — on every item from `list_mails`, `search_mails`, `get_mail`, `export_mails`. Opaque; quote it verbatim. Invalid after delete; changes after a move between stores.
- `internet_message_id` — the `Message-ID` header, on every item from `list_mails`, `search_mails`, `get_mail`, `get_conversation`, `export_mails`. This is the note identity. It is `""` for drafts and on some IMAP/POP stores; then use `entry_id` and write `internet_message_id: ""`.
- `conversation_id` — in `outlook_get_mail`, `outlook_get_conversation` items and `outlook_export_mails` rows. `list_mails` / `search_mails` do not include it. For a single mail, `get_mail` is the cheapest way; for a batch, one `export_mails(entry_ids=[...], fmt="json")` call beats N `get_mail` calls.
- `from_address` — a real SMTP address in 0.4.0 (the server resolves Exchange `EX:/O=...` senders). If a value still starts with `/O=`, the server could not resolve it: store it as is in `from`, and say so in the note's summary line.
- `recipients[]` (from `get_mail` only) gives SMTP addresses per recipient with `type` `to` / `cc` / `bcc`. The flat `to` / `cc` strings on list items are display names only.
- `received` — ISO with the user's local offset. Copy it unchanged into frontmatter; use its date part for filenames.

## Dates

All `since`, `until`, `start`, `end` parameters are ISO-8601 strings; with no offset they mean the user's local time, which is what you want. Work out "yesterday", "since Monday" yourself before calling. For the inbox window use the `inbox_checked` value from the most recent daily note's frontmatter (that note's date at 00:00 if the key is missing), else now minus 24 hours.

## Paths

`output_dir` and `output_path` must be absolute and under `C:\Users\<them>\`. The vault is the usual place; if `ADMINISTRATOR_VAULT` is outside the profile, exports fail with a sandbox error — tell the user about `OUTLOOK_MCP_ALLOW_ANY_PATH=1` from the outlook skill's setup notes rather than trying another path.

## Tools that need a yes first

Before any of these, list what will be affected (count, subjects, target) and wait for a clear yes in this conversation:

`outlook_mark_mail`, `outlook_bulk_mark_mails`, `outlook_move_mail`, `outlook_bulk_move_mails`, `outlook_delete_mail`, `outlook_bulk_delete_mails`, `outlook_set_category`, `outlook_save_mail_as`, `outlook_save_attachments`, `outlook_create_folder`, `outlook_create_task`, `outlook_complete_task`, `outlook_toggle_rule`.

Not used in v0.0.1 at all — do not call them even if asked; explain that the plugin does not send yet:

`outlook_send_mail`, `outlook_reply_mail`, `outlook_forward_mail`, `outlook_create_event`, `outlook_update_event`, `outlook_delete_event`, `outlook_respond_event`.

Free, no yes needed: `outlook_list_mails`, `outlook_search_mails`, `outlook_get_mail`, `outlook_get_conversation`, `outlook_export_mails` (writes only a file you asked for, under the vault), `outlook_list_folders`, `outlook_list_events`, `outlook_get_event`, `outlook_list_contacts`, `outlook_search_contacts`, `outlook_get_contact`, `outlook_resolve_name`, `outlook_list_tasks`, `outlook_list_categories`, `outlook_list_rules`, `outlook_get_out_of_office`, `outlook_whoami`.

## Things that bite

- First call after a cold start can take several seconds. Do not retry.
- `search_mails` matches all words in any order, not the phrase. Fewer, more specific words work better.
- `bulk_*` never raises on a stale id; check `failed > 0`.
- `set_category` and `bulk_mark_mails(categories=...)` replace the whole category list. Read `categories` from `get_mail` first if the user wants to keep existing ones.
- Only classic Outlook. If tools return nothing or are missing, read the outlook skill's `references/setup.md`.
