---
name: time-block
description: Plans the week's focus and admin blocks as appointments in the user's own Outlook calendar. Reads `Preferences.md` and `Priorities.md`, shows how last week went (`vault_time_audit`), lets `vault_time_block_plan` place `[Focus] <priority>` and `[Admin] Email and small tasks` blocks around the meetings with a slack share kept free, shows one line per day, books them with `outlook_create_event` only after a yes (appointments without attendees — nothing is sent to anyone), then writes `Administrator/Time-blocks/YYYY-Www.md` with `vault_time_block_write`. Trigger when the user says "/administrator:time-block", "plan my week", "block time for", "time-block next week", "book my focus blocks", "protect my mornings", "when do I get to work on X", "re-plan the week", "how did my week go against my priorities". Never deletes or moves an appointment; a re-plan only adds.
---

# time-block — the week's focus and admin blocks

The planner (`vault_time_block_plan`) does the placing; you show the week, ask once, create the appointments, and let `vault_time_block_write` keep the plan. Why the blocks look the way they do — specific when-and-where plans, long blocks in peak hours, shallow work in a few batches, a fifth of the day left free, a weekly audit — is in `references/method.md` (load it when the user asks why, or wants to change a preference). Worked runs with every call and result: `references/examples.md` — load it the first time this runs in a session. Outlook mechanics follow the `outlook` skill; notes go only through `vault_*` tools (`skills/administrator/references/vault.md`).

Once per session: `vault_status` (a false folder or file flag → `vault_init(created_by="administrator/0.3.0")`; vault unset or not a directory → stop and say so) and `outlook_whoami(response_format="json")` — `local_time` is "now" and "today"; the offset in it is the one every ISO string below carries.

## Steps

### 1. Preferences and priorities

`vault_read("Administrator/Preferences.md")` once per session (skip when the `schedule` skill already read it). The planner reads the keys itself and returns `preferences_used` and `missing_keys`; you need the values only to explain a placement. Never edit the file.

`vault_read("Administrator/Priorities.md")` once per run: the numbered lines under `## Priorities` are the ranked list (a `[[Wiki/Topics/…]]` link or plain words each). When there is no numbered line, or only the placeholder `(your first priority — …)`, ask exactly this and stop the turn: "Priorities.md is empty. What are your three priorities for the coming weeks, most important first? (a topic name or a few words each)". The plugin never writes `Priorities.md`: the answer is used for this run (step 4) and the report ends with the file's link and the ask to put the three lines there.

### 2. Which week

`week` = the argument as `YYYY-Www`, a date inside the week, `this`, or `next`. Default: the ISO week containing today; on a Friday, Saturday or Sunday, next week (say which was used). `today` = the date of `whoami.local_time`; days before it are never planned. Blocks go on Monday to Friday only.

### 3. Last week first

```
outlook_list_events(start="<last Monday>T00:00:00", end="<last Sunday>T23:59:59", include_recurrences=true, limit=200,
                    fields=["subject","start","end","all_day","attendee_count","is_meeting","occurrence_key","busy_status"], response_format="json")
vault_time_audit(week=<last ISO week>, events=<items[]>)
```

→ `{week, hours: {meeting, focus, admin, other, unplanned}, work_hours, shares, per_priority: [{name, planned_hours, held_hours}], blocks: {planned, held, moved, skipped, unanswered}, held_rows, lines}`. Show the three `lines` as they came, under "Last week:"; nothing else from the result. No blocks last week → the second line reads `Blocks: none planned this week.` and that is fine. `unanswered` above zero → one clause: "`/administrator:collect-information` asks about today's blocks each day".

### 4. Plan

```
outlook_list_events(start="<Monday>T00:00:00", end="<Sunday>T23:59:59", include_recurrences=true, limit=200,
                    fields=["subject","start","end","all_day","attendee_count","is_meeting","occurrence_key","entry_id","busy_status"], response_format="json")
vault_time_block_plan(week=<week>, events=<items[]>, today=<today>, now=<HH:MM>)   # now from whoami.local_time; today is planned from that time on
```

→ `{week, start, end, today, priorities: [{rank, name, page}], days: [{date, day, work_minutes, meeting_minutes, bookable_minutes, booked_minutes, slack_minutes, blocks: [{date, day, start, end, minutes, kind, subject, priority, page, existing}]}], totals: {focus_minutes, admin_minutes, new_blocks, existing_blocks, slack_share_kept}, unplaced: [{rank, name, page, reason}], skipped_days: [{date, reason}], preferences_used, missing_keys}`. Blocks with `existing: true` are already in Outlook (they carry `occurrence_key` and `entry_id`) and are never booked again. `priorities` are the numbered lines plus active wiki topics due within 30 days or with open items. Pass the events exactly as listed; the planner ignores all-day and free-marked events itself.

