# administrator

A Claude Code plugin that runs your classic Outlook mailbox and keeps the paper trail in an Obsidian vault.

It reads Outlook through the bundled `outlook-classic-mcp` server, decides what matters, and writes plain markdown notes into one folder of your vault through that package's second server, `administrator-vault`. It reads freely. It never moves, marks, deletes, books, or sends anything without an explicit yes from you, and it never sends plain email: the most it does with mail is save a draft to your Drafts folder.

## What you get

- **`/administrator:setup`** — checks that both MCP servers, classic Outlook and the vault are reachable, creates the `Administrator\` folder, `Follow-ups.md`, `Preferences.md` and the Bases views if missing (asking your work hours once), and warns when exports cannot work. Run it first.
- **`/administrator:inbox`** — goes through unread mail, sorts each item into act / reply / waiting / fyi / noise, writes today's daily note, and offers batch clean-up you can accept or decline.
- **`/administrator:save`** — saves one email (or, on request, its whole thread via `outlook_get_conversation`) as a note with stable identity, the body without quoted history or signature (`trim_quoted`), action items, a link to a person note, and optional `.msg` and attachment exports.
- **`/administrator:daily`** — inbox plus today's calendar in one daily note, with clashes and meetings that have no prep note called out.
- **`/administrator:prep`** — a prep brief per meeting in `Meetings\`: the previous occurrence and its open action items, attendee person notes, the last five related email threads, open follow-ups, suggested points. Read-only in Outlook.
- **`/administrator:notes`** — paste your raw notes (or a transcript) after a meeting; they go into the meeting note, action items and waiting-on items are pulled out (and into `Follow-ups.md`), and a minutes email is offered that goes to your Drafts folder only after you say yes. Nothing is ever sent.
- **`/administrator:free`** — tells you when the named people and you are all free, using `outlook_find_meeting_times` and your own preferences (working hours, buffers, no-meeting blocks, daily limit). Read-only.
- **`/administrator:schedule`** — the same, then books the slot you pick after you say yes (the invite goes out at once), writes the `Meetings\` note, and adds the meeting to the daily note. Moves one meeting on request, and drafts a "proposed times" email when someone's calendar is not visible.
- **`/administrator:followups`** — threads where you wrote last and nobody answered for N days (default 3): who, subject, days waiting, the last line you wrote. Updates `Follow-ups.md` (new rows, closes rows that got a reply) and offers a short nudge email per thread that goes to your Drafts folder only after you say yes.
- **`/administrator:weekly`** — one review note per week in `Weekly\`: inbox items still open, what you are waiting on and for how long, meetings held with their unchecked action items, next week's calendar with clashes, and people you have not heard from in 30+ days. Read-only in Outlook.

## Requirements

- Windows 10 or 11.
- **Classic** Outlook (desktop, `outlook.exe`) with a configured mail profile. The new Outlook (`olk.exe`) is not supported; switch back to classic if you are on it.
- [uv](https://docs.astral.sh/uv/) on your PATH.
- A local checkout of `outlook-classic-mcp` (the version with `outlook_get_event_by_key`, `outlook_get_free_busy`, `outlook_find_meeting_times`, `trim_quoted` and the `administrator-vault` script — 40 Outlook tools plus 8 vault tools), with its path in the `OUTLOOK_MCP_DIR` environment variable (see "Set the vault path" below). The plugin starts two servers from that checkout: `outlook` (`uv run --directory $OUTLOOK_MCP_DIR outlook-mcp`, reads Outlook) and `vault` (`… administrator-vault`, writes the notes). Both need `OUTLOOK_MCP_DIR`; `vault` also needs `ADMINISTRATOR_VAULT`.
- An Obsidian vault on disk. Notes are plain markdown with frontmatter; no community plugins are needed to read them.

## Install

1. Clone or copy this folder somewhere on disk, for example `C:\Users\<you>\PycharmProjects\administrator`.
2. In Claude Code, add it as a local plugin:

   ```
   /plugin install C:\Users\<you>\PycharmProjects\administrator
   ```

   or register it in your marketplace settings, then restart Claude Code.
3. Run `/administrator:setup`. It reports the Outlook account and timezone, creates the vault folder layout, and ends with a link that opens `Preferences.md` in Obsidian. If it says a server is missing, check `OUTLOOK_MCP_DIR` and restart Claude Code.

## Set the vault path

The plugin writes only under `<vault>\Administrator\`. Tell it where the vault is with one environment variable holding an absolute path:

```powershell
# Current session
$env:ADMINISTRATOR_VAULT = "C:\Users\<you>\Documents\MyVault"

