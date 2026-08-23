# Preferences reference — `<vault>/Administrator/Preferences.md`

One file holds the user's scheduling preferences. The `schedule` skill reads it (`vault_read("Administrator/Preferences.md")`) once per session — again only when the user says they changed it — and applies it on top of what Outlook returns. The user edits it by hand in Obsidian; `vault_init` creates it when it is missing (`/administrator:setup` asks for work hours first, every other command uses the defaults below) and only `vault_init(overwrite=true)` ever rewrites it.

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
created_by: administrator/0.1.0
---

# Scheduling preferences

Edit the frontmatter above. The plugin reads it before suggesting or booking any meeting. Plain words on what each key does:

- `work_start` / `work_end` — the only hours a slot may be suggested in. 24-hour `"HH:MM"`, quoted.
- `timezone` — a note to yourself; the plugin always works in the local time Outlook reports. Change your Windows timezone, not this line, if you travel.
- `buffer_minutes` — free minutes the plugin keeps before and after every existing meeting. `0` switches it off.
- `no_meeting_blocks` — weekday plus a time range, one per line, that are never offered: `"Fri 13:00-17:30"`, `"Mon 09:00-10:00"`. Weekday names: Mon Tue Wed Thu Fri Sat Sun. An empty list `[]` means none.
- `max_meetings_per_day` — days that already have this many meetings are skipped. `0` means no limit.
- `default_duration` — minutes, used when you do not say how long.
- `default_location` — used when you do not say where. `"Teams"`, a room name, or `""` for none.
- `preferred_days` — days listed here are shown first when there is a choice. An empty list `[]` means no preference.

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
