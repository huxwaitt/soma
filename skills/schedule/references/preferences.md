# Preferences reference — `<vault>/Administrator/Preferences.md`

One file holds the user's scheduling preferences. The `schedule` skill reads it (`vault_read("Administrator/Preferences.md")`) once per session — again only when the user says they changed it — and applies it on top of what Outlook returns. The `time-block` skill's planner (`vault_time_block_plan`) and `/administrator:collect-information` (`vault_changed_notes`) read the same file inside the vault server. The user edits it by hand in Obsidian; `vault_init` creates it when it is missing (`/administrator:setup` asks for work hours first, every other command uses the defaults below) and only `vault_init(overwrite=true)` ever rewrites it.

## Template (what `vault_init` writes with the defaults)

```markdown
---
type: preferences
source: administrator
work_start: "09:00"
work_end: "17:00"
timezone: "local — the timezone Outlook reports in outlook_whoami; all times in this file are in it"
buffer_minutes: 15
no_meeting_blocks:
  - "Fri 13:00-17:00"
max_meetings_per_day: 5
default_duration: 30
default_location: "Teams"
preferred_days:
  - Tue
  - Wed
  - Thu
peak_hours:
  - "09:00-12:00"
focus_block_minutes: 90
focus_blocks_per_day: 2
admin_blocks_per_day: 2
admin_block_minutes: 45
slack_share: 0.2
collect_folders: []
created_by: administrator/0.4.0
---

# Scheduling preferences

Edit the frontmatter above. The plugin reads it before suggesting or booking any meeting and before planning focus and admin blocks. Plain words on what each key does:

- `work_start` / `work_end` — the only hours a slot may be suggested in. 24-hour `"HH:MM"`, quoted.
- `timezone` — a note to yourself; the plugin always works in the local time Outlook reports. Change your Windows timezone, not this line, if you travel.
- `buffer_minutes` — free minutes the plugin keeps before and after every existing meeting. `0` switches it off.
- `no_meeting_blocks` — weekday plus a time range, one per line, that are never offered: `"Fri 13:00-17:30"`, `"Mon 09:00-10:00"`. Weekday names: Mon Tue Wed Thu Fri Sat Sun. An empty list `[]` means none.
- `max_meetings_per_day` — days that already have this many meetings are skipped. `0` means no limit.
- `default_duration` — minutes, used when you do not say how long.
- `default_location` — used when you do not say where. `"Teams"`, a room name, or `""` for none.
- `preferred_days` — days listed here are shown first when there is a choice. An empty list `[]` means no preference.
- `peak_hours` — the hours you think best, as ranges `"09:00-12:00"`, one per line; focus blocks are placed there first. `/administrator:setup` asks for them together with the work hours; a file from before 0.3.0 has no such key, and `/administrator:time-block` then asks once per session and uses the answer for that run only.
- `focus_block_minutes` — length of one focus block; nothing shorter is booked.
- `focus_blocks_per_day` — how many focus blocks a day may get at most.
- `admin_blocks_per_day` — how many admin blocks (email and small tasks) a day may get at most.
- `admin_block_minutes` — length of one admin block.
- `slack_share` — the share of the work day left unbooked for what comes up: `0.2` keeps a fifth free. Days where meetings already eat past this share get no blocks.
- `collect_folders` — extra folders /administrator:collect-information reads for changed notes, as paths relative to the vault root (`"Projects"`, `"Journal/2026"`). They are only read, never written. An empty list `[]` means only the Administrator/ notes.

## Notes

Anything you write below this line is yours; the plugin never touches it.
```

## Rules

