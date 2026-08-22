---
description: Write a prep brief into a meeting note for today's meetings (or one meeting named by date or words) — previous occurrence, carried-over action items, attendee person notes, the last related email threads, open follow-ups. Read-only in Outlook.
argument-hint: "[date | event words]"
---

# /administrator:prep

Argument (optional): a date (`2026-08-25`, `tomorrow`, `Monday`) for all meetings that day, or words that match one event (`supplier sync`, `jane`, `1pm`). Nothing → today.

Argument given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `meetings` skill and its `references/meeting-note.md`. Load the `outlook` skill if it is not already loaded.
2. Check `ADMINISTRATOR_VAULT` is set; create `Administrator/Meetings/` and `Administrator/People/` if missing. Call `outlook_whoami` once for the user's own address.
3. Find the events: `outlook_list_events(start=<day 00:00>, end=<day 23:59:59>, include_recurrences=true, response_format="json")`. With words, list today plus the next 7 days and match against subject, attendee names, location and start time; one hit → take it, several → show a numbered list and ask, none → say so and stop. Skip all-day and `Canceled:` events unless named.
4. For each event, in this order, as the `meetings` skill describes:
   - Grep `Administrator/Meetings/` frontmatter for `occurrence_key: "<key>"`. Found → the note exists (it may have been written by `/administrator:schedule`); everything below is appended as `## Update <ISO>` with a `### Prep` of what is new, and the report says "existing note found" with the path. Not found → grep for `global_id: "<id>"`; a hit with the same `start` date but a different key is a moved meeting (treat as existing); earlier hits are previous occurrences — the most recent one becomes the previous meeting and its unchecked action items are carried over.
   - Find or create `People/<Display Name>.md` for the organizer and every attendee except the user (grep `email:` / `aliases:` first so nobody gets two notes; stubs get `last_contact: ""`); add a `## Meetings` line.
   - Pull the last 5 related threads from the last 30 days (`outlook_search_mails` on subject words, `outlook_list_mails(from_address=<attendee>)`, a Sent search per name; dedupe by `internet_message_id` and stripped subject); `outlook_get_conversation` for the top 2; link existing `Emails/` notes.
   - Copy `Follow-ups.md` `## Open` rows whose `Who` is an attendee.
   - Write `Meetings/YYYY-MM-DD HHmm <slug>.md` from the template: frontmatter (`global_id`, `occurrence_key`, `subject`, `start`, `end`, `location`, `organizer`, `organizer_link`, `attendees`, `attendee_links`, `is_recurring`, `status: upcoming`, `created_by: administrator/0.0.3`), header lines, `## Prep` with Previous meeting / Carried over / People / Open follow-ups with them / Recent threads / Suggested points, then empty `## Notes`, `## Action items`, `## Waiting on`, and `## Related emails` with the thread links.
5. Report one or two lines per event (path, new or existing, carried-over count, threads, follow-ups) and the suggested points for the next meeting. Do not call any Outlook tool that changes anything; prep is read-only.

## Example

```
/administrator:prep
/administrator:prep tomorrow
/administrator:prep supplier sync
```

`/administrator:prep supplier sync` on 2026-08-25 finds "Weekly supplier sync" at 13:00, finds no note for its `occurrence_key` but one for the same `global_id` dated 2026-08-18, writes `Meetings/2026-08-25 1300 Weekly supplier sync.md` with two carried-over items, three threads and one open follow-up, creates `People/Tom Lee.md`, and reports:

> Prep written: `Meetings/2026-08-25 1300 Weekly supplier sync.md` (previous: 2026-08-18, 2 items carried over, 3 threads, 1 open follow-up). New person note `People/Tom Lee.md`.
> Points: sign the contract or say what blocks it; answer Tom on the 8 Sep delivery; packaging spec; Leipzig address.

Running it again appends `## Update 2026-08-25T…` with "Nothing new since the last prep." and reports "existing note found". The full worked example is in `skills/meetings/SKILL.md`.
