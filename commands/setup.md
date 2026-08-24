---
description: Check that Outlook and the vault are reachable, create the Administrator folder, the wiki and their files (Priorities.md included) if they are missing, set your work hours and peak hours once, say whether the optional Teams server can read the local Teams cache, and offer to move an older vault's People folder into the wiki (dry run shown first). Run this first on a new machine.
argument-hint: ""
---

# /administrator:setup

No arguments. Read-only apart from one call to `vault_init`, which creates missing folders and files under `<vault>/Administrator/` and never overwrites anything, and — only after a yes — `vault_wiki_migrate`, which moves an older vault's `People/` folder into the wiki with a backup.

## Steps

1. Load the `administrator` skill. Load the `outlook` skill if it is not already loaded.
2. **Are the MCP servers running?** Look at the tools you have.
   - No `vault_*` tools: stop and say "The vault server is not running. `OUTLOOK_MCP_DIR` must point to your `outlook-classic-mcp` checkout (a version that has the `administrator-vault` script; run `uv sync` in that folder once), and Claude Code must be restarted after setting it." Do not try to write notes by hand.
   - No `outlook_*` tools: say the same for the `outlook` server (same variable, same checkout). Continue with the vault checks so the user gets one complete report.
   - No `teams_*` tools: not a failure. One line: "The optional `local-ms-teams` server is not running; `/administrator:collect-information` will skip Teams. It starts from the same checkout once `uv sync --extra teams` has run there and Claude Code was restarted."
3. **Vault.** Call `vault_status`. The result has `vault` (the value of `ADMINISTRATOR_VAULT`), `exists`, `is_dir`, `administrator_dir_exists`, `folders`, `files`, `old_people_dir`, `under_user_profile`, `vault_name`.
   - `vault` empty: say "ADMINISTRATOR_VAULT is not set. Set it to the absolute path of your Obsidian vault (for example `C:\Users\<you>\Documents\Vault`), then restart Claude Code." and skip to step 4; do not guess a vault, do not search the disk.
   - `exists` or `is_dir` false: say "ADMINISTRATOR_VAULT points to `<vault>`, which is not a directory." Do not create the vault itself.
   - Otherwise note which of `folders` and `files` are false; they are created in step 5.
4. **Outlook.** Call `outlook_whoami`. Report the account (`accounts[].smtp_address`) and the timezone (`utc_offset`) in one line.
   On an error, say what it most likely means, in plain words:
   - "Class not registered", "Invalid class string", or a COM error: Outlook is not the classic desktop version. The new Outlook (`olk.exe`) has no COM interface; switch back to classic Outlook (`outlook.exe`) and try again.
   - "No profile", "The operation failed", or a prompt that never returns: Outlook has no mail profile, or asks for one on start. Open Outlook once by hand, finish the profile setup, leave it running, and run this command again.
   - A timeout on the first call is normal after a cold start; try once more before calling it a failure.
   **Teams** (only when `teams_*` tools exist): `teams_status()` → one line from `reader_installed`, `cache_found`, `accounts[].label`, `chats`, `messages`, `newest`; when `hint` is set, print the hint as that line (missing extra: `uv sync --extra teams` in the checkout, then restart; no cache: sign in to the new Teams client once). Never a failure; the Teams cache is read from a copy and never written.
5. **Create what is missing.** If `administrator_dir_exists` is false or any `folders` / `files` flag is false:
   - If `files["Preferences.md"]` is false, ask once, in one short message ending in a question: "I will set work hours 09:00–17:00, a 15-minute buffer, and 09:00–12:00 as your sharpest hours (focus blocks go there first). Keep those, or tell me yours?" Wait for the answer. A plain yes keeps the defaults; otherwise take the hours (`HH:MM`), the buffer (minutes) and the peak hours (one or more `HH:MM-HH:MM` ranges) from the reply. Do not ask when `Preferences.md` already exists.
   - Call `vault_init(work_start=<HH:MM>, work_end=<HH:MM>, buffer_minutes=<n>, peak_hours=["<HH:MM-HH:MM>", …], created_by="administrator/0.3.0")`. Never pass `overwrite=true` from this command. Report `created` and `skipped` as two short lists of paths.
   - When nothing is missing, say so in one line and call nothing.
   - `vault_init` also creates `Administrator/Wiki/` with `Wiki.md` (the page contract, the server's copy of `skills/wiki/references/wiki.md`), empty `Index.md`, `Log.md`, `Review.md`, the page folders and `_views/Wiki.base`, plus `Teams/`, `Time-blocks/` and `Priorities.md` (the user's ranked priorities, created once with one placeholder line; `/administrator:time-block` reads it, suggests a list when it is empty, and replaces the list only with lines the user confirmed).
