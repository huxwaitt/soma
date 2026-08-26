---
description: Show up to five times when the named people and you are all free, using your scheduling preferences. Read-only — books nothing, sends nothing.
argument-hint: "<people> [duration] [window]"
---

# /soma:free

Arguments: `people` (required; names or addresses, separated by commas or "and"), `duration` (optional; "30 min", "1 h"; default from `Preferences.md`), `window` (optional; "today", "tomorrow", "this week", "next week", a weekday, a date or date range, with "morning" / "afternoon"; default the next five working days).

Argument given: `$ARGUMENTS`

## Steps

1. Load the `soma` skill, then the `schedule` skill. Load the `outlook` skill if it is not already loaded. Load `skills/schedule/references/examples.md` only if a step is unclear.
2. Once per session: `vault_status` (if `files["Preferences.md"]` or anything else is false, `vault_init(created_by="soma/0.4.1")` creates it with defaults — say so and mention `/soma:setup` for other work hours), `outlook_whoami(response_format="json")`, and `vault_read("Soma/Preferences.md")`. Do not read the preferences again in this session unless the user says they changed them.
3. Turn each name into an SMTP address: `outlook_resolve_name`, then `outlook_search_contacts(include_directory=true, limit=5)`, then ask the user. Never guess an address. Say which address each name became.
4. Work out `duration_minutes` and the `start` / `end` window as the `schedule` skill describes.
5. One call: `outlook_find_meeting_times(addresses, start, end, duration_minutes, work_start, work_end, buffer_minutes, weekdays_only=true, include_self=true, max_results=15)` with the values from `Preferences.md`; leave `include_slots` false. Then drop candidates inside `no_meeting_blocks`, drop days at `max_meetings_per_day` (one `outlook_list_events(..., fields=["entry_id","subject","start","end","all_day"], response_format="json")` per day that still has candidates, at most 10; events whose subject starts with `[Focus]` or `[Admin]` are the user's own time blocks and do not count towards the limit), put `preferred_days` first, keep five.
6. Show the candidates in local time with who is free and who is unknown. If someone is `unknown` on every candidate, say plainly that their calendar is not visible (outside the organisation) and that the times only account for the others; offer to draft an email proposing times instead.
7. No candidates: say which preference or window removed them and offer a wider window, a shorter duration, or skipping one preference for this request.
8. Only if the user asks why someone is busy: `outlook_get_free_busy(addresses=[<that address>], start=<day 00:00>, end=<day 23:59:59>)` and read `people[].busy_blocks[]`; `busy_blocks_only` stays true.
9. Stop. This command writes no notes, creates no events and saves no drafts. If the user then says "book 2", run `/soma:schedule` from step 5 of that command with the chosen candidate.
10. If the host exposes the token count of this turn, end with one line `Tokens this turn: <n>`; otherwise add nothing. This command never calls `vault_write_daily`, so there is no `tokens_used` to pass.
