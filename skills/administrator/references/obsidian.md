# Obsidian reference — links, Bases views, the `.msg` back-reference, and what the plugin never touches

The vault is an ordinary Obsidian vault. The plugin writes plain markdown under `<vault>/Administrator/` through the `vault_*` tools (see `references/vault.md`) and relies on nothing but core Obsidian: wikilinks, properties, and Bases (core plugin, Obsidian 1.9 or later). No Dataview, no Templater, no community plugin.

## What the plugin never touches

- `<vault>/.obsidian/` — Obsidian's own settings, workspace, themes, plugin list. Never read, never written. Do not "fix" a vault by editing anything in there.
- Anything outside `<vault>/Administrator/`. The `vault_*` tools refuse every path that does not start with `Administrator/`, reads included. If the user keeps other notes in the vault, they are invisible to the plugin.
- Existing text in a record. Appends only; see "Append on existing" in `references/vault.md`. Wiki pages are the exception by design: their lead and Facts are kept current by the `vault_wiki_*` tools, with every replaced fact kept in `## History`; anything under `## Notes` is never touched (`skills/wiki/references/wiki.md`).
- `Preferences.md` after it was created. `Follow-ups.md` is never edited either: code writes it from the open items of the wiki pages after every wiki change, and a row put in by hand is gone on the next write — tick or change the item on its page instead.

The only exception to "plain markdown" is `Administrator/_views/*.base`, the five Bases files below. `vault_init` writes them from the server package; `vault_init(overwrite=true)` rewrites them (and `Preferences.md`) and nothing else.

## `obsidian://open` links

Every reply that wrote or appended a note ends with one link per note, so the user can jump there from the terminal:

```
Open: obsidian://open?vault=<vault name>&file=<vault-relative path, URL-encoded, without .md>
```

Rules:

- `<vault name>` = `vault_status.vault_name` (the `ADMINISTRATOR_VAULT_NAME` variable when set, else the last segment of `ADMINISTRATOR_VAULT`). Obsidian matches it against the names in its vault list, so a vault opened from `C:\Users\<you>\Documents\Work Vault` is `Work Vault`.
- `file` is the path `vault_write` / `vault_row` returned, URL-encoded: spaces `%20`, `&` `%26`, `#` `%23`, `+` `%2B`, non-ASCII as UTF-8 percent-escapes. Obsidian opens the note with or without the `.md` and with `/` kept or encoded as `%2F`, so `Administrator/Daily/2026-08-22` and `Administrator%2FDaily%2F2026-08-22.md` both work; prefer the short form (no `.md`, `/` kept) when writing a link by hand.
- Spaces in the vault name are encoded the same way: `vault=Work%20Vault`. Never put quotes around the URL.
- One link per note written, in the order they were written; a run that wrote nothing prints no link.
- When a terminal does not make the link clickable, the user can paste it into the Windows Run dialog (`Win+R`) or a browser address bar.

Examples:

```
Open: obsidian://open?vault=MyVault&file=Administrator/Emails/2026-08-21%20Q3%20supplier%20contract%20%E2%80%93%20signature%20needed
Open: obsidian://open?vault=Work%20Vault&file=Administrator/Daily/2026-08-22
Open: obsidian://open?vault=MyVault&file=Administrator/Preferences
```

`Follow-ups.md` gets a link only when an open item was added or ticked in that run. The `.base` files can be linked too (`file=Administrator/_views/People.base` — keep the extension for non-markdown files); `setup` prints those four once.

## The five Bases views

`Administrator/_views/` holds one `.base` file per list. Each is a table over the notes' frontmatter; open it like a note, or embed it in any note with `![[Administrator/_views/People.base]]`. The user can add views, columns and filters in the Obsidian UI; `vault_init` without `overwrite` leaves edited files alone.

| File | Over | Views | Columns |
| --- | --- | --- | --- |
| `People.base` | `Wiki/People/`, `type: person` | **People** (newest contact first), **Quiet for 30 days** (`last_contact` older than 30 days, oldest first; stubs with `last_contact: ""` left out), **By company** | name, email, company, `last_contact`, "Since" (relative), "Emails + meetings" = number of links in the page (`file.links.length`: the `## Records` list plus any wiki links) |
| `Follow-ups.base` | `Emails/` + `Meetings/` | **Waiting on** (email notes with `status: waiting`, oldest first), **Held meetings** (`status: held`, newest first — these are the notes whose `## Waiting on` and `## Action items` may still be open), **Everything open** (every email/meeting note not `done` / `fyi` / `cancelled`, grouped by status) | note, who (`from_link` or `organizer_link`), since (`received` or `start`), "Waiting for" (relative) |
| `Meetings.base` | `Meetings/`, `type: meeting` | **By week** (grouped by ISO week `YYYY-Www` from `start`, newest week first), **Upcoming**, **Held**, **Cancelled** | meeting, when, where, organizer, attendee count (`attendee_links.length`), status |
| `Emails.base` | `Emails/`, `type: email` | **By status**, **By sender** (grouped by `from_link`), **To do**, **Last 7 days** | email, from, received, age, status, has attachments |
| `Wiki.base` | `Wiki/**`, wiki page types | **Projects** (topics with a `due`, soonest first), **Decisions** (`type: decision`, newest `decided` first), **Active topics by verified**, **Stale** (`flags` contains `stale`), **Review queue** (non-empty `flags`), **People by org**, **All pages** | title, type, status, owner, due, outcome, `decided`, `by`, what would reopen it, `verified`, `sources`, `open_items`, `flags` |

Two limits worth knowing:

