---
description: Show up to five times when the named people and you are all free, using your scheduling preferences. Read-only — books nothing, sends nothing.
argument-hint: "<people> [duration] [window]"
---

# /administrator:free

Arguments: `people` (required; names or addresses, separated by commas or "and"), `duration` (optional; "30 min", "1 h"; default from `Preferences.md`), `window` (optional; "today", "tomorrow", "this week", "next week", a weekday, a date or date range, with "morning" / "afternoon"; default the next five working days).

Argument given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `schedule` skill. Load the `outlook` skill if it is not already loaded.
2. Check `ADMINISTRATOR_VAULT` is set. Read `Administrator/Preferences.md`; if it is missing, create it from the template in the `schedule` skill's `references/preferences.md` and say so.
3. Turn each name into an SMTP address: `outlook_resolve_name`, then `outlook_search_contacts(include_directory=true, limit=5)`, then ask the user. Never guess an address. Say which address each name became.
4. Work out `duration_minutes` and the `start` / `end` window as the `schedule` skill describes.
5. Call `outlook_find_meeting_times(addresses, start, end, duration_minutes, work_start, work_end, buffer_minutes, weekdays_only=true, include_self=true, max_results=15)` with the values from `Preferences.md`. Then drop candidates inside `no_meeting_blocks`, drop days at `max_meetings_per_day` (one `outlook_list_events` per day), put `preferred_days` first, keep five.
6. Show the candidates in local time with who is free and who is unknown. If someone is `unknown` on every candidate, say plainly that their calendar is not visible (outside the organisation) and that the times only account for the others; offer to draft an email proposing times instead.
7. If there are no candidates, say which preference or window removed them and offer a wider window, a shorter duration, or skipping one preference for this request.
8. Stop. This command writes no notes, creates no events and saves no drafts. If the user then says "book 2", run `/administrator:schedule` from step 5 of that command with the chosen candidate.
