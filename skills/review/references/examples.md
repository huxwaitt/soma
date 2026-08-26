# review — worked examples

Two full runs, call by call, for `skills/review/SKILL.md`. The user is `hux@example.com`, the vault is `MyVault`.

## followups

`/administrator:followups` on Saturday 2026-08-22 10:05 (+02:00). `outlook_whoami` → `hux@example.com`.

### Step 1

`outlook_awaiting_reply(days=3, since_days=30, limit=50)` →

```
sent_scanned: 39, threads_checked: 23, capped: false, count: 3
items:
  - conversation_id: "CAE…01", entry_id: "00000000B3…", internet_message_id: "<DB7PR05MB1234A1@…>",
    subject: "Re: Delivery schedule September", to: ["tom.lee@acme-parts.com"], to_names: ["Tom Lee"],
    last_sent: "2026-08-16T14:10:00+02:00", days_waiting: 6,
    last_line: "Can you confirm 8 Sep works for the first delivery?"
  - conversation_id: "CAE…02", entry_id: "00000000B5…", internet_message_id: "<DB7PR05MB1234A9@…>",
    subject: "Offsite venue options", to: ["priya.nair@northwind.example"], to_names: ["Priya Nair"],
    last_sent: "2026-08-18T09:02:00+02:00", days_waiting: 4,
    last_line: "Which of the three venues should I hold?"
  - conversation_id: "CAE…03", entry_id: "00000000B9…", internet_message_id: "<DB7PR05MB1234B1@…>",
    subject: "Re: offsite dates", to: ["bob.lee@example.com"], to_names: ["Bob Lee"],
    last_sent: "2026-08-19T17:40:00+02:00", days_waiting: 3,
    last_line: "Week 36 works for me — shall I send the invite?"
```

Two `Accepted:` responses in Sent were skipped by the server; nothing was read by the model.

### Step 2

| # | Who | Subject | Days | Last line I wrote |
| --- | --- | --- | --- | --- |
| 1 | Tom Lee <tom.lee@acme-parts.com> | Delivery schedule September | 6 | Can you confirm 8 Sep works for the first delivery? |
| 2 | Priya Nair <priya.nair@northwind.example> | Offsite venue options | 4 | Which of the three venues should I hold? |
| 3 | Bob Lee <bob.lee@example.com> | Re: offsite dates | 3 | Week 36 works for me — shall I send the invite? |

### Step 3

