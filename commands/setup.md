---
description: Check that Outlook and the vault are reachable, create the Administrator folder, the wiki and their files (Priorities.md and the wiki's Questions.md included) if they are missing, set your work hours and peak hours once, say whether the optional Teams server can read the local Teams cache, and offer to move an older vault's People folder into the wiki (dry run shown first). Run this first on a new machine.
argument-hint: ""
---

# /administrator:setup

No arguments. Read-only apart from one call to `vault_init`, which creates missing folders and files under `<vault>/Administrator/` and never overwrites anything, and — only after a yes — `vault_wiki_keep(action="migrate")`, which moves an older vault's `People/` folder and the rows of `Follow-ups.md` into the wiki with a backup.

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
   - A timeout on the first call is normal while Outlook is still waking up; try once more before calling it a failure.
   **Teams** (only when `teams_*` tools exist): `teams_status()` → one line from `reader_installed`, `cache_found`, `accounts[].label`, `chats`, `messages`, `newest`; when `hint` is set, print the hint as that line (missing extra: `uv sync --extra teams` in the checkout, then restart; no cache: sign in to the new Teams client once). Never a failure; the Teams cache is read from a copy and never written.
5. **Create what is missing.** `vault_init` runs on every setup — it writes only what is absent — so the bullets below apply whether or not `administrator_dir_exists` and the `folders` / `files` flags are all true:
   - If `files["Preferences.md"]` is false, ask once, in one short message ending in a question: "I will set work hours 09:00–17:00, a 15-minute buffer, and 09:00–12:00 as your sharpest hours (focus blocks go there first). Keep those, or tell me yours?" Wait for the answer. A plain yes keeps the defaults; otherwise take the hours (`HH:MM`), the buffer (minutes) and the peak hours (one or more `HH:MM-HH:MM` ranges) from the reply. Do not ask when `Preferences.md` already exists.
   - Call `vault_init(work_start=<HH:MM>, work_end=<HH:MM>, buffer_minutes=<n>, peak_hours=["<HH:MM-HH:MM>", …], created_by="administrator/0.4.1")`. Never pass `overwrite=true` from this command. Report `created` and `skipped` as two short lists of paths. When `backup` comes back set, one more line: "A copy of `Administrator/` is kept at `<backup>`" — the vault already held wiki pages written before this version, and the first call that writes reads them all back, so one zip is made first (`_cache/` and `_backup/` left out). `backup: null` means there was nothing to keep; say nothing.
   - When nothing is missing, call `vault_init(created_by="administrator/0.4.1")` once all the same and say "Nothing to create." in one line: it writes no file that already exists, and it is the call that makes the backup of a vault whose wiki this version has not read back yet.
   - `vault_init` also creates `Administrator/Wiki/` with `Wiki.md` (the page contract, the server's copy of `skills/wiki/references/wiki.md`), empty `Index.md`, `Log.md`, `Review.md`, `Questions.md` (the questions you want the wiki to be able to answer, with the page that should answer each — it starts empty with two examples above the list, it is yours, and `/administrator:lint` asks the wiki every question on it and reports the ones it could not answer), the page folders `People/`, `Orgs/`, `Topics/`, `Decisions/` and `Howto/`, and `_views/Wiki.base` (with its Projects and Decisions views), plus `Teams/`, `Time-blocks/`, `Documents/` (one record per file read in, written by `/administrator:save <file path>` and by the watched folders of `/administrator:collect-information`) and `Priorities.md` (the user's ranked priorities, created once with one placeholder line; `/administrator:time-block` reads it, suggests a list when it is empty, and replaces the list only with lines the user confirmed).
6. **Migration of an older vault.** Call `vault_wiki_keep(action="migrate", dry_run=true)` when `vault_status` shows `old_people_dir` true (a 0.1.0 vault with `Administrator/People/`) or `Follow-ups.md` still holds rows of its own. The plan comes back as `{needed, parts: {people, followups, views}, people[], links, views, followups, left, backup}`; show only the parts that are `true`, each as its own offer, one question at a time:
   - `parts.people`: `people[]` (how many person notes move to `Wiki/People/`, `exists` marks a name clash), `links` (`files`, `count`: old `People/…` links in records, daily and weekly notes that become `[[Wiki/People/…]]`), `left` (files in `People/` that are not person notes), the backup (`Administrator/_backup/<stamp>/People/`). Ask: "Move People/ into the wiki now? (a backup is kept; nothing else changes)".
   - `parts.followups`: `followups` = `{open: [{who, text, since, page, record, src}], done: [{…, closed}], count, backup}` — the `## Open` rows become open items on the page the `Who` names (an unknown name lands on `Wiki/Me.md` with the name in the text) and the `## Done` rows become History lines, after which the file is written from the pages. Say how many of each and where the backup goes (`Administrator/_backup/<stamp>/Follow-ups.md`), then ask: "Move the Follow-ups rows onto the pages now? (a backup is kept)".
   - `parts.views`: `views` lists the `.base` files that are out of date; they are brought up to date with the run.
   Only on a clear yes: `vault_wiki_keep(action="migrate", dry_run=false, created_by="administrator/0.4.1")` — one call does every part the plan named — and report `moved` (count), `skipped`, `links_rewritten`, `followups_moved` (`{open, done}`), `backup`, and `old_folder_removed` (false with `old_folder_left` listing what stayed, when the user put other files there). A no leaves everything as it is; new people still go to `Wiki/People/`, `Follow-ups.md` keeps its own rows until it is migrated, and the user can run this command again later.
7. **Offer to load the past.** Only when this run's `vault_init` created the wiki (a first run: `folders["Wiki"]` was false in step 3) and nothing else in this turn is a question — a migration offer from step 6 is answered first — end with one line, not a question of its own: "Load the last 90 days into the wiki in batches of 25 (one yes per batch)? — `/administrator:load-history`". It reads the Outlook inbox, the sent items and the Teams chats from before the "last collected" stamps, oldest first, and asks once per batch; the stamps are never moved. Say nothing about it when the wiki already existed.
8. **Export sandbox.** If `under_user_profile` is false, warn: "The vault is outside `C:\Users\<you>`, so `.msg` and attachment exports (`outlook_save_mail_as`, `outlook_save_attachments`) will be refused. Notes still work. To allow exports anyway set `OUTLOOK_MCP_ALLOW_ANY_PATH=1` and restart Claude Code."
9. **Report.** Eight lines at most: servers (both present or which one is missing), Outlook account and timezone, the Teams line from step 4 (or the one-line hint when the server is absent), vault path and name, what was created (with the backup line when `vault_init` made one), the migration result or offer (People/, Follow-ups rows, views), the load-history line from step 7 on a first run, the sandbox warning if any. End with the links `obsidian://open?vault=<vault_name>&file=Administrator%2FPreferences.md`, `obsidian://open?vault=<vault_name>&file=Administrator%2FPriorities.md` and `obsidian://open?vault=<vault_name>&file=Administrator%2FWiki%2FQuestions.md` (`vault_name` from `vault_status`) and one line: "Edit Preferences.md, Priorities.md and Questions.md in Obsidian any time; the plugin reads them once per session, never changes Preferences.md or Questions.md, and writes Priorities.md only with lines you confirmed."

## Example

```
/administrator:setup
```

> Both servers are up. Outlook: hux@example.com, UTC+02:00.
> Teams: cache found for Example GmbH, 41 chats, 1180 messages, newest Tue 25 Aug 17:31.
> Vault: `C:\Users\<you>\Documents\Vault` (name `Vault`). Created `Administrator/`, 9 folders (`Documents/` among them), `Wiki/` (Wiki.md, Index, Log, Review, Questions.md, 5 page folders including `Decisions/`), `Follow-ups.md` (written from the wiki pages), `Preferences.md` (09:00–17:00, buffer 15, peak 09:00–12:00), `Priorities.md` and 5 views.
> obsidian://open?vault=Vault&file=Administrator%2FPreferences.md
> obsidian://open?vault=Vault&file=Administrator%2FPriorities.md
> obsidian://open?vault=Vault&file=Administrator%2FWiki%2FQuestions.md
> Edit Preferences.md, Priorities.md and Questions.md in Obsidian any time; the plugin reads them once per session, never changes Preferences.md or Questions.md, and writes Priorities.md only with lines you confirmed. Questions.md is where you write what the wiki should be able to answer; every `/administrator:lint` asks it those questions.

Without the Teams extra the second line reads "Teams: install the `teams` extra: `uv sync --extra teams` in the checkout, then restart Claude Code." — not a failure.

On a vault from 0.1.0 the run adds, before the link:

> Found `Administrator/People/` with 12 person notes. Plan (dry run): move 12 notes to `Wiki/People/`, rewrite 41 old `People/…` links in 28 records and 9 daily notes, update `People.base`; backup to `Administrator/_backup/2026-08-22T10-15-00/People/`. Move People/ into the wiki now? (a backup is kept; nothing else changes)

and, when `Follow-ups.md` still holds its own rows, one more question after that one is answered:

> `Follow-ups.md` has 7 open and 23 closed rows. They become open items on the pages (5 person pages, 2 on `Wiki/Me.md` because the name matched none) and History lines; the file is then written from the pages. Backup to `Administrator/_backup/2026-08-22T10-15-00/Follow-ups.md`. Move the Follow-ups rows onto the pages now? (a backup is kept)

Running it again when everything exists reports "Nothing to create." and the same link.
