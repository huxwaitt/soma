---
name: review
description: Two look-back workflows over Outlook and the vault. `followups` finds threads where the user wrote last and nobody answered for N days, updates `Follow-ups.md` (opens new rows, closes rows that got a reply), and offers short nudge emails that go to Drafts only. `weekly` writes one note `Administrator/Weekly/YYYY-Www.md` with what is still open from the week's inbox, what the user is waiting on and for how long, meetings held with their unchecked action items, next week's calendar with clashes, and people with a person note who have gone quiet for 30+ days. Trigger when the user says "/administrator:followups", "/administrator:weekly", "who hasn't replied", "who owes me an answer", "what am I waiting on", "anything I chased and heard nothing", "weekly review", "wrap up the week", "what did I not get to this week", "what's next week look like", "who have I not talked to in a while". Reads Outlook only; the single Outlook write is `outlook_send_mail(save_only=true)` for a nudge draft, one yes per draft, never a send.
---

# review — followups and weekly

Both workflows look back instead of at the inbox of the moment. They read Outlook through the `outlook_*` tools, read and write the vault only through the `vault_*` tools (`skills/administrator/references/vault.md`), and change nothing in Outlook except, in `followups`, a draft the user said yes to. Outlook mechanics (folders, `entry_id`, dates, `response_format`) follow the `outlook` skill and `skills/administrator/references/outlook.md`; do not duplicate them here.

Before either workflow: call `vault_status` once per session (run `vault_init(created_by="administrator/0.0.4")` if a folder or file flag is false) and `outlook_whoami(response_format="json")` once per session. "Self" means any `accounts[].smtp_address` from `whoami`, compared case-insensitively. Work out "today" and "now" from `whoami.local_time`, never from a guess.

## followups — who has not replied

`/administrator:followups [days]`. `days` = how long a thread must have been quiet to count, default 3. Read-only in Outlook apart from the optional nudge drafts at the end.

### 1. Sent mail, last 30 days

`outlook_list_mails(folder="sent", since=<now − 30 days, ISO>, limit=100, response_format="json")`. If `has_more` is true, call once more with `offset=100`; stop there (200 mails at most). Items have `entry_id`, `internet_message_id`, `subject`, `to` (display names only), `received`, `preview`. `list_mails` does not return `conversation_id`, so threads are grouped in step 2.

Skip items whose subject starts with `Accepted:`, `Tentative:`, `Declined:`, `Automatic reply:`, `Automatische Antwort:`, or `Read:` (calendar responses, auto-replies, read receipts), and items with an empty `to`.

### 2. One conversation per thread

Walk the remaining items newest first. Keep a set of `entry_id`s already seen inside a fetched conversation. For an item not in the set, call `outlook_get_conversation(entry_id=<item entry_id>, include_body=true, max_body_chars=2000, limit=50)` and add every `items[].entry_id` from the result to the set. Stop after 60 conversations; tell the user if the cap was hit ("older sent mail not checked, run with a narrower window later").

Each result has `conversation_id` and `items[]` oldest first, each with `entry_id`, `internet_message_id`, `from`, `from_address`, `to`, `received`, `folder`, `body`. `received` is the time Outlook stamped on the item; for a sent mail it is the send time.

### 3. Which threads are waiting

Take the item with the newest `received` in the thread (the last message). The thread is **waiting** when all of these hold:

- `from_address` of the last message is self.
- `received` of that message is at least `days` × 24 hours before now.
- The last message has at least one recipient who is not self (check `to` for a name or address that is not the user's own display name or address; mails to oneself are not follow-ups).

Everything else is **not waiting**: the last message is from someone else (they answered), or the user's mail is younger than `days`.

For each waiting thread, call `outlook_get_mail(entry_id=<last message entry_id>, include_body=false, response_format="json")` once for `recipients[]` (SMTP addresses per recipient). `Who` = the first `recipients[]` entry with `type: "to"` whose `address` is not self; if none, the first `cc`. If `recipients` is empty, `outlook_resolve_name(name=<first name in the flat to string>)`; if that fails too, use the display name and say the address is unknown.

The **last line the user wrote**: take the last message's `body`, cut quoted history and the signature with the trimming rule from `skills/save/SKILL.md` step 3, then take the last non-empty line that is not a sign-off (`Thanks`, `Best`, `Regards`, `Cheers`, `Viele Grüße`, the user's own name). Cut to 100 characters. If nothing is left, use the first 100 characters of the trimmed text.

Days waiting = whole days between the `received` date of the last message and today (local dates).

### 4. Show the table

Sorted by days waiting, longest first:

