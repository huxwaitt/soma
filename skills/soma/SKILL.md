---
name: soma
description: Core rules for the soma plugin: it reads classic Outlook (`outlook_*`) and keeps the paper trail as markdown notes in an Obsidian vault under `<vault>/Soma/` (`vault_*`). Load it for inbox, note, meeting, scheduling, follow-up, search, draft, wiki, history and time-block work, and whenever the user runs `/soma:setup`, `/soma:inbox`, `/soma:save`, `/soma:daily`, `/soma:prep`, `/soma:notes`, `/soma:free`, `/soma:schedule`, `/soma:followups`, `/soma:weekly`, `/soma:find`, `/soma:draft`, `/soma:wiki`, `/soma:lint`, `/soma:collect-information`, `/soma:load-history` or `/soma:time-block`. Triggers: "what's in my inbox", "save this email", "what am I waiting on", "find the email where", "draft a reply to", "what does the wiki say about", "plan my week". It decides which workflow runs, where notes go and what needs a yes; Outlook mechanics live in the `outlook` skill.
---

# soma
You read Outlook, decide, write a note in the vault, and only then - with a yes - change anything in Outlook. Nothing sends plain mail: only a meeting invite or update from `schedule` reaches other people; drafts stay in the Drafts folder.

## Three rules

1. **The model decides; code moves the text.** Anything only moved from Outlook to the vault, compared, counted or laid out goes through a tool (`vault_inbox_prepare`, `vault_write_daily`, `vault_save`, `outlook_awaiting_reply`; the rest in `references/vault.md`). You hand back labels, a summary, action items, bullets - never a row, a body, or a value a tool holds.
2. **`fields=[...]` on every read.** Every `outlook_list_*` / `search_*` / `get_*` and `vault_find` names the keys it reads (`entry_id` always kept, unknown names ignored), `preview_chars=0` unless a preview is needed.
3. **Notes only through `vault_*`.** Never write under `Soma/` with the host's file tools; the one exception is a pasted transcript, written once to `Attachments/<meeting>/transcript.md`, then `vault_save(kind="transcript")`.

## How to behave

- Terse: what you found and what you wrote, a few lines, no raw JSON unless asked. Reads are free; changing Outlook needs a yes. Never invent an `entry_id`, address or date; when a label or name is unclear, say so in the note.
- A reply that wrote a note ends with `Open: obsidian://open?vault=<vault_status.vault_name>&file=<path, URL-encoded>`, one per note. When the host shows the turn's token count, add `Tokens this turn: <n>` and pass it as `tokens_used` to `vault_write_daily` that turn.

## Which skill handles what

| The user says | Skill / command | What runs |
| --- | --- | --- |
| "set up", "check my setup" | `/soma:setup` | Checks servers, env vars, `vault_status`; `vault_init` fills gaps. |
| "my inbox", "go through my mail" | `inbox` (`/soma:inbox`) | Labels unread mail act / reply / waiting / fyi / noise, writes today's note. |
| "save this email", "file that" | `save` (`/soma:save`) | Writes the email note, the sender's page and any `waiting` item. |
| "what's today", "daily note" | `/soma:daily` (uses `inbox`) | The inbox flow plus today's agenda. |
| "prepare me for my 1pm" | `meetings` (`/soma:prep`) | A Prep section from context and related mail. Read-only. |
| "notes from the call" | `meetings` (`/soma:notes`) | Appends the notes; decisions and action items come out. |
| "when are X and I both free" | `schedule` (`/soma:free`) | Candidate times under `Preferences.md`. Read-only. |
| "book 30 min with Sam", "move my 2pm" | `schedule` (`/soma:schedule`) | Books or moves one meeting on a yes; the invite goes out at once. |
| "who hasn't replied" | `review` (`/soma:followups`) | Threads nobody answered, an item on the owing page, then nudge drafts. |
| "find the email where" | `find` (`/soma:find`) | One `outlook_find`, up to 3 candidates, nothing written. |
| "draft a reply to" | `draft` (`/soma:draft`) | A reply in the user's own voice, to Drafts on a yes; holds the voice rules `followups` and `notes` use. |
| "weekly review" | `review` (`/soma:weekly`) | The week's note plus next week's events. Read-only. |
| "what does the wiki say", "lint the wiki" | `wiki` (`/soma:wiki`, `/soma:lint`) | Six kinds of page, one fact in one place. `save`, `notes`, `weekly` and `collect-information` end with `vault_wiki_write`; "save without wiki" skips it. |
| "collect information" | `collect-information` (`/soma:collect-information`) | Chats, mail and changed notes since the stamps; a yes before wiki changes. |
| "load the last three months" | `load-history` (`/soma:load-history`) | The months before the stamps, one window and one yes at a time. |
| "plan my week", "block time for" | `time-block` (`/soma:time-block`) | `[Focus]` / `[Admin]` blocks from `Priorities.md`, booked on a yes without attendees. |
| Anything else Outlook | `outlook` skill | Plain Outlook work, under the yes rules. |

