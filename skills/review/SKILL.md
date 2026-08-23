---
name: review
description: Two look-back workflows over Outlook and the vault. `followups` asks `outlook_awaiting_reply` for the threads where the user wrote last and nobody answered for N days, updates `Follow-ups.md` (opens new rows, closes rows that got a reply), and offers short nudge drafts that go to Drafts only. `weekly` takes `vault_weekly_facts` plus next week's calendar and writes one note `Administrator/Weekly/YYYY-Www.md` with what is still open from the week's inbox, what the user is waiting on and for how long, meetings held with their unchecked action items, next week's calendar with clashes, and people who have gone quiet for 30+ days. Trigger when the user says "/administrator:followups", "/administrator:weekly", "who hasn't replied", "who owes me an answer", "what am I waiting on", "anything I chased and heard nothing", "weekly review", "wrap up the week", "what did I not get to this week", "what's next week look like", "who have I not talked to in a while". Reads Outlook only; the single Outlook write is a nudge draft with `save_only=true`, one yes per draft, never a send.
---

# review — followups and weekly

Both workflows look back instead of at the inbox of the moment. The tools do the collecting, comparing and counting; you decide and write the few lines only a person can write. Outlook is read through `outlook_*` tools, the vault is read and written only through `vault_*` tools (`skills/administrator/references/vault.md`), and nothing in Outlook changes except, in `followups`, a draft the user said yes to. Outlook mechanics follow the `outlook` skill and `skills/administrator/references/outlook.md`. Worked examples with real call sequences: `references/examples.md` (load it the first time a workflow runs in a session).

Before either workflow: `vault_status` once per session (run `vault_init(created_by="administrator/0.1.0")` if a folder or file flag is false) and `outlook_whoami(response_format="json")` once per session. "Self" = any `accounts[].smtp_address`, compared case-insensitively. "Today" and "now" come from `whoami.local_time`, never from a guess.

Cost rules for both: pass `fields=[...]` on every list, search, get and conversation call and `preview_chars=0` unless a preview is needed; never repeat text a tool result already holds (paste `last_line`, `subject`, `who` as they came); never read a note with `vault_read` when a helper already returned the facts.

## followups — who has not replied

`/administrator:followups [days]`. `days` = how long a thread must have been quiet to count, default 3.

### 1. One call

`outlook_awaiting_reply(days=<N>, since_days=30, limit=50)` → `items[]` longest wait first, each `conversation_id, entry_id, internet_message_id, subject, to[] (SMTP), to_names[], last_sent, days_waiting, last_line`; top-level `sent_scanned, threads_checked, capped`. The server already skipped calendar responses, auto-replies, read receipts and mails to oneself, and cut `last_line` to the last real sentence the user wrote. `capped: true` → say "older sent mail not checked; run again with a smaller `since_days` later".

### 2. Show the table

```
| # | Who | Subject | Days | Last line I wrote |
| --- | --- | --- | --- | --- |
| 1 | Tom Lee <tom.lee@acme-parts.com> | Delivery schedule September | 6 | Can you confirm 8 Sep works for the first delivery? |
```

`Who` = `to_names[0] <to[0]>`; `to[]` empty → the name and "(address unknown)". Subject = `subject` with reply/forward prefixes stripped. No items → "Nothing waiting longer than N days across M threads" and go on to step 3 (rows may need closing).

### 3. Update Follow-ups.md

`vault_read("Administrator/Follow-ups.md")` once — the only `vault_read` in this workflow; `Follow-ups.md` has no helper and is short. From `## Open` collect each row's hidden key (`<!-- entry_id: … -->`, `<!-- internet_message_id: … -->`, `<!-- occurrence_key: … -->`), `Who` and `What`.

**Open.** Per item: key = `internet_message_id`, `entry_id` when empty; `key_label` to match. Skip the item as "already listed" when an `## Open` row's key equals the item's `internet_message_id` or `entry_id`, or the row has the same `Who` link and the same `What` text. Otherwise `vault_find("person", <to[0]>, fields=["name"])` → `Who` cell `[[People/<note name>]]` when found, else `to_names[0]`; `vault_find("email", {"internet_message_id": <key or "">, "entry_id": <entry_id>}, fields=[])` → `Email` cell `[[Emails/<filename without .md>]]` when found, else empty. Then