```
| # | Who | Subject | Days | Last line I wrote |
| --- | --- | --- | --- | --- |
| 1 | Tom Lee <tom.lee@acme-parts.com> | Delivery schedule September | 6 | Can you confirm 8 Sep works for the first delivery? |
```

Subject = the last message's subject with reply/forward prefixes stripped (the slug rule in `vault.md`, without the character replacement). No waiting threads → say "Nothing waiting longer than N days across M threads" and go to step 5 anyway (rows may need closing).

### 5. Update Follow-ups.md

Read it once: `vault_read("Administrator/Follow-ups.md")`. From the `## Open` table collect each row's hidden key (`<!-- entry_id: … -->`, `<!-- internet_message_id: … -->`, or `<!-- occurrence_key: … -->`), its `Who`, and its `What`.

**Open.** For each waiting thread, one row under `## Open`:

1. Key = `internet_message_id` of the user's last message; `entry_id` when it is empty. Label = `internet_message_id` or `entry_id` to match.
2. Skip the thread when any `## Open` row's key equals the key or the `entry_id` / `internet_message_id` of **any** message in the thread (the `inbox` or `save` skill already listed it), or when an `## Open` row has the same `Who` link and the same `What` text. An `## Open` row that matches does not get a second row; report it as "already listed".
3. Otherwise: `vault_find("person", <Who SMTP>)` → `Who` cell = `[[People/<note name>]]` when found, else the display name. `vault_find("email", {"internet_message_id": <key or "">, "entry_id": <last message entry_id>})` → `Email` cell = `[[Emails/<filename without .md>]]` when found, else empty. Then

   ```
   vault_append_row("Administrator/Follow-ups.md", "Open",
       [<received date of the user's last message>, <Who cell>, <subject, ten words or fewer>, <Email cell>, <today>],
       dedupe_key=<key>, key_label="internet_message_id" | "entry_id")
   ```

   `appended: false, reason: duplicate` means the key was already in the file (possibly under `## Done`); leave it and say so.

**Close.** For each `## Open` row whose key matches an `entry_id` or `internet_message_id` of any message in a thread that is **not waiting because someone else wrote last**: the wait is over.

```
vault_move_row("Administrator/Follow-ups.md", "Open", "Done", <row key>, set_last_cell=<received date of that reply>)
```

Rows whose key matches nothing fetched (older than 30 days, a meeting row, a row with no key) stay where they are; do not guess. Report each closed row as "Carol Ng replied on Contract draft (2026-08-22) → Done".

Never write to `Follow-ups.md` in any other way. Existing `## Open` rows that are still waiting keep their `Last checked` value (there is no tool to edit a cell in place); the table you showed in step 4 is the current view.

### 6. Offer nudge drafts

Only for threads that are waiting (new rows and "already listed" ones). For each, write a draft of 2–3 sentences in the user's language of the original mail: name the original subject and date, repeat the ask in one sentence using the last line the user wrote, and end with a question. No apologies, no "just checking in", nothing the original mail did not ask for.

Show one draft at a time:

```
Draft 1 of 2 → Tom Lee <tom.lee@acme-parts.com>
Subject: Re: Delivery schedule September
Body:
Hi Tom,

on 16 Aug I asked whether 8 Sep works for the first delivery. Could you confirm the date, or tell me what still needs checking on your side?

Thanks
Hux

Save this to Drafts? (yes / no / skip all)
```

Only on a clear yes: `outlook_send_mail(to=[<Who SMTP>], subject="Re: <original subject>", body=<text>, save_only=true)`. Say that it landed in Drafts as a new message (not threaded under the original; the user sends it from Outlook). "no" moves to the next draft; "skip all" stops. Never call `outlook_send_mail` without `save_only=true`, never `outlook_reply_mail` or `outlook_forward_mail`. A missing address (step 3 could not resolve one) → show the draft, say it cannot be saved to Drafts without an address, and move on.

When an email note exists for the thread (the `Email` cell), append the fact: `vault_write("email", <that note's frontmatter>, "Nudge draft saved to Drafts via /administrator:followups.", mode="append")`. Skip this when there is no note; do not create one.

### 7. Report

Three to five lines: threads checked, how many waiting, rows opened / already listed / closed, drafts saved. End with an `obsidian://open?vault=<vault_status.vault_name>&file=Administrator/Follow-ups` link.

## weekly — one note for the week

`/administrator:weekly [week]`. `week` = `YYYY-Www` (ISO week, Monday–Sunday), a date inside the week, `this`, or `last`. Default: the ISO week containing today, except on a Monday or Tuesday, when it is the previous week (say which week was used). Read-only in Outlook; exactly one `vault_write`.

