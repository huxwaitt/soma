---
name: collect-information
description: Gathers what happened since the last run — Teams chats from the local client cache (through the `teams_*` tools), new mail in Inbox and Sent, vault notes that changed, and the files that changed in the folders the user watches — keeps only the chats with work content (banter is skipped and named), writes the records (chat records, saved emails), shows the wiki changes it proposes as bullets grouped by page, and applies them only after a yes, oldest record first. Ends with one question about today's [Focus] / [Admin] blocks. Trigger when the user says "/administrator:collect-information", "collect information", "catch the wiki up", "what happened since Friday", "pull in my Teams chats", "update the wiki from my mail", "what did I miss", "bring the wiki up to date", "collect since yesterday". Reads Outlook and Teams only; nothing in either is changed.
---

# collect-information — three sources, one confirmation, then the wiki

Teams, Outlook and the vault's own notes are read in that order; records are written first, then every wiki change is shown and applied only after a yes. The `wiki` skill decides *where* a fact goes; this skill decides *what comes in* and *in which order*. Worked runs (a full one, and one where Teams is not available): `references/examples.md` — load it the first time this runs in a session. Load `skills/wiki/SKILL.md` before step 6.

Once per session: `vault_status` (any folder or file flag false → `vault_init(created_by="administrator/0.4.1")`; vault unset or not a directory → stop and tell the user) and `outlook_whoami(response_format="json")` — `local_time` is "now", `accounts[].smtp_address` are `self_addresses`, `current_user` and `accounts[].display_name` are `self_names`.

## Caps (fixed, say when one is hit)

Teams: 15 chats, 12 messages each at 200 characters; at most 3 chats read in full with `teams_read_chat` (100 messages). Outlook: 50 mails per folder (Inbox, Sent), 80-character previews, at most 8 mails opened and saved. Notes: 20 changed notes at 1200 characters. Documents: the changed files of the watched folders are listed, never opened; at most 5 are read in per run. Wiki: at most 3 pages read per record (for a chat, the reads of step 3 are those). Everything else waits for the next run; the stamps still advance, so say what was left out.

## Steps

### 1. Stamps and the one question

`vault_collect(action="read")` → `{stamps: {teams, outlook, notes}, age_hours, ask, default_since, last_collected}`. When `ask` is true (a stamp is missing or older than 24 h) and the user gave no range, ask exactly this and stop the turn: "Last collected: <last_collected>. Collect since then, or just today?" (`last_collected` is `never` on a first run: "Last collected: never. Since when — a date, or just today?"). "Since then" → `since = default_since`; "just today" → today `00:00`; a date → that date `00:00`. When `ask` is false, `since = default_since` without asking. One `since` for all three sources.

### 2. Teams

Skip when there are no `teams_*` tools; say "Teams: not set up (no local-ms-teams server)" in one line. Otherwise `teams_status()` → skip with its `hint` in one line when `cache_found` or `reader_installed` is false. Then:

```
teams_list_chats(since=<since>, include_messages=true, per_chat=12, max_chars=200, limit=15)
```

→ `{chats: [{id, title, type, members, count, last_time, last_sender, preview, account, messages: [{id, time, sender, sender_org, is_self, text, truncated}], truncated}], total_messages, capped}`. A chat whose `truncated` is above 0 may be read whole with `teams_read_chat(chat_id=<id>, since=<since>, limit=100, max_chars=600)` — at most 3 chats, the busiest first. Meeting chats (`type: meeting`) and channels count like any other chat.

### 3. Which chats matter