# Permanent (user scope)
[Environment]::SetEnvironmentVariable("ADMINISTRATOR_VAULT", "C:\Users\<you>\Documents\MyVault", "User")
```

In the same way, tell the plugin where your `outlook-classic-mcp` checkout is:

```powershell
$env:OUTLOOK_MCP_DIR = "C:\Users\<you>\PycharmProjects\outlook-classic-mcp"
[Environment]::SetEnvironmentVariable("OUTLOOK_MCP_DIR", "C:\Users\<you>\PycharmProjects\outlook-classic-mcp", "User")
```

The plugin registers two MCP servers from that directory: `outlook` (`outlook-mcp`, reads Outlook) and `vault` (`administrator-vault`, writes the notes). Both need `OUTLOOK_MCP_DIR`; `vault` also needs `ADMINISTRATOR_VAULT`. `OUTLOOK_MCP_DIR` is only needed while the servers are run from a local checkout. Once `outlook-classic-mcp` is published, the plugin will start them with `uvx` and this variable goes away.

Restart Claude Code after setting either variable permanently. `/administrator:setup` (or the first command you run) creates this layout with `vault_init`:

```
<vault>\Administrator\
  Daily\YYYY-MM-DD.md          one per day
  Emails\YYYY-MM-DD <slug>.md  one per saved mail
  Meetings\YYYY-MM-DD HHmm <slug>.md  one per meeting (prepared, noted, or booked)
  People\<Display Name>.md     one per sender or attendee
  Attachments\<date slug>\     .msg and attachment exports, one folder per saved mail
  Weekly\YYYY-Www.md           one review note per week
  _views\*.base                four Bases views (People, Follow-ups, Meetings, Emails)
  Follow-ups.md                rolling "waiting on" list
  Preferences.md               your scheduling preferences (created by setup, edited by you)
```

## Commands

### `/administrator:setup`

```
/administrator:setup
```

> Both servers are up. Outlook: hux@example.com, UTC+02:00.
> Vault: `C:\Users\<you>\Documents\Vault` (name `Vault`). Created `Administrator/`, 7 folders, `Follow-ups.md`, `Preferences.md` (09:00–17:00, buffer 15) and 4 views.
> obsidian://open?vault=Vault&file=Administrator%2FPreferences.md
> Edit Preferences.md in Obsidian any time; the plugin reads it on every scheduling request and never changes it.

Running it again when everything exists reports "Nothing to create." and the same link.

### `/administrator:inbox [folder] [since]`

```
/administrator:inbox
/administrator:inbox inbox 2026-08-20
/administrator:inbox "Inbox/Projects/Acme"
```

Lists unread mail since the last daily note's `inbox_checked` time (or the last 24 hours), sorts it, writes `Daily\<today>.md`, adds waiting items to `Follow-ups.md`, then lists possible batch changes (mark fyi/noise as read, move to a folder, set categories) with the count and subjects each one touches. Nothing runs until you say yes to a specific option.

### `/administrator:save <entry_id | search terms>`

```
/administrator:save invoice acme july
/administrator:save 00000000AC3F...
```

With search terms it shows up to five matches and asks you to pick. Then it asks whether to export the `.msg` and attachments into `Attachments\`, writes `Emails\<date> <subject>.md`, and creates or updates `People\<Sender>.md`. Running it twice on the same mail appends an update section instead of making a duplicate.

### `/administrator:daily [date]`

```
/administrator:daily
/administrator:daily 2026-08-25
```

Runs the inbox workflow, then adds today's agenda from `outlook_list_events`, flags overlapping meetings and meetings with no prep note, and gives you a short brief.

### `/administrator:prep [date | event words]`

```
/administrator:prep
/administrator:prep tomorrow
/administrator:prep supplier sync
```

Lists the day's meetings (all-day events skipped unless named) and writes `Meetings\<date> <time> <subject>.md` for each, with a Prep section. Running it twice appends an update instead of making a second note.

### `/administrator:notes [event words | path] <raw notes or file path>`

```
/administrator:notes supplier sync
- Jane ok with net 45, I'll sign tomorrow
- Tom to send updated schedule by Wed
```

Finds the meeting (today's first, asks if unclear), appends your notes, pulls out action items and things you are waiting on, marks the meeting held, updates `last_contact` on the attendees, then shows a minutes email and asks before saving it to Drafts.

Paste a transcript instead of notes (Teams/Copilot speaker-by-speaker text; a ready-made Copilot prompt is in `skills/meetings/references/copilot-transcript-prompt.md`) and it is stored under `## Transcript` in a collapsed callout, each speaker linked to their person note, decisions and action items pulled out, and `## Notes` left for your own summary unless you ask for one.

### `/administrator:free <people> [duration] [window]`

```
/administrator:free Sam
/administrator:free Sam, Jane Doe 45 min next week
/administrator:free sam.ortiz@example.com tomorrow afternoon
```

Turns names into addresses (asks if it cannot), reads free/busy, applies `Administrator\Preferences.md`, and shows up to five times in your local time with who is free. People outside your organisation have no visible calendar; it says so and offers an email instead. Nothing is written or sent.

### `/administrator:schedule <people> [duration] [window] [subject]`

```
/administrator:schedule Sam 30 min next week "Budget review"
/administrator:schedule Sam, Jane Doe Thursday
move my 2pm with Sam to Thursday
```