- File path is fixed: `<vault>/Administrator/Preferences.md`. Identity is the path; there is never a second file.
- Created by `vault_init` (work hours and buffer from its arguments; `/administrator:setup` asks for them once, other commands pass the defaults 09:00–17:00, 15). Report "Created Administrator/Preferences.md with defaults — edit it any time, or run /administrator:setup to set your work hours." once, then carry on.
- Never rewritten, never appended by the plugin (only `vault_init(overwrite=true)`, on the user's explicit request). The user owns it. If a key is missing, malformed, or the frontmatter cannot be parsed, use the default from the template for that key, and say so in one line ("`work_end` missing in Preferences.md, using 17:00"). Do not fix the file.
- Times are `"HH:MM"` strings, always quoted in YAML so `09:00` is not read as a number.
- `no_meeting_blocks` entries are `<Day> <HH:MM>-<HH:MM>`. An entry that does not match that shape is ignored with a one-line warning naming it.
- `preferred_days` and the day part of `no_meeting_blocks` use three-letter English names. Anything else is ignored with a warning.

## How each key is applied

`outlook_find_meeting_times` only knows `work_start`, `work_end`, `buffer_minutes`, and `weekdays_only`. Pass those straight in. The other keys are applied by the skill after the call:

| Key | Where it is applied | How |
| --- | --- | --- |
| `work_start`, `work_end` | `outlook_find_meeting_times(work_start=…, work_end=…)` | Passed verbatim. |
| `buffer_minutes` | `outlook_find_meeting_times(buffer_minutes=…)` | Passed verbatim. |
| `no_meeting_blocks` | After the call | Drop every candidate that overlaps a block on that weekday, even by one minute. |
| `max_meetings_per_day` | After the call | For each day that still has candidates, `outlook_list_events(start=<day 00:00>, end=<day 23:59:59>, include_recurrences=true, response_format="json")` on the user's calendar; count non-all-day events; if the count is at or above the limit, drop that day's candidates. One `list_events` call per day, at most 10 days. |
| `default_duration` | Before the call | `duration_minutes` when the user gave none. |
| `default_location` | At booking | `location` for `outlook_create_event` when the user gave none. |
| `preferred_days` | Ordering | Candidates on a preferred day first (earliest first inside each group), then the rest, earliest first. With an empty list, plain earliest-first. |
| `peak_hours` | `vault_time_block_plan` (in the server) | Each range is parsed as `HH:MM-HH:MM`; a focus block goes into the largest free piece inside a range first, outside only when none fits. |
| `focus_block_minutes` | `vault_time_block_plan` | Length of every new focus block; a free piece shorter than this gets none. An existing `[Focus]` appointment of any length is kept and counted. |
| `focus_blocks_per_day` | `vault_time_block_plan` | Cap per working day, existing `[Focus]` appointments included. |
| `admin_blocks_per_day` | `vault_time_block_plan` | Cap per working day, existing `[Admin]` appointments included; the first ends at or before 13:00, the second at the end of the day when there is room. |
| `admin_block_minutes` | `vault_time_block_plan` | Length of every new admin block. |
| `slack_share` | `vault_time_block_plan` | Bookable minutes = (1 − `slack_share`) × work minutes − meeting minutes; nothing is booked on a day where that is 0 or less (`skipped_days` names the reason). `work_start`, `work_end`, `buffer_minutes` and `no_meeting_blocks` are applied by the planner the same way `free` applies them. |
| `collect_folders` | `vault_changed_notes` (in the server) | Extra vault-relative folders scanned for changed notes; read only. |

`max_meetings_per_day` counts non-all-day events whose subject does not start with `[Focus]` or `[Admin]` — the user's own time blocks never fill a day for the meeting limit.

Weekends: always `weekdays_only=true` unless the user explicitly names a weekend day or says "including weekends".

## Worked example

Preferences (user changed two keys from the defaults):

```yaml
work_start: "08:30"
work_end: "17:00"
buffer_minutes: 10
no_meeting_blocks:
  - "Fri 12:00-17:00"
  - "Wed 08:30-09:30"
max_meetings_per_day: 4
default_duration: 45
default_location: "Room 2.14"
preferred_days:
  - Tue
  - Thu
```

Request: "when are Sam and I both free next week" (no duration given → 45 minutes).

`outlook_find_meeting_times(addresses=["sam.ortiz@example.com"], start="2026-08-24T00:00:00", end="2026-08-28T23:59:59", duration_minutes=45, work_start="08:30", work_end="17:00", buffer_minutes=10, weekdays_only=true, include_self=true, max_results=15)` returns 9 candidates. Then:

1. `no_meeting_blocks`: a Wed 08:30 candidate and two Fri afternoon candidates are dropped → 6 left.
2. `max_meetings_per_day`: `list_events` for Mon shows 4 meetings → Monday's candidate dropped → 5 left.
3. `preferred_days`: Tue and Thu candidates listed first.

Shown to the user (up to 5):

```
1. Tue 25 Aug 10:00–10:45  — Sam free, you free
2. Tue 25 Aug 14:30–15:15  — Sam free, you free
3. Thu 27 Aug 09:00–09:45  — Sam free, you free
4. Wed 26 Aug 11:00–11:45  — Sam free, you free
5. Wed 26 Aug 15:00–15:45  — Sam free, you free
```
