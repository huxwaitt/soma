# time-block — worked examples

Three runs, call by call. Tool results are cut to what the model reads. Times are local (UTC+02:00); the vault is `C:\Users\<you>\Documents\Vault` (`vault_name: Vault`); `outlook_whoami` gave `local_time: "2026-08-24T08:05:40+02:00"` (Monday). `Preferences.md` holds the defaults: work 09:00–17:00, buffer 15, `no_meeting_blocks: ["Fri 13:00-17:00"]`, `peak_hours: ["09:00-12:00"]`, focus 90 × 2, admin 45 × 2, `slack_share: 0.2`.

## Example 1 — planning this week on Monday morning

User: `/administrator:time-block`

1. `vault_read("Administrator/Priorities.md")` → body under `## Priorities`:

```
1. [[Wiki/Topics/acme-supplier-contract]]
2. [[Wiki/Topics/q3-budget]]
3. [[Wiki/Topics/offsite-2026]]
```

   Three numbered lines, so no question. Week: today is Monday 24 Aug → `2026-W35` (Mon 24 – Sun 30 Aug); last week `2026-W34`.

2. Last week:

```
outlook_list_events(start="2026-08-17T00:00:00", end="2026-08-23T23:59:59", include_recurrences=true, limit=200,
                    fields=["subject","start","end","all_day","attendee_count","is_meeting","occurrence_key","busy_status"], response_format="json")
```

   → 15 items (six `[Focus]` / `[Admin]` blocks, eight meetings, one all-day "Team day" marked free).

```
vault_time_audit(week="2026-W34", events=<items[]>)
```

```json
{"week": "2026-W34", "hours": {"meeting": 9.0, "focus": 3.0, "admin": 2.2, "other": 1.5, "unplanned": 24.2}, "work_hours": 40.0,
 "shares": {"meeting": 0.23, "focus": 0.07, "admin": 0.06, "other": 0.04, "unplanned": 0.61},
 "per_priority": [{"name": "ACME supplier contract", "planned_hours": 3.0, "held_hours": 3.0}, {"name": "Q3 budget", "planned_hours": 1.5, "held_hours": 0.0}],
 "blocks": {"planned": 6, "held": 3, "moved": 1, "skipped": 1, "unanswered": 1}, "held_rows": 5,
 "lines": ["Meetings 9 h (23%), focus 3 h (7%), admin 2.2 h (6%), other 1.5 h (4%), unplanned 24.2 h (61%) of 40 work hours.",
           "Blocks: 6 planned — 3 held, 1 moved, 1 skipped, 1 unanswered.",
           "Focus: ACME supplier contract 3 h planned, 3 h held; Q3 budget 1.5 h planned, 0 h held."]}
```

3. This week:

```
outlook_list_events(start="2026-08-24T00:00:00", end="2026-08-30T23:59:59", include_recurrences=true, limit=200,
                    fields=["subject","start","end","all_day","attendee_count","is_meeting","occurrence_key","entry_id","busy_status"], response_format="json")
```

   → 10 items: Mon Stand-up 09:30–10:00 (4 attendees) and Budget review with Jane 13:00–14:00 (2); Tue Weekly supplier sync 10:00–11:00 (3) and 1:1 with Priya 15:00–15:30 (1); Wed Offsite planning workshop 09:00–12:00 (6), Vendor demo 13:00–15:00 (5), Leadership sync 15:30–17:00 (7); Thu `[Focus] ACME supplier contract` 09:00–10:30 (0 attendees, `entry_id: "000000000400C2709"`, `occurrence_key: "0400C|2026-08-27T09:00:00+02:00"`) and Dentist 14:00–14:30 (0); Fri Stand-up 11:00–11:30 (4).

```
vault_time_block_plan(week="2026-W35", events=<items[]>, today="2026-08-24", now="08:40")
```

