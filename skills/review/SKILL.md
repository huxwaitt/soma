---
name: review
description: Two look-back workflows over Outlook and the vault. `followups` asks `outlook_awaiting_reply` for the threads where the user wrote last and nobody answered for N days, opens an item on the person page of whoever owes an answer and ticks the ones that got a reply (`Soma/Follow-ups.md` is written from those items), and offers short nudge drafts that go to Drafts only. `weekly` takes `vault_weekly_facts` plus next week's calendar and writes one note `Soma/Weekly/YYYY-Www.md` with what is still open from the week's inbox, what the user is waiting on and for how long, meetings held with their unchecked action items, next week's calendar with clashes, people who have gone quiet for 30+ days, and where the week's hours went against the user's priorities (`vault_time_block(action="audit")` over the week's events and the `[Focus]` / `[Admin]` blocks). Trigger when the user says "/soma:followups", "/soma:weekly", "who hasn't replied", "who owes me an answer", "what am I waiting on", "anything I chased and heard nothing", "weekly review", "wrap up the week", "what did I not get to this week", "what's next week look like", "who have I not talked to in a while". Reads Outlook only; the single Outlook write is a nudge draft with `save_only=true`, one yes per draft, never a send.
---

# review — followups and weekly
Both workflows look back instead of at the inbox of the moment. The tools do the collecting, comparing and counting; you decide and write the few lines only a person can write. Outlook is read through `outlook_*` tools, the vault is read and written only through `vault_*` tools (`skills/soma/references/vault.md`), and nothing in Outlook changes except, in `followups`, a draft the user said yes to. Outlook mechanics follow the `outlook` skill and `skills/soma/references/outlook.md`. Worked examples with real call sequences: `references/examples.md` (load it the first time a workflow runs in a session).

Before either workflow: `vault_status` once per session (run `vault_init(created_by="soma/0.4.1")` if a folder or file flag is false) and `outlook_whoami(response_format="json")` once per session. "Self" = any `accounts[].smtp_address`, compared case-insensitively. "Today" and "now" come from `whoami.local_time`, never from a guess.

Cost rules for both: pass `fields=[...]` on every list, search, get and conversation call and `preview_chars=0` unless a preview is needed; never repeat text a tool result already holds (paste `last_line`, `subject`, `who` as they came); never read a note with `vault_read` when a helper already returned the facts.

## followups — who has not replied

`/soma:followups [days]`. `days` = how long a thread must have been quiet to count, default 3.

### 1. One call

`outlook_awaiting_reply(days=<N>, since_days=30, limit=50)` → `items[]` longest wait first, each `conversation_id, entry_id, internet_message_id, subject, to[] (SMTP), to_names[], last_sent, days_waiting, last_line`; top-level `sent_scanned, threads_checked, capped`. The server already skipped calendar responses, auto-replies, read receipts and mails to oneself, and cut `last_line` to the last real sentence the user wrote. `capped: true` → say "older sent mail not checked; run again with a smaller `since_days` later".

### 2. Show the table

```
| # | Who | Subject | Days | Last line I wrote |
| --- | --- | --- | --- | --- |
| 1 | Tom Lee <tom.lee@acme-parts.com> | Delivery schedule September | 6 | Can you confirm 8 Sep works for the first delivery? |
```

`Who` = `to_names[0] <to[0]>`; `to[]` empty → the name and "(address unknown)". Subject = `subject` with reply/forward prefixes stripped. No items → "Nothing waiting longer than N days across M threads" and go on to step 3 (open items may need closing).

### 3. The open items on the pages

`vault_wiki_search(query="", open_items=true, owner="others")` — one call, no `vault_read`: `[{page, stem, type, title, owner_name, id, text, owner, due, since, src, record, done}]`, oldest `since` first. These are the lines `Soma/Follow-ups.md` is written from; the file itself takes no rows (`vault_row` refuses it). Load `skills/wiki/SKILL.md` before the first write here.