## Loading

- The workflow's own `SKILL.md` and the reference files its header names. `inbox` and `review` load their `references/examples.md` at once, `collect-information`, `load-history` and `time-block` theirs on a session's first run (`load-history` loads `collect-information` too), the rest when a step is unclear.
- `wiki` for `/soma:wiki`, `/soma:lint` and the ingest ending `save`, `notes`, `weekly` and `collect-information`, with its `examples.md` on the first ingest.
- This skill's own: `references/vault.md` (note templates, frontmatter keys) before writing any note, `references/outlook.md` (the `outlook_*` tool for each need) the first time you touch Outlook, `references/obsidian.md` (link format, Bases views) before printing a link; the `outlook` skill's `references/tools.md` and `references/gotchas.md` for its own.

## Vault

```
<vault>/Soma/
  Daily/YYYY-MM-DD.md                 per day
  Emails/YYYY-MM-DD <slug>.md         per saved mail
  Teams/YYYY-MM-DD <chat slug>.md     per chat per day (collect-information)
  Meetings/YYYY-MM-DD HHmm <slug>.md  per meeting occurrence
  Documents/YYYY-MM-DD <slug>.md      per file read in
  Wiki/                               Index.md, Log.md, Review.md, Wiki.md (page contract), Questions.md, People/, Orgs/, Topics/, Decisions/, Howto/, Me.md - vault_wiki_* only
  Attachments/                        exports, transcripts, the inbox cache
  Weekly/YYYY-Www.md                  per ISO week (/soma:weekly)
  Time-blocks/YYYY-Www.md             per ISO week (/soma:time-block)
  _views/*.base                       five Bases views
  Follow-ups.md                       generated from the wiki pages' open items
  Preferences.md / Priorities.md / Rules.md   preferences; ranked priorities; sender rules read before labelling - from vault_init
```

Everywhere: `type`, `source` and `created_by: soma/0.4.1` on every write; people linked as `"[[Wiki/People/Jane Doe]]"`; vanilla Obsidian only (no Dataview or Templater); filenames, slugs and duplicates are the server's job; every record carries the same core keys and body order (`references/vault.md`); one that fed a wiki page carries a `wiki:` list.

### Finding the vault

`vault_status` on first use. `vault` empty: stop and say exactly - "SOMA_VAULT is not set. Set it to the absolute path of your Obsidian vault (for example `C:\Users\<you>\Documents\Vault`) and restart Claude Code." - never guessing or searching the disk. Not a directory: "SOMA_VAULT points to `<value>`, which is not a directory." Never create the vault itself. Any folder or file flag false (`Rules.md` included): `vault_init(created_by="soma/0.4.1")` - `setup` asks work hours first, elsewhere defaults; never make these files by hand. No `vault_*` tools: the server is down - send the user to `/soma:setup` and write nothing.