Work out `start` = Monday of the week and `end` = Sunday of the week as local dates, `next_start` = the Monday after `end`, `next_end` = the Friday after that.

### 1. Still open from inbox

`vault_list("daily", since=<start>)` → keep notes whose `frontmatter.date` is within `start`..`end`. `vault_read` each. From every `| # | Label | … |` table (under `## Inbox …` and under `### Inbox …` inside `## Update` sections) take rows whose `Label` is `act` or `reply`. For each row read the `<!-- entry_id: … -->` comment and the `Note` link. Drop the row when:

- the daily note's `## To do` holds a ticked line `- [x]` for the same subject, or
- `vault_find("email", {"internet_message_id": "", "entry_id": <comment>})` finds a note with `status: done`.

List what is left, oldest day first:

```
- 2026-08-19 — act — Budget Q3 (Jane Doe) — [[Emails/2026-08-19 Budget Q3]]
- 2026-08-21 — reply — Re: offsite dates (Bob Lee) <!-- entry_id: 00000000AB… -->
```

Nothing left → the single line `- nothing open`. No daily notes in the week → `- no daily notes this week (run /administrator:inbox)`.

### 2. Waiting on

`vault_read("Administrator/Follow-ups.md")` → every `## Open` row, with age = whole days between `Since` and `end` (or today when `end` is in the future). Sorted oldest first:

```
| Since | Who | What | Days |
| --- | --- | --- | --- |
| 2026-08-16 | [[People/Tom Lee]] | Delivery schedule September | 7 |
```

Copy `Who` and `What` verbatim, without the hidden comment. Empty table → `- nothing`. Suggest `/administrator:followups` in the report when any row is older than 7 days.

### 3. Meetings held

`vault_list("meeting", since=<start>)` → keep notes whose `frontmatter.start` date is within `start`..`end` and `status` is `held`. `vault_read` each and collect the `- [ ]` lines under `## Action items` (also `- [ ]` lines inside any `## Update` section). Per meeting:

```
### [[Meetings/2026-08-18 1300 Weekly supplier sync]] — 2026-08-18

- [ ] Confirm Leipzig delivery address — owner: Tom Lee
```

A held meeting with no unchecked items gets the line `- all done`. Meeting notes in the week with `status: upcoming` and `start` in the past are listed at the end under the line `No notes taken (run /administrator:notes):` as plain links. No meetings → `- none`.

### 4. Next week

`outlook_list_events(start="<next_start>T00:00:00", end="<next_end>T23:59:59", include_recurrences=true, limit=200, response_format="json")`. One table per weekday that has events:

```
### Monday 2026-08-24

| Start | End | Subject | Location | Organizer |
| --- | --- | --- | --- | --- |
| 09:30 | 10:00 | Stand-up | Teams | Bob Lee |
```

All-day events show `all day` in both time columns. Below the tables, a `**Watch out**` list: clashes (overlapping `start`/`end` on the same day, each pair once) and the count of meetings with no prep note (`vault_find("meeting", {"occurrence_key": <key>, "global_id": <id>})` finds nothing; all-day events exempt). No events → `- nothing booked`.

### 5. People going quiet

`vault_list("person")` → keep notes whose `last_contact` is non-empty and more than 30 days before `end`. Skip stubs with `last_contact: ""`. Oldest first, at most 20:

```
- [[People/Carol Ng]] — last contact 2026-07-10 (43 days)
```

None → `- nobody`.

### 6. Write the note

Identity = `week`. One call:

```
vault_write("weekly",
    {"type": "weekly", "source": "administrator", "week": "2026-W34", "start": "2026-08-17", "end": "2026-08-23",
     "generated": "<ISO now with offset>", "created_by": "administrator/0.0.4"},
    <body below>, mode="upsert")
```

Body:

```markdown
# Week 2026-W34 (2026-08-17 – 2026-08-23)

## Still open from inbox

…

## Waiting on

…

## Meetings held

…

## Next week

…

## People going quiet

…
```

`action: created` → new note. `action: appended` → the week already had a note; the server put the whole body under `## Update <ISO>`, which is what you want (the old text stays as the record of the earlier run). Say which happened.

### 7. Report

Counts per section in one line each, then the note path and an `obsidian://open?vault=<vault_name>&file=Administrator/Weekly/<week>` link. Offer `/administrator:followups` or `/administrator:prep` only when step 2 or step 4 gave a reason.

## Rules that apply to both

