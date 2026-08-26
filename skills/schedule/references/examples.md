# schedule — worked examples

Three runs of the `schedule` skill with every call and result. Load this when a step in `SKILL.md` is unclear; it adds nothing the skill does not already say. Session setup (`vault_status`, `outlook_whoami`, one `vault_read("Administrator/Preferences.md")`) happened before each example; the preferences are the template defaults (09:00–17:00, buffer 15, `Fri 13:00-17:00` blocked, max 5 per day, preferred Tue Wed Thu, default 30 min, Teams). The user is `hux@example.com`, today is Sat 2026-08-22.

## Example 1 — `/administrator:free Sam 30 min next week`

1. `outlook_resolve_name(name="Sam")` → `resolved: true`, `smtp_address: "sam.ortiz@example.com"`.
2. "next week" → `start="2026-08-24T00:00:00"`, `end="2026-08-28T23:59:59"`; duration 30.
3. `outlook_find_meeting_times(addresses=["sam.ortiz@example.com"], start=…, end=…, duration_minutes=30, work_start="09:00", work_end="17:00", buffer_minutes=15, weekdays_only=true, include_self=true, max_results=15)` → 11 `items`, `unknown: []`. No `people[]` block — `include_slots` was left false.
4. Filters: two Friday-afternoon candidates dropped (no-meeting block). Four days keep candidates → four `outlook_list_events(start="2026-08-24T00:00:00", end="2026-08-24T23:59:59", include_recurrences=true, fields=["entry_id","subject","start","end","all_day"], response_format="json")` calls; Monday has 5 non-all-day events → dropped. Tue/Wed/Thu first, earliest first, five kept.

Reply:

> Sam → sam.ortiz@example.com. Free for 30 min next week:
> 1. Tue 25 Aug 10:00–10:30 — Sam free, you free
> 2. Tue 25 Aug 14:30–15:00 — Sam free, you free
> 3. Wed 26 Aug 11:00–11:30 — Sam free, you free
> 4. Thu 27 Aug 09:00–09:30 — Sam free, you free
> 5. Thu 27 Aug 16:00–16:30 — Sam free, you free
>
> (Monday skipped: already 5 meetings. Friday afternoon skipped: your no-meeting block.) Say a number to book one.

Nothing written, nothing sent. Had the user then asked "why is Sam busy Tuesday morning?": `outlook_get_free_busy(addresses=["sam.ortiz@example.com"], start="2026-08-25T00:00:00", end="2026-08-25T23:59:59")` → `people[0].busy_blocks` = `[{start: "…T09:00:00+02:00", end: "…T10:00:00+02:00"}, …]` → "Sam is busy 09:00–10:00 and 11:00–12:30." `slots[]` is not returned and not needed.

## Example 2 — `/administrator:schedule Sam, Jane Doe 30 min next week "Budget review"`

Names: Sam as above; `outlook_resolve_name(name="Jane Doe")` → `resolved: false`; `outlook_search_contacts(query="Jane Doe", include_directory=true, limit=5)` → one hit `jane.doe@acme-parts.com`, company ACME Parts GmbH. `find_meeting_times` with both addresses → candidates with `unknown: ["jane.doe@acme-parts.com"]` on every one.

Reply:

> Sam → sam.ortiz@example.com, Jane Doe → jane.doe@acme-parts.com (ACME Parts GmbH).
> No calendar visible for jane.doe@acme-parts.com — she is outside your organisation, so the times below only account for you and Sam.
> 1. Tue 25 Aug 10:00–10:30 — Sam free, you free, Jane unknown
> 2. Tue 25 Aug 14:30–15:00 — Sam free, you free, Jane unknown
> 3. Wed 26 Aug 11:00–11:30 — Sam free, you free, Jane unknown
>
> Two ways forward: (a) book one and let Jane accept or decline, or (b) I draft an email to Jane proposing these times and you send it. Which?

User: "a, 1". `outlook_list_events` for Tue 25 Aug with the same `fields` → nothing with that subject and those attendees at 10:00. Then:

> Subject:   Budget review
> When:      Tue 25 Aug 2026 10:00–10:30 (your local time)
> Attendees: Sam Ortiz <sam.ortiz@example.com>, Jane Doe <jane.doe@acme-parts.com>
> Location:  Teams (online meeting)
>
> Send this invite? Outlook sends it to both the moment it is created.

User: "yes". `outlook_create_event(subject="Budget review", start="2026-08-25T10:00:00", end="2026-08-25T10:30:00", attendees=["sam.ortiz@example.com","jane.doe@acme-parts.com"], location="Teams", is_online_meeting=true, body="Booked by administrator on 2026-08-22")` → `{"status":"created","entry_id":"00000000C1…","global_id":"040000008200E0…","occurrence_key":"040000008200E0…|2026-08-25T10:00:00+02:00","subject":"Budget review","start":"2026-08-25T10:00:00+02:00","end":"2026-08-25T10:30:00+02:00","invite_sent":true}`. `global_id` is there, so no `outlook_get_event`.

Person notes: `vault_find("person", {"email": "jane.doe@acme-parts.com"})` → found (from an earlier save) → `vault_write("person", <frontmatter as found>, "- 2026-08-25 — [[Meetings/2026-08-25 1000 Budget review]]", mode="append")`. `vault_find("person", {"email": "sam.ortiz@example.com"})` → not found → `vault_write("person", {type: person, name: "Sam Ortiz", email: "sam.ortiz@example.com", last_contact: "", aliases: [], created_by: "administrator/0.4.0"}, "- 2026-08-25 — [[Meetings/2026-08-25 1000 Budget review]]", mode="create")` (the server writes the `draft` wiki page with that line under `## Records`).

Meeting note — frontmatter passed as an object (the server quotes what needs quoting):

```yaml
type: meeting
source: outlook
entry_id: 00000000C1…
global_id: 040000008200E0…
occurrence_key: 040000008200E0…|2026-08-25T10:00:00+02:00
subject: Budget review
start: 2026-08-25T10:00:00+02:00
end: 2026-08-25T10:30:00+02:00
location: Teams
organizer: hux@example.com
organizer_link: ""
attendees:
  - sam.ortiz@example.com
  - jane.doe@acme-parts.com
attendee_links:
  - "[[Wiki/People/Sam Ortiz]]"
  - "[[Wiki/People/Jane Doe]]"
is_recurring: false
status: upcoming
created_by: administrator/0.4.0
```

Body:

```markdown
# Budget review

**When:** 2026-08-25 10:00–10:30
**Where:** Teams
**Organizer:** me <hux@example.com>
**Attendees:** [[Wiki/People/Sam Ortiz]] (required, no reply), [[Wiki/People/Jane Doe]] (required, no reply)

## Prep

_(booked by /administrator:schedule on 2026-08-22; no prep was run)_

## Notes

_(none yet)_

## Action items

- none

## Waiting on

- none

## Related emails

- none
```

`vault_write("meeting", frontmatter, body, mode="upsert")` → `{"path": "Administrator/Meetings/2026-08-25 1000 Budget review.md", "action": "created"}`. `vault_find("daily", {"date": "2026-08-25"})` → not found → nothing added.

Report:

> Sent. Invite went to Sam Ortiz and Jane Doe. Note: `Meetings/2026-08-25 1000 Budget review.md`; new person note `Wiki/People/Sam Ortiz.md`.
> obsidian://open?vault=Vault&file=Administrator%2FMeetings%2F2026-08-25%201000%20Budget%20review.md

Had the user answered "b":

```
To:      jane.doe@acme-parts.com
Subject: Proposed times — Budget review
Body:
  Hi Jane,

  would one of these work for a 30-minute call on the Q3 budget? Times are CEST.

  - Tue 25 Aug, 10:00–10:30
  - Tue 25 Aug, 14:30–15:00
  - Wed 26 Aug, 11:00–11:30

  Let me know which suits and I will send the invite.

  Best regards
  Hux

Save this as a draft in Outlook? Nothing is sent; you send it from Drafts.
```