**Open.** Per item: key = `internet_message_id`, `entry_id` when empty. Skip the thread as "already listed" when an open item's `src` holds that key, or an item on that person's page has the same text. Otherwise `vault_find("person", <to[0]>, fields=["name"])` → the person page; not found → `vault_write("person", {type: person, name: <to_names[0], else the local part of the address>, email: <to[0]>, last_contact: "", aliases: [], created_by: "soma/0.4.1"}, "", mode="create")` writes the draft page first. Then

```
vault_wiki_write(pages=[{"path": "Wiki/People/<name>", "ops": [{"op": "open", "text": <subject, ten words or fewer>,
    "owner": "[[Wiki/People/<name>]]", "since": <last_sent date>, "src": <key>}]}], src=<key>)
```

→ `{record: null, candidate: null, pages: [{path, written, applied: [{op, id, owner}], refused: [...]}]}`. `refused` with `duplicate` → that record already opened an item on the page; leave it and say so.

**Close.** For each open item whose `src` matched no item of this run:

- `src` an `entry_id` (items from `inbox`, `save`, `prep`): `outlook_get_conversation(entry_id=<src>, include_body=false, limit=50, fields=["entry_id","from_address","received"])`. Last item from someone who is not self → `vault_wiki_write(pages=[{"path": <the item's page>, "ops": [{"op": "done", "id": <the item's id>, "src": "user"}]}])`. Last item from self, or a tool error (mail moved or deleted) → leave it. At most 10 such calls per run; say when items were left unchecked.
- `src` an `internet_message_id` (items this workflow wrote): the user's mail was in the scan when `capped` is false and `since` is within the last 30 days; not being an item means the wait is over (a reply, or a newer mail from the user that now has its own item). Send the same `done` op and report "no longer waiting". `capped: true` or an older `since` → leave it.
- Items whose `src` is `user`, a `proposal:` key or an `occurrence_key` stay, and so does anything with `owner: me`. Never guess.

Never tick a box by hand and never write a row into `Follow-ups.md`; the file is written again from the pages after every wiki change.

### 4. Nudge drafts

Only for waiting items (new ones and "already listed" ones). Voice: `outlook_voice_sample(address=<to[0]>, n=10, max_chars=300)` once per distinct recipient, at most 5 calls per run; `used_address: false` means the sample is the user's sent mail overall — build that general profile once and reuse it for every later draft this session. Read the six facts from `items[].opening` / `closing` and `stats` as `skills/draft/references/voice.md` says ("nudge" variant); hard rules in `Preferences.md` `## Voice` win.

Body, 2–3 sentences in the language of `last_line`: the original subject and `last_sent` date, the ask in one sentence built from `last_line`, one closing question. No apology, no "just checking in", nothing the original mail did not ask. `[fill in: …]` for anything missing. Show one draft at a time:

```
Draft 1 of 2 → Tom Lee <tom.lee@acme-parts.com>
Subject: Re: Delivery schedule September
Body:
<text>

Save this to Drafts? (yes / no / skip all)
```

Only on a clear yes: `outlook_reply_mail(entry_id=<item entry_id, the user's own last mail>, body=<text>, reply_all=false, html=false, save_only=true)` → the draft lands in Drafts inside the thread, addressed to the original recipients; tell the user to check the To line before sending from Outlook. `to[]` empty → show the draft, say it cannot be saved without an address, move on. "no" skips one, "skip all" stops. Never `outlook_reply_mail` or `outlook_send_mail` without `save_only=true`, never `outlook_forward_mail`. When the item's `record` links an email note: `vault_write("email", <frontmatter from a `vault_find`>, "Nudge draft saved to Drafts via /soma:followups.", mode="append")`; no note → nothing.

### 5. Report

Three to five lines: `threads_checked` from `sent_scanned` mails, waiting count, open items added / already listed / closed, drafts saved. End with `obsidian://open?vault=<vault_status.vault_name>&file=Soma/Follow-ups`.

## weekly — one note for the week

