# administrator

A Claude Code plugin that runs your classic Outlook mailbox and keeps the paper trail in an Obsidian vault.

It reads Outlook through the bundled `outlook-classic-mcp` server, decides what matters, and writes plain markdown notes into one folder of your vault through that package's second server, `administrator-vault`. It reads freely. It never moves, marks, deletes, books, or sends anything without an explicit yes from you, and it never sends plain email: the most it does with mail is save a draft to your Drafts folder.

## What you get

- **`/administrator:setup`** — checks that both MCP servers, classic Outlook and the vault are reachable, creates the `Administrator\` folder, the `Wiki\` folder, `Follow-ups.md`, `Preferences.md`, `Rules.md` and the Bases views if missing (asking your work hours and peak hours once), offers to move an older vault's `People\` into the wiki (dry run first), and warns when exports cannot work. Run it first.
- **`/administrator:inbox`** — goes through unread mail, sorts each item into act / reply / waiting / fyi / noise, writes today's daily note, and offers batch clean-up you can accept or decline.
- **`/administrator:save`** — saves one email (or, on request, its whole thread via `outlook_get_conversation`) as a note with stable identity, the body without quoted history or signature (`trim_quoted`), action items, a link to a person note, and optional `.msg` and attachment exports.
- **`/administrator:daily`** — inbox plus today's calendar in one daily note, with clashes and meetings that have no prep note called out.
- **`/administrator:prep`** — a prep brief per meeting in `Meetings\`: the previous occurrence and its open action items, attendee person notes, the last five related email threads, open follow-ups, suggested points. Read-only in Outlook.
- **`/administrator:notes`** — paste your raw notes (or a transcript) after a meeting; they go into the meeting note, action items and waiting-on items are pulled out (and into `Follow-ups.md`), and a minutes email is offered that goes to your Drafts folder only after you say yes. Nothing is ever sent.
- **`/administrator:free`** — tells you when the named people and you are all free, using `outlook_find_meeting_times` and your own preferences (working hours, buffers, no-meeting blocks, daily limit). Read-only.
- **`/administrator:schedule`** — the same, then books the slot you pick after you say yes (the invite goes out at once), writes the `Meetings\` note, and adds the meeting to the daily note. Moves one meeting on request, and drafts a "proposed times" email when someone's calendar is not visible.
- **`/administrator:followups`** — threads where you wrote last and nobody answered for N days (default 3): who, subject, days waiting, the last line you wrote. Updates `Follow-ups.md` (new rows, closes rows that got a reply) and offers a short nudge email per thread that goes to your Drafts folder only after you say yes.
- **`/administrator:weekly`** — one review note per week in `Weekly\`: inbox items still open, what you are waiting on and for how long, meetings held with their unchecked action items, next week's calendar with clashes, people you have not heard from in 30+ days, and the wiki's lint result and review queue. Read-only in Outlook.
- **`/administrator:find`** — describe an email the way you remember it ("the email where we agreed on the Q3 budget with Sam", "the spreadsheet Maria sent with vendor pricing last month") and get up to three candidates with the exact line that answers you, attachment names, and a link if the note already exists. One `outlook_find` call searches Inbox and Sent and ranks; attachment names and indexed text are checked when you mention a file. Read-only; offers to save the winner.
- **`/administrator:wiki`** — read a wiki page, ask the wiki a question ("what do we know about the ACME contract"), add or change a fact from chat (kept as yours, so no later mail overrides it), resolve the review queue, or ingest a record saved before the wiki existed.
- **`/administrator:lint`** — the wiki's fixed checklist: index drift, dangling links, orphans, stale pages, size caps, possible duplicates, records never ingested, contradictions. `fix` applies the safe fixes; merges and new pages only after a yes.
- **`/administrator:collect-information`** — everything since the last run in one pass: Teams chats from the local client cache (optional, see "Teams" below), new mail in Inbox and Sent, and notes that changed in the vault. Chat records and the mails that touch a wiki page are saved, the wiki changes are shown as bullets grouped by page, and only after your yes are they applied, oldest record first — a later source wins, an older one that disagrees goes to the review queue. Then one question: how did today's `[Focus]` / `[Admin]` blocks go? Nothing in Outlook or Teams is changed.
- **`/administrator:time-block`** — plans your week's focus and admin blocks around the meetings already in your calendar, shows how last week went against your priorities, and after your yes books the blocks as appointments in your own calendar — no attendees, so nothing is sent to anyone. A re-plan fills gaps that opened up and never deletes a block. See "Time blocks" below.
- **`/administrator:draft`** — a reply to any thread, written the way you write: it reads the thread with the quoted history removed, the sender's wiki page and your open follow-ups, learns your greeting, sign-off and length from your sent mail, answers every question in the last mail and marks anything it does not know as `[fill in: …]`. Shows the draft; on a yes it lands in Outlook Drafts as a reply in the thread. Never sends.

## The wiki

Records (saved emails, meeting notes, daily and weekly notes) are never edited; they are what happened. Next to them, `Administrator\Wiki\` holds what is *currently true*: one page per person, organisation, topic (a subject with a timeline and an outcome) and procedure, each with a short lead, dated facts that point back to the records they came from, open items, and a History that keeps every fact that was replaced. `save` and `notes` end by putting the facts of the new record onto the pages they belong to; `prep`, `find` and `draft` read the pages before they read old mail; `weekly` runs the lint and shows the review queue. A fact changes only when a *later* record says so — an old thread you save today can never overwrite a newer fact; it goes to `Wiki\Review.md` for you to settle. A topic page is created only when a subject shows up in two records on two different days, or when you name it. Nothing is deleted, merged, or resolved without your yes. `Wiki\Index.md` is the home page (generated, one line per page); `Wiki\Wiki.md` is the contract, the same text the plugin reads, and you can add your own notes at the bottom. Say "save without wiki" to skip the step for one record. A vault from 0.1.0 keeps working; `/administrator:setup` shows a dry run and moves `People\` into the wiki only after you agree.

## Time blocks

`/administrator:time-block` puts your own work into the calendar the way meetings already are, on five findings that hold up (the sources and numbers are in `skills/time-block/references/method.md`). A task with a fixed day and hour gets done far more often than one on a list, so every block is an appointment with a start and an end. Thinking is measurably better at some hours of the day than others, and deep work needs a long run, so focus blocks are 90 minutes or more and go into your `peak_hours` first, named after a priority from `Administrator\Priorities.md` (`[Focus] ACME supplier contract`; rank 1 gets every other block). Email and small tasks cost more when they interrupt than when they are batched, so they get two shorter `[Admin] Email and small tasks` blocks outside the peak hours. A fifth of each day stays free for what comes up (`slack_share`), and a day the meetings have already filled past that gets no blocks at all rather than a squeezed one. Finally, `/administrator:collect-information` asks each day whether the blocks were held, moved or skipped, and `/administrator:weekly` prints where the hours went — meetings, focus, admin, other, unplanned — against your priorities under `## Time`. The blocks are appointments without attendees, marked busy and filed under the Outlook category `Administrator`; nothing is ever sent to anyone, and the plugin never deletes one — if a block is in the way, delete it in Outlook, or let `/administrator:daily` move it when a meeting lands on it. `/administrator:free` and `/administrator:schedule` do not count blocks towards your `max_meetings_per_day`.

