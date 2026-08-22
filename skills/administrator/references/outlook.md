# Outlook reference — plugin needs → `outlook_*` tools

This is a map, not a manual. Exact parameter tables, return shapes, and quirks are in the `outlook` skill: `references/tools.md` (parameters) and `references/gotchas.md` (failure modes). Read those the first time you call a tool in a session. Server: outlook-classic-mcp 0.4.0 or later with `outlook_get_conversation`, `internet_message_id`, `outlook_get_event_by_key`, `outlook_get_free_busy` and `outlook_find_meeting_times` (40 tools), classic Outlook only. The same package ships a second server, `vault` (`administrator-vault`, 8 tools `vault_*`), which writes the notes; see `references/vault.md` and the table at the end of this page.

Always pass `response_format="json"` when you will use a field from the result (an `entry_id`, a `conversation_id`, a `received` time). Use the default markdown only when the result itself is the answer for the user.

## Map

| Plugin need | Tool | Parameters to use | What to take from the result |
| --- | --- | --- | --- |
| Inbox window (`inbox`, `daily`) | `outlook_list_mails` | `unread_only=true`, `since=<ISO>`, `limit=100`, `folder` (default `inbox`, or the one the user named), `response_format="json"` | `items[]`: `entry_id, internet_message_id, subject, from, from_address, to, received, unread, has_attachments, importance, preview`. `has_more` / `next_offset` → page once more if needed. |
| Find a mail by words (`save`) | `outlook_search_mails` | `query=<words>`, `scope` = `subject_body` (default) / `subject` / `from`, `limit=5`, `response_format="json"` | Same item shape as `list_mails`. Show the user up to 5 candidates and let them pick. |
| The whole thread (`save` with "the thread", `followups`) | `outlook_get_conversation` | `entry_id=<any mail in the thread>`, `include_body=true`, `max_body_chars=0`, `limit=20`, `trim_quoted=true` when the bodies go into a note (always returns JSON) | `conversation_id`, `items[]` oldest first, each the `list_mails` item shape plus `conversation_id`, `folder`, `body` (and `body_trimmed`, `trimmed_chars`, `trim_markers` with `trim_quoted=true`). `truncated=true` → thread longer than `limit`. One item only when Outlook has no conversation (IMAP/POP, drafts). |
| Full mail for a note (`save`, ambiguous classification in `inbox`) | `outlook_get_mail` | `entry_id`, `response_format="json"`, `max_body_chars=10000` (raise only if `body_truncated`), `trim_quoted=true` for a note body, `include_body=false` when only `recipients` are needed | `entry_id, internet_message_id, conversation_id, subject, from, from_address, to, cc, recipients[{name,address,type}], received, sent, categories, attachments[{index,filename,size_bytes}], body`; with `trim_quoted=true` also `body_trimmed` (quoted history and signature removed), `trimmed_chars`, `trim_markers[]` |
| Many mails' metadata in one call, with `conversation_id` | `outlook_export_mails` | `entry_ids=[...]` or the same filters as `list_mails`, `fmt="json"`, `output_path=<vault>/Administrator/Attachments/_export/<date>.json`, `include_body=false` | File at `path`; columns `entry_id, subject, from, from_address, to, cc, received, sent, unread, flagged, has_attachments, importance, categories, conversation_id, internet_message_id`. Read the file, then delete it when done. |
| Export the mail itself (`save`, optional) | `outlook_save_mail_as` | `entry_id`, `output_dir=<vault>/Administrator/Attachments/<YYYY-MM-DD slug>`, `fmt="msg"` | `path` → `msg_file` in the note. Never overwrites; Outlook adds ` (1)`. |
| Export attachments (`save`, optional) | `outlook_save_attachments` | `entry_id`, `output_dir=<same folder>`, `attachment_index` (1-based) or omit for all | `files[]` → `attachments` list in the note. |
| Today's agenda (`daily`), meetings of a day or a week (`prep`, `notes`, `schedule`) | `outlook_list_events` | `start=<day 00:00>`, `end=<day 23:59:59>`, `include_recurrences=true`, `limit` (default 50, max 200), `response_format="json"` | `items[]`: `entry_id, global_id, occurrence_key, subject, start, end, location, organizer, organizer_address, attendees[{name,address,type,response}], response_status, is_recurring, recurrence_state, all_day, preview`. Clash = overlapping `start`/`end`. `occurrence_key` is the meeting note identity. |
| Find one occurrence again (`prep` re-run, `notes` by path) | `outlook_get_event_by_key` | `occurrence_key=<key>` (or `global_id=<id>` for the first occurrence in the window), `window_start=<start − 1 day>`, `window_end=<end + 1 day>`; JSON only | The full event (same keys as `outlook_get_event`). Not found → an error line "No event with global_id …" — treat as "not found", and in `prep` mark the note `status: cancelled`. |
| Full event after a booking or for a move (`schedule`) | `outlook_get_event` | `entry_id`, `response_format="json"` | Summary keys above plus `body`, `reminder_minutes`, `categories`. This is where `global_id` / `occurrence_key` come from after `outlook_create_event`. |
| Mail from an attendee (`prep`) | `outlook_list_mails` | `from_address=<SMTP>`, `since=<now − 30 days>`, `limit=10`, `response_format="json"` | Same item shape; dedupe across attendees by `internet_message_id`. |
| Mail about a subject (`prep`) | `outlook_search_mails` | `query=<2–4 subject words>`, `since=<now − 30 days>`, `limit=10`, `folder="inbox"` or `"sent"`, `response_format="json"` | Same item shape. |
| Who is free when (`schedule`) | `outlook_find_meeting_times` | `addresses=[smtp…]` (never the user's own), `start`, `end` (max 62 days), `duration_minutes`, `work_start`, `work_end`, `buffer_minutes` (from `Preferences.md`), `weekdays_only=true`, `include_self=true`, `max_results=15`; JSON only | `items[]`: `start, end, free[], unknown[]`; top-level `unknown[]`. An address in `unknown` has no free/busy (outside the tenant). |
| Raw busy blocks for one window (`schedule`, "what does Sam's Tuesday look like") | `outlook_get_free_busy` | `addresses` (max 20), `start`, `end`, `interval_minutes=30`; JSON only | `people[{address, resolved, has_data, slots[], busy_blocks[]}]`, `unknown[]`. |
| Book a meeting (`schedule`, after a yes) | `outlook_create_event` | `subject`, `start`, `end`, `attendees=[smtp…]`, `location`, `is_online_meeting`, `body`; JSON only | `{status: "created", entry_id, global_id, occurrence_key, subject, start, end, invite_sent}`. The invite is sent on success. |
| Move one meeting (`schedule`, after a yes) | `outlook_update_event` | `entry_id`, `start`, `end`, `send_update` (default true); JSON only | `{status: "updated", entry_id, update_sent}`. Attendees get the updated invite. |
| Minutes or proposed-times email to Drafts (`notes`, `schedule`, after a yes) | `outlook_send_mail` | `to=[...]`, `subject`, `body` (plain text), `save_only=true`; JSON only | Lands in Drafts; nothing is sent. `save_only=true` is mandatory. |
| Who is this person (`save` → person note `company`) | `outlook_search_contacts` | `query=<SMTP address or full name>`, `include_directory=true`, `limit=5` | `items[]`: `full_name, email, company, job_title`. Use `company` only when `email` equals the sender's SMTP. |
| Name → SMTP | `outlook_resolve_name` | `name` | `smtp_address` when `resolved=true`. |
| Folder path for a move offer | `outlook_list_folders` | `max_depth=4`, `response_format="json"` | `items[].path` — pass it verbatim as `target_folder`. |
| Category names for a category offer | `outlook_list_categories` | — | `items[].name`. Never use a name that is not in this list. |
| Which mailbox, which timezone | `outlook_whoami` | — | `accounts[].smtp_address` (the user's own address, to tell "from me" apart), `utc_offset`. |
| Mark read / flag / category in bulk (offered by `inbox`) | `outlook_bulk_mark_mails` | `entry_ids`, `read=true|false|null`, `flagged`, `categories=[...]` (replaces the list; `[]` clears) | `status`, `failed`, `failures[]`. Report failures by subject. |
| Move in bulk (offered by `inbox`) | `outlook_bulk_move_mails` | `entry_ids`, `target_folder=<path from list_folders>` | `results[].new_entry_id` — the old `entry_id` is dead after a cross-store move. |
| Single mark / move | `outlook_mark_mail`, `outlook_move_mail` | `entry_id` + the change | `unread` (not `read`) / `new_entry_id`. |
| Sent mail of the last 30 days (`followups`) | `outlook_list_mails` | `folder="sent"`, `since=<now − 30 days>`, `limit=100`, `offset=100` for one more page, `response_format="json"` | Same item shape; `received` of a sent item is the send time. No `conversation_id` — group with `outlook_get_conversation`. |

## Vault tools (`vault_*`, server `administrator-vault`)

Same package, second MCP server named `vault`. All paths are vault-relative with forward slashes and start with `Administrator/`; the server refuses anything else, reads included. Everything returns JSON; an error (missing key, duplicate on create, missing note on append, bad path) comes back as a tool error — fix the input and call again, never fall back to the file tools.

| Plugin need | Tool | Parameters to use | What to take from the result |
| --- | --- | --- | --- |
| Is the vault there, what is it called (every session, `setup`) | `vault_status` | — | `vault`, `exists`, `is_dir`, `administrator_dir_exists`, `folders{}`, `files{}`, `under_user_profile`, `vault_name` (for `obsidian://open?vault=…`). Never raises. |
| Create missing folders and files (`setup`, first use) | `vault_init` | `work_start`, `work_end`, `buffer_minutes`, `created_by="administrator/0.0.4"`; `overwrite=true` only on the user's say-so | `created[]`, `skipped[]`. Never overwrites `Follow-ups.md`. |
| Does a note exist (before every write) | `vault_find` | `type` (`email` / `meeting` / `person` / `daily` / `weekly`), `identity` object or string | `found`, `path`, `frontmatter`, `matches[]` (newest first) |
| Write or update a note | `vault_write` | `type`, `frontmatter` (object, every required key included, `created_by` too), `body` (markdown, no fences), `mode="upsert"` (`create` / `append` when you know) | `path`, `action` (`created` / `appended`), `identity`; on append also `update_heading`, `frontmatter_changed[]` |
| A row in `Follow-ups.md` or a daily table | `vault_append_row` | `path`, `section` (heading text without `## `), `row[]`, `dedupe_key`, `key_label` (`entry_id` default / `occurrence_key` / `internet_message_id` / `proposal`), `header[]` for a table that does not exist yet | `appended` true, or false with `reason: "duplicate"` and `line` |
| Close a follow-up | `vault_move_row` | `path`, `from_section`, `to_section`, `dedupe_key`, `set_last_cell=<date>` | `moved` true / false with `reason` |
| Read one note | `vault_read` | `path` | `frontmatter`, `body`, `sections[]` |
| Newest notes of a type (`inbox` window, `weekly`) | `vault_list` | `type`, `since` (ISO), `limit` | `[{path, frontmatter}]` newest first |

No `vault_*` call needs a yes except `vault_init(overwrite=true)`.

## Identity fields: where they come from

- `entry_id` — on every item from `list_mails`, `search_mails`, `get_mail`, `export_mails`. Opaque; quote it verbatim. Invalid after delete; changes after a move between stores.
- `internet_message_id` — the `Message-ID` header, on every item from `list_mails`, `search_mails`, `get_mail`, `get_conversation`, `export_mails`. This is the note identity. It is `""` for drafts and on some IMAP/POP stores; then use `entry_id` and write `internet_message_id: ""`.
- `conversation_id` — in `outlook_get_mail`, `outlook_get_conversation` items and `outlook_export_mails` rows. `list_mails` / `search_mails` do not include it. For a single mail, `get_mail` is the cheapest way; for a batch, one `export_mails(entry_ids=[...], fmt="json")` call beats N `get_mail` calls.
- `from_address` — a real SMTP address in 0.4.0 (the server resolves Exchange `EX:/O=...` senders). If a value still starts with `/O=`, the server could not resolve it: store it as is in `from`, and say so in the note's summary line.
- `recipients[]` (from `get_mail` only) gives SMTP addresses per recipient with `type` `to` / `cc` / `bcc`. The flat `to` / `cc` strings on list items are display names only.
- `received` — ISO with the user's local offset. Copy it unchanged into frontmatter; use its date part for filenames.
- `global_id` / `occurrence_key` — on every event item from `list_events`, `get_event`, `get_event_by_key`. `global_id` (Outlook's GlobalAppointmentID) is the same for all occurrences of a recurring meeting and survives a move; `occurrence_key` = `global_id|start` is unique per occurrence and is the meeting note identity. `entry_id` on an occurrence item is not stable; do not use it as identity. `outlook_create_event` returns neither — call `outlook_get_event` on its `entry_id`.

## Dates

All `since`, `until`, `start`, `end` parameters are ISO-8601 strings; with no offset they mean the user's local time, which is what you want. Work out "yesterday", "since Monday" yourself before calling. For the inbox window use the `inbox_checked` value from the most recent daily note's frontmatter (that note's date at 00:00 if the key is missing), else now minus 24 hours.

## Paths

`output_dir` and `output_path` must be absolute and under `C:\Users\<them>\`. The vault is the usual place; if `ADMINISTRATOR_VAULT` is outside the profile, exports fail with a sandbox error — tell the user about `OUTLOOK_MCP_ALLOW_ANY_PATH=1` from the outlook skill's setup notes rather than trying another path.

## Tools that need a yes first

Before any of these, list what will be affected (count, subjects, target) and wait for a clear yes in this conversation:

`outlook_mark_mail`, `outlook_bulk_mark_mails`, `outlook_move_mail`, `outlook_bulk_move_mails`, `outlook_delete_mail`, `outlook_bulk_delete_mails`, `outlook_set_category`, `outlook_save_mail_as`, `outlook_save_attachments`, `outlook_create_folder`, `outlook_create_task`, `outlook_complete_task`, `outlook_toggle_rule`, `outlook_send_mail` (only ever with `save_only=true`, only from the `meetings` or `schedule` skill, after the draft was shown), `outlook_create_event` with attendees (sends the invite; `schedule` only), `outlook_update_event` (sends an update; `schedule` only).

Not used by the plugin at all — do not call them even if asked; explain that the plugin does not send plain mail and does not cancel or answer invites:

`outlook_send_mail` with `save_only=false`, `outlook_reply_mail`, `outlook_forward_mail`, `outlook_delete_event`, `outlook_respond_event`.

Free, no yes needed: `outlook_list_mails`, `outlook_search_mails`, `outlook_get_mail`, `outlook_get_conversation`, `outlook_export_mails` (writes only a file you asked for, under the vault), `outlook_list_folders`, `outlook_list_events`, `outlook_get_event`, `outlook_get_event_by_key`, `outlook_get_free_busy`, `outlook_find_meeting_times`, `outlook_list_contacts`, `outlook_search_contacts`, `outlook_get_contact`, `outlook_resolve_name`, `outlook_list_tasks`, `outlook_list_categories`, `outlook_list_rules`, `outlook_get_out_of_office`, `outlook_whoami`.

## Things that bite

- First call after a cold start can take several seconds. Do not retry.
- `search_mails` matches all words in any order, not the phrase. Fewer, more specific words work better.
- `bulk_*` never raises on a stale id; check `failed > 0`.
- `set_category` and `bulk_mark_mails(categories=...)` replace the whole category list. Read `categories` from `get_mail` first if the user wants to keep existing ones.
- `outlook_get_free_busy` / `outlook_find_meeting_times` need Exchange; people outside the tenant come back in `unknown[]` with no data, not as an error. `find_meeting_times` works on a 15-minute grid.
- `outlook_update_event` saves the change and, for meetings the user organises, sends the updated invite to all attendees in the same call (`update_sent` in the result). Pass `send_update=false` only if the user explicitly wants a local-only change.
- Only classic Outlook. If tools return nothing or are missing, read the outlook skill's `references/setup.md`.
