---
description: Save one email (or a thread) from Outlook as a note in the vault, with a person note for the sender and optional .msg and attachment exports, or read a file (pdf, docx, pptx, xlsx, txt, md, csv) into a document record and put its facts on the wiki pages.
argument-hint: "<entry_id | search terms | file path>"
---

# /administrator:save

Argument (required): an exact Outlook `entry_id`, free-text search terms (subject words, sender name), or the path of a file to read in (absolute, or relative to the vault). Add "the thread" / "whole conversation" to save every mail of the thread into one note; add "without wiki" to skip the wiki ingest at the end.

Argument given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `save` skill and its `skills/save/references/examples.md`. Load the `outlook` skill if it is not already loaded.
2. Once per session: `vault_status` (if `administrator_dir_exists` or any folder or file flag is false, `vault_init(created_by="administrator/0.4.1")` and mention `/administrator:setup`) and `outlook_whoami(response_format="json")` for the user's own addresses.
3. **A file path was given** (it has a drive letter or a slash and an extension the reader knows): skip to step 11 — no Outlook call is made. Otherwise find the mail:
   - `entry_id` given (long hex string, no spaces) → use it.
   - Otherwise `outlook_search_mails(query=<terms>, folder="inbox", limit=5, fields=["entry_id","from","subject","received","preview"], preview_chars=80, response_format="json")` (`scope="from"` for a sender name; then `folder="sent"`). One hit → take it and say so; more → show date, sender, subject, preview and ask the user to pick.
4. `outlook_get_mail(entry_id, trim_quoted=true, response_format="json", fields=["entry_id","internet_message_id","conversation_id","subject","from","from_address","to","cc","recipients","received","attachments","body_trimmed","body_truncated"])`. For a thread also `outlook_get_conversation(entry_id, include_body=true, trim_quoted=true, max_body_chars=0, limit=20, preview_chars=0, fields=["entry_id","from","received","folder","body_trimmed"])`, and pass its `items[]` to step 7 as `thread=` — the helper writes one `### m<n> — <date> <from>` section per mail itself.
5. `vault_find("email", {"internet_message_id": …, "entry_id": …}, fields=["status","msg_file","attachments"])` — found means the helper will append an update, and exports are only offered when the user asked for them now and they are not yet linked. `vault_find("person", {"email": <from_address>}, fields=["name"])`; not found → one `outlook_search_contacts(query=<from_address>, include_directory=true, limit=5)` for `company` (only when an item's `email` equals the sender's address).
6. If the mail has attachments or the user asked to keep the original, ask first (one question, nothing else in that turn) whether to export. On a yes: `outlook_save_mail_as(entry_id, output_dir="<vault>\Administrator\Attachments\<YYYY-MM-DD slug>", fmt="msg", filename="<YYYY-MM-DD slug>")` and `outlook_save_attachments(entry_id, output_dir=<same>)`. Both only accept paths under the user profile; if `vault_status.under_user_profile` is false, say so and skip.
7. Write a summary (at most 2 sentences) and the action items from `body_trimmed`, then one call: `vault_save(kind="email", mail=<step 4 JSON>, summary, action_items, attachments_saved=[<paths>], msg_file=<path>, thread=<the conversation items[], for a thread>, self_addresses=<whoami addresses>, company=<step 5>, created_by="administrator/0.4.1")`. It writes the email note (`Administrator/Emails/YYYY-MM-DD <slug>.md`, or an `## Update` on an existing one), the sender's person page and, for `waiting`, one open item owned by the counterpart on their page (`Follow-ups.md` is written from those items). No `vault_write`, `vault_row` or hand-written frontmatter.
8. Wiki ingest, unless the argument or the user said "save without wiki": load the `wiki` skill, `vault_wiki_search(query=<subject + first 300 chars>, pages=true, people=[<from_address>], domains=[<sender domain>])`, `vault_wiki_read(path, sections=["lead","facts"])` on at most 3 hits, one `vault_wiki_write(record_path=<step 7 path>, pages=[...], created_by="administrator/0.4.1")` with ops only for what the mail adds, changes or confirms (`skills/wiki/SKILL.md`). The sender's person page gets a `lead` when it is still `draft`. Nothing matched → `pages=[]`. A topic candidate over the threshold → propose, create only on a yes. A mail over 1500 characters gets the `wiki` skill's ingest step 5 as well: read it once more for facts the ops left off the pages, and send those as a second, smaller ingest in the same turn.
8b. **The attachments too?** When step 6 exported files the reader knows (pdf, docx, pptx, xlsx, txt, md, csv), ask once, nothing else in that turn: "Read `<file>` into the vault too, so its text can go on the pages?" On a yes, one `vault_save(kind="document", path=<the exported file>, summary, action_items, from_email=<the step 7 path>, created_by="administrator/0.4.1")` per file, then step 11's wiki run for each. The report names both records.
9. Report the note path and `action`, status and action-item count, the person note (`person_action`), any files saved, the document records written, one `Wiki:` line (pages and changes, Review items, or "skipped"), ending with `obsidian://open?vault=<vault_name>&file=<url-encoded path>` (`vault_name` from `vault_status`, `path` from `vault_save`). Do not change the mail in Outlook (no mark, move, or category) unless the user asks and says yes.
10. If the host shows the token count of this turn, add it as the last line of the report; otherwise say nothing about it. (`save` does not write a daily note, so there is no `vault_write_daily(tokens_used=…)` call here.)
11. **A file.** One call: `vault_save(kind="document", path=<the argument>, summary=<empty unless the user described the file>, action_items=[], created_by="administrator/0.4.1")` → `{path, action, record_id, format, parts, chars, empty, text_file, sections: [{locator, heading, chars}], from_email, linked}`. A format the reader does not know, or a missing file, comes back as a refusal naming it — say so and stop; `empty: true` is a pdf with no text layer (no OCR), so say "no text could be read (scanned?)" and stop. Name the parts in one line, then, unless the user said "without wiki": `vault_wiki_search(query=<title + the part headings>, pages=true, limit=8)`, `vault_read(<the record path>, section=<locator>)` on **at most 5** matched parts, largest matched first, and one `vault_wiki_write(record_path=<the record path>, pages=[...], created_by="administrator/0.4.1")` whose ops cite `src: "<record_id>#<locator>"` (`#p3` a page, `#s7` a slide, `#Sheet1!A7` a row). Report as in step 9, with the record path, the format, the part count and the pages changed.

