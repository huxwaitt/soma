---
name: save
description: Turn one Outlook email (or the thread it belongs to), or a file on disk, into a note in the Obsidian vault — frontmatter with stable IDs, the trimmed body without quoted history or signature, recipients, a wikilink to the sender's person note, a short summary, and extracted action items; optionally export the .msg and attachments into the vault. Trigger when the user says "/soma:save", "save this email", "note this", "put that email in the vault", "keep a record of the thread with X", "file this mail", "save the attachment from Bob's email to my notes", or gives an entry_id, search terms or a file path after asking to save ("save this deck", "read that pdf into the vault"). Reads Outlook only; the only Outlook calls that touch disk are outlook_save_mail_as and outlook_save_attachments, both optional and both write into the vault's Attachments folder.
---

# save — one email or one file → one vault note

One mail (or the mail plus its thread) goes from Outlook into `<vault>/Soma/Emails/`; a file goes into `<vault>/Soma/Documents/` (step 8). Outlook gives the facts, `vault_save(kind="email")` writes the note, the person page and, for a `waiting` mail, one open item owned by the counterpart; you decide only the summary, the action items and the status. Never send, move, delete, mark or categorise anything in Outlook. Outlook mechanics follow the `outlook` skill and `skills/soma/references/outlook.md`; note layout is `skills/soma/references/vault.md`; worked examples (single mail, thread, re-run) are in `references/examples.md` — load it the first time a save runs in a session.

Once per session: `vault_status` (any folder or file flag false → `vault_init(created_by="soma/0.4.1")`; vault unset or not a directory → stop and tell the user, do not guess a path) and `outlook_whoami(response_format="json")` for `self_addresses` (every `accounts[].smtp_address`).

## Steps

### 1. Resolve the target

- **A file path was given** (`C:\…\deck.pptx`, or a path under the vault): no Outlook call at all — go to step 8.
- **An `entry_id` was given** (long opaque string, usually starts with `000000`): go to step 2 with it.
- **Search terms were given**: `outlook_search_mails(query=<terms>, folder="inbox", limit=5, fields=["entry_id","from","subject","received","preview"], preview_chars=80, response_format="json")`. A sender name rather than a subject → `scope="from"`. Nothing in Inbox → `folder="sent"`, then ask the user for a folder.
  - One hit: proceed, but say which mail you picked.
  - Two to five hits: numbered list (`received`, `from`, `subject`, `preview`), ask the user to pick a number. Do not guess.
  - Five hits and the user wanted something else: offer to narrow by `since` or `scope`.

### 2. Read the mail

```
outlook_get_mail(entry_id=<id>, trim_quoted=true, response_format="json",
  fields=["entry_id","internet_message_id","conversation_id","subject","from","from_address",
          "to","cc","recipients","received","attachments","body_trimmed","body_truncated"])
```

`body_truncated: true` → call again with `max_body_chars=0`. Never ask for `include_html`; never read `body` when `body_trimmed` is there. Keep the whole result as `mail` — it goes into `vault_save` unchanged.

**Whole thread requested** ("save the thread", "the whole conversation"): also call `outlook_get_conversation(entry_id=<id>, include_body=true, trim_quoted=true, max_body_chars=0, limit=20, preview_chars=0, fields=["entry_id","from","received","folder","body_trimmed"])`. Items come oldest first across folders. `truncated: true` → tell the user only the oldest 20 were saved. The note is still one note whose record is the **newest** mail (step 2's `mail`; re-run `get_mail` on the newest item's `entry_id` if it is not the one you fetched). Pass the whole `items[]` list to `vault_save` as `thread=`, unchanged: the helper sorts it oldest first and writes one `### m<n> — <date> <from>` section per mail, each holding that item's `body_trimmed` verbatim. Do not retype, summarise or tidy it, and do not build the sections by hand. A fact taken from the second mail then cites `src: "<record_id>#m2"`.

### 3. Duplicate and person lookups (frontmatter only)

- `vault_find("email", {"internet_message_id": mail.internet_message_id, "entry_id": mail.entry_id}, fields=["status","msg_file","attachments"])`. `found: true` → the note exists; skip step 4 unless the user clearly asked for the .msg or attachments this time and they are not in the returned frontmatter. `vault_save` will append an `## Update` section, not a second note; say "already saved" in the report.
- `vault_find("person", {"email": mail.from_address}, fields=["name"])`. `found: false` and the sender is not self → `outlook_search_contacts(query=<from_address>, include_directory=true, limit=5)` once; `company` only from an item whose `email` equals the sender's SMTP, never from the domain.