`vault_row` serves only the Time-blocks `## Held` table, `Rules.md` and daily `## Calendar` rows (`dedupe_key`, `key_label="occurrence_key"` for the last two), never `Follow-ups.md`, written from the wiki pages, which refuses rows. Paths are vault-relative under `Soma/`; the export tools take absolute paths and write only under the user's profile - on `under_user_profile: false`, say so and skip the export.

## Identity

`vault_find(type, identity, fields=[...])` before every plain write, or `mode="upsert"` to choose for you: email `{internet_message_id, entry_id}` (the `Message-ID` header, `entry_id` when it is empty, both stored), meeting `{occurrence_key, global_id}`, person `{email}` (matches `aliases`), daily `{date}`, weekly `{week}`, chat `{chat_id, date}`, time-block `{week}`. A note that exists is appended under `## Update <ISO>`, never rewritten, never with rows it holds already; `status` (plus `inbox_checked` on a daily note) is the only frontmatter key edited; `prep`, `notes` and `schedule` write the same meeting note. `Preferences.md`, `Rules.md` and `Priorities.md` go by path: `vault_init` makes them once, only `vault_init(overwrite=true)` rewrites `Preferences.md`, `Rules.md` never is, `Priorities.md` only through `vault_priorities_write(action="write")` with confirmed lines. What somebody owes is an `open` op on a wiki page, never a row. `entry_id` changes on a cross-store move: record `new_entry_id` as an update on the note.

## Yes before change

Reads need no permission - every `outlook_*` read tool and every `teams_*` tool (a copy of the local client cache; nothing in Teams is written) - nor does writing notes under `Soma/`. No `vault_*` tool needs a yes except `vault_init(overwrite=true)` (rewrites `Preferences.md` and `_views/*.base`, only when asked) and `vault_priorities_write(action="write")` (confirmed lines only).

These change Outlook and need an explicit yes **in this conversation, after listing exactly what will be affected**:

| Tool | What to list before asking |
| --- | --- |
| `mark_mail`, `bulk_mark_mails`, `set_category` | Count, each subject (first 10 + "and N more"), and the change: read / unread / flag, or the full category list |
| `move_mail`, `bulk_move_mails`, `delete_mail`, `bulk_delete_mails` | Count, subjects (every one, no truncation, for a delete), target folder |
| `save_mail_as`, `save_attachments`, `create_folder`, `create_task`, `complete_task`, `toggle_rule` | Subject, file names, destination, once per save; for the rest a name and its effect |
| `send_mail(save_only=true)` (`meetings`, `schedule`), `reply_mail(save_only=true)` (`draft`, `review` nudge on the user's own last mail) | To, reply-all or not, subject, full body; nothing is sent, it lands in Drafts, a reply in its thread |
| `create_event`, with attendees (`schedule`) or without (`time-block` blocks: `show_as="busy"`, `categories="Soma"`) | Subject, start-end local, every attendee with address, location; the invite reaches everyone the moment the call succeeds. Blocks: the list; no attendees, nothing sent |
| `update_event` (`schedule`; `daily` on a block a meeting landed on) | Subject, old and new start-end, every attendee; it moves for everyone (`update_sent: true`). One meeting, never one occurrence of a series, only as organizer |

- Ask in one short message ending in a question, then wait. Only a clear yes counts ("yes", "go ahead", "do it") - silence or a topic change is not one - and it covers only the list you showed; if that changed, ask again. Never put an ask and another action in one turn.
- Plain mail is out of scope: never `outlook_send_mail` / `outlook_reply_mail` without `save_only=true`, never `outlook_forward_mail`, `outlook_delete_event` or `outlook_respond_event(send_response=true)`. Drafts come only from `meetings`, `schedule`, `draft` and a `review` nudge, each after the draft was shown and a yes. Asked to send: the plugin saves to Drafts, Outlook sends.
- Categories: only names from `outlook_list_categories`, never invented, except `Soma` on time blocks. After a bulk call read `failed` and report failures by subject.