```
vault_append_row("Administrator/Follow-ups.md", "Open",
    [<last_sent date>, <Who cell>, <subject, ten words or fewer>, <Email cell>, <today>],
    dedupe_key=<key>, key_label="internet_message_id" | "entry_id")
```

`appended: false, reason: duplicate` → the key is already in the file (maybe under `## Done`); leave it and say so.

**Close.** For each `## Open` row whose key matched no item:

- key label `entry_id` (rows from `inbox`, `save`, `prep`): `outlook_get_conversation(entry_id=<key>, include_body=false, limit=50, fields=["entry_id","from_address","received"])`. Last item from someone who is not self → `vault_move_row("Administrator/Follow-ups.md", "Open", "Done", <key>, set_last_cell=<that received date>)`. Last item from self, or a tool error (mail moved or deleted) → leave the row. At most 10 such calls per run; say when rows were left unchecked.
- key label `internet_message_id` (rows this workflow wrote): the user's mail was in the scan when `capped` is false and `Since` is within the last 30 days; not being an item means the wait is over (a reply, or a newer mail from the user that now has its own row). Move it to Done with `set_last_cell=<today>` and report "no longer waiting". `capped: true` or an older `Since` → leave it.
- `occurrence_key` rows and rows without a key stay. Never guess.

Never write `Follow-ups.md` in any other way. Rows still waiting keep their `Last checked` value (no tool edits a cell in place); the table from step 2 is the current view.

### 4. Nudge drafts

Only for waiting items (new rows and "already listed" ones). Voice: `outlook_voice_sample(address=<to[0]>, n=10, max_chars=300)` once per distinct recipient, at most 5 calls per run; `used_address: false` means the sample is the user's sent mail overall — build that general profile once and reuse it for every later draft this session. Read the six facts from `items[].opening` / `closing` and `stats` as `skills/draft/references/voice.md` says ("nudge" variant); hard rules in `Preferences.md` `## Voice` win.

Body, 2–3 sentences in the language of `last_line`: the original subject and `last_sent` date, the ask in one sentence built from `last_line`, one closing question. No apology, no "just checking in", nothing the original mail did not ask. `[fill in: …]` for anything missing. Show one draft at a time:

```
Draft 1 of 2 → Tom Lee <tom.lee@acme-parts.com>
Subject: Re: Delivery schedule September
Body:
<text>

Save this to Drafts? (yes / no / skip all)
```

Only on a clear yes: `outlook_reply_mail(entry_id=<item entry_id, the user's own last mail>, body=<text>, reply_all=false, html=false, save_only=true)` → the draft lands in Drafts inside the thread, addressed to the original recipients; tell the user to check the To line before sending from Outlook. `to[]` empty → show the draft, say it cannot be saved without an address, move on. "no" skips one, "skip all" stops. Never `outlook_reply_mail` or `outlook_send_mail` without `save_only=true`, never `outlook_forward_mail`. When the `Email` cell links a note: `vault_write("email", <frontmatter from the vault_find>, "Nudge draft saved to Drafts via /administrator:followups.", mode="append")`; no note → nothing.

### 5. Report

Three to five lines: `threads_checked` from `sent_scanned` mails, waiting count, rows opened / already listed / closed, drafts saved. End with `obsidian://open?vault=<vault_status.vault_name>&file=Administrator/Follow-ups`.

## weekly — one note for the week

`/administrator:weekly [week]`. `week` = `YYYY-Www` (ISO, Monday–Sunday), a date inside the week, `this`, or `last`. Default: the ISO week containing today, except on a Monday or Tuesday, when it is the previous week (say which was used). Read-only in Outlook; exactly one `vault_write`.

### 1. Two calls

