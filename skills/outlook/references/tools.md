# Tool reference

Every `outlook_*` tool, with parameters, defaults, return shape, and notes on chaining. Skim the table of contents, then jump to the tools you need.

## Contents

- [Smaller results: `fields` and `preview_chars`](#smaller-results-fields-and-preview_chars)
- [Mail](#mail) — list_mails, search_mails, search_attachments, advanced_search, extract_attachment_text, get_mail, get_conversation, send_mail, reply_mail, forward_mail, move_mail, delete_mail, mark_mail, save_attachments, bulk_move_mails, bulk_delete_mails, bulk_mark_mails, export_mails, save_mail_as
- [Mail (computed)](#mail-computed) — awaiting_reply, find, voice_sample
- [Folders](#folders) — list_folders, create_folder
- [Calendar](#calendar) — list_events, get_event, get_event_by_key, create_event, update_event, delete_event, respond_event
- [Availability](#availability) — get_free_busy, find_meeting_times
- [Contacts](#contacts) — list_contacts, search_contacts, get_contact, resolve_name
- [Tasks](#tasks) — list_tasks, create_task, complete_task
- [Categories](#categories) — list_categories, set_category
- [Rules](#rules) — list_rules, toggle_rule
- [Out-of-Office](#out-of-office) — get_out_of_office
- [Account](#account) — whoami
- [Common return-field glossary](#common-return-field-glossary)

---

## Smaller results: `fields` and `preview_chars`

The default JSON of a list or search is the biggest cost of a session. Two parameters cut it down; they never change what is searched, only what comes back.

- `fields` (list of strings, optional) — on `list_mails`, `search_mails`, `get_mail`, `get_conversation`, `list_events`, `get_event`, `advanced_search`, `search_attachments`. When given, every returned item keeps only those keys. `entry_id` is always kept so the item can still be passed on; unknown names are ignored (no error), so you can ask for a key that only some shapes carry. For `get_mail` and `get_event` the filter applies to the record itself. Collections echo the list back as `fields`. Example: `outlook_list_mails(unread_only=true, fields=["from_address", "subject", "received", "preview"], preview_chars=80)` returns five keys per mail instead of twelve.
- `preview_chars` (int, default `200`, `0` = no preview) — on `list_mails`, `search_mails`, `get_conversation`. Sets the length of each item's `preview`; `0` leaves the key out and skips reading the body altogether, which is also faster on big folders.
- Free/busy has its own switches: `get_free_busy(busy_blocks_only=true)` (default) drops the per-slot `slots` array and keeps the merged `busy_blocks`; `find_meeting_times(include_slots=false)` (default) returns candidates only, `true` adds `people[]` with every person's slots.

Rule of thumb: ask for the keys you will actually read. If you will only show subjects and pick an `entry_id`, pass `fields=["subject", "from", "received"]` and `preview_chars=0`.

## Mail

### `outlook_list_mails`

List mail items from a folder, newest first. Read-only.

| Param            | Type      | Default     | Notes |
| ---------------- | --------- | ----------- | ----- |
| `folder`         | string    | `"inbox"`   | Well-known name or path. See SKILL.md → Folder references. |
| `limit`          | int 1–100 | `25`        | Max items to return. |
| `offset`         | int ≥0    | `0`         | Skip this many before returning. Use with the returned `next_offset` to paginate. |
| `unread_only`    | bool      | `false`     | If true, only unread mails. |
| `since`          | ISO-8601  | `null`      | Lower bound on `ReceivedTime`. |
| `until`          | ISO-8601  | `null`      | Upper bound on `ReceivedTime`. |
| `from_address`   | string    | `null`      | **Substring** match on sender SMTP address (Exchange `EX` senders are resolved, so `@corp.com` works). Applied server-side via DASL. |
| `has_attachments`| bool/null | `null`      | `true` = only with attachments, `false` = only without. |
| `fields`         | string[]  | `null`      | Keep only these keys per item (`entry_id` always kept). See [Smaller results](#smaller-results-fields-and-preview_chars). |
| `preview_chars`  | int 0–5000| `200`       | Length of `preview`; `0` leaves it out. |
| `response_format`| `markdown`/`json` | `markdown` | Use `json` to extract `entry_id`s. |

**Returns** (`json` shape): `{ folder, count, offset, limit, items: [...], has_more, next_offset }`. Each item has: `entry_id, internet_message_id, subject, from, from_address, to, received, unread, flagged, has_attachments, importance, bulk, bulk_why, preview` (body excerpt of `preview_chars`). `from_address` is always a real SMTP address when Outlook can resolve one. `bulk` is true when a machine wrote the mail — a `List-Unsubscribe`, `Precedence: bulk / list / junk`, `Auto-Submitted` other than `no` or `X-Auto-Response-Suppress` header, a no-reply / newsletter / marketing / alerts sender, or the message class of a meeting response, read receipt or out-of-office reply — and `bulk_why` names the signal that decided it (`""` when it is not bulk). The headers behind it cost one read per mail, so they are only read when `bulk` is among `fields` (or no `fields` were given); ask for it whenever a run should leave machine mail unread. `outlook_get_mail` has no such field.

### `outlook_search_mails`

Search a single folder by subject/body, subject-only, sender, or raw DASL. Read-only.

| Param            | Type     | Default          | Notes |
| ---------------- | -------- | ---------------- | ----- |
| `query`          | string   | required         | Search words (ALL must match, any order) — or a DASL @SQL filter when `scope='dasl'`. |
| `folder`         | string   | `"inbox"`        | Where to search. |
| `scope`          | enum     | `"subject_body"` | `subject_body` (default), `subject`, `from`, or `dasl`. |
| `limit`          | int 1–100| `25`             | |
| `since` / `until`| ISO-8601 | `null`           | Bounds on `ReceivedTime`, combined into the same DASL filter. Ignored for `scope='dasl'`. |
| `unread_only`    | bool     | `false`          | Ignored for `scope='dasl'`. |
| `has_attachments`| bool/null| `null`           | Ignored for `scope='dasl'`. |
| `fields`         | string[] | `null`           | Keep only these keys per item. |
| `preview_chars`  | int      | `200`            | `0` = no preview. |
| `response_format`| str      | `markdown`       | |

**Returns**: `{ query, scope, folder, count, items: [...] }`. Items have the same summary shape as `list_mails`, `bulk` / `bulk_why` included.

Multi-word queries match items containing **all** the words (not the exact phrase), so `"teams not working"` finds "MESP-1 teams is not working". `scope='from'` matches display name, raw address, **and** the real SMTP address (works for Exchange senders too).

`scope='dasl'` is for power use — pass a complete `@SQL=...` filter and the server applies it raw. Only reach for this when subject_body/subject/from can't express what the user wants.

### `outlook_search_attachments`

Find mails by **attachment filename** ("the spreadsheet Sam sent", "that PDF about the lease"). Read-only. Only mails that have attachments are opened (DASL `hasattachment = 1` plus `since`), so it stays fast on big folders.

| Param                | Type      | Default   | Notes |
| -------------------- | --------- | --------- | ----- |
| `query`              | string    | required  | Words that must **all** appear in the filename, any order, case-insensitive (`"budget q3"` finds `Q3_Budget_final.xlsx`). With `*` or `?` it is a glob over the whole name (`"*.pdf"`, `"invoice*.xlsx"`). |
| `folder`             | string    | `"inbox"` | Folder to start in. |
| `since`              | ISO-8601  | `null`    | Lower bound on `ReceivedTime`. |
| `limit`              | int 1–200 | `50`      | Max mails returned. |
| `include_subfolders` | bool      | `true`    | Walk every folder below `folder` too. |
| `fields`             | string[]  | `null`    | Keep only these keys per item (`matches` and `folder` count as keys). |

**Returns** (always JSON): `{ query, folder, folders_searched, count, truncated, items: [...] }`. Each item is the `list_mails` summary shape without `bulk` / `bulk_why`, plus `folder` (the folder it sits in) and `matches: [{index, filename, size_bytes}]` — only the attachments that matched. `index` is 1-based and goes straight into `save_attachments` or `extract_attachment_text`. Inline images (hidden attachments such as signature logos) never match. Newest first across all folders searched.

### `outlook_advanced_search`

Search **every folder of every store at once** through Outlook's Windows Search index (`Application.AdvancedSearch`). Because it is the index, it also matches the **contents of attachments** (PDF, Word, Excel...) when the store is indexed. Read-only.

| Param         | Type      | Default | Notes |
| ------------- | --------- | ------- | ----- |
| `query`       | string    | required | Words that must all match (index phrase match, `ci_phrasematch`) in subject, body, or indexed attachment text. |
| `scope`       | string    | `"all"` | `all` = the root of every store (mailbox, archive, PSTs). Or one folder name/path — searched with its sub-folders. |
| `since`       | ISO-8601  | `null`  | Lower bound on `ReceivedTime`. |
| `limit`       | int 1–200 | `50`    | Max mails returned, newest first. |
| `timeout_sec` | int 1–55  | `20`    | How long to wait for the index. What has arrived by then is returned with `timed_out: true`. |
| `fields`      | string[]  | `null`  | Keep only these keys per item. |

**Returns** (always JSON): `{ query, scope, filter, count, total_found, timed_out, items: [...] }`. Items are the `list_mails` summary shape plus `folder`, without `bulk` / `bulk_why` (only `list_mails` and `search_mails` work those out). `filter` is the `@SQL=` string that was run (useful when nothing comes back). The index returns results in no particular order; the server sorts by `ReceivedTime` newest-first before applying `limit`.

Needs Outlook's indexing to be on (see gotchas). `count: 0` with `timed_out: false` on an unindexed store means "not indexed", not "no such mail" — fall back to `search_mails` per folder or `search_attachments`.

### `outlook_extract_attachment_text`

Read the **text inside one attachment** without leaving a file behind. The attachment is saved to a temporary folder under the user's profile (`%LOCALAPPDATA%\outlook-mcp\tmp`), the text pulled out, and the file deleted again. Read-only from Outlook's point of view.

| Param       | Type   | Default | Notes |
| ----------- | ------ | ------- | ----- |
| `entry_id`  | string | required | The mail. |
| `index`     | int ≥1 | required | 1-based attachment index from `get_mail.attachments[]` or `search_attachments.matches[]`. |
| `max_chars` | int ≥0 | `20000` | Truncate beyond this; `0` = no limit. |

**Returns** (always JSON): `{ entry_id, index, filename, kind, chars, truncated, text }`. `kind` is one of `pdf`, `docx`, `xlsx`, `pptx`, `text` (`.txt`, `.csv`, `.md`, `.log`, `.json`, `.xml`, `.html`). `chars` is the full length before truncation. Excel text is one line per row with cells separated by tabs, one block per sheet headed `# <sheet name>`; PowerPoint is one block per slide.

Any other file type (`.zip`, `.msg`, images, `.doc`/`.xls` old binary formats) is an error naming the supported types — use `save_attachments` and tell the user where the file is. PDF and Excel need the optional `search` extra of the integration (`pypdf`, `openpyxl`); the error message says so when it is missing.

### `outlook_get_mail`

Fetch the body, all headers, and the attachment manifest for one mail. Read-only.

| Param            | Type   | Default | Notes |
| ---------------- | ------ | ------- | ----- |
| `entry_id`       | string | required | From a list/search result. |
| `include_body`   | bool   | `true`   | If false, omits `body`. Useful when you only need metadata. |
| `include_html`   | bool   | `false`  | Adds the raw `html_body`. Usually huge — leave off unless you specifically need the markup. |
| `max_body_chars` | int ≥0 | `10000`  | Body truncation cap; `0` = unlimited. |
| `trim_quoted`    | bool   | `false`  | Adds `body_trimmed`, `trimmed_chars`, `trim_markers` (see below). `body` is never altered. |
| `fields`         | string[] | `null` | Keep only these keys of the record (`entry_id` always kept). `fields=["recipients", "conversation_id"]` with `include_body=false` is the cheapest way to get SMTP recipients. |
| `response_format` | str | `markdown` | |

**Returns**: `{ entry_id, conversation_id, internet_message_id, subject, from, from_address, to, cc, bcc, recipients: [{name, address, type}], received, sent, unread, importance, categories, attachments: [{index, filename, size_bytes}], body }` — `recipients[].address` is the SMTP address and `type` is `to` / `cc` / `bcc` (the flat `to` / `cc` strings are display names), plus `body_truncated`/`body_total_chars` when the cap was hit (re-call with a higher `max_body_chars` to read more) and `html_body` when `include_html=true`. `internet_message_id` is the RFC 5322 `Message-ID` header (`""` for drafts) — use it to correlate with other systems; it also appears on list/search summaries and export rows.

With `trim_quoted=true` each body-bearing result also carries `body_trimmed` (the new content only: quoted history after Outlook/OWA/Gmail reply headers, `Von:`/`De:`/`Da:` blocks, `>`-quoted runs, and the trailing signature — `-- `, "Sent from my ...", or the sender's name followed by phone/title lines — are cut), `trimmed_chars` (how many characters were removed) and `trim_markers` (which rules fired, e.g. `["header block", "name signature"]`; `["kept: too short"]` means trimming would have left under 20 chars so the full body was kept; `[]` means nothing matched). Trimming is deterministic and text-based — prefer `body_trimmed` when summarising a thread, fall back to `body` when a marker looks wrong.

### `outlook_get_conversation`

Return every mail in the thread that contains a given mail, oldest first, including replies filed in other folders (Sent Items, sub-folders). Read this before drafting a reply to a long exchange.

| Param            | Type   | Default | Notes |
| ---------------- | ------ | ------- | ----- |
| `entry_id`       | string | required | Any mail in the thread. |
| `include_body`   | bool   | `false` | Add each mail's plain-text `body`. |
| `max_body_chars` | int ≥0 | `2000`  | Per-mail truncation; `0` = unlimited. |
| `limit`          | int 1–500 | `200` | Max mails returned (oldest first). |
| `trim_quoted`    | bool   | `false` | With `include_body`, adds `body_trimmed` / `trimmed_chars` / `trim_markers` per item (same rules as `get_mail`). Use it to read a long thread without every mail repeating the ones before it. |
| `fields`         | string[] | `null` | Keep only these keys per item. `fields=["from_address", "received", "body_trimmed"]` with `trim_quoted=true` is the usual way to read a thread. |
| `preview_chars`  | int    | `200`   | `0` = no preview (pointless next to `body` anyway). |

**Returns** (always JSON): `{ conversation_id, count, truncated, items: [...] }`. Each item is the `list_mails` summary shape plus `conversation_id`, `folder`, and (with `include_body`) `body` / `body_truncated` / `body_total_chars`, plus `body_trimmed` / `trimmed_chars` / `trim_markers` when `trim_quoted=true`. If Outlook has no conversation for the item (IMAP/POP stores, drafts), `items` contains just that one mail.

`attachments[].index` is **1-indexed**; pass it to `save_attachments` to save a single file.

### `outlook_send_mail`

Compose and send a new mail, or save it to Drafts. Has external side effect.

| Param          | Type      | Default   | Notes |
| -------------- | --------- | --------- | ----- |
| `to`           | list[str] | required  | One or more SMTP addresses. |
| `subject`      | string    | required  | |
| `body`         | string    | required  | Plain text unless `html=true`. |
| `cc`           | list[str] | `null`    | |
| `bcc`          | list[str] | `null`    | |
| `html`         | bool      | `false`   | When true, `body` is HTML. |
| `attachments`  | list[str] | `null`    | Absolute paths under user profile. |
| `importance`   | enum      | `"normal"`| `low` / `normal` / `high`. |
| `save_only`    | bool      | `false`   | **Save to Drafts instead of sending.** |

**Returns** (sent): `{ status: "sent", to, cc, bcc, subject }`. (Drafts): `{ status: "saved_to_drafts", entry_id, subject }`.

Always confirm the recipient list and subject with the user before calling this tool unless they have explicitly authorized you to send.

### `outlook_reply_mail`

Reply (or reply-all) to an existing mail. The original message is appended below your body, the same way Outlook's Reply button does it. Has external side effect.

| Param         | Type      | Default | Notes |
| ------------- | --------- | ------- | ----- |
| `entry_id`    | string    | required | The mail being replied to. |
| `body`        | string    | required | Your reply text. The quoted original is appended automatically. |
| `reply_all`   | bool      | `false`  | If true, includes the original CC list. |
| `html`        | bool      | `false`  | |
| `attachments` | list[str] | `null`   | |
| `save_only`   | bool      | `false`  | **Save the reply to Drafts instead of sending.** The draft keeps the thread headers, so it shows up under the original conversation and the user sends it from Outlook. |

**Returns** (sent): `{ status: "sent", reply_all, in_reply_to, subject }`. (Drafts): `{ status: "saved", reply_all, in_reply_to, entry_id, subject }` — `entry_id` is the draft.

Prefer `save_only=true` for "draft a reply for me to look at" requests; it beats building the reply by hand with `send_mail(save_only=true)` because the recipients and the quoted original come from Outlook.

### `outlook_forward_mail`

Forward an existing mail to new recipients with an optional note above. Has external side effect.

| Param      | Type      | Default | Notes |
| ---------- | --------- | ------- | ----- |
| `entry_id` | string    | required | |
| `to`       | list[str] | required | |
| `body`     | string    | `""`     | Optional note prepended to the forwarded content. |
| `cc`       | list[str] | `null`   | |
| `html`     | bool      | `false`  | |
| `save_only`| bool      | `false`  | Save the forward to Drafts instead of sending. |

**Returns** (sent): `{ status: "sent", forwarded, to, subject }`. (Drafts): `{ status: "saved", forwarded, to, entry_id, subject }`.

### `outlook_move_mail`

Move a mail to another folder.

| Param           | Type   | Default | Notes |
| --------------- | ------ | ------- | ----- |
| `entry_id`      | string | required | |
| `target_folder` | string | required | Well-known name or path. |

**Returns**: `{ status: "moved", new_entry_id, folder }`.

The `entry_id` changes when an item moves stores. **Use the returned `new_entry_id`** if you need to act on the moved item again.

### `outlook_delete_mail`

Soft-delete (moves to Deleted Items). Reversible by the user from Outlook.

| Param      | Type   | Default | Notes |
| ---------- | ------ | ------- | ----- |
| `entry_id` | string | required | |

**Returns**: `{ status: "deleted", subject, entry_id }`.

### `outlook_mark_mail`

Toggle read state and/or follow-up flag.

| Param      | Type | Default | Notes |
| ---------- | ---- | ------- | ----- |
| `entry_id` | string | required | |
| `read`     | bool/null | `null` | `true` = mark read, `false` = mark unread, `null` = no change. |
| `flagged`  | bool/null | `null` | `true` = flag for follow-up, `false` = clear flag, `null` = no change. |

**Returns**: `{ status: "updated", entry_id, unread, flagged }`.

### `outlook_save_attachments`

Save one or all attachments from a mail to a local directory.

| Param              | Type    | Default | Notes |
| ------------------ | ------- | ------- | ----- |
| `entry_id`         | string  | required | |
| `output_dir`       | string  | required | Absolute path under user profile. Created if missing. |
| `attachment_index` | int ≥1  | `null`  | 1-indexed. Omit to save all. |

**Returns**: `{ status: "saved", count, files: [absolute paths], output_dir }`.

### `outlook_bulk_move_mails` / `outlook_bulk_delete_mails` / `outlook_bulk_mark_mails`

Apply one operation to many mails in a single call. Prefer these over looping `move_mail` / `delete_mail` / `mark_mail` whenever you have more than a handful of ids.

| Param           | Type          | Default  | Notes |
| --------------- | ------------- | -------- | ----- |
| `entry_ids`     | string[] 1–500| required | From `list_mails` / `search_mails` with `response_format='json'`. |
| `target_folder` | string        | required | `bulk_move_mails` only. |
| `read` / `flagged` | bool/null  | `null`   | `bulk_mark_mails` only; `null` = no change. |
| `categories`    | string[]/null | `null`   | `bulk_mark_mails` only. Replaces the category list; `[]` clears it. |
| `stop_on_error` | bool          | `false`  | Abort at first failure instead of continuing. |

**Returns**: `{ status: "ok"|"partial"|"failed", requested, succeeded, failed, results: [{entry_id, subject, ...}], failures: [{entry_id, error}] }`. A stale id is reported in `failures`, not raised — check `failed > 0` before telling the user everything succeeded. `bulk_move_mails` results carry `new_entry_id`.

### `outlook_export_mails`

Write mail metadata to a CSV or JSON file so it can be opened in Excel or consumed by a script, without streaming rows through the chat.

| Param          | Type     | Default   | Notes |
| -------------- | -------- | --------- | ----- |
| `output_path`  | string   | required  | Absolute `.csv` or `.json` path under the user profile. Parent folders are created. |
| `entry_ids`    | string[] | `null`    | If given, export exactly these and ignore folder/filters. |
| `folder`, `limit` (1–10000), `unread_only`, `since`, `until`, `from_address`, `has_attachments` | | | Same semantics as `list_mails`. |
| `include_body` | bool     | `false`   | Adds a `body` column (plain text). |
| `max_body_chars`| int     | `2000`    | Body truncation; `0` = unlimited. |
| `fmt`          | `csv`/`json` | `csv` | CSV is written with a UTF-8 BOM so Excel opens it correctly. |

Columns: `entry_id, subject, from, from_address, to, cc, received, sent, unread, flagged, has_attachments, importance, categories, conversation_id, internet_message_id[, body]`.

**Returns**: `{ status: "exported", format, path, source, count, truncated, failures }`. Report `path` and `count` to the user; `truncated=true` means the folder query hit `limit`.

### `outlook_save_mail_as`

Save one mail to disk.

| Param        | Type   | Default  | Notes |
| ------------ | ------ | -------- | ----- |
| `entry_id`   | string | required | |
| `output_dir` | string | required | Absolute directory under user profile. |
| `fmt`        | `msg`/`txt`/`html` | `msg` | `.msg` keeps attachments and headers and re-opens in Outlook. |
| `filename`   | string | `null`   | Bare name only. Defaults to a sanitized subject. Existing files are never overwritten — ` (1)`, ` (2)` is appended. |

**Returns**: `{ status: "saved", entry_id, format, path, subject }`.

---

## Mail (computed)

Three read-only tools that do a whole job in code and return only the answer, so you do not have to page through lists and bodies yourself. Always JSON. None of them writes anything.

### `outlook_awaiting_reply`

Threads where the user wrote last and nobody has answered. Replaces "list sent mail, fetch every conversation, compare dates" with one call.

| Param        | Type      | Default  | Notes |
| ------------ | --------- | -------- | ----- |
| `days`       | int 0–365 | `3`      | A thread counts when the user's last mail is at least this many days old. |
| `since_days` | int 1–365 | `30`     | How far back to read the sent folder. |
| `limit`      | int 1–200 | `50`     | Max threads returned, longest wait first. |
| `folder`     | string    | `"sent"` | The folder holding the user's sent mail. |

How it works: sent mail newer than `since_days` is walked newest first, calendar responses / auto-replies / read receipts and mails with an empty `To` are skipped, and mails are grouped by `conversation_id`. Each conversation is read once (at most 60; `capped: true` when the cap was hit — narrow `since_days`). A thread is **waiting** when its newest mail is from the user (`whoami` address, compared case-insensitively; on profiles without a current user, the sender of the sent mail), is older than `days`, and went to somebody other than the user.

**Returns**: `{ days, since, folder, self, sent_scanned, threads_checked, capped, count, items: [...] }`. Each item: `{ conversation_id, entry_id, internet_message_id, subject, to: [smtp...], to_names, last_sent, days_waiting, last_line }` — `entry_id` / `internet_message_id` are the user's last mail in the thread (the note key for a follow-up row), `to` lists SMTP recipients other than the user (`to` first, `cc` when there is no other `to`), `to_names` is the raw display string, `days_waiting` counts local dates, and `last_line` is the last meaningful line the user wrote (sign-offs, the user's name and signature details are skipped; max 200 chars; falls back to the start of the body). Sorted by `days_waiting`, longest first.

### `outlook_find`

Runs the "find that email" search plan in code: per folder, one `from` search per person and one subject/body search per word, merged into one mail per conversation and scored.

| Param                | Type      | Default              | Notes |
| -------------------- | --------- | -------------------- | ----- |
| `people`             | string[]  | `[]`                 | Names or addresses to match on the sender. Each becomes a `scope='from'` search. |
| `words`              | string[]  | `[]`                 | Topic words, 2–4 work best. Each becomes a `scope='subject_body'` search. At least one person or word is required. |
| `since` / `until`    | ISO-8601  | `null`               | Bounds on `ReceivedTime`, pushed into every search. |
| `folders`            | string[]  | `["inbox", "sent"]`  | Folders to search, in order (well-known names or paths). |
| `include_subfolders` | bool      | `false`              | Also walk every folder below each listed folder. |
| `limit`              | int 1–50  | `10`                 | Max threads returned, best score first. |

Scoring per candidate (the newest mail of its conversation): each matching person `+3` (name or address found in the sender's name or SMTP address), each word in the subject `+2`, each word in the trimmed body `+1` (bodies are read only for the 20 best candidates after the first pass — `body_read` says whether it happened), received inside `since`/`until` `+1`. Ties go to the newer mail. `snippet` is the sentence of the trimmed body (split on `.`, `!`, `?` and line breaks) that holds the most query words, cut to 200 characters; empty when the body was not read.

**Returns**: `{ people, words, since, until, folders, folders_searched, searches, candidates, count, items: [...] }`. Each item: `{ entry_id, conversation_id, subject, from_address, received, score, snippet, folder, body_read }`. Read the top 1–3 with `get_conversation(trim_quoted=true, fields=[...])` when the snippet is not enough. Note that the newest mail of a thread may be the user's own reply, which scores no person points — that is why the person search and the word search both feed the same pool.

### `outlook_voice_sample`

How the user writes, from their own sent mail — for drafting a reply, a nudge or minutes in their voice.

| Param       | Type       | Default | Notes |
| ----------- | ---------- | ------- | ----- |
| `address`   | string     | `null`  | Use mails sent to this address (substring match on the recipients) when at least 3 exist in the newest 300 sent mails; otherwise the newest sent mails overall. |
| `n`         | int 1–50   | `10`    | How many mails to sample. |
| `max_chars` | int 50–5000| `300`   | Length of each `opening`. |

Each sampled body is trimmed first (quoted history and signature removed, same rules as `trim_quoted`), so the sample is the user's own words only.

**Returns**: `{ address, used_address, matched, scanned, count, items: [...], stats }`. Each item: `{ entry_id, to: [smtp...], subject, sent, opening, closing: [last two non-empty lines] }`. `used_address: false` means the fallback to overall sent mail happened (`matched` says how many were found). `stats`: `{ avg_chars, greeting_counts, signoff_counts }` — `avg_chars` of the trimmed bodies, `greeting_counts` the first word of each first line (two words for "good morning" / "guten Morgen") with counts, `signoff_counts` the sign-off line near the end (known sign-offs such as "thanks", "best regards", "viele grüße", or any short closing line; the user's name and phone/URL lines are skipped). Lowercased, trailing punctuation removed, highest count first.

---

## Folders

### `outlook_list_folders`

Walk the folder tree under a root.

| Param            | Type    | Default | Notes |
| ---------------- | ------- | ------- | ----- |
| `root`           | string  | `null`  | Folder to start from. Default = the default mailbox root. |
| `max_depth`      | int 1–10| `4`     | How deep to walk. |
| `response_format`| str     | `markdown` | |

**Returns**: `{ count, items: [{name, path, item_count, unread_count, default_item_type}, ...] }`. The `path` strings are exactly what you pass back as a `folder` parameter elsewhere.

### `outlook_create_folder`

Create a sub-folder under a parent.

| Param    | Type   | Default   | Notes |
| -------- | ------ | --------- | ----- |
| `name`   | string | required  | New folder name. |
| `parent` | string | `"inbox"` | Where to put it. |

**Returns**: `{ name, path, entry_id }`.

---

## Calendar

### `outlook_list_events`

List calendar events in a date range, including expanded recurring instances.

| Param                 | Type    | Default        | Notes |
| --------------------- | ------- | -------------- | ----- |
| `start`               | ISO-8601| now            | |
| `end`                 | ISO-8601| `start + 14d`  | |
| `limit`               | int 1–200| `50`          | |
| `include_recurrences` | bool    | `true`         | If false, only the master entries — usually you want true. |
| `fields`              | string[]| `null`         | Keep only these keys per event (`entry_id` always kept). `["subject", "start", "end", "location", "organizer", "occurrence_key"]` is enough for an agenda. |
| `response_format`     | str     | `markdown`     | |

**Returns**: `{ start, end, count, items: [...] }`. Items carry the **event shape** below (without `body`).

#### Event shape (shared by `list_events`, `get_event`, `get_event_by_key`)

| Field | Notes |
| ----- | ----- |
| `entry_id` | Outlook EntryID. For an occurrence of a recurring series this is the *master's* EntryID — not unique per occurrence. |
| `global_id` | `GlobalAppointmentID` — stable across mailboxes (same value in the organizer's and every attendee's calendar). Shared by all occurrences of a series. `""` if Outlook has none. |
| `occurrence_key` | `"<global_id>|<start ISO>"`. **Unique per occurrence** of a recurring series; the key to persist externally and feed back into `get_event_by_key`. |
| `subject`, `start`, `end`, `location`, `all_day`, `preview` | As before (`preview` = 200-char body excerpt). |
| `organizer` | Organizer display name. |
| `organizer_address` | Organizer SMTP address (resolved via `GetOrganizer().GetExchangeUser()` → `PR_SMTP_ADDRESS` → falls back to the display name when unresolvable). |
| `attendees` | `[{name, address, type, response}]` — `address` is a real SMTP address (Exchange DNs resolved); `type` ∈ `required` / `optional` / `resource`; `response` ∈ `none` / `organizer` / `tentative` / `accepted` / `declined` / `notresponded`. |
| `response_status` | The *user's own* RSVP status, same vocabulary as `attendees[].response`. |
| `is_recurring` | bool. |
| `recurrence_state` | `not_recurring` / `master` / `occurrence` / `exception`. |

### `outlook_get_event`

Full event detail, including attendees and their RSVP status.

| Param      | Type   | Default | Notes |
| ---------- | ------ | ------- | ----- |
| `entry_id` | string | required | |
| `fields`   | string[] | `null` | Keep only these keys of the record. |
| `response_format` | str | `markdown` | |

**Returns**: event shape + `body, reminder_minutes, categories`.

### `outlook_get_event_by_key`

Find an event by its stable `global_id` / `occurrence_key` instead of EntryID — use this when correlating with an external system (a meeting tracked in a ticket, a key stored from a previous session) or to pin one occurrence of a recurring series. Read-only; always returns JSON.

| Param            | Type     | Default | Notes |
| ---------------- | -------- | ------- | ----- |
| `occurrence_key` | string   | `null`  | `"<global_id>|<ISO start>"` exactly as returned on events. Matches one occurrence. |
| `global_id`      | string   | `null`  | Used when `occurrence_key` is omitted; returns the first item of the series inside the window. Pass one of the two. |
| `window_start`   | ISO-8601 | `null`  | Defaults to the key's start − 1 day (or now when only `global_id` is given). |
| `window_end`     | ISO-8601 | `null`  | Defaults to the key's start + 1 day (or `window_start + 14d`). |

**Returns**: the same full record as `get_event` (event shape + `body, reminder_minutes, categories`). Raises "No event with global_id ..." when nothing in the window matches — widen the window or re-list.

### `outlook_create_event`

Create a calendar event or meeting invite. **Adding any attendee turns this into a meeting that is sent immediately on success — there is no draft state for meeting invites.**

| Param               | Type           | Default | Notes |
| ------------------- | -------------- | ------- | ----- |
| `subject`           | string         | required | |
| `start`             | ISO-8601       | required | |
| `end`               | ISO-8601       | required | |
| `location`          | string         | `null`  | |
| `body`              | string         | `null`  | |
| `attendees`         | list[str]      | `null`  | Email addresses. Adding any value here makes this a meeting and sends invites. |
| `is_online_meeting` | bool           | `false` | Reserved — current behavior is to mark the meeting; the actual Teams/Zoom link is added by Outlook clients. |
| `reminder_minutes`  | int 0–10080    | `15`    | Minutes before start. |
| `recurrence`        | Recurrence obj | `null`  | See SKILL.md → Recurrence. |

**Returns**: `{ status: "created", entry_id, global_id, occurrence_key, subject, start, end, invite_sent }`. `invite_sent` is true when attendees were given.

Confirm attendee list, times, and recurrence with the user before calling.

### `outlook_update_event`

Update fields on an event. Only non-null fields are written. Does **not** modify recurrence — for cadence changes, delete and recreate.

| Param      | Type     | Default | Notes |
| ---------- | -------- | ------- | ----- |
| `entry_id` | string   | required | |
| `subject`  | string   | `null`  | |
| `start`    | ISO-8601 | `null`  | |
| `end`      | ISO-8601 | `null`  | |
| `location` | string   | `null`  | |
| `body`     | string   | `null`  | |
| `send_update` | bool  | `true`  | For meetings the user organises: send the updated invite to attendees after saving. `false` saves locally only. |

**Returns**: `{ status: "updated", entry_id, update_sent }`. `update_sent` is true only when the item is a meeting the user organises, it has attendees, and `send_update` was true — then every attendee receives the updated invite immediately. Received meetings and plain appointments never send.

### `outlook_delete_event`

Delete a calendar event. **If the event has attendees, this sends a cancellation notice.**

**Returns**: `{ status: "deleted", subject, entry_id }`.

### `outlook_respond_event`

Respond to a meeting invite.

| Param           | Type   | Default | Notes |
| --------------- | ------ | ------- | ----- |
| `entry_id`      | string | required | |
| `response`      | enum   | required | `accept` / `tentative` / `decline`. |
| `send_response` | bool   | `true`   | Set false to record locally without emailing the organizer. |

**Returns**: `{ status: "responded", response }`.

---

## Availability

Both tools read Exchange free/busy via `Recipient.FreeBusy`. They need an Exchange/Microsoft 365 account; on IMAP/POP profiles every address comes back in `unknown`. People **outside the tenant** resolve but have no free/busy data, so they also land in `unknown` — never claim they are free. Read-only; always JSON.

### `outlook_get_free_busy`

Per-person availability slots for a window.

| Param              | Type          | Default | Notes |
| ------------------ | ------------- | ------- | ----- |
| `addresses`        | list[str] 1–20| required | SMTP addresses. |
| `start`            | ISO-8601      | required | |
| `end`              | ISO-8601      | required | At most 62 days after `start`. |
| `interval_minutes` | int 1–1440    | `30`    | Slot granularity. Outlook reports one status per interval, so a 10-minute meeting inside a 30-minute slot marks the whole slot busy. |
| `busy_blocks_only` | bool          | `true`  | Leave out the per-slot `slots` array (one entry per interval — hundreds per person per week) and return only `busy_blocks`. Pass `false` when you need every slot. |

**Returns**: `{ start, end, interval_minutes, count, people: [...], unknown: [...] }`. Each person: `{ address, resolved, has_data, busy_blocks: [{start, end, status}] }` plus `slots: [{start, end, status}]` when `busy_blocks_only=false` — `status` ∈ `free` / `tentative` / `busy` / `oof` / `elsewhere`; `busy_blocks` is the non-free slots merged into contiguous runs of the same status (the thing to show the user). `resolved=false` means the address is not in the address book; `resolved=true, has_data=false` means no free/busy was published (external person, or not Exchange). `unknown` lists both kinds.

### `outlook_find_meeting_times`

Candidate start times when everyone with free/busy data is free.

| Param              | Type      | Default  | Notes |
| ------------------ | --------- | -------- | ----- |
| `addresses`        | list[str] | required | Attendees. |
| `start` / `end`    | ISO-8601  | required | Search window, max 62 days. |
| `duration_minutes` | int       | required | |
| `work_start` / `work_end` | `HH:MM` | `09:00` / `17:00` | Local working hours; candidates must fit inside. |
| `buffer_minutes`   | int 0–240 | `0`      | Required free margin before and after the meeting. |
| `weekdays_only`    | bool      | `true`   | Skip Saturday/Sunday. |
| `include_self`     | bool      | `true`   | Also require the current user (`whoami`) to be free. |
| `max_results`      | int 1–100 | `10`     | |
| `include_slots`    | bool      | `false`  | Also return `people[]` with each person's `slots` and `busy_blocks`. Off by default — the candidates already say who was checked, and the slot arrays are the bulk of the payload. |

**Returns**: `{ start, end, duration_minutes, addresses, unknown, count, items: [{start, end, free: [...], unknown: [...]}] }` sorted by `start`, on a 15-minute grid (or the duration when shorter), plus `people: [...]` (the `get_free_busy` person shape with `slots`) when `include_slots=true`. `free` lists the people whose calendars were checked; `unknown` the ones that could not be — tell the user those were not verified. Feed a chosen `start`/`end` straight into `create_event`.

---

## Contacts

### `outlook_list_contacts`

List saved contacts from **every contact folder in every store**, sorted by full name within each folder.

| Param            | Type     | Default | Notes |
| ---------------- | -------- | ------- | ----- |
| `limit`          | int 1–200| `50`    | |
| `offset`         | int ≥0   | `0`     | |
| `response_format`| str      | `markdown` | |

**Returns**: `{ count, offset, items: [...], has_more }`. Items: `entry_id, full_name, email, company, job_title, mobile, folder`.

On corporate accounts the personal contact folders are often nearly empty — colleagues live in the **directory** (Global Address List), which this tool does not list. Use `search_contacts` to find people.

### `outlook_search_contacts`

Word search across saved contacts (name, email, company, job title) **and the org directory (GAL)**. All query words must match.

| Param               | Type    | Default | Notes |
| ------------------- | ------- | ------- | ----- |
| `query`             | string  | required | e.g. `"anas shaikh"` matches "Anas Ahmed Shaikh". |
| `limit`             | int 1–100| `25`   | |
| `include_directory` | bool    | `true`  | Also scan the Exchange Global Address List. A few seconds on large directories. |
| `response_format`   | str     | `markdown` | |

**Returns**: `{ query, count, items, searched_directory }`. Each item has `source: "contacts" | "directory"`. Directory items carry `full_name, email (SMTP), company, job_title, mobile` but **no `entry_id`** — they aren't Outlook items, so don't pass them to `get_contact`.

### `outlook_get_contact`

Full contact record (saved contacts only — needs an `entry_id`). Returns the summary fields plus `business_phone, home_phone, address, notes`.

### `outlook_resolve_name`

Resolve a display name, alias, or address to its SMTP address — same mechanism as typing a name in To: and pressing Ctrl+K. Use before sending when you only know a person's name.

| Param  | Type   | Default | Notes |
| ------ | ------ | ------- | ----- |
| `name` | string | required | Full names resolve best; short fragments are often ambiguous. |

**Returns**: `{ resolved: true, query, display_name, smtp_address }` or `{ resolved: false, query, note }`. Ambiguous names do **not** resolve — fall back to `search_contacts` to browse candidates.

---

## Tasks

### `outlook_list_tasks`

List tasks from the default Tasks folder, sorted by due date.

| Param                | Type     | Default | Notes |
| -------------------- | -------- | ------- | ----- |
| `limit`              | int 1–200| `50`    | |
| `include_completed`  | bool     | `false` | Default hides done tasks. |
| `response_format`    | str      | `markdown` | |

**Items**: `entry_id, subject, due_date, start_date, complete, percent_complete, importance, status`.

### `outlook_create_task`

| Param        | Type     | Default   | Notes |
| ------------ | -------- | --------- | ----- |
| `subject`    | string   | required  | |
| `due_date`   | ISO-8601 | `null`    | |
| `body`       | string   | `null`    | |
| `importance` | enum     | `"normal"`| low/normal/high. |
| `reminder`   | ISO-8601 | `null`    | Sets a reminder time. |

**Returns**: `{ status: "created", entry_id, subject }`.

### `outlook_complete_task`

| Param      | Type   | Default | Notes |
| ---------- | ------ | ------- | ----- |
| `entry_id` | string | required | |

Marks the task 100% complete. Returns `{ status: "completed", entry_id }`.

---

## Categories

### `outlook_list_categories`

Returns the color categories defined in the user's Outlook profile: `{ count, items: [{name, color}, ...] }`. Categories are profile-wide, not per-folder.

### `outlook_set_category`

Replace the categories on any item (mail, event, task).

| Param        | Type   | Default | Notes |
| ------------ | ------ | ------- | ----- |
| `entry_id`   | string | required | |
| `categories` | string | required | **Comma-separated names.** Empty string clears all. e.g. `"Important"` or `"Work, Follow-up"`. |

This **replaces** existing categories rather than adding to them. To add `Foo` to an item that already has `Bar`, send `"Bar, Foo"`. Get the current value first via `get_mail` / `get_event` if needed.

---

## Rules

### `outlook_list_rules`

Returns the user's mail rules with their on/off state: `{ count, items: [{index, name, enabled}] }`.

### `outlook_toggle_rule`

| Param       | Type   | Default | Notes |
| ----------- | ------ | ------- | ----- |
| `rule_name` | string | required | **Exact** name from `list_rules`. |
| `enabled`   | bool   | required | `true` to enable, `false` to disable. |

This change is live the moment it's saved — no staging buffer. Confirm the rule name with the user before calling.

---

## Out-of-Office

### `outlook_get_out_of_office`

Reports whether OOO auto-reply is currently on. Returns `{ out_of_office: bool, status: "on"|"off" }`, or `{ out_of_office: null, status: "unknown", note: ... }` if the property isn't readable on this profile.

There is **no tool to enable, disable, or schedule OOO**. Tell users to manage it via Outlook → File → Automatic Replies.

---

## Account

### `outlook_whoami`

Returns the bound user, the account list, and the user's timezone: `{ current_user, accounts: [{display_name, smtp_address, user_name, account_type}, ...], local_time, timezone, utc_offset }`. Useful as a sanity check when the user has multiple mailboxes, and as the authority on what timezone all returned datetimes are in.

---

## Common return-field glossary

- `entry_id` — opaque, stable handle for an item. Pass back verbatim. Becomes invalid on delete; changes on cross-store move.
- `conversation_id` — groups mails in a thread. Same value across replies/forwards in one conversation.
- `from` — display name of the sender.
- `from_address` — sender SMTP address (since 0.4.0 Exchange `EX:/O=...` senders are resolved). The `from_address` *filter* on `list_mails` / `export_mails` matches by substring.
- `internet_message_id` — RFC 5322 `Message-ID` header; stable across moves and reinstalls, `""` for drafts. Present on list/search summaries, `get_mail`, `get_conversation` items, and export rows.
- `received` / `sent` / `start` / `end` / `due_date` — ISO-8601 strings **in the user's local timezone with explicit offset** (e.g. `2026-06-10T16:33:22+05:00`). Present as-is; never convert to another timezone.
- `unread` — bool. Note `mark_mail` returns `unread` (not `read`).
- `importance` — integer (0=low, 1=normal, 2=high).
- `categories` — comma-separated string of category names; empty string = none.
- `preview` — body excerpt (`preview_chars` long, default 200; absent when `preview_chars=0`). Not a substitute for `get_mail` / `get_event` when you need the full body.
- `fields` — echoed on collections when the caller asked for a subset of keys; every item then carries only those keys plus `entry_id`.
- `has_more` / `next_offset` — pagination signals on list endpoints.