A yes → `outlook_send_mail(to=["jane.doe@acme-parts.com"], subject="Proposed times — Budget review", body=…, save_only=true)`, then `vault_append_row("Administrator/Follow-ups.md", "Open", ["2026-08-22", "[[Wiki/People/Jane Doe]]", "pick a time — Budget review", "", "2026-08-22"], dedupe_key="jane.doe@acme-parts.com # pick a time — Budget review", key_label="proposal")` (the comment reads `<!-- proposal: … -->`), and the report "Draft saved in Drafts — open Outlook to send it. Added a follow-up for Jane." No event, no meeting note.

## Example 3 — "move my 2pm with Sam to Thursday"

1. `outlook_list_events(start="2026-08-25T00:00:00", end="2026-08-25T23:59:59", include_recurrences=true, fields=["entry_id","subject","start","end","organizer_address","attendees","is_recurring"], response_format="json")` → one event at 14:00 whose attendees include Sam: `Budget review with Sam`, `entry_id "00000000C2…"`, `organizer_address: "hux@example.com"`, `is_recurring: false`. `global_id` is not in the filtered item → `outlook_get_event(entry_id="00000000C2…", fields=["global_id","recurrence_state"], response_format="json")` → `global_id "0400…"`, `recurrence_state: "not_recurring"`.
2. Window "Thursday" → Thu 27 Aug 00:00–23:59:59, duration 30 (from the event). `find_meeting_times(addresses=["sam.ortiz@example.com"], …)` → 4 candidates after filters.
3. User: "the 9 o'clock one".

> Move:      Budget review with Sam
> From:      Tue 25 Aug 14:00–14:30
> To:        Thu 27 Aug 09:00–09:30 (your local time)
> Attendees: Sam Ortiz <sam.ortiz@example.com> — the meeting moves for everyone and each attendee gets an updated invite.
>
> Move it?

4. "yes" → `outlook_update_event(entry_id="00000000C2…", start="2026-08-27T09:00:00", end="2026-08-27T09:30:00")` → `{"status":"updated","entry_id":"00000000C2…","update_sent":true}`.
5. `vault_find("meeting", {"global_id": "0400…"})` → `Administrator/Meetings/2026-08-25 1400 Budget review with Sam.md` → `vault_write("meeting", <frontmatter as found>, "- Moved from 2026-08-25 14:00 to 2026-08-27 09:00 (attendee: Sam Ortiz; new occurrence_key: 0400…|2026-08-27T09:00:00+02:00)", mode="append")`, which lands as:

```markdown
## Update 2026-08-22T16:10:00+02:00

- Moved from 2026-08-25 14:00 to 2026-08-27 09:00 (attendee: Sam Ortiz; new occurrence_key: 0400…|2026-08-27T09:00:00+02:00)
```

`vault_find("daily", {"date": "2026-08-25"})` → found → `vault_write("daily", <frontmatter as found>, "- Moved: Budget review with Sam → Thu 27 Aug 09:00", mode="append")`. `vault_find("daily", {"date": "2026-08-27"})` → not found → nothing.

Report:

> Moved to Thu 27 Aug 09:00–09:30; Sam Ortiz has been sent the updated invite. Appended the move to `Meetings/2026-08-25 1400 Budget review with Sam.md`.
> obsidian://open?vault=Vault&file=Administrator%2FMeetings%2F2026-08-25%201400%20Budget%20review%20with%20Sam.md

## Preferences applied, with changed values

Preferences (user changed two keys from the defaults: `buffer_minutes: 10`, `max_meetings_per_day: 4`, `no_meeting_blocks: ["Fri 12:00-17:00", "Wed 08:30-09:30"]`, `default_duration: 45`, `preferred_days: [Tue, Thu]`). Request: "when are Sam and I both free next week" → 45 minutes. `find_meeting_times(…, buffer_minutes=10, …)` → 9 candidates. A Wed 08:30 and two Fri afternoon candidates dropped (blocks) → 6; Monday's `list_events` shows 4 meetings → Monday dropped → 5; Tue and Thu listed first, then Wed. Full key table: `references/preferences.md`.
