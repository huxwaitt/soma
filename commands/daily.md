---
description: Build today's daily note from the inbox and today's calendar, pointing out clashes and meetings with no prep note.
argument-hint: "[date]"
---

# /administrator:daily

Argument (optional): `date` as `YYYY-MM-DD`. Default: today in the user's local timezone.

Argument given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `inbox` skill. Load the `outlook` skill if it is not already loaded.
2. Check `ADMINISTRATOR_VAULT` is set; create `Administrator/Daily/` if missing.
3. Run the inbox workflow exactly as `/administrator:inbox` does (steps 3 to 5 of that command), writing to `Administrator/Daily/<date>.md`. Skip the batch-action offer for now; collect it for step 7.
4. Call `outlook_list_events(start="<date>T00:00:00", end="<date>T23:59:59", include_recurrences=true, limit=50, response_format="json")`.
5. Add a `## Calendar` section to the same daily note, laid out as in the daily note template in `administrator/references/vault.md`: a table with start, end, subject, location, organizer (all-day events show `all day`). Below it, a `## Watch out` list with:
   - clashes (events whose time ranges overlap),
   - meetings with no prep note: no file in `Administrator/Emails/` or `Administrator/Daily/` mentions the event subject (case-insensitive substring match) and the event is not all-day.
   Append as a `## Update <ISO timestamp>` section if the note already had a calendar section.
6. Show the user a short brief: inbox counts, action list, agenda, and the watch-out items.
7. Offer the batch Outlook changes from the inbox workflow as a numbered list with counts and subjects. Run nothing until the user gives an explicit yes to a specific option. Nothing in this command creates, updates, or responds to calendar events.
