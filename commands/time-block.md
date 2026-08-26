---
description: Plan the week's focus and admin blocks around your meetings and book them in your own Outlook calendar as appointments without attendees — nothing is sent to anyone. Shows how last week went against your priorities first, asks once before booking, writes Soma/Time-blocks/YYYY-Www.md. A re-plan adds blocks where room opened up and never deletes one.
argument-hint: "[week | this | next | suggest priorities]"
---

# /soma:time-block

Argument (optional): `week` as `YYYY-Www` (ISO week, Monday–Sunday), a date inside the week, `this`, or `next`. Default: the week containing today; on a Friday, Saturday or Sunday, next week. `suggest priorities` (or "what should I focus on") asks for a new list first (step 3).

Argument given: `$ARGUMENTS`

## Steps

1. Load the `soma` skill, then the `time-block` skill and its `skills/time-block/references/examples.md` (the first time this session). Load the `outlook` skill if it is not already loaded. `skills/time-block/references/method.md` only when the user asks why a block sits where it does or wants to change a preference.
2. Once per session: `vault_status` (if `soma_dir_exists` or any folder or file flag is false, `vault_init(created_by="soma/0.4.2")` and mention `/soma:setup`) and `outlook_whoami(response_format="json")` — the date of `local_time` is `today`.
3. `vault_read("Soma/Preferences.md")` once per session (skip when already read this session) and `vault_read("Soma/Priorities.md")` once. No numbered line under `## Priorities`, or only the placeholder, or the user asked for a suggestion → `vault_priorities_write(action="candidates")` (writes nothing) → propose 3–5 ranked priorities as a numbered list with one short reason each (due dates, open items, the oldest follow-ups, unfinished weekly items), ask exactly "Use these as your priorities? (reorder, drop or add lines, or say yes)" and stop the turn. On a yes, or the edited list: `vault_priorities_write(action="write", lines=[...], created_by="soma/0.4.2")`, then carry on in the same turn; a "no" leaves the file alone. The plugin writes `Priorities.md` only with lines you confirmed; edit it in Obsidian any time.
4. Work out the target ISO week (Monday–Sunday) and last week's.
5. **Last week.** `outlook_list_events(start="<last Monday>T00:00:00", end="<last Sunday>T23:59:59", include_recurrences=true, limit=200, fields=["subject","start","end","all_day","attendee_count","is_meeting","occurrence_key","busy_status"], response_format="json")`, then `vault_time_block(action="audit", week=<last week>, events=<items[]>)`. Show its three `lines` as they came, under "Last week:".
6. **Plan.** `outlook_list_events(start="<Monday>T00:00:00", end="<Sunday>T23:59:59", include_recurrences=true, limit=200, fields=["subject","start","end","all_day","attendee_count","is_meeting","occurrence_key","entry_id","busy_status"], response_format="json")`, then `vault_time_block(action="plan", week=<week>, events=<items[]>, today=<today>, now=<HH:MM from whoami.local_time>)`. Blocks with `existing: true` are already in Outlook and are never booked again. `missing_keys` naming `peak_hours` (a vault from before 0.3.0) → do not use the default silently: ask exactly "When are you sharpest? (focus blocks go there first; e.g. 09:00–12:00)" and stop the turn (once per session; only when `missing_keys` names it), then run `vault_time_block(action="plan", ..., peak_hours=[<the answer as "HH:MM-HH:MM">])` again for this run — the file is not changed.
7. **Show the week.** One line per working day: `Mon 24 Aug — 10:15–11:45 [Focus] ACME supplier contract · 12:00–12:45 [Admin] · … (meetings 1.5 h, free 2 h)`; `(already booked)` after an existing block; a skipped day shows its `reason`; one line for `deadlines` when it is not empty ("Due this week: <name> (<due>) → <the day of its block, or the `unplaced` reason when `block_date` is null>"); one line each for `unplaced` and `missing_keys` when present. Then exactly: "Book these N blocks? They are appointments without attendees — nothing is sent to anyone." (N = `totals.new_blocks`). Nothing else in that turn. N = 0 → say the week is planned or has no room, and stop. A struck or moved block → change it, re-show, ask again.
8. **Book.** Only on a clear yes: one `outlook_create_event(subject=<block.subject>, start=<block.start>, end=<block.end>, show_as="busy", categories="Soma", reminder_minutes=0, body="Planned by soma on <today> for <priority, or 'email and small tasks'>")` per new block, in date order — no attendees, no location. Keep `entry_id` and `occurrence_key` from each result (`invite_sent` is always false). A failed create: say which block and carry on.
9. **Note.** `vault_time_block(action="write", week=<week>, blocks=<every block of the plan, the new ones with entry_id and occurrence_key merged in>, created_by="soma/0.4.2")` → `{path, action, week, blocks, planned}`. `appended` = the week's note existed; the new rows sit under `## Update`. No `vault_write` for this note.
10. **Re-plan.** The same steps on a week that has blocks: the planner keeps them as `existing` and fills only gaps. Nothing is deleted or moved here — an unwanted block is deleted in Outlook by the user; `/soma:daily` offers to move a block when a meeting lands on it.
11. **Report.** Three or four lines: blocks booked with focus and admin hours and the slack share kept (`totals.slack_share_kept`), existing blocks kept and days skipped; last week in one line; the note path with `action` and `obsidian://open?vault=<vault_name>&file=Soma%2FTime-blocks%2F<week>`; when step 3 wrote `Priorities.md`, `obsidian://open?vault=<vault_name>&file=Soma%2FPriorities.md` (edit it in Obsidian any time); when step 6 asked for peak hours, `obsidian://open?vault=<vault_name>&file=Soma%2FPreferences.md` with "put `peak_hours: ["HH:MM-HH:MM"]` in the file".
12. If the host shows the token count of this turn, add it as the last line; otherwise say nothing about it. (This command writes no daily note, so there is no `vault_write_daily(tokens_used=…)` call here.)