- Never call `outlook_mark_mail`, `outlook_move_mail`, `outlook_delete_mail`, `outlook_set_category`, any `bulk_*` tool, `outlook_create_event`, `outlook_update_event`, `outlook_reply_mail`, `outlook_forward_mail`, or `outlook_send_mail` without `save_only=true`.
- The vault is written only through `vault_append_row`, `vault_move_row` and `vault_write`; nothing is edited by hand and nothing outside `Administrator/`.
- Keep datetimes exactly as Outlook returned them. "Days" are counted on local dates.
- No raw JSON in the reply. Tables and bullet lines only.
- Running either workflow twice in a row leaves the vault as it was after the first run: `followups` finds every key already present; `weekly` appends an `## Update` section to the same note and never creates a second file.

## Worked example — followups

`/administrator:followups` on Saturday 2026-08-22 10:05 (+02:00). `outlook_whoami` → `hux@example.com`.

`outlook_list_mails(folder="sent", since="2026-07-23T10:05:00", limit=100, response_format="json")` → 41 items, `has_more: false`. Two are `Accepted:` calendar responses → skipped. Walking the 39 newest first: 23 `outlook_get_conversation` calls cover all of them (replies in the same thread share a conversation).

Three threads have the user's mail as the last message and are older than 3 days:

| # | Who | Subject | Days | Last line I wrote |
| --- | --- | --- | --- | --- |
| 1 | Tom Lee <tom.lee@acme-parts.com> | Delivery schedule September | 6 | Can you confirm 8 Sep works for the first delivery? |
| 2 | Priya Nair <priya.nair@northwind.example> | Offsite venue options | 4 | Which of the three venues should I hold? |
| 3 | Bob Lee <bob.lee@example.com> | Re: offsite dates | 3 | Week 36 works for me — shall I send the invite? |

`vault_read("Administrator/Follow-ups.md")` → `## Open` has two rows: Carol Ng / Contract draft (`<!-- entry_id: 00000000AC… -->`) and Tom Lee / Delivery schedule September (`<!-- entry_id: 00000000B3… -->`, written by `prep`). The Tom Lee row's key is the `entry_id` of Tom's 19 Aug mail, which is in thread 1 → thread 1 is "already listed". Carol's key is in a thread whose last message is from `carol.ng@example.com` on 2026-08-22 → closed:

```
vault_move_row("Administrator/Follow-ups.md", "Open", "Done", "00000000AC…", set_last_cell="2026-08-22")
```

Threads 2 and 3 get rows. `vault_find("person", "priya.nair@northwind.example")` → not found; `vault_find("person", "bob.lee@example.com")` → `Administrator/People/Bob Lee.md`. No email notes for either.

```
vault_append_row("Administrator/Follow-ups.md", "Open",
    ["2026-08-18", "Priya Nair", "Offsite venue options", "", "2026-08-22"],
    dedupe_key="<DB7PR05MB1234A9@DB7PR05MB1234.eurprd05.prod.outlook.com>", key_label="internet_message_id")
vault_append_row("Administrator/Follow-ups.md", "Open",
    ["2026-08-19", "[[People/Bob Lee]]", "offsite dates", "", "2026-08-22"],
    dedupe_key="<DB7PR05MB1234B1@DB7PR05MB1234.eurprd05.prod.outlook.com>", key_label="internet_message_id")
```

`## Open` now reads:

```markdown
| Since | Who | What | Email | Last checked |
| --- | --- | --- | --- | --- |
| 2026-08-19 | [[People/Tom Lee]] | Delivery schedule September | [[Meetings/2026-08-25 1300 Weekly supplier sync]] | 2026-08-21 <!-- entry_id: 00000000B3… --> |
| 2026-08-18 | Priya Nair | Offsite venue options |  | 2026-08-22 <!-- internet_message_id: <DB7PR05MB1234A9@DB7PR05MB1234.eurprd05.prod.outlook.com> --> |
| 2026-08-19 | [[People/Bob Lee]] | offsite dates |  | 2026-08-22 <!-- internet_message_id: <DB7PR05MB1234B1@DB7PR05MB1234.eurprd05.prod.outlook.com> --> |
```

Drafts: the user says yes to draft 1 (Tom), no to draft 2, yes to draft 3. Two `outlook_send_mail(..., save_only=true)` calls; nothing sent.

Report:

> 23 threads checked from 39 sent mails. 3 waiting longer than 3 days (Tom Lee 6 d, Priya Nair 4 d, Bob Lee 3 d). Follow-ups: 2 rows added, 1 already listed (Tom Lee), 1 closed (Carol Ng replied on Contract draft, 2026-08-22). 2 nudge drafts saved to Drafts (Tom Lee, Bob Lee); nothing sent.
> obsidian://open?vault=MyVault&file=Administrator/Follow-ups