Same as `free`, then you pick a slot, it shows subject / time / attendees / location, and only after a clear yes calls `outlook_create_event`. The invite reaches everyone the moment it is created, so it tells you that before asking. Then it writes `Meetings\<date time> <subject>.md` (the same note `prep` uses) and adds a row to that day's daily note if one exists. For a move it finds the meeting, offers new times, and on a yes calls `outlook_update_event`. One meeting per request; it will not move a whole day.

### `/administrator:followups [days]`

```
/administrator:followups
/administrator:followups 5
```

Reads your Sent folder for the last 30 days, fetches each thread once, and lists the ones where your mail is the last message and it is at least `days` old. New threads get a row in `Follow-ups.md`; rows whose thread has since been answered move to Done. Then it shows one nudge draft at a time and saves it to Drafts only on a yes. Nothing is ever sent.

### `/administrator:weekly [week]`

```
/administrator:weekly
/administrator:weekly last
/administrator:weekly 2026-W33
```

Writes `Weekly\YYYY-Www.md` from the week's daily notes, `Follow-ups.md`, the meeting notes, next week's calendar and the person notes. Running it again on the same week appends an update section.

### `Administrator\Preferences.md`

Created by `/administrator:setup` (or with defaults the first time any command needs it). Edit it in Obsidian: `work_start`, `work_end`, `buffer_minutes`, `no_meeting_blocks`, `max_meetings_per_day`, `default_duration`, `default_location`, `preferred_days`. The plugin reads it every time and never changes it.

## What never happens without a yes

- Marking mail read or unread, flagging, or setting categories (`outlook_mark_mail`, `outlook_bulk_mark_mails`, `outlook_set_category`).
- Moving or deleting mail (`outlook_move_mail`, `outlook_delete_mail`, `outlook_bulk_move_mails`, `outlook_bulk_delete_mails`). The inbox workflow never deletes at all; it offers a move instead.
- Writing files from Outlook to disk (`outlook_save_mail_as`, `outlook_save_attachments`); these land in `<vault>\Administrator\Attachments\<date slug>\` and are offered once per save.
- Saving an email draft (`outlook_send_mail(save_only=true)` — minutes after `/administrator:notes`, proposed times from `/administrator:schedule`, nudge drafts from `/administrator:followups`). The plugin never sends plain email, not even with a yes: `outlook_send_mail` without `save_only`, `outlook_reply_mail` and `outlook_forward_mail` are never called. You send from Drafts.
- Creating or moving a meeting (`outlook_create_event`, `outlook_update_event`), both only from `/administrator:schedule` after the full summary. An invite goes to every attendee as soon as it is created. Deleting events or answering invites never happens.

Every offer states the exact action, the number of items, and their subjects. "Yes" means that option only.

## Path sandbox

`outlook_save_mail_as` and `outlook_save_attachments` only write to absolute paths under your user profile (`C:\Users\<you>\...`). Keep the vault there and exports land in `<vault>\Administrator\Attachments\` without trouble. If the vault lives on another drive or a network share, the export step is skipped unless you set `OUTLOOK_MCP_ALLOW_ANY_PATH=1` in your environment. The plugin's own note writing has no such limit, but it never writes outside `<vault>\Administrator\`.

## Classic Outlook only

The connector talks to Outlook through COM, which only classic desktop Outlook exposes. It needs Outlook installed with a profile on the same Windows machine where Claude Code runs. Corporate machines may show a "Programmatic Access" prompt on first write; see the `outlook` skill's gotchas if a change seems to silently do nothing.

## Notes the plugin writes

Every note has frontmatter with `type` (`email`, `daily`, `person`, `meeting`, `weekly`, or `preferences`), `source: outlook` (`administrator` for preferences and weekly notes), `created_by: administrator/0.0.4`, and for emails the Outlook identity (`internet_message_id`, `entry_id`, `conversation_id`), sender SMTP address, recipients, `received` with timezone offset, and a `status` of `todo`, `waiting`, `done`, or `fyi`. Meeting notes carry the event's `global_id` and `occurrence_key` (one note per occurrence of a recurring meeting) and a `status` of `upcoming`, `held`, or `cancelled`. Links use wikilinks (`[[People/Jane Doe]]`) so Obsidian's graph and backlinks work out of the box.

Existing notes are never overwritten. When a mail is saved again, an `## Update <timestamp>` section is appended. Every command that writes a note ends with an `obsidian://open` link to it. The notes are written by the `vault` server, which also enforces the frontmatter and never edits text that is already there.

## Obsidian

Notes are plain markdown with frontmatter and wikilinks; nothing beyond core Obsidian is needed. `Administrator\_views\` holds four Bases files (core plugin, Obsidian 1.9+): `People.base`, `Follow-ups.base`, `Meetings.base` (by week), `Emails.base` (by status and sender). Open them like notes or embed one with `![[Administrator/_views/People.base]]`. Every command reply ends with an `obsidian://open` link to the note it wrote; set `ADMINISTRATOR_VAULT_NAME` if the name Obsidian shows differs from the folder name. The plugin never touches `.obsidian\` or anything outside `Administrator\`. Details, including sync advice and why the saved `.msg` is the way back to the original mail: `skills/administrator/references/obsidian.md`.

## License

MIT