For each chat with messages, one `vault_wiki_search(query=<the messages joined, sender names included>, pages=true, people=[], domains=[], limit=5)` → `{pages: [{path, line, score, why}], candidates: [{subject, records, days}]}`. Then, *before* judging the chat, one `vault_wiki_search(query=<the same joined messages>, brief=true, max_chars=1200)` → `{text, pages, facts: [{page, id, text, since}], chars}`: leads, the facts with their `f:<id>` and dates, open items. That is the chat's page context — step 6 does not read again, and those ids are the ids its ops name. Keep a chat when it touches a matched page or candidate, or carries work content on its own (a decision, a date, an amount, an ask, a commitment, a fact about a person's role). Skip banter, jokes, thanks / ok chains and GIF or sticker exchanges (their text is already empty); they stay in Teams, `teams_search` reaches them later, and the report names them in one line: "4 chats skipped: no work content — Lunch?, Friday drinks, …". Choppy messages are read against the page: "moved to the 29th" in a chat with Jane resolves to the deadline fact on the matched topic page and becomes a `supersede` with the message time as `since`; a fragment that cannot be pinned to a page or a candidate is not a fact and stays in the record only.

### 4. Outlook

```
outlook_list_mails(folder="inbox", since=<since>, limit=50, preview_chars=80, response_format="json",
                   fields=["entry_id","internet_message_id","subject","from","from_address","to","received","bulk","bulk_why","preview"])
```

and the same with `folder="sent"`. Then, before one preview is read, one `vault_rules(action="match", items=<the two listings joined>)` → `{results, kept, dropped: [{entry_id, why}], counts: {bulk, never_save, kept}}`: `bulk` is the server saying a machine wrote the mail (a mailing list, a notice, a meeting response, a receipt, an out-of-office reply), the rest went on the user's own never-save rows. Work on `kept` only and report the counts in one clause ("9 bulk / 1 by your rules dropped"). For each kept mail: `vault_wiki_search(query=<subject + preview>, pages=true, people=[<from_address>], domains=[<its domain>], limit=3)`. Keep the mails with a `pages` hit or a `candidates` entry, highest score first, newest first within a score, and open at most 8 of them — after the cost line of step 5b — with the `save` skill's `outlook_get_mail(..., trim_quoted=true, fields=[...])` call. For each: one `vault_save(kind="email", mail, summary, action_items, self_addresses, created_by="administrator/0.4.1")` (an existing note gets an `## Update`, `action: appended`). Mails without a match are counted, not saved; name up to 3 of them the user may want to `/administrator:save` by hand.

### 5. Notes and documents

`vault_collect(action="changed", since=<since>)` → `{count, total, capped, folders, skipped, missing, notes: [{path, type, modified, ingested, excerpt, from_update, truncated}], documents: [{path, kind: "document", modified, size, format}], documents_total, document_folders}`. The default folders are `Administrator/Meetings`, `Emails`, `Daily`, `Weekly` plus `collect_folders` from `Preferences.md`; the tool never reads `Wiki/`, `Attachments/`, `_views/`, `_backup/`. Emails this run just saved are in the list too — ingest each record once; the chat records from step 6 are not listed (`Teams/` is not a default folder) and are ingested from the `vault_save(kind="chat")` results. A note of type `email`, `meeting`, `chat` or `document` is a record for `vault_wiki_write`; a daily, weekly or user-folder note is not: a fact worth keeping from one of those becomes a `vault_wiki_write(pages=[{"path": …, "ops": […]}], src="user")` line in the proposal, and only when the excerpt states it plainly.

`documents` are the files that changed in the `document_folders` of `Preferences.md` (pdf, docx, pptx, xlsx, txt, md, csv). They are listed, never opened: nothing was read, so the gate runs on the **file name** first — one `vault_wiki_search(query=<the file name without its extension>, pages=true, limit=3)` per file. A page hit or a candidate keeps it; nothing matched leaves the file alone and names it in the report, for the user to run `/administrator:save <path>` on by hand. Reading is what saving does, so a kept file goes through `vault_save(kind="document", path=<its path>, summary="", action_items=[], created_by="administrator/0.4.1")` (at most 5 a run, the newest first) and then one `vault_read(<the record path>, section=<the first locator>)` — the **first part** is the second half of the gate: it either shows work content and the record stays, or it does not and the record is named in the report and left un-ingested. From there a document is a record like any other: step 6 drafts its ops from the parts, step 7 ingests it. `action: "unchanged"` means that exact file is already in the vault; say nothing and move on.