## Example

```
/soma:time-block
/soma:time-block next
/soma:time-block 2026-W36
```

> Last week: Meetings 9 h (23%), focus 3 h (7%), admin 2.2 h (6%), other 1.5 h (4%), unplanned 24.2 h (61%) of 40 work hours. Blocks: 6 planned — 3 held, 1 moved, 1 skipped, 1 unanswered. Focus: ACME supplier contract 3 h planned, 3 h held; Q3 budget 1.5 h planned, 0 h held.
> Mon 24 Aug — 10:15–11:45 [Focus] ACME supplier contract · 12:00–12:45 [Admin] · 14:15–15:45 [Focus] Q3 budget · 16:15–17:00 [Admin]  (meetings 1.5 h, free 2 h)
> Tue 25 Aug — 12:00–13:30 [Focus] ACME supplier contract · 13:30–14:15 [Admin] · 16:15–17:00 [Admin]  (meetings 1.5 h, free 3.5 h)
> Wed 26 Aug — no blocks: meetings take 390 of 480 work minutes; the slack share of 0.2 leaves nothing to book
> Thu 27 Aug — 09:00–10:30 [Focus] ACME supplier contract (already booked) · 10:30–12:00 [Focus] Offsite 2026 · 12:15–13:00 [Admin] · 16:15–17:00 [Admin]  (meetings 0.5 h, free 3 h)
> Fri 28 Aug — 09:00–10:30 [Focus] ACME supplier contract · 12:15–13:00 [Admin]  (meetings 0.5 h, free 5.25 h)
> Book these 12 blocks? They are appointments without attendees — nothing is sent to anyone.

After "yes":

> Booked 12 blocks for 2026-W35: focus 9 h, admin 5.25 h, at least 25 % of each day left free; Thursday's existing block kept; Wednesday skipped.
> Written: Soma/Time-blocks/2026-W35.md (created). Open: obsidian://open?vault=Vault&file=Soma%2FTime-blocks%2F2026-W35

The full runs (a plan, a re-plan after a cancellation, the audit in `weekly`) are in `skills/time-block/references/examples.md`.
