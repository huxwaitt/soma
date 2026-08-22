# administrator

A Claude Code plugin that runs your classic Outlook mailbox and keeps the paper trail in an Obsidian vault.

It reads Outlook through the bundled `outlook-classic-mcp` server, decides what matters, and writes plain markdown notes into one folder of your vault. It reads freely. It never moves, marks, deletes, or sends anything without an explicit yes from you, and version 0.0.1 sends no mail at all.

## What you get

- **`/administrator:inbox`** — goes through unread mail, sorts each item into act / reply / waiting / fyi / noise, writes today's daily note, and offers batch clean-up you can accept or decline.
- **`/administrator:save`** — saves one email (or, on request, its whole thread via `outlook_get_conversation`) as a note with stable identity, cleaned body, action items, a link to a person note, and optional `.msg` and attachment exports.
- **`/administrator:daily`** — inbox plus today's calendar in one daily note, with clashes and meetings that have no prep note called out.

## Requirements

- Windows 10 or 11.
- **Classic** Outlook (desktop, `outlook.exe`) with a configured mail profile. The new Outlook (`olk.exe`) is not supported; switch back to classic if you are on it.
- [uv](https://docs.astral.sh/uv/) on your PATH.
- A local checkout of `outlook-classic-mcp` (0.4.0 or later). The plugin currently points at `C:\Users\huxle\PycharmProjects\outlook-classic-mcp`; edit `.claude-plugin/plugin.json` if yours is elsewhere.
- An Obsidian vault on disk. Notes are plain markdown with frontmatter; no community plugins are needed to read them.

## Install

1. Clone or copy this folder somewhere on disk, for example `C:\Users\<you>\PycharmProjects\administrator`.
2. In Claude Code, add it as a local plugin:

   ```
   /plugin install C:\Users\<you>\PycharmProjects\administrator
   ```

   or register it in your marketplace settings, then restart Claude Code.
3. Confirm the Outlook tools are present: ask "who am I in Outlook?" and the agent should call `outlook_whoami`.

## Set the vault path

The plugin writes only under `<vault>\Administrator\`. Tell it where the vault is with one environment variable holding an absolute path:

```powershell
# Current session
$env:ADMINISTRATOR_VAULT = "C:\Users\<you>\Documents\MyVault"

# Permanent (user scope)
[Environment]::SetEnvironmentVariable("ADMINISTRATOR_VAULT", "C:\Users\<you>\Documents\MyVault", "User")
```

Restart Claude Code after setting it permanently. The plugin creates this layout on first use:

```
<vault>\Administrator\
  Daily\YYYY-MM-DD.md          one per day
  Emails\YYYY-MM-DD <slug>.md  one per saved mail
  People\<Display Name>.md     one per sender
  Attachments\<date slug>\     .msg and attachment exports, one folder per saved mail
  Follow-ups.md                rolling "waiting on" list
```

## Commands

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

With search terms it shows up to five matches and asks you to pick. Then it writes `Emails\<date> <subject>.md`, creates or updates `People\<Sender>.md`, and asks whether to export the `.msg` and attachments into `Attachments\`. Running it twice on the same mail appends an update section instead of making a duplicate.

### `/administrator:daily [date]`

```
/administrator:daily
/administrator:daily 2026-08-25
```

Runs the inbox workflow, then adds today's agenda from `outlook_list_events`, flags overlapping meetings and meetings with no prep note, and gives you a short brief.

## What never happens without a yes

- Marking mail read or unread, flagging, or setting categories (`outlook_mark_mail`, `outlook_bulk_mark_mails`, `outlook_set_category`).
- Moving or deleting mail (`outlook_move_mail`, `outlook_delete_mail`, `outlook_bulk_move_mails`, `outlook_bulk_delete_mails`). The inbox workflow never deletes at all; it offers a move instead.
- Writing files from Outlook to disk (`outlook_save_mail_as`, `outlook_save_attachments`); these land in `<vault>\Administrator\Attachments\<date slug>\` and are offered once per save.
- Sending anything (`outlook_send_mail`, `outlook_reply_mail`, `outlook_forward_mail`). Version 0.0.1 does not send mail even with a yes; that is deferred.
- Creating, changing, or responding to calendar events. Calendar use in 0.0.1 is read-only.

Every offer states the exact action, the number of items, and their subjects. "Yes" means that option only.

## Path sandbox

`outlook_save_mail_as` and `outlook_save_attachments` only write to absolute paths under your user profile (`C:\Users\<you>\...`). Keep the vault there and exports land in `<vault>\Administrator\Attachments\` without trouble. If the vault lives on another drive or a network share, the export step is skipped unless you set `OUTLOOK_MCP_ALLOW_ANY_PATH=1` in your environment. The plugin's own note writing has no such limit, but it never writes outside `<vault>\Administrator\`.

## Classic Outlook only

The connector talks to Outlook through COM, which only classic desktop Outlook exposes. It needs Outlook installed with a profile on the same Windows machine where Claude Code runs. Corporate machines may show a "Programmatic Access" prompt on first write; see the `outlook` skill's gotchas if a change seems to silently do nothing.

## Notes the plugin writes

Every note has frontmatter with `type` (`email`, `daily`, or `person`), `source: outlook`, `created_by: administrator/0.0.1`, and for emails the Outlook identity (`internet_message_id`, `entry_id`, `conversation_id`), sender SMTP address, recipients, `received` with timezone offset, and a `status` of `todo`, `waiting`, `done`, or `fyi`. Links use wikilinks (`[[People/Jane Doe]]`) so Obsidian's graph and backlinks work out of the box.

Existing notes are never overwritten. When a mail is saved again, an `## Update <timestamp>` section is appended.

## License

MIT