### 5b. Expected cost

The three listings are in; nothing has been opened yet — no `outlook_get_mail`, no `teams_read_chat`, no wiki page read. Work the run out first (tokens = chars ÷ 4):

> in ≈ Teams min(total_messages, chats × per_chat) × (max_chars × 0.6 + 40) ÷ 4 + Outlook listed × 60 + opened × 900 + notes count × max_chars ÷ 4 + documents read in × 1200 + records × 3 × 200 (page reads); out ≈ ops × 45 + records × 60 + bullets × 25 + 300

`vault_collect(action="read")` in step 1 carries `tokens: {"collect-information": {runs, ratio_in, ratio_out}}` — the last 20 runs measured against their estimates. When `runs` is 3 or more, multiply `in` by `ratio_in` and `out` by `ratio_out`; below that use the numbers as they are. Show one line, then go on: "Expected ~N in / ~M out for this run". When the host shows the turn's token count, the run ends with `vault_collect(action="tokens", payload={"command": "collect-information", "predicted_in": N, "predicted_out": M, "actual_in": <in>, "actual_out": <out>})` and one line "Cost: N in / M out (expected N'/M')"; when it does not, skip the call and say nothing about it.

### 6. Records first, then the proposal

For every chat kept in step 3: `vault_save(kind="chat", chat=<the chat entry>, messages=<its messages>, self_names=<self_names>, created_by="administrator/0.4.1")` → `{path, action (created / appended / unchanged), date, record_id, added, skipped_duplicates, messages, people: [{name, page}], unknown_people}` (a list, one per day, when the messages span days). `unknown_people` get no page; name them in the report. Then, per record, the `wiki` skill's match and read steps (`people[]` from the chat result are the person pages; a chat reuses the match and the brief of step 3; for the others `vault_wiki_search(query=<title + first 300 chars>, pages=true)` finds the topics and one `vault_wiki_search(query=<title + first 300 chars>, brief=true, max_chars=1200)` gives their leads, facts and ids), and draft the ops. Order the records by time: chat `date` + `last`, email `received`, meeting `start`, then apply the chronology rule below.

Show the proposal as short bullets grouped by page, plus the Review items expected, and wait:

> **Topics/q3-budget** — deadline 27 → 29 Aug (supersede, Teams chat Fri 21); forecast closes 2 Sep (add); Jane sends the sheet by 27 Aug (open item, owner Jane). **Decisions/net-45-terms** — new page: "We go with net 45" (needs your yes). **People/Jane Doe** — confirm "owns the forecast"; last contact Fri 21. **Review** — 2 expected: Tom's older mail says net 30; the new decision. Apply these? (name a line to drop it)

Nothing else happens in that turn. On a yes, drop the struck lines and go on; "no" ends the run with the records written and the stamps untouched.

### 7. Ingest, oldest first

One `vault_wiki_write(record_path=<path>, pages=[...], created_by="administrator/0.4.1")` per record, oldest record first, exactly the ops that were agreed (`src` and `since` default to the record's id and date: `internet_message_id`, `occurrence_key`, or the chat's `record_id`). Refusals are answers (`older-than-current`, `user-pin` → Review; `cap` → resend smaller; `append-only` → the page is a decision, so write a new one or put it on the topic). A topic candidate over the threshold: ask in the report, create only on a yes.