```json
{"week": "2026-W35", "start": "2026-08-24", "end": "2026-08-30", "today": "2026-08-24",
 "priorities": [{"rank": 1, "name": "ACME supplier contract", "page": "[[Wiki/Topics/acme-supplier-contract]]"},
                {"rank": 2, "name": "Q3 budget", "page": "[[Wiki/Topics/q3-budget]]"},
                {"rank": 3, "name": "Offsite 2026", "page": "[[Wiki/Topics/offsite-2026]]"}],
 "days": [
  {"date": "2026-08-24", "day": "Mon 24 Aug", "work_minutes": 480, "meeting_minutes": 90, "bookable_minutes": 294, "booked_minutes": 270, "slack_minutes": 120,
   "blocks": [
    {"start": "2026-08-24T10:15:00", "end": "2026-08-24T11:45:00", "minutes": 90, "kind": "focus", "subject": "[Focus] ACME supplier contract", "priority": "ACME supplier contract", "page": "[[Wiki/Topics/acme-supplier-contract]]", "existing": false},
    {"start": "2026-08-24T12:00:00", "end": "2026-08-24T12:45:00", "minutes": 45, "kind": "admin", "subject": "[Admin] Email and small tasks", "priority": null, "page": null, "existing": false},
    {"start": "2026-08-24T14:15:00", "end": "2026-08-24T15:45:00", "minutes": 90, "kind": "focus", "subject": "[Focus] Q3 budget", "priority": "Q3 budget", "page": "[[Wiki/Topics/q3-budget]]", "existing": false},
    {"start": "2026-08-24T16:15:00", "end": "2026-08-24T17:00:00", "minutes": 45, "kind": "admin", "subject": "[Admin] Email and small tasks", "priority": null, "page": null, "existing": false}]},
  {"date": "2026-08-25", "day": "Tue 25 Aug", "work_minutes": 480, "meeting_minutes": 90, "bookable_minutes": 294, "booked_minutes": 180, "slack_minutes": 210,
   "blocks": [
    {"start": "2026-08-25T12:00:00", "end": "2026-08-25T13:30:00", "minutes": 90, "kind": "focus", "subject": "[Focus] ACME supplier contract", "priority": "ACME supplier contract", "existing": false},
    {"start": "2026-08-25T13:30:00", "end": "2026-08-25T14:15:00", "minutes": 45, "kind": "admin", "subject": "[Admin] Email and small tasks", "priority": null, "existing": false},
    {"start": "2026-08-25T16:15:00", "end": "2026-08-25T17:00:00", "minutes": 45, "kind": "admin", "subject": "[Admin] Email and small tasks", "priority": null, "existing": false}]},
  {"date": "2026-08-27", "day": "Thu 27 Aug", "work_minutes": 480, "meeting_minutes": 30, "bookable_minutes": 354, "booked_minutes": 270, "slack_minutes": 180,
   "blocks": [
    {"start": "2026-08-27T09:00:00", "end": "2026-08-27T10:30:00", "minutes": 90, "kind": "focus", "subject": "[Focus] ACME supplier contract", "priority": "ACME supplier contract", "page": null, "existing": true, "occurrence_key": "0400C|2026-08-27T09:00:00+02:00", "entry_id": "000000000400C2709"},
    {"start": "2026-08-27T10:30:00", "end": "2026-08-27T12:00:00", "minutes": 90, "kind": "focus", "subject": "[Focus] Offsite 2026", "priority": "Offsite 2026", "page": "[[Wiki/Topics/offsite-2026]]", "existing": false},
    {"start": "2026-08-27T12:15:00", "end": "2026-08-27T13:00:00", "minutes": 45, "kind": "admin", "subject": "[Admin] Email and small tasks", "priority": null, "existing": false},
    {"start": "2026-08-27T16:15:00", "end": "2026-08-27T17:00:00", "minutes": 45, "kind": "admin", "subject": "[Admin] Email and small tasks", "priority": null, "existing": false}]},
  {"date": "2026-08-28", "day": "Fri 28 Aug", "work_minutes": 480, "meeting_minutes": 30, "bookable_minutes": 354, "booked_minutes": 135, "slack_minutes": 315,
   "blocks": [
    {"start": "2026-08-28T09:00:00", "end": "2026-08-28T10:30:00", "minutes": 90, "kind": "focus", "subject": "[Focus] ACME supplier contract", "priority": "ACME supplier contract", "existing": false},
    {"start": "2026-08-28T12:15:00", "end": "2026-08-28T13:00:00", "minutes": 45, "kind": "admin", "subject": "[Admin] Email and small tasks", "priority": null, "existing": false}]}],
 "totals": {"focus_minutes": 540, "admin_minutes": 315, "new_blocks": 12, "existing_blocks": 1, "slack_share_kept": 0.25},
 "unplaced": [],
 "skipped_days": [{"date": "2026-08-26", "reason": "meetings take 390 of 480 work minutes; the slack share of 0.2 leaves nothing to book", "meeting_minutes": 390, "existing": []}],
 "preferences_used": {"work_start": "09:00", "work_end": "17:00", "buffer_minutes": 15, "no_meeting_blocks": ["Fri 13:00-17:00"], "peak_hours": ["09:00-12:00"], "focus_block_minutes": 90, "focus_blocks_per_day": 2, "admin_blocks_per_day": 2, "admin_block_minutes": 45, "slack_share": 0.2},
 "missing_keys": []}
```

   Reading it: Monday's Stand-up plus its 15-minute buffers cuts the peak hours to 10:15–12:00, so the first focus block starts 10:15; the second lands outside the peak at 14:15. Tuesday's sync splits the morning into two pieces under 90 minutes, so the focus block goes to 12:00 and one admin block sits right after it, the other at the end of the day. Wednesday has 390 meeting minutes against 384 bookable, so it is skipped with the reason. Thursday keeps the block that already exists and adds a second focus block for rank 3 (rank 1 took blocks 1, 3 and 5; rank 2 block 2; rank 3 block 4 — the existing block does not count). Friday afternoon is a no-meeting block, so only the morning is used.

