---
description: Find a free time with the named people and, after you say yes, send the invite, write a meeting note, and add it to the daily note. Also moves one existing meeting, or drafts a "proposed times" email when someone's calendar is not visible.
argument-hint: "<people> [duration] [window] [subject]"
---

# /administrator:schedule

Arguments: `people` (required), `duration` (optional; default from `Preferences.md`), `window` (optional; default the next five working days), `subject` (optional; in quotes). Also accepts a move request in plain words: "move my 2pm with Sam to Thursday".

Argument given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `schedule` skill (and `skills/meetings/references/meeting-note.md` before writing a meeting note). Load the `outlook` skill if it is not already loaded.
2. Check `ADMINISTRATOR_VAULT` is set; create `Administrator/Meetings/` if missing. Read `Administrator/Preferences.md`; create it from the template in `references/preferences.md` if missing and say so.
3. If the request is a move ("move", "reschedule", "push … to"), go to step 10. Otherwise resolve names to SMTP addresses (`outlook_resolve_name`, then `outlook_search_contacts`, then ask), work out duration and window, and get candidates exactly as `/administrator:free` does (steps 3–7 of that command).
4. If anyone is `unknown` on every candidate (outside the organisation), say so and offer two paths: (a) book anyway and let them accept or decline, or (b) draft a "proposed times" email. Wait for the answer. For (b) go to step 9.
5. Pick the slot: the number or time the user names; candidate 1 if they said "just book it". Otherwise ask "Which one?" and wait.
6. Fill in subject (given, else "<topic> with <names>", else "<you> / <names>"), location (given, else `default_location`), attendees (the resolved addresses). Before asking, `outlook_list_events` for the chosen slot: if an event with the same subject and attendees already sits there, say so and stop.
7. Show subject, start–end in local time, the full attendee list with addresses, and location. Ask "Send this invite? Outlook sends it to everyone listed the moment it is created." Wait for a clear yes. If you filled in any field yourself, ask even when the user said "just book it".
8. On yes: `outlook_create_event(subject, start, end, attendees, location, is_online_meeting, body)`. Say "Sent. Invite went to <names>." Then, as the `schedule` skill describes: `outlook_get_event(entry_id, response_format="json")` for `global_id` and `occurrence_key`; Grep `Administrator/Meetings/` for the `occurrence_key`; find or create a person note per attendee; write `Meetings/<YYYY-MM-DD HHmm> <slug>.md` from the template in `skills/meetings/references/meeting-note.md` (or append an update if it exists); if `Daily/<date>.md` exists, add a row to its `## Calendar` table or an `## Update` line. Report the paths. Done.
9. Proposed-times draft: show To, Subject and the body with up to five times in local time. Ask "Save this as a draft in Outlook? Nothing is sent." On yes: `outlook_send_mail(to, subject, body, save_only=true)`, add a row to `Follow-ups.md` under `## Open`, and report "Draft saved in Drafts — open Outlook to send it." Never call `outlook_send_mail` with `save_only=false`. Done.
10. Move one meeting: `outlook_list_events` for the day named (default today), match by time and subject or attendee, ask if more than one matches. `outlook_get_event` for attendees and recurrence. Stop with a plain explanation if it is one occurrence of a series or if the user is not the organizer (offer a draft reply to the organizer instead). Find candidates in the new window for the same attendees and duration, let the user pick, then show From / To / attendees with the line "the meeting moves for everyone" and ask "Move it?". On a clear yes: `outlook_update_event(entry_id, start, end)`, which saves the move and sends the updated invite to the attendees (`update_sent: true`). Append an `## Update` to the meeting note if one exists (never rename it) and to the old day's daily note if one exists; add a row to the new day's daily note if one exists. Report. This command moves one meeting per request; it does not move a whole day.