- **`Follow-ups.md` itself is one file with markdown tables.** A Bases view reads frontmatter, not table rows, so `Follow-ups.base` cannot list its rows. It shows the notes behind them instead: email notes with `status: waiting` and held meetings. The list itself is written from the wiki pages' open items; the Bases file is the cross-check ("which saved mails are still marked waiting"), and `Wiki.base`'s **Projects** view shows the pages those items sit on.
- **Unchecked action items are body text.** Bases cannot count `- [ ]` lines, so `Meetings.base` groups by week and shows `status`; a held meeting with open boxes has to be opened to see them. `/administrator:weekly` reads the boxes itself and lists them in the weekly note.

What was checked against the Obsidian help (`obsidian.md/help/bases/syntax`, `obsidian.md/help/bases/functions`, fetched 2026-08-22) and is used in the files: top-level `filters` / `formulas` / `properties` / `views`; `and` / `or` / `not` filter lists with string expressions; `file.inFolder("…")`, `file.name`, `file.links` and `list.length`; `note.<key>` references; `formula.<name>` references; `groupBy: {property, direction}`; `order:` lists; `properties: <column>: displayName:`; `if(…)`, `date("…")`, `.isType("date")`, `.format("<moment format>")`, `.relative()`; `now() - "7d"` style date arithmetic. The `sort:` list (`- property: …` / `direction: ASC|DESC`) is what Obsidian itself writes when you sort a column in the UI; the help page example does not show it, so if a view ever opens unsorted, sort it once in the UI and Obsidian rewrites the key. Date fields: Obsidian reads `received` / `start` / `last_contact` as text when the ISO value carries an offset (`+02:00`), so every formula wraps them in `if(x.isType("date"), x, date(x))` before calling `.format()` / `.relative()`.

Adding a view: copy a `views:` entry in the `.base` file, or use "Add view" in the UI. Only reference frontmatter keys that exist in the templates in `references/vault.md` / `meeting-note.md`; `tests/test_vault_views.py` in the server repo checks the shipped files for that.

## No link back into Outlook — the `.msg` is the back-reference

An email note carries `entry_id`, `internet_message_id` and `conversation_id`, but no clickable link into Outlook, on purpose:

- `outlook:<entry_id>` URLs (the old `outlook:` protocol) are not registered on most installs, and an `entry_id` dies the moment the mail is moved to another store or archived. A link that works today is broken next month.
- The `internet_message_id` is stable but Outlook has no URL scheme that opens a mail by it.

The durable back-reference is the exported message: `/administrator:save` offers to write the original as `Administrator/Attachments/<YYYY-MM-DD slug>/<YYYY-MM-DD slug>.msg` and links it from the note's `msg_file` key and `## Files` section. Clicking that link in Obsidian opens the `.msg` in Outlook as a copy of the original, with headers and attachments, no matter where the live item went. So when the user asks "can I get back to the original mail": if `msg_file` is set, point at it; if not, offer `/administrator:save` on the note's `entry_id` (or `outlook_search_mails` on the subject if the `entry_id` is stale) and say yes to the export. The `entry_id` in the note is for the plugin (`outlook_get_mail`, `outlook_move_mail`), not for the user.

Meeting notes are the same: `occurrence_key` / `global_id` are for `outlook_get_event_by_key`, not for a link. Nothing is exported for meetings.

## Obsidian Sync, OneDrive, and other sync tools

- Keep the work vault its own vault, separate from a private one. Everything the plugin writes is mail content; a separate vault keeps it out of any sync the user has on their private notes and lets them pick a different sync (or none) for it.
- If the vault is synced (Obsidian Sync, OneDrive, iCloud, Dropbox): sync the `Administrator/` folder, but never `.obsidian/workspace.json` or `.obsidian/workspace-mobile.json` — those change on every click and produce conflicts. In Obsidian Sync that is the default (workspace is excluded unless "Sync … workspace" is on); in OneDrive/Dropbox exclude the file by hand or accept the conflict copies.
- `Attachments/` holds `.msg` files and real attachments. They are the bulk of the vault's size; if sync space matters, exclude that folder from sync (Obsidian Sync: "Excluded folders") — the notes still read fine, only the `msg_file` / `attachments` links go dead on the other device.
- OneDrive "Files On-Demand": a vault whose files are not downloaded locally makes `vault_find` slow (every read pulls the file) and can make Obsidian show stale notes. Mark the vault folder "Always keep on this device".
- Outlook's export tools (`outlook_save_mail_as`, `outlook_save_attachments`) need the vault under `C:\Users\<you>\` — a OneDrive-backed Documents folder (`C:\Users\<you>\OneDrive\Documents\…`) is still under the profile and works. A vault on another drive or a UNC path makes `vault_status.under_user_profile` false; then exports are skipped, as `references/outlook.md` says.
- Never let two machines run the plugin against the same synced vault at the same time: `vault_write` checks for an existing note before creating one, but it cannot see a note the other machine wrote seconds ago and not yet synced; you would get two notes for one mail. Run it on one machine, read on the others.

## Vault names with spaces or odd characters

`obsidian://open?vault=…` takes the vault's display name, not its path. Encode spaces as `%20` and `&` as `%26` (`vault=Acme%20%26%20Co`). If the folder name is not what Obsidian shows in its vault switcher (the user renamed the vault inside Obsidian, or the folder is a junction), set `ADMINISTRATOR_VAULT_NAME` to the name Obsidian shows; `vault_status.vault_name` then returns it and every link uses it. Non-ASCII names (`Arbeit Büro`) are percent-encoded as UTF-8 (`Arbeit%20B%C3%BCro`), which Obsidian decodes.
