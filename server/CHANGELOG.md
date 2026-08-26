# Changelog

Two servers ship from this checkout: `outlook-mcp`, which reads classic Outlook, and `soma-vault`, which writes the Obsidian notes. The version here is the one the vault stamps on every note it writes as `created_by: soma/<version>`.

## 0.4.1

- **`documents.py`.** One reader for pdf (through `pypdf`, which the `search` extra installs — without it the call is refused by name), docx, pptx, xlsx, txt, md and csv. Every format answers the same shape: a list of parts, each with a label the model can cite (`p3`, `s7`, `Sheet1`), the heading that names it and its text. Word, PowerPoint and Excel files are read with the standard library alone. A broken file, an unreadable page or a missing reader is a refusal, never a crash.
- **`vault_save(kind="document")`.** Writes `Soma/Documents/<date> <name>.md` with the parts under `## Content`. The same file again (same hash) is left alone; the same path with new text gets an `## Update` holding the parts as they are now. Over forty thousand characters the whole text goes to `Attachments/<name>/text.md` and the record keeps each part's heading plus its first three hundred characters. With `from_email` the mail record and the document name each other.
- **`vault_read(path, section=…)`.** Returns one part of a record — a locator, a heading or the whole heading line — so a forty-slide deck is read slide by slide instead of whole.
- **One record contract, in one place.** `notes.with_core_keys` fills `source`, `record_id`, `title`, `date`, `people`, `wiki` and `ingested` after `type` from the kind's own keys, and `store.write` calls it, so every writer gets them: emails, meetings, chats, documents, daily and weekly notes. An append changes a key, never blanks one.
- **Locators in fact sources.** A source may name the part it came from (`<record_id>#p3`). The string is stored whole, and everything that compares or counts sources reads the record alone, so one document cited from three pages is one source.
- **The email record reads like the others.** `## Body` became `## Content`, `## Attachments` became `## Files`, and a thread becomes one `### m<n> — <date> <from>` section per mail, from the new `thread` parameter.
- **`vault_collect(action="changed")` also watches folders.** The files that changed in the `document_folders` of `Preferences.md` come back under `documents`, listed and never opened.
- **Thirty-four vault tools became twenty.** `vault_save`, `vault_collect`, `vault_wiki_write`, `vault_wiki_keep`, `vault_time_block`, `vault_row`, `vault_find` and `vault_wiki_search` absorbed the rest; the answers keep their shapes and every old tool name is gone.
- **Machine-written mail is flagged in code.** Every listed mail carries `bulk` and `bulk_why`, worked out from its transport headers, its sender and its message class; `vault_rules(action="match")` answers `kept`, `dropped` and `counts` so no preview of a dropped mail is ever read.
- **Safety rails.** `vault_init` zips an existing `Soma/` before the first call that rewrites a wiki written by an older version; the read tools only report hand edits and the next writing call adopts them; the Teams reader is pinned to a known commit.

## 0.4.0

- **Classic Outlook over COM.** Mail, calendar, contacts, tasks, folders, categories and rules — 46 tools, `fields=` and `preview_chars=` on every read so nothing comes back that was not asked for.
- **Threads and identity.** `internet_message_id` on every listed mail, `outlook_get_conversation` for the whole thread, `trim_quoted` to stop before the quoted history and drop the signature.
- **Calendar identity and booking.** `global_id` and `occurrence_key` per occurrence, free/busy, meeting-time search, and updates that reach every attendee.
- **Finding things.** Attachment and indexed search, one `outlook_find` that searches Inbox and Sent and ranks, and text out of pdf and Excel attachments behind the `search` extra.
- **Drafts only.** Replies and mails are written with `save_only=true` and land in Drafts; nothing is ever sent, forwarded or deleted by a tool.
- **`soma-vault`.** A second server that writes the Obsidian notes, picks the filenames, checks the required keys and refuses a second note for an identity that already exists.
- **The wiki.** Pages of six kinds, dated fact operations with supersession, an index, a log and a review queue, a lint checklist, page merges and the migration of an older vault.
- **Commitments and decisions.** Open items with an owner and a due date on the pages themselves, `Follow-ups.md` written from them, decision pages that are added to but never rewritten, and topics that carry an owner, a due date, an outcome, milestones and risks.
- **The search engine.** Facts ranked by what they say, page ids, writes verified after writing with a restore, an index that checks itself, and hand edits adopted from Obsidian.
- **`local-ms-teams`.** A read-only reader of the local Teams cache, plus chat records, the "last collected" stamps, changed notes, the time-block planner and `Priorities.md`.