### 4. Optional exports (ask first, once, before the note is written)

`vault_save` puts `msg_file` / `attachments` into the frontmatter only when they are passed at write time, so ask before writing. When `mail.attachments` is non-empty or the user mentioned keeping the original, ask in one short message ending in a question and nothing else in that turn: "Export the original .msg and N attachment(s) to Soma/Attachments/<YYYY-MM-DD slug>/?" Only on a clear yes; no, silence or a change of topic → step 5 without exports (a later "yes, export it" runs as a re-save and lands in an `## Update`). Destination: `<vault>\Soma\Attachments\<YYYY-MM-DD slug>\` — `received` date plus the subject with `Re:`/`FW:`/`AW:`/`WG:`/`TR:`/`SV:` stripped, `\ / : * ? " < > |` → `_`, 60 characters (the slug rule in `vault.md`; check the `path` step 5 returns and say so if it differs).

- `outlook_save_mail_as(entry_id, output_dir="<vault>\\Soma\\Attachments\\<YYYY-MM-DD slug>", fmt="msg", filename="<YYYY-MM-DD slug>")` — never overwrites (adds ` (1)`); keep the returned `path`.
- `outlook_save_attachments(entry_id, output_dir=<same folder>)`, or with `attachment_index` (1-based) per file. Skip inline images under 20 KB unless asked; they are listed as "(not exported)" by the helper.
- `vault_status.under_user_profile` false → the tools refuse; say so, mention `OUTLOOK_MCP_ALLOW_ANY_PATH=1` from the outlook skill, and skip the export. Leave files where the tools put them.
- **Files that were exported can be read in.** After the note is written (step 5), ask once more, nothing else in that turn: "Read `<file>` into the vault too, so its text can go on the pages?" On a yes, one `vault_save(kind="document", path=<the exported file>, summary, action_items, from_email=<the step 5 path>, created_by="soma/0.4.1")` per file, then step 8's wiki run for each. The two records name each other; `linked: true` says it happened. Inline images and files the reader does not know (`.png`, `.zip`, …) are not offered.

### 5. Decide, then write

You supply, from `body_trimmed` only:

- **summary** — at most 2 sentences, 40 words or fewer: what the mail is and what it wants.
- **action_items** — only asks directed at the user, or that the user (as sender) gave someone else, in the mail's own wording shortened to one line, a date only when the mail states one, `— owner: me | <name>`. Nothing invented from context. Empty list when there are none.
- **status** — leave it to the helper (`todo` with action items, `fyi` without, `waiting` when the mail is from self and has action items) unless the user said otherwise or the mail is clearly `waiting` (they promise to come back to you) or `done`.

```
vault_save(kind="email", mail=<step 2 result>, summary, action_items, attachments_saved=[<file paths>],
                 msg_file=<.msg path>, status=<only when you override>, self_addresses=<whoami>,
                 thread=<the conversation items[], only for a thread>,
                 company=<step 3, only when found>, created_by="soma/0.4.1")
```

