# administrator — v0.0.1 scope

**One line:** an agent plugin that runs the user's Outlook (via `outlook-classic-mcp` 0.4.0) and keeps the paper trail in an Obsidian vault.

v0.0.1 goal: *prove the loop* — read Outlook → decide → write a durable note → (optionally) act in Outlook. Nothing automated, nothing scheduled, nothing sent without confirmation.

## Non-goals (deferred)

- Obsidian Local REST API / Obsidian MCP server — v0.0.1 treats the vault as plain markdown on disk.
- Sending mail without explicit per-message confirmation.
- Calendar/contact *writes* (create/update events, contacts) — read-only use of calendar in 0.0.1.
- Dataview/Templater dependence in notes — notes must be readable with a vanilla Obsidian.
- Excel / any non-Outlook source.
- Scheduling / cron / background runs.

## Architecture

```
administrator/                      # plugin repo (this dir)
  .claude-plugin/plugin.json        # name: administrator, bundles outlook MCP server
  skills/
    administrator/SKILL.md          # core: how it behaves, vault conventions, when to ask, which skill to use
    administrator/references/vault.md      # note templates + frontmatter schema
    administrator/references/outlook.md    # pointer to outlook skill conventions (entry_id, folders, dates)
    inbox/SKILL.md                  # go-through-inbox workflow
    save/SKILL.md                   # email/thread → note workflow
  commands/
    inbox.md                       # /administrator:inbox [folder] [since]
    save.md                      # /administrator:save <entry_id | search terms>
    daily.md                        # /administrator:daily  (inbox + today's calendar → daily note)
  README.md
```

**Outlook:** `plugin.json` `mcpServers.outlook` → `uv run --directory <outlook-classic-mcp> outlook-mcp` for now (local path); switch to `uvx --from <your-package>` once published.

**Obsidian:** the vault is just files. The agent uses the host's file tools (Read/Write/Glob) against `ADMINISTRATOR_VAULT` (absolute path, env var or `~/.administrator/config.json`). All writes go under one subfolder `Administrator/` so the plugin never touches the user's other notes. Attachment exports from Outlook (`outlook_save_mail_as`, `outlook_save_attachments`) land in `Administrator/Attachments/`, which is inside the user profile sandbox as long as the vault is.

## Vault layout & note schema

```
<vault>/Administrator/
  Daily/YYYY-MM-DD.md          # one per day: inbox summary, calendar, action items
  Emails/YYYY-MM-DD <slug>.md  # one per saved mail/thread
  People/<Display Name>.md     # auto-created stub the first time someone is saved; links back to emails
  Attachments/                 # .msg / .pdf / etc. exported from Outlook
  Follow-ups.md                # single rolling list of "waiting on" items
```

Frontmatter (every generated note):

```yaml
---
type: email | daily | person
source: outlook
entry_id: "<exact EntryID>"        # email notes only
conversation_id: "<id>"            # email notes only
from: alice@example.com            # SMTP — guaranteed by 0.4.0 sender_smtp
received: 2026-08-22T09:14:00+02:00
status: todo | waiting | done | fyi
created_by: administrator/0.0.1
---
```

Rules: never overwrite a note that already has an `entry_id` match — append a `## Update <timestamp>` section instead. Person notes are linked from email notes; daily notes link to every email note touched that day.

## Skills

### `administrator` (core — always loaded)
- Who it is: acts like an assistant; terse; confirms before anything leaves the machine.
- Routing: "what's in my inbox / anything urgent" → inbox; "save/note this" → save; "what's today" → daily.
- Vault conventions (above), slug rules, `entry_id` handling, when to append vs create.
- Confirmation policy: reads free; `bulk_*`, `move_mail`, `delete_mail`, `send_mail`, `reply_mail` require an explicit yes listing the affected subjects/count.
- Hands all Outlook mechanics to the existing `outlook` skill (don't duplicate tool docs).

### `inbox`
1. `outlook_list_mails(unread_only=true, since=<last daily note or 24h>, limit=100, response_format=json)`
2. Classify each into **act / reply / waiting / fyi / noise** using subject, sender, preview; `get_mail` only for ambiguous ones (cap 10).
3. Write/append `Daily/YYYY-MM-DD.md` with a table + action list; add `waiting` items to `Follow-ups.md`.
4. Offer (not execute) batch actions: `bulk_mark_mails(read=true)` for fyi/noise, `bulk_move_mails` to a user-named folder, `bulk_mark_mails(categories=[...])` using only names from `list_categories`.

### `save`
1. Resolve target: `entry_id` given → `get_mail`; otherwise `search_mails` and show candidates (max 5) for the user to pick.
2. Create `Emails/<date> <slug>.md` with frontmatter, cleaned body (strip quoted history past first reply), recipients, `[[People/…]]` links, and a one-line summary + extracted action items.
3. Optional: `save_mail_as(fmt="msg")` and `save_attachments` into `Attachments/`, linked from the note.
4. Create/append `People/<name>.md` stub for the sender.

### `daily` (command only, composes the two skills)
- Run inbox, then `outlook_list_events(today)`; render agenda into the daily note; point out clashes and meetings with no prep note.

## Outlook server requirements

Everything needed exists in 0.4.0: `list_mails` (unread/since/from/has_attachments), `search_mails`, `get_mail` (now with `recipients` + SMTP `from_address`), `bulk_move/delete/mark`, `export_mails`, `save_mail_as`, `save_attachments`, `list_events`, `list_categories`, `whoami`.

Added to the server during the v0.0.1 build: `internet_message_id` on every mail item (stable identity) and `outlook_get_conversation(entry_id)` to pull a whole thread in one call (37 tools). The stale "EX:/O=… addresses" line in `skills/outlook/SKILL.md` was fixed at the same time.

## Definition of done (v0.0.1)

- [ ] `plugin.json` loads; `outlook_*` tools appear alongside the skills.
- [ ] `/administrator:inbox` on a real inbox produces a correct daily note and no Outlook writes without a confirm.
- [ ] `/administrator:save <search terms>` produces an email note + person stub with valid frontmatter and working wikilinks in Obsidian.
- [ ] `/administrator:daily` runs end-to-end in < 60 s on a 100-mail inbox.
- [ ] Running a command twice is safe (appends, never duplicates notes).
- [ ] README: install, `ADMINISTRATOR_VAULT`, sandbox note, classic-Outlook-only note.

## Open decisions (my defaults in bold)

- Vault config: **env var `ADMINISTRATOR_VAULT`** vs config file.
- Person note key: **display name** vs SMTP address (display is readable; SMTP is unique — store both in frontmatter).
- Inbox window default: **since last daily note, else 24 h**.