**What somebody owes.** A mail or chat where someone says they will send, check or decide something becomes an `open` op in the same call, on the topic or decision page the record matched, else on that person's page: `{"op": "open", "text": <what, ten words or fewer>, "owner": "[[Wiki/People/<Name>]]" (the plain name when there is no page), "due": <the date the message names, if any>}`. What the user promised is the same op with `owner: "me"`. A message that says one is finished becomes `{"op": "done", "id": <the id from the page's open items>}`. These lines are what `Administrator/Follow-ups.md` shows; never write a row into it.

**A second pass over every record.** After a record's ingest, with the record still in front of you, answer one question: which facts in it are not on the pages yet? Read the ops that went through (and the refused ones) against the record and list what is missing — a date, a name, a number, a promise. A non-empty list is a second, smaller `vault_wiki_write` with the same `record_path`, sent right after the first and without asking again (the proposal already covered this record). Never ask yourself whether the first ingest was good; only what it left out. Nothing missing → say nothing about the pass.

**A decision in the words.** "we agreed", "we are going with", "approved", "beschlossen" → a decision page in the same call, without asking: `{"new": {"type": "decision", "title": …, "lead": …, "summary": …}, "ops": [{"op": "add", "text": "<the choice>"}, …]}` with `decided` and `by` (see the `wiki` skill). Code flags it `unconfirmed-decision` and writes one Review line; say in the report that it needs a yes or a drop.

### 8. Advance the stamps

`vault_collect(action="advance", source=<teams | outlook | notes>, at=<the local ISO time that source was read>)` for every source that was actually read — a skipped Teams keeps its old stamp. `refused: [{reason: "older-than-stamp"}]` means the stamp was already newer; say so and move on.

### 9. Today's blocks

`outlook_list_events(start="<today>T00:00:00", end="<today>T23:59:59", include_recurrences=true, limit=50, fields=["subject","start","end","occurrence_key"], response_format="json")`; keep the subjects starting with `[Focus]` or `[Admin]`. Skip the question when there are none, when `vault_find("time-block", {"week": "<ISO week>"}, fields=[])` is not found, or when `vault_read` of that note shows every `occurrence_key` already in a `## Held` row. Otherwise one question, nothing else: "Today's blocks: 09:00–10:30 [Focus] ACME contract, 14:00–14:45 [Admin] Email and small tasks — held, moved or skipped? (a word each, a note is welcome)". Per answer:

```
vault_row(action="append", path="Administrator/Time-blocks/<week>.md", section="Held",
                 row=["<Tue 25 Aug>", "<subject> <HH:MM–HH:MM>", "<held | moved | skipped>", "<note or empty>"],
                 dedupe_key=<occurrence_key>, key_label="occurrence_key", header=["Day","Block","Result","Note"])
```

`appended: false, reason: duplicate` = already answered, say nothing. Unanswered blocks stay unanswered; `/administrator:weekly` counts them.

### 10. Report

Seven lines at most: Teams (chats, messages, records created / appended, unknown people, then "N chats skipped: no work content — <titles>"), Outlook (mails seen, "N bulk / M by your rules dropped", saved, the 3 worth saving by hand), Notes (changed, ingested), Documents ("N files changed in your watched folders, 2 read in (12 slides, 4 pages), 3 left — <names>"), pages changed with one `obsidian://open` link each, Review count when it grew, and "Last collected: <now as Thu 21 Aug 18:10>". Then the cost line of step 5b when the host shows the turn's token count.

## Chronology

A later item wins: when a record newer than the fact's `since` changes a claim, `supersede`. An older record that disagrees goes to Review: send `contest`, or let `supersede` be refused with `older-than-current` — both land there. Same time, same day, or unclear which is newer → `contest`. Records are ingested oldest first so the pages end in the state of the newest source, and every earlier state sits in History.

## Rules

- Nothing in Outlook or Teams is changed: no mark, move, category, reply, or event. The vault is written only through `vault_*` tools; wiki pages only through `vault_wiki_*`.
- No `vault_wiki_write` before the proposal was shown and answered. No new page and no `vault_wiki_keep(action="merge")` without a yes.
- The stamp question, the proposal, and the blocks question are three separate turns; never fold one into another.
- A watched folder is only ever read: no file in it is moved, renamed or written, and a file the reader does not know (an image, a zip) is not listed at all.
- Chats hold no addresses: a sender with no person page stays in `unknown_people`; never create a person page from a chat. A chat skipped in step 3 gets no record and no ingest; it is only named.
- `fields=[...]` and the caps above on every read; `since` is the same local ISO string for every source.