4. Shown, then the question, nothing else:

```
Last week: Meetings 9 h (23%), focus 3 h (7%), admin 2.2 h (6%), other 1.5 h (4%), unplanned 24.2 h (61%) of 40 work hours.
Blocks: 6 planned — 3 held, 1 moved, 1 skipped, 1 unanswered.
Focus: ACME supplier contract 3 h planned, 3 h held; Q3 budget 1.5 h planned, 0 h held.

This week (2026-W35):
Mon 24 Aug — 10:15–11:45 [Focus] ACME supplier contract · 12:00–12:45 [Admin] · 14:15–15:45 [Focus] Q3 budget · 16:15–17:00 [Admin]  (meetings 1.5 h, free 2 h)
Tue 25 Aug — 12:00–13:30 [Focus] ACME supplier contract · 13:30–14:15 [Admin] · 16:15–17:00 [Admin]  (meetings 1.5 h, free 3.5 h)
Wed 26 Aug — no blocks: meetings take 390 of 480 work minutes; the slack share of 0.2 leaves nothing to book
Thu 27 Aug — 09:00–10:30 [Focus] ACME supplier contract (already booked) · 10:30–12:00 [Focus] Offsite 2026 · 12:15–13:00 [Admin] · 16:15–17:00 [Admin]  (meetings 0.5 h, free 3 h)
Fri 28 Aug — 09:00–10:30 [Focus] ACME supplier contract · 12:15–13:00 [Admin]  (meetings 0.5 h, free 5.25 h; afternoon is a no-meeting block)

Book these 12 blocks? They are appointments without attendees — nothing is sent to anyone.
```

   User: "yes".

5. Twelve creates, date order; the first:

```
outlook_create_event(subject="[Focus] ACME supplier contract", start="2026-08-24T10:15:00", end="2026-08-24T11:45:00",
                     show_as="busy", categories="Administrator", reminder_minutes=0,
                     body="Planned by administrator on 2026-08-24 for ACME supplier contract")
```

```json
{"status": "created", "entry_id": "00000000D01…", "global_id": "0400D01…", "occurrence_key": "0400D01…|2026-08-24T10:15:00+02:00",
 "subject": "[Focus] ACME supplier contract", "start": "2026-08-24T10:15:00+02:00", "end": "2026-08-24T11:45:00+02:00",
 "show_as": "busy", "categories": "Administrator", "invite_sent": false}
```

   The admin blocks get `body="Planned by administrator on 2026-08-24 for email and small tasks"`. Thursday's existing block is not created again.

6. The note — all 13 blocks, the 12 new ones with their `entry_id` and `occurrence_key` merged in:

```
vault_time_block_write(week="2026-W35", blocks=[...13 blocks...], created_by="administrator/0.3.0")
```

   → `{"path": "Administrator/Time-blocks/2026-W35.md", "action": "created", "week": "2026-W35", "blocks": 13, "planned": 13}`. The note (the model never types it):