The helper copies the body, builds the frontmatter (identity, recipients, `has_attachments`, links), names the file, writes or appends the email note, creates or updates the sender's person page in the wiki (`last_contact`, `aliases`, one `## Records` line) and, when the status is `waiting`, adds one open item to the counterpart's page (the first recipient of the user's own mail, else the sender) owned by them, with the mail as its record. Result: `{path, action: created | appended, status, person_path, person_action, followup_added}` — `followup_added` is true when that item was written. It shows up in `Soma/Follow-ups.md`, which is written from the pages. A tool error (bad status, missing identity) is yours to fix: correct the input and call again; never write the file by hand.

### 6. Wiki ingest (after the record is written)

Skip when the user said "save without wiki" (say so in one line) or when `action` was `appended` and the note already had a `wiki:` key (add `"wiki"` to the `fields` of the step 3 `vault_find`). Otherwise load `skills/wiki/SKILL.md` (and `skills/wiki/references/examples.md` the first time this session) and run its ingest steps: `vault_wiki_search(query=<subject + first 300 chars of body_trimmed>, pages=true, people=[mail.from_address], domains=[<sender domain>])`, `vault_wiki_read(path, sections=["lead","facts"])` on at most 3 hits, then one `vault_wiki_write(record_path=<step 5 path>, pages=[...], created_by="soma/0.4.1")`. The sender's person page is always one of the pages (`vault_save` created it as `draft` when new): give it a `lead` when it has none, and `confirm` / `add` the role facts the mail states. No page matched and no candidate over the threshold → `vault_wiki_write` with `pages=[]` so the record is marked seen, nothing else. A candidate over the threshold → propose the topic page in the report; create it only on a yes.

**A long mail gets a second pass.** Over 1500 characters in `body_trimmed`: before the report, run the `wiki` skill's ingest step 5 — read the mail once more against the ops you sent and ask which of its facts are not on the pages yet. A non-empty list is a second, smaller `vault_wiki_write` in the same turn, with the same `record_path`. A shorter mail does not need it.

### 7. Report

Two or three lines: note path and `action`, status and number of action items, person note (`person_action`), what was exported, the document record when one was written (its path, format, parts and characters — both records are named), one `Wiki:` line with the pages touched and what changed (superseded / added / confirmed / sent to Review) or "skipped". End with `obsidian://open?vault=<vault_name>&file=<url-encoded path>` (`vault_name` from `vault_status`, `path` from the result). Ask nothing further. If the host shows the turn's token count, add it as a last line; otherwise say nothing about it.

### 8. A file instead of a mail

One call reads the file and writes the record; nothing is typed by hand:

```
vault_save(kind="document", path=<the path as the user gave it>, summary=<empty on the first call>,
                 action_items=[], from_email=<the mail record, only for an exported attachment>,
                 created_by="soma/0.4.1")
```

Formats: `.pdf` (needs the server's `search` extra; the refusal names it), `.docx`, `.pptx`, `.xlsx`, `.txt`, `.md`, `.csv`. Anything else, or a path that does not exist, is refused by name — say so and stop. The answer is `{path, action, record_id, format, parts, chars, empty, text_file, sections: [{locator, heading, chars}], from_email, linked}`; `action: "unchanged"` means that exact file is already a record (say which), and a second read of a changed file appends an `## Update` with the parts as they are now. `empty: true` is a pdf with no text layer — say "no text could be read (scanned?)" and stop; there is no OCR.

- **Show the parts.** Name the sections in one line ("18 slides: 1 ACME kickoff, 2 Scope, … 7 Pricing"), so the user sees what came in without the text being repeated.
- **Then the wiki step**, unless the user said "save without wiki": `vault_wiki_search(query=<title + the headings of the parts>, pages=true, limit=8)`, then read **at most 5** of the parts the match points at, largest matched first, one call each: `vault_read(<the record path>, section="s7")` → `{section: {locator, heading, text, chars}, …}`. Never read the whole record back.
- **Cite the part.** Every op from a part carries `src: "<record_id>#<locator>"` (`#p3` a page, `#s7` a slide, `#Sheet1!A7` a row); a fact from no single part uses the bare record id. However many facts cite it, the document is one source. Then `vault_wiki_write(record_path=<the record path>, pages=[...], created_by="soma/0.4.1")` as in step 6, second pass included when the record is over 1500 characters.
- A summary is worth having once the parts are known: a second `vault_save(kind="document", path=<same>, summary=<one line>)` is refused as `unchanged`, so write the summary into the first call when the user described the file, and otherwise leave it empty rather than guessing.

## Rules that apply to every run

- Running the same command twice leaves one email note and one person note; the second run only appends `## Update`.
- Every note goes through `vault_save` (or `vault_write` for anything it does not cover); never write or edit a vault file with the host's file tools. The server never edits existing text; it appends.
- Never write outside `<vault>/Soma/` (the server refuses any other path anyway). A document record only ever reads the file it was given; the file itself is never moved or changed.
- Never call `outlook_send_mail`, `reply_mail`, `forward_mail`, `move_mail`, `delete_mail`, `mark_mail`, `set_category`, or any `bulk_*` tool from this skill. Saving a mail does not mark it read.
- Keep datetimes exactly as Outlook returned them (local time with offset). Do not convert.
- Never put the full `html_body`, raw headers or the untrimmed `body` into the vault. Never re-type the body, the recipients or the identity fields — they travel inside `mail`.
- `fields=` on every Outlook read; `preview_chars=0` on the conversation. Do not read the vault through `vault_read` for this workflow; `vault_find(fields=...)` answers what you need, and wiki pages are read only through `vault_wiki_search` and `vault_wiki_read`.
- Wiki pages are written only by `vault_wiki_write`; an op the server refuses (`older-than-current`, `user-pin`, `cap`) is an answer, not an error — report it as the `wiki` skill says.