## Example

```
/administrator:save supplier contract jane
/administrator:save 00000000AC1F2B3C…
/administrator:save the thread with Jane about the supplier contract
/administrator:save C:\Users\<you>\Downloads\ACME-kickoff.pptx
```

> Saved `Emails/2026-08-21 Q3 supplier contract – signature needed.md` (todo, 2 action items). New person note `Wiki/People/Jane Doe.md`. Exported the .msg and `Q3-supplier-contract-v3.pdf` to `Administrator/Attachments/2026-08-21 Q3 supplier contract – signature needed/`, and read the pdf into `Documents/2026-08-21 Q3-supplier-contract-v3.md` (12 pages); the two records link to each other. Wiki: `Topics/acme-supplier-contract` (net 30 → net 45 superseded from page 3, 1 open item), `People/Jane Doe` (lead written).
> obsidian://open?vault=Vault&file=Administrator%2FEmails%2F2026-08-21%20Q3%20supplier%20contract%20%E2%80%93%20signature%20needed.md

With a file path:

> Read `Downloads/ACME-kickoff.pptx` into `Documents/2026-08-24 ACME-kickoff.md` (pptx, 18 slides, 9140 characters). Wiki: `Topics/acme-supplier-contract` (net 45 from 1 Sep added from slide 7, scope confirmed from slide 2). Topic candidate `acme kickoff` — create a page for it?
> obsidian://open?vault=Vault&file=Administrator%2FDocuments%2F2026-08-24%20ACME-kickoff.md

The full worked examples (one mail, a re-run, a thread, a file) are in `skills/save/references/examples.md`.