`/soma:weekly [week]`. `week` = `YYYY-Www` (ISO, Monday–Sunday), a date inside the week, `this`, or `last`. Default: the ISO week containing today, except on a Monday or Tuesday, when it is the previous week (say which was used). Read-only in Outlook; exactly one `vault_write`, plus the wiki lint and whatever the user says yes to in step 2.

### 1. Three calls

- `vault_weekly_facts(week=<YYYY-Www>, today=<today>)` → `start, end, open_from_inbox[] {date, label, subject, from, entry_id, note, daily}, waiting[] {since, who, what, email, age_days} (from the open items other people owe), promised_overdue[] {due, what, page, id, days_over} (the user's own items past their due date), meetings_held[] {path, subject, date, unchecked_actions[]}, no_notes[] {path, subject, date}, quiet_people[] {name, email, path, last_contact, days}`. Ticked to-dos, `status: done` email notes and the 30-day cut are already applied.
- `outlook_list_events(start="<Monday after end>T00:00:00", end="<Friday after that>T23:59:59", include_recurrences=true, limit=200, fields=["subject","start","end","location","organizer","attendees","all_day","occurrence_key","global_id"], response_format="json")`. Prep-note check: `vault_find("meeting", {"occurrence_key": …, "global_id": …}, fields=[])` per event that is not all-day, at most 15; beyond that say "not checked".
- `outlook_list_events(start="<start>T00:00:00", end="<end>T23:59:59", include_recurrences=true, limit=200, fields=["subject","start","end","all_day","attendee_count","is_meeting","occurrence_key","busy_status"], response_format="json")` for the review week itself, then `vault_time_block(action="audit", week=<YYYY-Www>, events=<items[]>)` → `{week, hours: {meeting, focus, admin, other, unplanned}, work_hours, shares, per_priority: [{name, planned_hours, held_hours}], blocks: {planned, held, moved, skipped, unanswered}, held_rows, lines}`. The server classifies each timed event (`[Focus]`, `[Admin]`, a meeting when it has attendees or `is_meeting`, else other; all-day and free-marked ones skipped), applies the `## Held` rows of `Time-blocks/<week>.md` (a skipped block counts as unplanned, a moved one keeps its minutes) and lays out `lines` for the note. No `vault_read` of the time-block note.

### 2. Wiki (load `skills/wiki/SKILL.md` first)

`vault_wiki_keep(action="lint", fix=true, items=true, created_by="soma/0.4.1")` once (`items=true` because the proposals and duplicates below are read out one by one; without it the answer carries counts only) (the safe fixes: index, code-owned keys, section order, ticked open items, stale topics to `dormant`, roll-overs); then `vault_wiki_keep(action="review")`. From the two results: the open Review items (`open[].text`: page, question, record links), the topic proposals (`checks["12"].items`: "create `<slug>` from N records?"), the possible duplicates (`checks["10"].items`, pairs `{a, b, shared}`), the un-ingested records (`checks["11"].count` and `records[]` with paths), the per-check numbers in `counts`. Ask one question per proposal and act only on a yes (a `new:` spec through `vault_wiki_write`, or `vault_wiki_keep(action="merge")`). Un-ingested records: offer "ingest the N records saved before the wiki, ten at a time?"; on a yes run the `wiki` skill's ingest steps on the first 10 (`vault_read` each once, oldest first), report, offer the next 10. Skip this whole step on "without wiki".

### 3. Write the note

Identity = `week`. Render the sections from the results, line for line, without rewording — the layout is in `references/examples.md`:

- `## Still open from inbox` — one line per `open_from_inbox` row, oldest first: `- <date> — <label> — <subject> (<from>) — <note>` (the `<!-- entry_id: … -->` comment when `note` is null). Empty → `- nothing open`; no daily notes → `- no daily notes this week (run /soma:inbox)`.
- `## Waiting on` — table `| Since | Who | What | Days |` from `waiting`, `who`/`what` as returned. Empty → `- nothing`. Then, when `promised_overdue` is not empty, one line per entry under `**Past due from me**`: `- <due> — <what> — [[<page>]] (<days_over> days over)`; done, rescheduled or dropped is a `done` / `reschedule` op on that page, one question at a time in step 2.
- `## Meetings held` — `### [[<path without .md>]] — <date>` then the `unchecked_actions` lines, or `- all done`; `no_notes` under `No notes taken (run /soma:notes):` as plain links. Nothing → `- none`.
- `## Next week` — one table per weekday with events `| Start | End | Subject | Location | Organizer |` (`all day` in both time columns for all-day events), then `**Watch out**`: each clash (overlapping `start`/`end` on the same day, each pair once) and the count without a prep note. No events → `- nothing booked`.
- `## People going quiet` — `- [[<path without .md>]] — last contact <last_contact> (<days> days)`. None → `- nobody`.
- `## Time` — the `lines` of `vault_time_block(action="audit")`, one bullet each, as returned (hours per kind with shares of the work hours; blocks planned / held / moved / skipped / unanswered; hours per priority planned and held). A week without a `Time-blocks/` note still gets the first line and `Blocks: none planned this week.`
- `## Wiki` — one line per `counts` entry above zero (`fixed` when the check has a fix), plus `questions <found>/<asked>` from `counts["questions"]` (a text, not a number: always shown when a question is on file) and `unanswered <n>` when it is above zero, then `Review (N open):` with each open line as returned, `Proposed:` the topic and merge proposals with the user's answer (created / merged / declined / no answer), `Not ingested: N records` (and what was ingested this run). All clean → `- clean; Review empty`.
- `## Notes` — the only part you write yourself: 3–6 bullets at most on what stands out (a wait past 7 days, a meeting whose actions all belong to the user, a clash worth moving, a person to call). Nothing stands out → leave the section out.

```
vault_write("weekly",
    {"type": "weekly", "source": "soma", "week": "2026-W34", "start": "2026-08-17", "end": "2026-08-23",
     "generated": "<ISO now with offset>", "created_by": "soma/0.4.1"},
    <body: "# Week 2026-W34 (2026-08-17 – 2026-08-23)" + the sections>, mode="upsert")
```

`action: created` → new note; `appended` → the week had a note and the server put the whole body under `## Update <ISO>` (the earlier text stays). Say which happened.

### 4. Report

One line per section with counts, the note path, and `obsidian://open?vault=<vault_name>&file=Soma/Weekly/<week>`. Offer `/soma:followups` only when a `waiting` row has `age_days` over 7 or `promised_overdue` is not empty, `/soma:prep` only when next week has meetings without a prep note, `/soma:wiki resolve review` when Review has open items, `/soma:time-block` when `blocks.planned` is 0 or `shares.unplanned` is above the `slack_share` of `Preferences.md`.

## Rules that apply to both

- Never call `outlook_mark_mail`, `outlook_move_mail`, `outlook_delete_mail`, `outlook_set_category`, any `bulk_*` tool, `outlook_create_event`, `outlook_update_event`, `outlook_forward_mail`, or `outlook_send_mail` / `outlook_reply_mail` without `save_only=true`.
- The vault is written only through `vault_write` and the `vault_wiki_*` tools (`open` / `done` items in `followups`, the ingest and lint in `weekly`); nothing by hand, nothing outside `Soma/`. `Follow-ups.md` is written from the pages and never edited.
- Keep datetimes exactly as the tools returned them. "Days" are counted on local dates by the tools; do not recount. No raw JSON in the reply: tables and bullet lines only.
- A second run leaves the vault as after the first: `followups` finds every key already on the pages; `weekly` appends an `## Update` section to the same note and never creates a second file.
- Measurement: when the host shows the turn's token count, end the reply with `Tokens this turn: <n>`; when it does not, say nothing about it. Neither workflow writes a daily note, so `tokens_used` is only passed to `vault_write_daily` when that tool is called in the same turn.