6. **Migration of an older vault.** If `vault_status` shows `old_people_dir` true (a 0.1.0 vault with `Administrator/People/`), call `vault_wiki_migrate(dry_run=true)` and show its plan in a few lines from the result: `people[]` (how many person notes move to `Wiki/People/`, `exists` marks a name clash), `links` (`files`, `count`: old `People/…` links in records, `Follow-ups.md`, daily and weekly notes that become `[[Wiki/People/…]]`), `views` (which `.base` files change), `left` (files in `People/` that are not person notes), where the backup goes (`Administrator/_backup/<stamp>/People/`). Then ask, in one short message ending in a question: "Move People/ into the wiki now? (a backup is kept; nothing else changes)". Only on a clear yes: `vault_wiki_migrate(dry_run=false, created_by="administrator/0.3.0")` and report `moved` (count), `skipped`, `links_rewritten`, `backup`, and `old_folder_removed` (false with `old_folder_left` listing what stayed, when the user put other files there). A no leaves everything as it is; new people still go to `Wiki/People/`, and the user can migrate later with this command.
7. **Export sandbox.** If `under_user_profile` is false, warn: "The vault is outside `C:\Users\<you>`, so `.msg` and attachment exports (`outlook_save_mail_as`, `outlook_save_attachments`) will be refused. Notes still work. To allow exports anyway set `OUTLOOK_MCP_ALLOW_ANY_PATH=1` and restart Claude Code."
8. **Report.** Seven lines at most: servers (both present or which one is missing), Outlook account and timezone, the Teams line from step 4 (or the one-line hint when the server is absent), vault path and name, what was created, the migration result or offer, the sandbox warning if any. End with the links `obsidian://open?vault=<vault_name>&file=Administrator%2FPreferences.md` and `obsidian://open?vault=<vault_name>&file=Administrator%2FPriorities.md` (`vault_name` from `vault_status`) and one line: "Edit Preferences.md and Priorities.md in Obsidian any time; the plugin reads them once per session, never changes Preferences.md, and writes Priorities.md only with lines you confirmed."

## Example

```
/administrator:setup
```

> Both servers are up. Outlook: hux@example.com, UTC+02:00.
> Teams: cache found for Example GmbH, 41 chats, 1180 messages, newest Tue 25 Aug 17:31.
> Vault: `C:\Users\<you>\Documents\Vault` (name `Vault`). Created `Administrator/`, 9 folders, `Wiki/` (Wiki.md, Index, Log, Review, 4 page folders), `Follow-ups.md`, `Preferences.md` (09:00–17:00, buffer 15, peak 09:00–12:00), `Priorities.md` and 5 views.
> obsidian://open?vault=Vault&file=Administrator%2FPreferences.md
> obsidian://open?vault=Vault&file=Administrator%2FPriorities.md
> Edit Preferences.md and Priorities.md in Obsidian any time; the plugin reads them once per session, never changes Preferences.md, and writes Priorities.md only with lines you confirmed.

Without the Teams extra the second line reads "Teams: install the `teams` extra: `uv sync --extra teams` in the checkout, then restart Claude Code." — not a failure.

On a vault from 0.1.0 the run adds, before the link:

> Found `Administrator/People/` with 12 person notes. Plan (dry run): move 12 notes to `Wiki/People/`, rewrite 41 old `People/…` links in 28 records, `Follow-ups.md` and 9 daily notes, update `People.base`; backup to `Administrator/_backup/2026-08-22T10-15-00/People/`. Move People/ into the wiki now? (a backup is kept; nothing else changes)

Running it again when everything exists reports "Nothing to create." and the same link.
