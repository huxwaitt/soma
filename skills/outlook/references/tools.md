# Tool reference

Every `outlook_*` tool, with parameters, defaults, return shape, and notes on chaining. Skim the table of contents, then jump to the tools you need.

## Contents

- [Mail](#mail) — list_mails, search_mails, get_mail, get_conversation, send_mail, reply_mail, forward_mail, move_mail, delete_mail, mark_mail, save_attachments, bulk_move_mails, bulk_delete_mails, bulk_mark_mails, export_mails, save_mail_as
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
| `response_format`| `markdown`/`json` | `markdown` | Use `json` to extract `entry_id`s. |

**Returns** (`json` shape): `{ folder, count, offset, limit, items: [...], has_more, next_offset }`. Each item has: `entry_id, internet_message_id, subject, from, from_address, to, received, unread, has_attachments, importance, preview` (200-char body excerpt). `from_address` is always a real SMTP address when Outlook can resolve one.

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
| `response_format`| str      | `markdown`       | |

**Returns**: `{ query, scope, folder, count, items: [...] }`. Items have the same summary shape as `list_mails`.

Multi-word queries match items containing **all** the words (not the exact phrase), so `"teams not working"` finds "MESP-1 teams is not working". `scope='from'` matches display name, raw address, **and** the real SMTP address (works for Exchange senders too).

`scope='dasl'` is for power use — pass a complete `@SQL=...` filter and the server applies it raw. Only reach for this when subject_body/subject/from can't express what the user wants.

### `outlook_get_mail`

Fetch the body, all headers, and the attachment manifest for one mail. Read-only.

| Param            | Type   | Default | Notes |
| ---------------- | ------ | ------- | ----- |
| `entry_id`       | string | required | From a list/search result. |
| `include_body`   | bool   | `true`   | If false, omits `body`. Useful when you only need metadata. |
| `include_html`   | bool   | `false`  | Adds the raw `html_body`. Usually huge — leave off unless you specifically need the markup. |
| `max_body_chars` | int ≥0 | `10000`  | Body truncation cap; `0` = unlimited. |
| `response_format` | str | `markdown` | |

**Returns**: `{ entry_id, conversation_id, internet_message_id, subject, from, from_address, to, cc, bcc, recipients: [{name, address, type}], received, sent, unread, importance, categories, attachments: [{index, filename, size_bytes}], body }` — `recipients[].address` is the SMTP address and `type` is `to` / `cc` / `bcc` (the flat `to` / `cc` strings are display names), plus `body_truncated`/`body_total_chars` when the cap was hit (re-call with a higher `max_body_chars` to read more) and `html_body` when `include_html=true`. `internet_message_id` is the RFC 5322 `Message-ID` header (`""` for drafts) — use it to correlate with other systems; it also appears on list/search summaries and export rows.

### `outlook_get_conversation`

Return every mail in the thread that contains a given mail, oldest first, including replies filed in other folders (Sent Items, sub-folders). Read this before drafting a reply to a long exchange.

| Param            | Type   | Default | Notes |
| ---------------- | ------ | ------- | ----- |
| `entry_id`       | string | required | Any mail in the thread. |
| `include_body`   | bool   | `false` | Add each mail's plain-text `body`. |
| `max_body_chars` | int ≥0 | `2000`  | Per-mail truncation; `0` = unlimited. |
| `limit`          | int 1–500 | `200` | Max mails returned (oldest first). |

**Returns** (always JSON): `{ conversation_id, count, truncated, items: [...] }`. Each item is the `list_mails` summary shape plus `conversation_id`, `folder`, and (with `include_body`) `body` / `body_truncated` / `body_total_chars`. If Outlook has no conversation for the item (IMAP/POP stores, drafts), `items` contains just that one mail.

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

**Returns**: `{ status: "sent", reply_all, in_reply_to, subject }`.

This sends immediately; there's no `save_only` flag on `reply_mail`. To stage a reply for review, copy the original's recipients yourself and call `send_mail` with `save_only=true` instead.

### `outlook_forward_mail`

Forward an existing mail to new recipients with an optional note above. Has external side effect.

| Param      | Type      | Default | Notes |
| ---------- | --------- | ------- | ----- |
| `entry_id` | string    | required | |
| `to`       | list[str] | required | |
| `body`     | string    | `""`     | Optional note prepended to the forwarded content. |
| `cc`       | list[str] | `null`   | |
| `html`     | bool      | `false`  | |

**Returns**: `{ status: "sent", forwarded, to, subject }`.

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

**Returns**: `{ start, end, interval_minutes, count, people: [...], unknown: [...] }`. Each person: `{ address, resolved, has_data, slots: [{start, end, status}], busy_blocks: [{start, end, status}] }` — `status` ∈ `free` / `tentative` / `busy` / `oof` / `elsewhere`; `busy_blocks` is the non-free slots merged into contiguous runs of the same status (the thing to show the user). `resolved=false` means the address is not in the address book; `resolved=true, has_data=false` means no free/busy was published (external person, or not Exchange). `unknown` lists both kinds.

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

**Returns**: `{ start, end, duration_minutes, addresses, unknown, count, items: [{start, end, free: [...], unknown: [...]}] }` sorted by `start`, on a 15-minute grid (or the duration when shorter). `free` lists the people whose calendars were checked; `unknown` the ones that could not be — tell the user those were not verified. Feed a chosen `start`/`end` straight into `create_event`.

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
- `preview` — 200-char body excerpt. Not a substitute for `get_mail` / `get_event` when you need the full body.
- `has_more` / `next_offset` — pagination signals on list endpoints.