`vault_read("Administrator/Follow-ups.md")` → `## Open` has two rows: Carol Ng / Contract draft (`<!-- entry_id: 00000000AC… -->`, written by `inbox`) and `[[Wiki/People/Tom Lee]]` / Delivery schedule September (`<!-- entry_id: 00000000AB… -->`, written by `prep` from Tom's 19 Aug mail).

- Item 1: no key match, but the row has the same `Who` (Tom Lee) and the same `What` → already listed.
- Item 2: `vault_find("person", "priya.nair@northwind.example", fields=["name"])` → not found; `vault_find("email", {"internet_message_id": "<DB7PR05MB1234A9@…>", "entry_id": "00000000B5…"}, fields=[])` → not found.
- Item 3: `vault_find("person", "bob.lee@example.com", fields=["name"])` → `Administrator/Wiki/People/Bob Lee.md`; email note not found.

```
vault_append_row("Administrator/Follow-ups.md", "Open",
    ["2026-08-18", "Priya Nair", "Offsite venue options", "", "2026-08-22"],
    dedupe_key="<DB7PR05MB1234A9@…>", key_label="internet_message_id")
vault_append_row("Administrator/Follow-ups.md", "Open",
    ["2026-08-19", "[[Wiki/People/Bob Lee]]", "offsite dates", "", "2026-08-22"],
    dedupe_key="<DB7PR05MB1234B1@…>", key_label="internet_message_id")
```

Closing: the Carol Ng row matched no item and has an `entry_id` key → `outlook_get_conversation(entry_id="00000000AC…", include_body=false, limit=50, fields=["entry_id","from_address","received"])` → last item `from_address: carol.ng@example.com`, `received: 2026-08-22T08:15:00+02:00` → `vault_move_row("Administrator/Follow-ups.md", "Open", "Done", "00000000AC…", set_last_cell="2026-08-22")`. Tom's row matched item 1 by `Who` + `What` → stays.

`## Open` now reads:

```markdown
| Since | Who | What | Email | Last checked |
| --- | --- | --- | --- | --- |
| 2026-08-19 | [[Wiki/People/Tom Lee]] | Delivery schedule September | [[Meetings/2026-08-25 1300 Weekly supplier sync]] | 2026-08-21 <!-- entry_id: 00000000AB… --> |
| 2026-08-18 | Priya Nair | Offsite venue options |  | 2026-08-22 <!-- internet_message_id: <DB7PR05MB1234A9@…> --> |
| 2026-08-19 | [[Wiki/People/Bob Lee]] | offsite dates |  | 2026-08-22 <!-- internet_message_id: <DB7PR05MB1234B1@…> --> |
```

### Step 4

`outlook_voice_sample(address="tom.lee@acme-parts.com", n=10, max_chars=300)` → `used_address: true, matched: 7`, `stats.greeting_counts: {"hi": 7}`, `stats.signoff_counts: {"thanks": 6, "best": 1}`, `stats.avg_chars: 310`. Profile for Tom: "Hi Tom," / "Thanks" + "Hux" / ~60 words / informal / prose / one question at the end.

```
Draft 1 of 3 → Tom Lee <tom.lee@acme-parts.com>
Subject: Re: Delivery schedule September
Body:
Hi Tom,

on 16 Aug I asked whether 8 Sep works for the first delivery. Could you confirm the date, or tell me what still needs checking on your side?

Thanks
Hux

Save this to Drafts? (yes / no / skip all)
```

User: "yes" → `outlook_reply_mail(entry_id="00000000B3…", body=<text>, reply_all=false, html=false, save_only=true)` → `{status: "saved", entry_id: "00000000C4…"}`. Reported as "in Drafts, inside the thread, addressed to Tom — check the To line before sending".

`outlook_voice_sample(address="priya.nair@northwind.example")` → `used_address: false, matched: 1` — the general profile, built from this result and reused for Bob as well (no third call). Draft 2 (Priya): "no". Draft 3 (Bob): "yes" → second `outlook_reply_mail(..., save_only=true)`. Nothing sent.

### Step 5

> 23 threads checked from 39 sent mails. 3 waiting longer than 3 days (Tom Lee 6 d, Priya Nair 4 d, Bob Lee 3 d). Follow-ups: 2 rows added, 1 already listed (Tom Lee), 1 closed (Carol Ng replied on Contract draft, 2026-08-22). 2 nudge drafts saved to Drafts (Tom Lee, Bob Lee); nothing sent.
> obsidian://open?vault=MyVault&file=Administrator/Follow-ups
> Tokens this turn: 4 900

Calls: 1 `awaiting_reply`, 1 `vault_read`, 4 `vault_find`, 2 `vault_append_row`, 1 `get_conversation`, 1 `vault_move_row`, 2 `voice_sample`, 2 `reply_mail` = 14 (plus `vault_status` / `whoami` once per session). A second run ten minutes later finds all three keys in the file: "3 waiting, 0 new rows, 0 closed".

## weekly

`/administrator:weekly` on Saturday 2026-08-22 → week `2026-W34` (2026-08-17 – 2026-08-23), next week 2026-08-24 – 2026-08-28.

### Step 1

`vault_weekly_facts(week="2026-W34", today="2026-08-22")` →

```
open_from_inbox: 4 rows (six act/reply rows across Daily/2026-08-19, -21, -22; one ticked in To do, one with a done email note — both dropped by the tool)
waiting: 3 rows, age_days 5 / 4 / 4
meetings_held: [{path: "Administrator/Meetings/2026-08-18 1300 Weekly supplier sync.md", date: "2026-08-18",
                 unchecked_actions: ["- [ ] Send revised forecast to Jane — owner: me", "- [ ] Confirm Leipzig delivery address — owner: Tom Lee"]}]
no_notes: [{path: "Administrator/Meetings/2026-08-20 1000 Budget review with Jane.md", subject: "Budget review with Jane", date: "2026-08-20"}]
quiet_people: [{name: "Carol Ng", path: "Administrator/Wiki/People/Carol Ng.md", last_contact: "2026-07-10", days: 44},
               {name: "Sam Ortiz", path: "Administrator/Wiki/People/Sam Ortiz.md", last_contact: "2026-07-18", days: 36}]
```

`outlook_list_events(start="2026-08-24T00:00:00", end="2026-08-28T23:59:59", include_recurrences=true, limit=200, fields=["subject","start","end","location","organizer","attendees","all_day","occurrence_key","global_id"], response_format="json")` → 9 events. Nine `vault_find("meeting", {...}, fields=[])` calls → 2 found, 7 without a prep note. Tuesday 13:00–14:00 and 13:30–14:30 overlap.

### Step 2

`vault_write("weekly", {...week: "2026-W34"...}, body, mode="upsert")` → `{"action": "created", "path": "Administrator/Weekly/2026-W34.md"}`:

```markdown
---
type: weekly
source: administrator
week: 2026-W34
start: 2026-08-17
end: 2026-08-23
generated: 2026-08-22T10:20:00+02:00
created_by: administrator/0.4.0
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
| 2026-08-19 | [[Wiki/People/Tom Lee]] | Delivery schedule September | 4 |
| 2026-08-19 | [[Wiki/People/Bob Lee]] | offsite dates | 4 |

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

- [[Wiki/People/Carol Ng]] — last contact 2026-07-10 (44 days)
- [[Wiki/People/Sam Ortiz]] — last contact 2026-07-18 (36 days)

## Notes

- Both open supplier-sync actions are still open a week later; the forecast one is yours.
- Tuesday's dentist overlaps the supplier sync — move one before Monday.
- Carol Ng has gone quiet since the contract draft closed; worth a call.
```

Everything above `## Notes` is the two tool results laid out; the three bullets are the only text written by the model.

### Step 3

> Week 2026-W34 written to `Weekly/2026-W34.md`. Open from inbox: 4. Waiting on: 3 (oldest 5 days). Meetings held: 1 with 2 open items; 1 without notes. Next week: 9 meetings, 1 clash, 7 without prep. Going quiet: 2. Run /administrator:prep for next week.
> obsidian://open?vault=MyVault&file=Administrator/Weekly/2026-W34
> Tokens this turn: 6 200

Calls: 1 `vault_weekly_facts`, 1 `list_events`, 9 `vault_find`, 1 `vault_write` = 12. Run again on Sunday: `action: appended`, the new pass sits under `## Update 2026-08-23T…` in the same file.