When the priorities came from the question in step 1, the file was empty and the plan's new focus blocks read `[Focus] Deep work`: give them the user's three in the planner's own order — rank 1 on the first, third, fifth… new focus block of the week, the other two in turn on the rest — as `[Focus] <priority>`, and set `priority` on those blocks to the same words. That is the one thing you change in the plan.

### 5. Show the week, ask once

One line per working day, in order, then the question — nothing else in that turn:

```
Mon 24 Aug — 10:15–11:45 [Focus] ACME supplier contract · 12:00–12:45 [Admin] · 14:15–15:45 [Focus] Q3 budget · 16:15–17:00 [Admin]  (meetings 1.5 h, free 2 h)
Wed 26 Aug — no blocks: meetings take 390 of 480 work minutes; the slack share of 0.2 leaves nothing to book
Thu 27 Aug — 09:00–10:30 [Focus] ACME supplier contract (already booked) · 10:30–12:00 [Focus] Offsite 2026 · 12:15–13:00 [Admin] · 16:15–17:00 [Admin]  (meetings 0.5 h, free 3 h)
```

`free` = `slack_minutes`; `(already booked)` marks `existing: true`; a `skipped_days` entry is its `reason`; `unplaced` and `missing_keys` get one line each when present ("Q3 budget got no block this week"; "`peak_hours` missing in Preferences.md, using 09:00-12:00"). Then exactly: "Book these N blocks? They are appointments without attendees — nothing is sent to anyone." with N = `totals.new_blocks`. N = 0 → say the week is planned already (or has no room) and stop; no question. "Drop Tuesday's second admin block" or a moved time → change that block, re-show, ask again; a yes covers only the list last shown.

### 6. Book

On a clear yes, one call per new block in date order, none for `existing: true`:

```
outlook_create_event(subject=<block.subject>, start=<block.start>, end=<block.end>,
                     show_as="busy", categories="Administrator", reminder_minutes=0,
                     body="Planned by administrator on <today> for <block.priority, or 'email and small tasks' on an admin block>")
```

No `attendees`, no `location`, no `is_online_meeting`, no `recurrence`. Result `{status, entry_id, global_id, occurrence_key, subject, start, end, show_as, categories, invite_sent}`; `invite_sent` is always false here. Keep `entry_id` and `occurrence_key` per block. `categories="Administrator"` is fixed by the plan — Outlook adds the name to the category list on first use — and it is how the blocks can be found and cleaned up in Outlook. A create that fails: say which block, leave it out of the note, carry on with the rest.

### 7. The plan note

```
vault_time_block_write(week=<week>, blocks=<every block of the shown plan; new ones with entry_id and occurrence_key from the create results merged in, existing ones as they came>, created_by="administrator/0.3.0")
```

→ `{path, action, week, blocks, planned}`. The note holds a `## Plan` table (one row per block, hidden `occurrence_key`), an empty `## Held` table that `/administrator:collect-information` fills day by day, and `## Notes`. `action: appended` = the week had a note; the new rows sit under `## Update`. Never `vault_write` this note yourself.

### 8. Report

Three or four lines: "Booked N blocks: focus <focus_minutes/60> h, admin <admin_minutes/60> h, at least <slack_share_kept as %> of each day left free" (plus existing blocks kept and days skipped); the note path and `obsidian://open?vault=<vault_name>&file=Administrator%2FTime-blocks%2F<week>`; the `Priorities.md` link with "put these three lines under ## Priorities" when step 1 asked; `Tokens this turn: <n>` when the host shows the count.

## Re-plan

The same run on a week that has blocks. The planner returns them as `existing` and fills only the gaps (a cancelled meeting frees a day; a day at `focus_blocks_per_day` and `admin_blocks_per_day` gets nothing). Nothing is deleted or moved by this skill: an unwanted block is deleted by the user in Outlook, and a struck line in step 5 stays free for this run. Every re-plan appends to the same `Time-blocks/<week>.md`.

## Rules

- `outlook_create_event` only after the exact question of step 5 got a clear yes, never with attendees from this skill. Never `outlook_delete_event`. `outlook_update_event` on a block is offered only by `/administrator:daily` when a meeting lands on it (no attendees, nothing sent).
- Subjects are exactly `[Focus] <priority>` and `[Admin] Email and small tasks`: `vault_time_audit`, `/administrator:daily`, `/administrator:collect-information` and `max_meetings_per_day` in `free` / `schedule` all key on the two prefixes.
- Never write `Preferences.md` or `Priorities.md`; never pass the events back with a value changed (times, keys and subjects come from Outlook).
- `fields=[...]` on every `outlook_list_events` call; `response_format="json"`; the same local ISO strings everywhere.
- One question per turn: the priorities question, the booking question, never both in one.
- Weeks are ISO weeks (Monday–Sunday); all-day events, free-marked events and weekends are the planner's to skip, not yours.