```markdown
---
type: time-block
source: administrator
week: 2026-W35
start: "2026-08-24"
end: "2026-08-30"
planned: 13
created_by: administrator/0.3.0
---

# Time blocks — 2026-W35

Week of Mon 24 Aug to Sun 30 Aug. Planned by /administrator:time-block; the appointments live in Outlook, this note keeps the plan and how it went.

## Plan

| Day | Start | End | Kind | Subject | Priority |
| --- | --- | --- | --- | --- | --- |
| Mon 24 Aug | 10:15 | 11:45 | focus | [Focus] ACME supplier contract | ACME supplier contract <!-- occurrence_key: 0400D01…\|2026-08-24T10:15:00+02:00 # plan --> |
| Mon 24 Aug | 12:00 | 12:45 | admin | [Admin] Email and small tasks | — <!-- occurrence_key: 0400D02…\|2026-08-24T12:00:00+02:00 # plan --> |
| … | | | | | |
| Thu 27 Aug | 09:00 | 10:30 | focus | [Focus] ACME supplier contract | ACME supplier contract <!-- occurrence_key: 0400C\|2026-08-27T09:00:00+02:00 # plan --> |
| … | | | | | |

## Held

| Day | Block | Result | Note |
| --- | --- | --- | --- |

## Notes
```

7. Report:

> Booked 12 blocks for 2026-W35: focus 9 h, admin 5.25 h, at least 25 % of each day left free; Thursday's existing block kept; Wednesday skipped (meetings 6.5 h).
> Last week: 6 blocks planned — 3 held, 1 moved, 1 skipped, 1 unanswered; ACME contract 3 h held, Q3 budget 0 h.
> Written: Administrator/Time-blocks/2026-W35.md (created). Open: obsidian://open?vault=Vault&file=Administrator%2FTime-blocks%2F2026-W35
> Tokens this turn: 9.8k

## Example 2 — re-plan on Tuesday after a cancellation

Tuesday 25 Aug, 08:10. The vendor demo on Wednesday was cancelled. User: `/administrator:time-block` (same week: Tuesday → `2026-W35`).

1. `Priorities.md` unchanged. Last week's audit is the same three lines as above (shown again).
2. `outlook_list_events(...)` for 24–30 Aug now returns 21 items: the 9 meetings and the Dentist, plus the 12 blocks booked on Monday (0 attendees, `busy_status: "busy"`, `categories: "Administrator"`) — Vendor demo gone.

```
vault_time_block_plan(week="2026-W35", events=<items[]>, today="2026-08-25", now="08:50")
```

```json
{"week": "2026-W35", "today": "2026-08-25",
 "days": [
  {"date": "2026-08-25", "day": "Tue 25 Aug", "meeting_minutes": 90, "bookable_minutes": 294, "booked_minutes": 180, "slack_minutes": 210,
   "blocks": [{"start": "2026-08-25T12:00:00", "end": "2026-08-25T13:30:00", "kind": "focus", "subject": "[Focus] ACME supplier contract", "priority": "ACME supplier contract", "existing": true, "occurrence_key": "0400D05…|2026-08-25T12:00:00+02:00", "entry_id": "00000000D05…"},
              {"start": "2026-08-25T13:30:00", "end": "2026-08-25T14:15:00", "kind": "admin", "subject": "[Admin] Email and small tasks", "existing": true, "…": "…"},
              {"start": "2026-08-25T16:15:00", "end": "2026-08-25T17:00:00", "kind": "admin", "subject": "[Admin] Email and small tasks", "existing": true, "…": "…"}]},
  {"date": "2026-08-26", "day": "Wed 26 Aug", "meeting_minutes": 270, "bookable_minutes": 114, "booked_minutes": 90, "slack_minutes": 120,
   "blocks": [{"start": "2026-08-26T12:15:00", "end": "2026-08-26T13:45:00", "minutes": 90, "kind": "focus", "subject": "[Focus] ACME supplier contract", "priority": "ACME supplier contract", "page": "[[Wiki/Topics/acme-supplier-contract]]", "existing": false}]},
  {"date": "2026-08-27", "day": "Thu 27 Aug", "blocks": ["…4 existing blocks…"]},
  {"date": "2026-08-28", "day": "Fri 28 Aug", "blocks": ["…2 existing blocks…"]}],
 "totals": {"focus_minutes": 450, "admin_minutes": 225, "new_blocks": 1, "existing_blocks": 9, "slack_share_kept": 0.25},
 "unplaced": [{"rank": 2, "name": "Q3 budget", "page": "[[Wiki/Topics/q3-budget]]", "reason": "no focus block left this week"}],
 "skipped_days": [{"date": "2026-08-24", "reason": "already past"}], "missing_keys": []}
```

   Monday is past (its blocks are not in `days`, so "Q3 budget" counts as unplaced from today on); Wednesday now has 114 bookable minutes — one focus block fits, at 12:15 after the workshop's buffer, and no admin block (24 minutes left). Everything else is `existing`.