- `vault_weekly_facts(week=<YYYY-Www>, today=<today>)` → `start, end, open_from_inbox[] {date, label, subject, from, entry_id, note, daily}, waiting[] {since, who, what, email, age_days}, meetings_held[] {path, subject, date, unchecked_actions[]}, no_notes[] {path, subject, date}, quiet_people[] {name, email, path, last_contact, days}`. Ticked to-dos, `status: done` email notes and the 30-day cut are already applied.
- `outlook_list_events(start="<Monday after end>T00:00:00", end="<Friday after that>T23:59:59", include_recurrences=true, limit=200, fields=["subject","start","end","location","organizer","attendees","all_day","occurrence_key","global_id"], response_format="json")`. Prep-note check: `vault_find("meeting", {"occurrence_key": …, "global_id": …}, fields=[])` per event that is not all-day, at most 15; beyond that say "not checked".

### 2. Write the note

Identity = `week`. Render the five sections from the two results, line for line, without rewording — the layout is in `references/examples.md`:

- `## Still open from inbox` — one line per `open_from_inbox` row, oldest first: `- <date> — <label> — <subject> (<from>) — <note>` (the `<!-- entry_id: … -->` comment when `note` is null). Empty → `- nothing open`; no daily notes → `- no daily notes this week (run /administrator:inbox)`.
- `## Waiting on` — table `| Since | Who | What | Days |` from `waiting`, `who`/`what` as returned. Empty → `- nothing`.
- `## Meetings held` — `### [[<path without .md>]] — <date>` then the `unchecked_actions` lines, or `- all done`; `no_notes` under `No notes taken (run /administrator:notes):` as plain links. Nothing → `- none`.
- `## Next week` — one table per weekday with events `| Start | End | Subject | Location | Organizer |` (`all day` in both time columns for all-day events), then `**Watch out**`: each clash (overlapping `start`/`end` on the same day, each pair once) and the count without a prep note. No events → `- nothing booked`.
- `## People going quiet` — `- [[<path without .md>]] — last contact <last_contact> (<days> days)`. None → `- nobody`.
- `## Notes` — the only part you write yourself: 3–6 bullets at most on what stands out (a wait past 7 days, a meeting whose actions all belong to the user, a clash worth moving, a person to call). Nothing stands out → leave the section out.

```
vault_write("weekly",
    {"type": "weekly", "source": "administrator", "week": "2026-W34", "start": "2026-08-17", "end": "2026-08-23",
     "generated": "<ISO now with offset>", "created_by": "administrator/0.1.0"},
    <body: "# Week 2026-W34 (2026-08-17 – 2026-08-23)" + the sections>, mode="upsert")
```

`action: created` → new note; `appended` → the week had a note and the server put the whole body under `## Update <ISO>` (the earlier text stays). Say which happened.

### 3. Report

One line per section with counts, the note path, and `obsidian://open?vault=<vault_name>&file=Administrator/Weekly/<week>`. Offer `/administrator:followups` only when a `waiting` row has `age_days` over 7, `/administrator:prep` only when next week has meetings without a prep note.

## Rules that apply to both

- Never call `outlook_mark_mail`, `outlook_move_mail`, `outlook_delete_mail`, `outlook_set_category`, any `bulk_*` tool, `outlook_create_event`, `outlook_update_event`, `outlook_forward_mail`, or `outlook_send_mail` / `outlook_reply_mail` without `save_only=true`.
- The vault is written only through `vault_append_row`, `vault_move_row` and `vault_write`; nothing by hand, nothing outside `Administrator/`.
- Keep datetimes exactly as the tools returned them. "Days" are counted on local dates by the tools; do not recount.
- No raw JSON in the reply. Tables and bullet lines only.
- A second run leaves the vault as after the first: `followups` finds every key already present; `weekly` appends an `## Update` section to the same note and never creates a second file.
- Measurement: when the host shows the turn's token count, end the reply with `Tokens this turn: <n>`; when it does not, say nothing about it. Neither workflow writes a daily note, so `tokens_used` is only passed to `vault_write_daily` when that tool is called in the same turn.