A second run ten minutes later finds the three keys in the file and reports "3 waiting, 0 new rows, 0 closed".

## Worked example — weekly

`/administrator:weekly` on Saturday 2026-08-22 → week `2026-W34` (2026-08-17 – 2026-08-23), next week 2026-08-24 – 2026-08-28.

1. `vault_list("daily", since="2026-08-17")` → `Daily/2026-08-19.md`, `Daily/2026-08-21.md`, `Daily/2026-08-22.md`. Six `act`/`reply` rows across them; one (`Re: Supplier sync agenda`) has a ticked `- [x]` line in `## To do`, one (`Budget Q3`) has an email note with `status: done`. Four remain.
2. `Follow-ups.md` `## Open` → three rows (after the followups run above).
3. `vault_list("meeting", since="2026-08-17")` → `Meetings/2026-08-18 1300 Weekly supplier sync.md` (`held`, two unchecked items) and `Meetings/2026-08-20 1000 Budget review with Jane.md` (`upcoming`, start in the past → no notes taken).
4. `outlook_list_events(start="2026-08-24T00:00:00", end="2026-08-28T23:59:59", include_recurrences=true, limit=200, response_format="json")` → 9 events; Tuesday has a clash; 7 have no prep note.
5. `vault_list("person")` → 12 notes; two have `last_contact` older than 2026-07-24.

`vault_write("weekly", {...week: "2026-W34"...}, body, mode="upsert")` → `{"action": "created", "path": "Administrator/Weekly/2026-W34.md"}`:

```markdown
---
type: weekly
source: administrator
week: 2026-W34
start: 2026-08-17
end: 2026-08-23
generated: 2026-08-22T10:20:00+02:00
created_by: administrator/0.0.4
---

# Week 2026-W34 (2026-08-17 – 2026-08-23)

## Still open from inbox

- 2026-08-19 — act — Q3 supplier contract – signature needed (Jane Doe) — [[Emails/2026-08-21 Q3 supplier contract – signature needed]]
- 2026-08-21 — reply — Re: offsite dates (Bob Lee) <!-- entry_id: 00000000AB… -->
- 2026-08-21 — act — Packaging spec v2 (Tom Lee) <!-- entry_id: 00000000B7… -->
- 2026-08-22 — reply — Invoice 4471 query (Accounts) <!-- entry_id: 00000000C2… -->

## Waiting on

| Since | Who | What | Days |
| --- | --- | --- | --- |
| 2026-08-18 | Priya Nair | Offsite venue options | 5 |
| 2026-08-19 | [[People/Tom Lee]] | Delivery schedule September | 4 |
| 2026-08-19 | [[People/Bob Lee]] | offsite dates | 4 |

## Meetings held

### [[Meetings/2026-08-18 1300 Weekly supplier sync]] — 2026-08-18

- [ ] Send revised forecast to Jane — owner: me
- [ ] Confirm Leipzig delivery address — owner: Tom Lee

No notes taken (run /administrator:notes):

- [[Meetings/2026-08-20 1000 Budget review with Jane]]

## Next week

### Monday 2026-08-24

| Start | End | Subject | Location | Organizer |
| --- | --- | --- | --- | --- |
| 09:30 | 10:00 | Stand-up | Teams | Bob Lee |

### Tuesday 2026-08-25

| Start | End | Subject | Location | Organizer |
| --- | --- | --- | --- | --- |
| 09:30 | 10:00 | Stand-up | Teams | Bob Lee |
| 13:00 | 14:00 | Weekly supplier sync | Room 4 | Jane Doe |
| 13:30 | 14:30 | Dentist |  | me |

**Watch out**

- Clash Tue: Weekly supplier sync (13:00–14:00) overlaps Dentist (13:30–14:30)
- 7 meetings have no prep note

## People going quiet

- [[People/Carol Ng]] — last contact 2026-07-10 (44 days)
- [[People/Sam Ortiz]] — last contact 2026-07-18 (36 days)
```

Report:

> Week 2026-W34 written to `Weekly/2026-W34.md`. Open from inbox: 4. Waiting on: 3 (oldest 5 days). Meetings held: 1 with 2 open items; 1 without notes. Next week: 9 meetings, 1 clash, 7 without prep. Going quiet: 2.
> obsidian://open?vault=MyVault&file=Administrator/Weekly/2026-W34

Run again on Sunday: `action: appended`, the new pass sits under `## Update 2026-08-23T…` in the same file.