3. Shown:

```
Tue 25 Aug — 12:00–13:30 [Focus] ACME supplier contract (already booked) · 13:30–14:15 [Admin] (already booked) · 16:15–17:00 [Admin] (already booked)
Wed 26 Aug — 12:15–13:45 [Focus] ACME supplier contract  (meetings 4.5 h, free 2 h)
Thu 27 Aug — 4 blocks already booked
Fri 28 Aug — 2 blocks already booked
Q3 budget gets no new block from today on (Monday's block was held).

Book these 1 blocks? They are appointments without attendees — nothing is sent to anyone.
```

   User: "yes" → one `outlook_create_event(subject="[Focus] ACME supplier contract", start="2026-08-26T12:15:00", end="2026-08-26T13:45:00", show_as="busy", categories="Administrator", reminder_minutes=0, body="Planned by administrator on 2026-08-25 for ACME supplier contract")` → `occurrence_key: "0400E01…|2026-08-26T12:15:00+02:00"`.

4. `vault_time_block_write(week="2026-W35", blocks=[<the one new block with its keys>], created_by="administrator/0.3.0")` → `{"path": "Administrator/Time-blocks/2026-W35.md", "action": "appended", "week": "2026-W35", "blocks": 1, "planned": 14}`. The note gains:

```markdown
## Update 2026-08-25T08:11:02+02:00

### Plan

| Day | Start | End | Kind | Subject | Priority |
| --- | --- | --- | --- | --- | --- |
| Wed 26 Aug | 12:15 | 13:45 | focus | [Focus] ACME supplier contract | ACME supplier contract <!-- occurrence_key: 0400E01…\|2026-08-26T12:15:00+02:00 # plan --> |
```

5. Report: "Added 1 block on Wednesday (vendor demo cancelled); 9 existing blocks kept, nothing deleted. Written: Administrator/Time-blocks/2026-W35.md (appended)." plus the link. Had the user said "no Wednesday, leave it free", nothing would be created or written.

## Example 3 — the audit inside `/administrator:weekly`

Saturday 22 Aug, `/administrator:weekly` for `2026-W34`. Next to `vault_weekly_facts` and next week's calendar, the `review` skill makes one more read for the review week itself:

```
outlook_list_events(start="2026-08-17T00:00:00", end="2026-08-23T23:59:59", include_recurrences=true, limit=200,
                    fields=["subject","start","end","all_day","attendee_count","is_meeting","occurrence_key","busy_status"], response_format="json")
vault_time_audit(week="2026-W34", events=<items[]>)
```

The result is the one in example 1 step 2: `/administrator:collect-information` had answered five of the six blocks in the note's `## Held` table (Mon focus held, Mon admin held, Tue focus skipped "urgent ACME call", Tue admin moved "done 17:30", Thu focus held; Thu admin never answered). The skipped block's 90 minutes count as unplanned; the moved block keeps its 45. The weekly note gets, between `## People going quiet` and `## Wiki`:

```markdown
## Time

- Meetings 9 h (23%), focus 3 h (7%), admin 2.2 h (6%), other 1.5 h (4%), unplanned 24.2 h (61%) of 40 work hours.
- Blocks: 6 planned — 3 held, 1 moved, 1 skipped, 1 unanswered.
- Focus: ACME supplier contract 3 h planned, 3 h held; Q3 budget 1.5 h planned, 0 h held.
```

A week without a `Time-blocks/` note still gets the section: line 1 from the calendar alone and `Blocks: none planned this week.` The report's line for it: "Time: meetings 9 h, focus 3 h of 4.5 h planned, unplanned 24.2 h."
