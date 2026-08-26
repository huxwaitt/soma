# Changelog

The version here is the one every note carries as `created_by: soma/<version>`.

## 0.4.2

- The three MCP servers ship inside the plugin under `server/` (the `outlook-classic-mcp` fork brought in with its history); `plugin.json` starts them from `${CLAUDE_PLUGIN_ROOT}/server`, so there is no `OUTLOOK_MCP_DIR` any more and nothing to check out separately.
- The `outlook` skill moved into the plugin.
- PDF and Excel reading and the Teams cache reader are standard parts of the server environment; `uv` builds it on first start.
- Licence: Apache 2.0 for the plugin; the Outlook server keeps its MIT notice in `server/LICENSE`.

## 0.4.1

- **Files can be records.** `/soma:save` takes a file path instead of a mail and reads a pdf, Word file, deck, workbook or plain `.txt` / `.md` / `.csv` into `Soma\Documents\<date> <name>.md`, part by part — a section per page, per slide, per heading, per sheet. A file over forty thousand characters keeps its part headings and the first three hundred characters of each, with the whole text in `Attachments\<name>\text.md`. There is no OCR: a scanned pdf says so.
- **Attachments can come in with the mail.** After `/soma:save` exports a mail's attachments it offers to read them in as well; on a yes the mail and each document name each other, so the note says where the file came from and the mail says what was in it.
- **Folders can be watched.** `document_folders` in `Preferences.md` names folders anywhere on the machine or inside the vault. `/soma:collect-information` lists the files that changed there since the last run, reads in the ones whose name matches a page the wiki already keeps, and names the rest for you to decide on. The folders are only ever read.
- **A fact can point at the part it came from.** `src: "<record id>#s7"` for a slide, `#p3` for a page, `#Sheet1!A7` for a row, `#m2` for one mail of a saved thread. However many facts cite it, one document still counts as one source, so a page standing on a single deck says so.
- **One record contract for every kind.** Email, meeting, chat, document, daily and weekly notes now carry the same keys after `type` — `source`, `record_id`, `title`, `date`, `people`, `wiki`, `ingested`, `created_by` — and the same body order. The email note's `## Body` is now `## Content` and its `## Attachments` is `## Files`; a saved thread becomes numbered `### m1`, `### m2` sections. The table is in `skills/soma/references/vault.md`.
- **Thirty-four vault tools became twenty.** `vault_save`, `vault_collect`, `vault_wiki_write`, `vault_wiki_keep`, `vault_time_block`, `vault_row`, `vault_find` and `vault_wiki_search` each took over what several tools used to do; every command, skill and example calls the new names, and the answers are the ones they always were.
- **Machine-written mail is dropped before it is read.** Mailing lists, notices, receipts, meeting responses and out-of-office replies are recognised from the mail's own headers and sender, dropped together with your never-save rules, and counted in one clause ("9 bulk / 1 by your rules dropped") — no preview of any of them is opened.
- **A copy before the first rewrite.** `/soma:setup` reports the zip of `Soma\` that is kept when a wiki written by an older version is about to be read back for the first time.
- **`/soma:load-history` takes "yes to all"**, with a token cap you can name, and stops on the first refusal or when the cap is in sight.
- **Cheaper runs.** Shorter tool descriptions, terser skills, lint counts unless you ask for the lists, and a line before the work starts saying what the run is expected to cost — corrected by what the last runs actually cost.

## 0.4.0

- **The wiki answers from the facts themselves.** A question is matched against the wording of every fact on every page, not just the page names, so "what did we agree on packaging" finds the bullet on a page called something else. Ids, dates, amounts and quoted phrases match exactly; a name spelt wrong still finds the person.
- **Every page has an id, and every write is checked.** A page is read again after it is written and compared with what was meant; one that does not come back as it went in keeps its previous text and says so.
- **Pages edited in Obsidian are read back.** A bullet typed under `## Facts` becomes a fact of yours that no later mail overrides; a reworded fact keeps its id and its old wording goes to History; a deleted one is retired; a renamed or moved page stays the same page.
- **Decision pages.** The moment a record says a choice was made, the page is written with the choice as its first fact, who made it and what would reopen it. It is added to but never rewritten, and stays flagged until you confirm or drop it.
- **A topic with an owner and a due date is a project.** No separate kind: the index simply groups those pages, and topics carry an outcome, milestones, risks and links.
- **Commitments live on the pages.** One `## Open` line is one thing somebody owes somebody, with an owner, a due date and the record it came from. `Soma\Follow-ups.md` is written from those lines after every change and refuses rows of its own.
- **A page can no longer hold two answers.** A new fact that names a different day or amount for the same thing is turned away with the one it clashes with, and goes in only as a replacement (when its record is newer) or as a contradiction for you (when it is older or unclear).
- **`Wiki\Questions.md`.** Your own list of what the wiki should be able to answer. Every `/soma:lint` asks all of them, scores the run, and shows the misses; a question the wiki could not answer at all, asked twice in a month, becomes a review line.
- **`/soma:load-history`.** Reads the months before the collect stamps into the wiki, oldest first, in batches of twenty-five records with one yes each, remembering where it got to and picking up there next time.
- **Migration of an older vault.** `/soma:setup` offers to move a 0.1.0 vault's `People\` folder and the rows of `Follow-ups.md` onto the pages, showing the dry run and keeping a backup first.
