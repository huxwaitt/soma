---
description: Write a prep brief into a meeting note for today's meetings (or one meeting named by date or words) — previous occurrence, carried-over action items, attendee person notes, the last related email threads, open follow-ups. Read-only in Outlook.
argument-hint: "[date | event words]"
---

# /administrator:prep

Argument (optional): a date (`2026-08-25`, `tomorrow`, `Monday`) for all meetings that day, or words that match one event (`supplier sync`, `jane`, `1pm`). Nothing → today.

Argument given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `meetings` skill and its `references/meeting-note.md`. Load the `outlook` skill if it is not already loaded.
2. Call `vault_status` if not done yet this session; if `administrator_dir_exists` or any folder or file flag is false, call `vault_init(created_by="administrator/0.0.4")`. Call `outlook_whoami` once for the user's own address.
3. Find the events: `outlook_list_events(start=<day 00:00>, end=<day 23:59:59>, include_recurrences=true, response_format="json")`. With words, list today plus the next 7 days and match against subject, attendee names, location and start time; one hit → take it, several → show a numbered list and ask, none → say so and stop. Skip all-day and `Canceled:` events unless named.
4. For each event, in this order, as the `meetings` skill describes:
   - `vault_find("meeting", {"occurrence_key": <key>, "global_id": <id>})`. Found → the note exists (it may have been written by `/administrator:schedule`); everything below is written with `vault_write(..., mode="append")` as a body of `### Prep` with what is new (plus `### Related emails` for new thread lines), and the report says "existing note found" with the path. Not found → `vault_find("meeting", {"global_id": <id>})`; the newest match whose Update section says it was moved to this start is a moved meeting (treat as existing); earlier matches are previous occurrences — the most recent one becomes the previous meeting and its unchecked action items (read with `vault_read`) are carried over.
   - Find or create a person note for the organizer and every attendee except the user: `vault_find("person", {"email": <smtp>})` (it also matches `aliases`, so nobody gets two notes); `vault_write("person", …, mode="create")` for a stub with `last_contact: ""`, else `mode="append"` with the `## Meetings` line as the body.
   - Pull the last 5 related threads from the last 30 days (`outlook_search_mails` on subject words, `outlook_list_mails(from_address=<attendee>)`, a Sent search per name; dedupe by `internet_message_id` and stripped subject); `outlook_get_conversation` for the top 2; `vault_find("email", …)` to link existing `Emails/` notes.
   - `vault_read("Administrator/Follow-ups.md")` and copy the `## Open` rows whose `Who` is an attendee.
   - `vault_write("meeting", frontmatter, body, mode="upsert")`: frontmatter (`global_id`, `occurrence_key`, `subject`, `start`, `end`, `location`, `organizer`, `organizer_link`, `attendees`, `attendee_links`, `is_recurring`, `status: upcoming`, `created_by: administrator/0.0.4`), body from the template: header lines, `## Prep` with Previous meeting / Carried over / People / Open follow-ups with them / Recent threads / Suggested points, then empty `## Notes`, `## Action items`, `## Waiting on`, and `## Related emails` with the thread links. The server names the file `Meetings/YYYY-MM-DD HHmm <slug>.md`.
5. Report one or two lines per event (path, new or existing, carried-over count, threads, follow-ups) with `obsidian://open?vault=<vault_name>&file=<url-encoded path>`, and the suggested points for the next meeting. Do not call any Outlook tool that changes anything; prep is read-only.

## Example

```
/administrator:prep
/administrator:prep tomorrow
/administrator:prep supplier sync
```

`/administrator:prep supplier sync` on 2026-08-25 finds "Weekly supplier sync" at 13:00, finds no note for its `occurrence_key` but one for the same `global_id` dated 2026-08-18, writes `Meetings/2026-08-25 1300 Weekly supplier sync.md` with two carried-over items, three threads and one open follow-up, creates `People/Tom Lee.md`, and reports:

> Prep written: `Meetings/2026-08-25 1300 Weekly supplier sync.md` (previous: 2026-08-18, 2 items carried over, 3 threads, 1 open follow-up). New person note `People/Tom Lee.md`.
> obsidian://open?vault=Vault&file=Administrator%2FMeetings%2F2026-08-25%201300%20Weekly%20supplier%20sync.md
> Points: sign the contract or say what blocks it; answer Tom on the 8 Sep delivery; packaging spec; Leipzig address.

Running it again appends `## Update 2026-08-25T…` with "Nothing new since the last prep." and reports "existing note found". The full worked example is in `skills/meetings/SKILL.md`.