## Requirements

- Windows 10 or 11.
- **Classic** Outlook (desktop, `outlook.exe`) with a configured mail profile. The new Outlook (`olk.exe`) is not supported; switch back to classic if you are on it. The new Teams client is fine (and the only one whose cache the optional Teams server reads).
- [uv](https://docs.astral.sh/uv/) on your PATH.
- A local checkout of `outlook-classic-mcp` 0.4.0 or later (the current checkout with `outlook_get_event_by_key`, `outlook_get_free_busy`, `outlook_find_meeting_times`, `outlook_search_attachments`, `outlook_advanced_search`, `outlook_extract_attachment_text`, `outlook_reply_mail(save_only=true)`, `outlook_awaiting_reply`, `outlook_find`, `outlook_voice_sample`, `fields=` / `preview_chars=` on every list, search and get tool, `trim_quoted` and the `administrator-vault` script with its `vault_wiki_*`, `vault_save_chat`, `vault_collect_sources` and `vault_changed_notes` tools — 46 Outlook tools plus 32 vault tools; install its `search` extra for PDF and Excel attachment text), with its path in the `OUTLOOK_MCP_DIR` environment variable (see "Set the vault path" below). The plugin starts three servers from that checkout: `outlook` (`uv run --directory $OUTLOOK_MCP_DIR outlook-mcp`, reads Outlook), `vault` (`… administrator-vault`, writes the notes) and the optional `local-ms-teams` (`… local-ms-teams`, reads the Teams cache; see "Teams" below). All need `OUTLOOK_MCP_DIR`; `vault` also needs `ADMINISTRATOR_VAULT`.
- An Obsidian vault on disk. Notes are plain markdown with frontmatter; no community plugins are needed to read them.

### Teams (optional)

`/administrator:collect-information` can read your Teams chats without any Graph permission or admin consent: the third server, `local-ms-teams` (`uv run --directory $OUTLOOK_MCP_DIR local-ms-teams`), reads a *copy* of the new Teams client's local cache on this machine and never writes to it or talks to the network. It sees what the client has synced — recent chats, group chats, channel and meeting chats you opened, with sender names and times — and nothing else: no meeting transcripts (those still go through `/administrator:notes`), no history the client has not loaded, no attachments. The cache format belongs to Microsoft and can change with a Teams update; when it does, `teams_status` says so and the command skips Teams. To turn it on, install the extra in the checkout once — `uv sync --extra teams` — sign in to the new Teams client on this machine, and restart Claude Code. Without the extra the server still starts and reports the one-line fix; nothing else in the plugin depends on it.

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

The plugin registers three MCP servers from that directory: `outlook` (`outlook-mcp`, reads Outlook), `vault` (`administrator-vault`, writes the notes) and `local-ms-teams` (reads the local Teams cache; optional). All three need `OUTLOOK_MCP_DIR`; `vault` also needs `ADMINISTRATOR_VAULT`. `OUTLOOK_MCP_DIR` is only needed while the servers are run from a local checkout. Once `outlook-classic-mcp` is published, the plugin will start them with `uvx` and this variable goes away.

Restart Claude Code after setting either variable permanently. `/administrator:setup` (or the first command you run) creates this layout with `vault_init`:

```
<vault>\Administrator\
  Daily\YYYY-MM-DD.md          one per day
  Emails\YYYY-MM-DD <slug>.md  one per saved mail
  Meetings\YYYY-MM-DD HHmm <slug>.md  one per meeting (prepared, noted, or booked)
  Wiki\                        the wiki: Index.md, Log.md, Review.md, Wiki.md (the contract),
    People\<Display Name>.md   one page per sender or attendee
    Orgs\ Topics\ Howto\       one page per organisation, topic, procedure
  Teams\YYYY-MM-DD <chat>.md   one record per Teams chat per day (collect-information)
  Attachments\<date slug>\     .msg and attachment exports, one folder per saved mail
  Weekly\YYYY-Www.md           one review note per week
  Time-blocks\YYYY-Www.md      one plan note per week (time-block), with how each block went
  _views\*.base                five Bases views (People, Follow-ups, Meetings, Emails, Wiki)
  Follow-ups.md                rolling "waiting on" list
  Preferences.md               your scheduling preferences (created by setup, edited by you)
  Priorities.md                your ranked priorities (created by setup; time-block suggests a list when it is empty and writes it only with lines you confirmed; edit it any time)
  Rules.md                     sender / subject rules applied before the inbox is labelled (created by setup, edited by you)
```

## How it keeps cost down

The model decides; code moves the text. Every list, search and get call names the `fields=` it will read, and the mechanical parts of each workflow run inside the servers: `vault_inbox_prepare` drops mail already noted and applies `Rules.md`, `vault_write_daily` renders the daily note from a list of labels, `vault_save_email` writes the email note and person note from the Outlook JSON, `vault_prep_context` and `vault_weekly_facts` collect what the vault knows in one call, `vault_attach_transcript` files a transcript, and `outlook_awaiting_reply`, `outlook_find`, `outlook_voice_sample` do the thread, search and voice work in the Outlook server. Every command ends with the turn's token count when Claude Code shows one.

## Commands

### `/administrator:setup`

```
/administrator:setup
```

> Both servers are up. Outlook: hux@example.com, UTC+02:00.
> Vault: `C:\Users\<you>\Documents\Vault` (name `Vault`). Created `Administrator/`, 7 folders, `Follow-ups.md`, `Preferences.md` (09:00–17:00, buffer 15), `Rules.md` and 4 views.
> obsidian://open?vault=Vault&file=Administrator%2FPreferences.md
> Edit Preferences.md in Obsidian any time; the plugin reads it once per session and never changes it.

Running it again when everything exists reports "Nothing to create." and the same link.

### `/administrator:inbox [folder] [since]`

```
/administrator:inbox
/administrator:inbox inbox 2026-08-20
/administrator:inbox "Inbox/Projects/Acme"
```

Lists unread mail since the last daily note's `inbox_checked` time (or the last 24 hours), lets `Rules.md` and the built-in rules label what they can, labels the rest, has the vault server write `Daily\<today>.md` and the waiting items in `Follow-ups.md`, then lists possible batch changes (mark fyi/noise as read, move to a folder, set categories) with the count and subjects each one touches. Nothing runs until you say yes to a specific option.

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

One `outlook_awaiting_reply` call checks your Sent folder for the last 30 days and lists the threads where your mail is the last message and it is at least `days` old, with the last line you wrote. New threads get a row in `Follow-ups.md`; rows whose thread has since been answered move to Done. Then it shows one nudge draft at a time and saves it to Drafts only on a yes. Nothing is ever sent.

### `/administrator:weekly [week]`

```
/administrator:weekly
/administrator:weekly last
/administrator:weekly 2026-W33
```

Writes `Weekly\YYYY-Www.md` from `vault_weekly_facts` (the week's daily notes, `Follow-ups.md`, the meeting notes and the person notes, counted in the vault server), next week's calendar, and the week's hours by kind against your priorities (`vault_time_audit`, under `## Time`), plus a few bullets of its own under `## Notes`. Running it again on the same week appends an update section.

### `/administrator:time-block [week | this | next]`

```
/administrator:time-block
/administrator:time-block next
```

Reads `Preferences.md` and `Priorities.md` — when the list is empty, or you say "suggest priorities", it proposes 3–5 from the wiki's due dates, open items, oldest follow-ups and unfinished weekly items and writes `Priorities.md` only after your yes (edit the file in Obsidian any time); a `Preferences.md` from before 0.3.0 has no `peak_hours`, so it asks once when you are sharpest — shows last week in three lines (hours per kind, blocks held / moved / skipped, hours per priority), then the plan for the week as one line per day — focus blocks in your peak hours named after your priorities, admin blocks outside them, a fifth of each day left free, days already full of meetings skipped with the reason — and asks once: "Book these N blocks? They are appointments without attendees — nothing is sent to anyone." On a yes it creates the appointments (busy, category `Administrator`, no reminder) and writes `Time-blocks\YYYY-Www.md`. Running it again keeps every existing block and adds only where room opened up.

### `/administrator:find <sentence>`

```
/administrator:find the email where we agreed on the Q3 budget with Sam
/administrator:find the spreadsheet Maria sent with vendor pricing last month
```

Pulls people, topic words, dates and attachment hints out of the sentence, makes one `outlook_find` call (the server searches the folders, ranks and returns ten snippets), opens at most two threads, and quotes the sentence that answers the question. Hard cap of 6 Outlook calls. Changes nothing; saving is offered through `/administrator:save`.

### `/administrator:collect-information [since <date> | today]`

```
/administrator:collect-information
/administrator:collect-information today
/administrator:collect-information since 2026-08-21
```

Reads the "last collected" stamps and, when they are older than a day, asks once: "Last collected: Fri 21 Aug 18:10. Collect since then, or just today?" Then Teams (`teams_list_chats`, at most 15 chats with 20 messages each), Inbox and Sent (`outlook_list_mails`, 50 per folder; at most 8 mails that touch a wiki page are opened and saved), and the vault's own notes changed since (`vault_changed_notes`, the record folders plus any `collect_folders` you list in `Preferences.md`). Chat records go to `Teams\`, mails to `Emails\`; then the wiki changes are shown grouped by page and applied only after your yes, oldest record first. The stamps move, and one last question asks whether today's `[Focus]` / `[Admin]` blocks were held, moved or skipped (recorded in the week's `Time-blocks\` note). Nothing in Outlook or Teams is changed.

### `/administrator:draft <thread words or entry_id> [what to say]`

```
/administrator:draft delivery schedule tom — 8 Sep is fine, ask for the packaging spec
/administrator:draft offsite venue priya
```

Finds the thread (asks when more than one matches), reads it, reads what the vault knows about the sender, and writes the reply in your voice. Your voice comes from one `outlook_voice_sample` call: the opening and sign-off of your last 10 sent mails to that person (or overall) plus counted greetings and sign-offs; you can add hard rules in `Preferences.md` under `## Voice` — the plugin only reads that file. Missing facts become `[fill in: …]` markers, never guesses. Only after a yes does it call `outlook_reply_mail(save_only=true)`; the draft sits in Drafts inside the conversation and you send it from Outlook.

### `/administrator:wiki <page | question | statement | ingest <record>>`

```
/administrator:wiki q3 budget
/administrator:wiki who owns the supplier contract at ACME
/administrator:wiki add: Jane is out of office until 2026-09-08
/administrator:wiki ingest Emails/2026-08-12 Net 30 terms
/administrator:wiki resolve review
```

A page name shows the page (lead, facts, open items, newest records). A question is answered from the two best-matching pages, every claim with its page link. A statement becomes one operation on one page, shown first and written only after you say ok, marked as yours so that no later mail replaces it without asking. `ingest` runs the wiki step on a record that was saved before the wiki existed; `resolve review` walks through `Wiki\Review.md` one item at a time.

### `/administrator:lint [fix]`

```
/administrator:lint
/administrator:lint fix
```

Runs the fifteen checks in `Wiki\Wiki.md` and reports the counts: index out of step, dangling links, orphans, frontmatter, section order, oversized pages, stale pages, past due dates, ticked open items, possible duplicates, records never ingested, topic candidates, contradictions, unconfirmed facts. With `fix` the safe ones are applied (index, keys, order, ticked items, stale topics set dormant, roll-overs). Merges and new topic pages are questions; nothing happens without a yes. `/administrator:weekly` runs the same with `fix` and offers to ingest records that were never ingested, ten at a time.

### `Administrator\Preferences.md`

Created by `/administrator:setup` (or with defaults the first time any command needs it). Edit it in Obsidian: `work_start`, `work_end`, `buffer_minutes`, `no_meeting_blocks`, `max_meetings_per_day`, `default_duration`, `default_location`, `preferred_days`, and for the time blocks `peak_hours`, `focus_block_minutes`, `focus_blocks_per_day`, `admin_blocks_per_day`, `admin_block_minutes`, `slack_share` (plus `collect_folders` for `/administrator:collect-information`). The plugin reads it once per session and never changes it. An optional `## Voice` section (plain bullets: greeting, sign-off, length, formality, hard rules like "no exclamation marks") is read by `/administrator:draft`, nudges and minutes; you write it yourself, the plugin never edits the file.

## What never happens without a yes

- Marking mail read or unread, flagging, or setting categories (`outlook_mark_mail`, `outlook_bulk_mark_mails`, `outlook_set_category`).
- Moving or deleting mail (`outlook_move_mail`, `outlook_delete_mail`, `outlook_bulk_move_mails`, `outlook_bulk_delete_mails`). The inbox workflow never deletes at all; it offers a move instead.
- Writing files from Outlook to disk (`outlook_save_mail_as`, `outlook_save_attachments`); these land in `<vault>\Administrator\Attachments\<date slug>\` and are offered once per save.
- Saving an email draft (`outlook_send_mail(save_only=true)` — minutes after `/administrator:notes`, proposed times from `/administrator:schedule`, nudge drafts from `/administrator:followups`; `outlook_reply_mail(save_only=true)` — a reply in the thread from `/administrator:draft`). The plugin never sends plain email, not even with a yes: `outlook_send_mail` without `save_only`, `outlook_reply_mail` without `save_only` and `outlook_forward_mail` are never called. You send from Drafts.
- Creating or moving a meeting (`outlook_create_event`, `outlook_update_event`), both only from `/administrator:schedule` after the full summary. An invite goes to every attendee as soon as it is created. Deleting events or answering invites never happens.
- Booking or moving your own time blocks (`outlook_create_event` without attendees from `/administrator:time-block` after "Book these N blocks?"; `outlook_update_event` on a block from `/administrator:daily` after "Move it?"). Blocks have no attendees, so nothing reaches anyone; the plugin never deletes one.

Every offer states the exact action, the number of items, and their subjects. "Yes" means that option only.

## Path sandbox

`outlook_save_mail_as` and `outlook_save_attachments` only write to absolute paths under your user profile (`C:\Users\<you>\...`). Keep the vault there and exports land in `<vault>\Administrator\Attachments\` without trouble. If the vault lives on another drive or a network share, the export step is skipped unless you set `OUTLOOK_MCP_ALLOW_ANY_PATH=1` in your environment. The plugin's own note writing has no such limit, but it never writes outside `<vault>\Administrator\`.

## Classic Outlook only

The connector talks to Outlook through COM, which only classic desktop Outlook exposes. It needs Outlook installed with a profile on the same Windows machine where Claude Code runs. Corporate machines may show a "Programmatic Access" prompt on first write; see the `outlook` skill's gotchas if a change seems to silently do nothing.

## Notes the plugin writes

Every note has frontmatter with `type` (`email`, `daily`, `person`, `meeting`, `weekly`, `chat`, `time-block`, `preferences`, `priorities`, or a wiki type `org`, `topic`, `howto`, `me`), `source: outlook` (`teams` for chat records, `administrator` for preferences, priorities, weekly and time-block notes), `created_by: administrator/0.3.0`, and for emails the Outlook identity (`internet_message_id`, `entry_id`, `conversation_id`), sender SMTP address, recipients, `received` with timezone offset, and a `status` of `todo`, `waiting`, `done`, or `fyi`. Meeting notes carry the event's `global_id` and `occurrence_key` (one note per occurrence of a recurring meeting) and a `status` of `upcoming`, `held`, or `cancelled`. Links use wikilinks (`[[Wiki/People/Jane Doe]]`) so Obsidian's graph and backlinks work out of the box.

Existing notes are never overwritten. When a mail is saved again, an `## Update <timestamp>` section is appended. Every command that writes a note ends with an `obsidian://open` link to it. The notes are written by the `vault` server, which also enforces the frontmatter and never edits text that is already there.

## Obsidian

Notes are plain markdown with frontmatter and wikilinks; nothing beyond core Obsidian is needed. `Administrator\_views\` holds five Bases files (core plugin, Obsidian 1.9+): `People.base`, `Follow-ups.base`, `Meetings.base` (by week), `Emails.base` (by status and sender), `Wiki.base` (active topics, stale pages, the review queue, people by organisation). Open them like notes or embed one with `![[Administrator/_views/People.base]]`. Every command reply ends with an `obsidian://open` link to the note it wrote; set `ADMINISTRATOR_VAULT_NAME` if the name Obsidian shows differs from the folder name. The plugin never touches `.obsidian\` or anything outside `Administrator\`. Details, including sync advice and why the saved `.msg` is the way back to the original mail: `skills/administrator/references/obsidian.md`.

## License

MIT
