---
name: schedule
description: Find when people are free and book meetings from classic Outlook — resolve names to addresses, read free/busy through outlook_get_free_busy and outlook_find_meeting_times, apply the user's preferences from Administrator/Preferences.md (working hours, buffers, no-meeting blocks, daily limit), show up to five candidate times, and on an explicit yes create the invite with outlook_create_event, write the meeting note, and add the meeting to the daily note; also move one existing meeting to a new time with outlook_update_event, and write a "proposed times" draft email when someone is outside the tenant. Trigger when the user says "/administrator:free", "/administrator:schedule", "when are X and I both free", "find a time with", "set up 30 min with", "book a meeting with", "schedule a call with Sam", "move my 2pm with Sam to Thursday", "reschedule the budget review". Reads are free; outlook_create_event, outlook_update_event and outlook_send_mail(save_only=true) each need an explicit yes first. Never sends a plain email, never deletes events, never moves more than one meeting per request.
---

# schedule — who is free, then book it

This skill answers "when can we meet" and, if asked, books the meeting. It uses the two scheduling tools in the Outlook server (`outlook_get_free_busy`, `outlook_find_meeting_times`), the user's own preferences from `<vault>/Administrator/Preferences.md`, and the existing calendar, contact and mail tools. Outlook mechanics follow the `outlook` skill; note layout follows `skills/administrator/references/vault.md` and, for the meeting note, `skills/meetings/references/meeting-note.md`; preferences follow `references/preferences.md` in this folder. Do not duplicate them — read them when unsure.

Vault root: the `ADMINISTRATOR_VAULT` environment variable (absolute path). If it is unset, stop and tell the user to set it; do not guess a path.

Three things leave the machine in this skill, and each needs its own yes after you have shown exactly what will happen:

- `outlook_create_event` with attendees — Outlook sends the invite to every attendee the moment the call returns. There is no draft step.
- `outlook_update_event` on a meeting that has attendees — the meeting changes for everyone. The server saves the change and sends the updated invite to every attendee in the same call (`update_sent: true`); there is no way to take it back.
- `outlook_send_mail(save_only=true)` — writes a draft to the Drafts folder. Nothing is sent, but it is still a change in Outlook.

Never call `outlook_send_mail` without `save_only=true`, never call `outlook_delete_event`, `outlook_respond_event`, `outlook_reply_mail` or `outlook_forward_mail` from this skill.

## Steps

### 1. Read the preferences

Read `<vault>/Administrator/Preferences.md`. If it does not exist, create it from the template in `references/preferences.md` exactly, say "Created Administrator/Preferences.md with defaults — edit it any time", and continue. Parse the frontmatter keys `work_start`, `work_end`, `buffer_minutes`, `no_meeting_blocks`, `max_meetings_per_day`, `default_duration`, `default_location`, `preferred_days`. A missing or unreadable key falls back to the template default for that key; say which one in a single line. Never edit the file.

Call `outlook_whoami` once per session for the user's own SMTP address and `utc_offset`. All times shown to the user are local time, the way Outlook returns them. Never convert.

### 2. Work out who, how long, when

**Who.** Split the people part of the request on commas, "and", "&". For each name:

1. If it already looks like an SMTP address (`@` with no spaces), use it as is.
2. `outlook_resolve_name(name=<name>)`. If `resolved` is true, use `smtp_address`.
3. Otherwise `outlook_search_contacts(query=<name>, include_directory=true, limit=5)`. One hit with an `email` → use it and say which ("Sam → sam.ortiz@example.com"). Two to five hits → show a numbered list (name, email, company) and ask the user to pick. No hit → ask the user for the address. Never guess an address and never build one from a name plus a domain.
4. If `People/<name>.md` exists in the vault and has an `email:` key, you may use that when steps 2 and 3 fail, and say the address came from the vault.

The user's own address is never in `addresses`; `include_self=true` adds it on the server side.

**How long.** A number followed by `min`, `minutes`, `h`, `hour(s)` in the request → `duration_minutes`. "Half an hour" = 30, "an hour" = 60. Nothing given → `default_duration` from the preferences.

**When.** Turn the window into `start` and `end` as local ISO strings, no offset:

| The user says | `start` | `end` |
| --- | --- | --- |
| nothing | now rounded up to the next half hour | end of the fifth working day from today (23:59:59) |
| "today" | now rounded up | today 23:59:59 |
| "tomorrow" | tomorrow 00:00:00 | tomorrow 23:59:59 |
| "this week" | now rounded up | this Friday 23:59:59 |
| "next week" | next Monday 00:00:00 | next Friday 23:59:59 |
| a weekday name ("Thursday") | the next such day 00:00:00 | same day 23:59:59 |
| a date or date range | that day 00:00:00 | that (or the last) day 23:59:59 |
| "morning" / "afternoon" added to any of the above | clamp to `work_start`–12:00 / 12:00–`work_end` inside the day | |

If the window ends before it starts (a weekday name that already passed today and the user clearly meant this week), say so and ask.

### 3. Find candidate times

Call once:

```
outlook_find_meeting_times(
  addresses=[<smtp>, ...],
  start=<start>, end=<end>,
  duration_minutes=<minutes>,
  work_start=<pref>, work_end=<pref>,
  buffer_minutes=<pref>,
  weekdays_only=true,            # false only if the user named a weekend day or said "including weekends"
  include_self=true,
  max_results=15)
```

The result is `{start, end, duration_minutes, addresses, unknown, count, items[]}`; each item (a candidate) is `{start, end, free: [addresses], unknown: [addresses]}`. Then apply the preferences the server does not know about, in this order (full rules in `references/preferences.md`): drop candidates inside a `no_meeting_blocks` range, drop days that already hold `max_meetings_per_day` meetings (one `outlook_list_events` per day, at most 10 days), sort `preferred_days` first then earliest first. Keep the first five.

Zero candidates after filtering: say so, name the filter that removed the most (for example "all Tuesday slots fall in your Fri 13:00 block" or "both days are at your 5-meeting limit"), and offer one of: a wider window, a shorter duration, or ignoring one preference for this request. Do not silently relax a preference.

**People outside the tenant.** If any address appears in `unknown` on every candidate, Outlook has no free/busy for them (another company, a private address, a distribution list). Say it plainly, once, before the list: "No calendar visible for jane@acme-parts.com — the times below only account for the others." For `/administrator:free` also suggest: "If you want, I can draft an email proposing these times to her." For `/administrator:schedule` see step 6.

### 4. Show the candidates

Up to five lines, local time, weekday and date, then who is free and who is unknown:

```
1. Tue 25 Aug 10:00–10:30  — Sam free, you free
2. Tue 25 Aug 14:30–15:00  — Sam free, you free
3. Thu 27 Aug 09:00–09:30  — Sam free, you free, Jane unknown
```

For `/administrator:free` stop here. It is read-only: no note, no event, no draft. If the user then says "book 2", continue with step 5 as if `/administrator:schedule` had been run.

### 5. Pick a slot, then ask before booking

- The user names a number or a time → that candidate. The user said "just book it", "book the first one", "whatever works" → candidate 1. Anything else → ask "Which one?" and wait.
- Subject: the one the user gave; else `<Topic> with <First names>` if a topic is obvious from the request ("budget review with Sam"); else `<Your first name> / <Their first names>`. Say which you chose.
- Location: the one the user gave, else `default_location`, else none. "Teams", "online", "call" → also `is_online_meeting=true`.
- Attendees: the resolved SMTP addresses. Include unknown-calendar people too if the user wants them invited.

Show exactly this, then ask, then wait:

```
Subject:   Budget review with Sam
When:      Tue 25 Aug 2026 10:00–10:30 (your local time)
Attendees: Sam Ortiz <sam.ortiz@example.com>
Location:  Teams (online meeting)

Send this invite? Outlook sends it to everyone listed the moment it is created.
```

A yes must be a clear yes ("yes", "go ahead", "send it", "book it"). "Just book it" said earlier in the same request counts as the yes for candidate 1 only if the subject, attendees and location were all given by the user; if you filled any of them in, still ask. Silence, "ok?", or a change of topic is not a yes. A yes covers only the summary shown; if anything changes, show it again and ask again.

On yes: `outlook_create_event(subject=…, start=<candidate start>, end=<candidate end>, attendees=[…], location=…, is_online_meeting=…, body=<one line: "Booked by administrator on <date>" plus the user's agenda text if they gave any>)`. The result is `{status: "created", entry_id, global_id, occurrence_key, subject, start, end, invite_sent}` — use `global_id`/`occurrence_key` directly in step 7 (call `outlook_get_event` only if `global_id` came back empty). Tell the user: "Sent. Invite went to Sam Ortiz." Do not say "created" without "sent" — the invite is already in their inbox.

### 6. When someone is outside the tenant (`/administrator:schedule` only)

If at least one attendee is `unknown`, offer two paths before step 5's summary, and wait for the choice:

1. **Book anyway** — "I cannot see Jane's calendar. Book the slot and let her accept or decline?" → step 5 as usual, with Jane in the attendee list.
2. **Propose times by email** — write a draft to Drafts, nothing sent. Show it first:

```
To:      jane.doe@acme-parts.com
Subject: Proposed times — Budget review
Body:
  Hi Jane,

  would one of these work for a 30-minute call on the Q3 budget? Times are CEST.

  - Tue 25 Aug, 10:00–10:30
  - Tue 25 Aug, 14:30–15:00
  - Thu 27 Aug, 09:00–09:30

  Let me know which suits and I will send the invite.

  Best regards
  <user's first name>

Save this as a draft in Outlook? Nothing is sent; you send it from Drafts.
```

On yes: `outlook_send_mail(to=[…], subject=…, body=…, save_only=true)`. Report "Draft saved in Drafts — open Outlook to send it." Then add one row to `Follow-ups.md` under `## Open` (`Who` = the person, `What` = "pick a time — <subject>", `Email` empty, `Last checked` = today with no entry_id comment), so the `inbox` workflow keeps an eye on the reply. Do not write a meeting note; there is no meeting yet.

Never send the proposal with `save_only=false`, even if the user says "send it" — say the plugin writes drafts only and they send from Outlook.

### 7. Meeting note (after a successful create)

Load `skills/meetings/references/meeting-note.md` and write the meeting note from its template — the same note `/administrator:prep` would write, so `prep` and `notes` find it later. Path: `<vault>/Administrator/Meetings/<YYYY-MM-DD HHmm> <slug>.md`, date and `HHmm` from the event `start` (local, as returned), slug by the vault slug rule applied to the subject. Create `Meetings/` if missing.

1. `outlook_get_event(entry_id=<entry_id from the create result>, response_format="json")` once. Take `global_id`, `occurrence_key`, `start`, `end`, `organizer_address`, `attendees[]` from it. If `global_id` is empty, write `global_id: ""` and use `<entry_id>|<start>` as the key, as `meeting-note.md` says.
2. Grep `Administrator/Meetings/` for `occurrence_key: "<key>"`. A hit means the note exists (a re-run after a tool timeout, for example): append `## Update <ISO timestamp>` with "Booked again via /administrator:schedule" and do not create a second file.
3. Person notes: one per attendee, found or created exactly as the `meetings` skill's prep step 3 does (exact filename, else grep `email:` / `aliases:`; stub with `last_contact: ""`, `aliases: []`, `company` only from `outlook_search_contacts`; a `## Meetings` line on each). Resources get none.
4. Write the note: frontmatter per `meeting-note.md` with `entry_id` (always), `global_id`, `occurrence_key`, `subject`, `start`, `end`, `location`, `organizer` = the user's address, `organizer_link: ""`, `attendees`, `attendee_links`, `is_recurring: false`, `status: upcoming`, `created_by: administrator/0.0.3`. Header lines `**When:**`, `**Where:**`, `**Organizer:** me <address>`, `**Attendees:**`. `## Prep` holds `_(booked by /administrator:schedule on <YYYY-MM-DD>; no prep was run)_` plus the agenda as bullets if the user gave one; `## Notes` holds `_(none yet)_`; `## Action items`, `## Waiting on`, `## Related emails` hold `- none`.

Example, for the booking in worked example 2:

```markdown
---
type: meeting
source: outlook
entry_id: "00000000C1…"
global_id: "040000008200E0…"
occurrence_key: "040000008200E0…|2026-08-25T10:00:00+02:00"
subject: "Budget review"
start: 2026-08-25T10:00:00+02:00
end: 2026-08-25T10:30:00+02:00
location: "Teams"
organizer: me@example.com
organizer_link: ""
attendees:
  - sam.ortiz@example.com
  - jane.doe@acme-parts.com
attendee_links:
  - "[[People/Sam Ortiz]]"
  - "[[People/Jane Doe]]"
is_recurring: false
status: upcoming
created_by: administrator/0.0.3
---

# Budget review

**When:** 2026-08-25 10:00–10:30
**Where:** Teams
**Organizer:** me <me@example.com>
**Attendees:** [[People/Sam Ortiz]] (required, no reply), [[People/Jane Doe]] (required, no reply)

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

`start` / `end` exactly as the tool returned them, with offset.

### 8. Daily note row (after a successful create)

If `<vault>/Administrator/Daily/<meeting date>.md` exists, add the meeting to it. If the file has a `## Calendar` table, append one row:

```markdown
| 10:00 | 10:30 | Budget review with Sam | Teams | me <!-- entry_id: <entry_id> --> |
```

If the file has no `## Calendar` section, append at the end:

```markdown
## Update <ISO timestamp>

- Booked: Budget review with Sam, 10:00–10:30, Teams → [[Meetings/2026-08-25 1000 Budget review with Sam]] <!-- entry_id: <entry_id> -->
```

Skip the row if the `entry_id` comment is already in the file. If no daily note exists for that day, write nothing — `/administrator:daily` will pick the meeting up from the calendar.

### 9. Moving one meeting ("move my 2pm with Sam to Thursday")

This moves exactly one event. Do not build a move-the-whole-day flow; if the user asks for that, say the plugin moves one meeting at a time and ask which one first.

1. Find the event: `outlook_list_events(start=<day 00:00>, end=<day 23:59:59>, include_recurrences=true, response_format="json")` for the day the user named (default today). Match on time and on subject or attendee names. One match → say which ("Found 'Budget review with Sam', today 14:00–14:30"). Several → numbered list, ask. None → say so, ask.
2. `outlook_get_event(entry_id=…, response_format="json")` for the attendees, `global_id`, and whether it is recurring (`is_recurring` / `recurrence_state` other than `not_recurring`). If it is an occurrence of a series, stop: "That is one occurrence of a recurring meeting; I cannot move a single occurrence yet — move it in Outlook." If the organizer is not the user, stop: "Sam organised this one; only the organiser can move it. Want me to draft a reply asking to move it?" (then step 6, path 2, with the draft addressed to the organizer).
3. Attendee addresses from `attendees[]` (`address`, skipping the user's own) → steps 2–4 with the same duration as the existing event and the new window. Drop any candidate overlapping the existing event itself.
4. The user picks. Show:

```
Move:      Budget review with Sam
From:      Tue 25 Aug 14:00–14:30
To:        Thu 27 Aug 09:00–09:30 (your local time)
Attendees: Sam Ortiz <sam.ortiz@example.com> — the meeting moves for everyone and each attendee gets an updated invite.

Move it?
```

5. On a clear yes: `outlook_update_event(entry_id=…, start=<new start>, end=<new end>)` → `{status: "updated", entry_id, update_sent: true}`. Report "Moved, and Sam Ortiz has been sent the updated invite." If `update_sent` is false (not a meeting you organise), say the change was saved locally only.
6. Notes: Grep `Administrator/Meetings/` for `global_id: "<global_id>"` (from `outlook_get_event`), else `entry_id: "<entry_id>"`. If a note exists, do not rename it and do not change `start` / `end` / `occurrence_key` in its frontmatter — append `## Update <ISO timestamp>` with "Moved from 2026-08-25 14:00 to 2026-08-27 09:00 (new occurrence_key: <global_id>|<new start>)". `prep` finds a moved note through the `global_id` grep. If a daily note exists for the old day, append an `## Update` line "Moved: Budget review with Sam → Thu 27 Aug 09:00"; if one exists for the new day, add the row as in step 8.

### 10. Report

Two or three lines: what was sent (or drafted), to whom, the note path if one was written, the daily note if touched. For `/administrator:free`: the candidate list and, if anyone was unknown, the one-line warning — nothing else.

## Rules that apply to every run

- Read `Preferences.md` on every run, not once per session — the user may have just edited it.
- Reads are free: `outlook_get_free_busy`, `outlook_find_meeting_times`, `outlook_list_events`, `outlook_get_event`, `outlook_resolve_name`, `outlook_search_contacts`, `outlook_whoami`.
- `outlook_create_event`, `outlook_update_event` and `outlook_send_mail(save_only=true)` each need a clear yes in this conversation, after the full summary was shown. One ask per turn, nothing else in that turn.
- Never `outlook_send_mail` without `save_only=true`. Never `outlook_delete_event`, `outlook_respond_event`, `outlook_reply_mail`, `outlook_forward_mail`.
- Never invent an address, a time, an `entry_id` or a `global_id`. Every value in a note comes from a tool result, the preferences file, or the user.
- Never rewrite `Preferences.md`, a meeting note above its first `## Update`, or any note outside `<vault>/Administrator/`.
- Result shapes to rely on: `outlook_find_meeting_times` → `items[]`; `outlook_get_free_busy` → `people[{address, resolved, has_data, slots[], busy_blocks[]}]` and `unknown[]`; `outlook_create_event` → `{status, entry_id, global_id, occurrence_key, subject, start, end, invite_sent}`; `outlook_update_event` → `{status: "updated", entry_id, update_sent}`; `outlook_get_event` → the full event with `global_id`, `occurrence_key`, `organizer_address`, `attendees[]`, `is_recurring`, `recurrence_state`.
- Running `/administrator:schedule` twice for the same meeting must not create a second event: before step 5, `outlook_list_events` for the chosen slot and, if an event with the same subject and attendees already sits there, say so and stop.
- Show at most five candidates. Times in local time, as returned. Never show `EX:/O=` addresses; if `outlook_get_event` gives one, show the display name only.
- If `outlook_get_free_busy` or `outlook_find_meeting_times` fails (Exchange unreachable, cached mode offline), say so and offer to show the user's own calendar for the window instead of guessing at free times.

## Worked example 1 — `/administrator:free Sam 30 min next week`

1. Preferences read: defaults (09:00–17:30, buffer 15, `Fri 13:00-17:30` blocked, max 5/day, preferred Tue Wed Thu).
2. `outlook_resolve_name(name="Sam")` → `resolved: true`, `smtp_address: "sam.ortiz@example.com"`.
3. Window "next week" → `start="2026-08-24T00:00:00"`, `end="2026-08-28T23:59:59"`. Duration 30.
4. `outlook_find_meeting_times(addresses=["sam.ortiz@example.com"], start=…, end=…, duration_minutes=30, work_start="09:00", work_end="17:30", buffer_minutes=15, weekdays_only=true, include_self=true, max_results=15)` → 11 candidates, `unknown: []` on all.
5. Filters: two Friday-afternoon candidates dropped (no-meeting block); `list_events` for Mon 24 shows 5 meetings → Monday dropped. Sorted Tue/Wed/Thu first. First five kept.

Reply:

> Sam → sam.ortiz@example.com. Free for 30 min next week:
> 1. Tue 25 Aug 10:00–10:30 — Sam free, you free
> 2. Tue 25 Aug 14:30–15:00 — Sam free, you free
> 3. Wed 26 Aug 11:00–11:30 — Sam free, you free
> 4. Thu 27 Aug 09:00–09:30 — Sam free, you free
> 5. Thu 27 Aug 16:00–16:30 — Sam free, you free
>
> (Monday skipped: already 5 meetings. Friday afternoon skipped: your no-meeting block.) Say a number to book one.

Nothing written, nothing sent.

## Worked example 2 — `/administrator:schedule Sam, Jane Doe 30 min next week "Budget review"`

Steps 1–4 as above, but `outlook_resolve_name(name="Jane Doe")` → `resolved: false`; `outlook_search_contacts(query="Jane Doe", include_directory=true, limit=5)` → one hit `jane.doe@acme-parts.com`, company ACME Parts GmbH. `find_meeting_times` returns candidates with `unknown: ["jane.doe@acme-parts.com"]` on every one.

Reply:

> Sam → sam.ortiz@example.com, Jane Doe → jane.doe@acme-parts.com (ACME Parts GmbH).
> No calendar visible for jane.doe@acme-parts.com — she is outside your organisation, so the times below only account for you and Sam.
> 1. Tue 25 Aug 10:00–10:30 — Sam free, you free, Jane unknown
> 2. Tue 25 Aug 14:30–15:00 — Sam free, you free, Jane unknown
> 3. Wed 26 Aug 11:00–11:30 — Sam free, you free, Jane unknown
>
> Two ways forward: (a) book one and let Jane accept or decline, or (b) I draft an email to Jane proposing these times and you send it. Which?

User: "a, 1". Then:

> Subject:   Budget review
> When:      Tue 25 Aug 2026 10:00–10:30 (your local time)
> Attendees: Sam Ortiz <sam.ortiz@example.com>, Jane Doe <jane.doe@acme-parts.com>
> Location:  Teams (online meeting)
>
> Send this invite? Outlook sends it to both the moment it is created.

User: "yes". `outlook_create_event(subject="Budget review", start="2026-08-25T10:00:00", end="2026-08-25T10:30:00", attendees=["sam.ortiz@example.com","jane.doe@acme-parts.com"], location="Teams", is_online_meeting=true, body="Booked by administrator on 2026-08-22")` → `{"status":"created","entry_id":"00000000C1…","subject":"Budget review","start":"2026-08-25T10:00:00+02:00","end":"2026-08-25T10:30:00+02:00"}`. Then `outlook_get_event(entry_id="00000000C1…", response_format="json")` → `global_id: "040000008200E0…"`, `occurrence_key: "040000008200E0…|2026-08-25T10:00:00+02:00"`, `attendees` with `response: "none"` for both.

Grep `Meetings/` for `occurrence_key: "040000008200E0…|2026-08-25T10:00:00+02:00"` → no hit. `People/Jane Doe.md` exists (from an earlier save); `People/Sam Ortiz.md` does not and no note has his address → stub created with `last_contact: ""`. Both get a `## Meetings` line. Write `Meetings/2026-08-25 1000 Budget review.md` exactly as shown in step 7. `Daily/2026-08-25.md` does not exist → nothing added.

Report:

> Sent. Invite went to Sam Ortiz and Jane Doe. Note: `Meetings/2026-08-25 1000 Budget review.md`; new person note `People/Sam Ortiz.md`.

Had the user answered "b": the draft shown in step 6, a yes, `outlook_send_mail(to=["jane.doe@acme-parts.com"], subject="Proposed times — Budget review", body=…, save_only=true)`, a new `Follow-ups.md` row `| 2026-08-22 | [[People/Jane Doe]] | pick a time — Budget review | | 2026-08-22 |`, and the report "Draft saved in Drafts — open Outlook to send it. Added a follow-up for Jane." No event, no meeting note.

## Worked example 3 — "move my 2pm with Sam to Thursday"

1. `outlook_list_events(start="2026-08-25T00:00:00", end="2026-08-25T23:59:59", include_recurrences=true, response_format="json")` → one event at 14:00 whose subject contains "Sam": `Budget review with Sam`, `entry_id "00000000C2…"`.
2. `outlook_get_event` → organizer is the user, not recurring, attendees `[sam.ortiz@example.com]`, `global_id "0400…"`.
3. Window "Thursday" → Thu 27 Aug 00:00–23:59:59, duration 30 (from the event). `find_meeting_times` → 4 candidates after filters.
4. User: "the 9 o'clock one".

> Move:      Budget review with Sam
> From:      Tue 25 Aug 14:00–14:30
> To:        Thu 27 Aug 09:00–09:30 (your local time)
> Attendees: Sam Ortiz <sam.ortiz@example.com> — the meeting moves for everyone and each attendee gets an updated invite.
>
> Move it?

5. "yes" → `outlook_update_event(entry_id="00000000C2…", start="2026-08-27T09:00:00", end="2026-08-27T09:30:00")` → `{"status":"updated","update_sent":true}`.
6. `Meetings/2026-08-25 1400 Budget review with Sam.md` exists → append:

```markdown
## Update 2026-08-22T16:10:00+02:00

- Moved from 2026-08-25 14:00 to 2026-08-27 09:00 (attendee: Sam Ortiz; new occurrence_key: 0400…|2026-08-27T09:00:00+02:00)
```

`Daily/2026-08-25.md` exists → append `## Update …` with "- Moved: Budget review with Sam → Thu 27 Aug 09:00". `Daily/2026-08-27.md` does not exist → nothing.

Report:

> Moved to Thu 27 Aug 09:00–09:30; Sam Ortiz has been sent the updated invite. Appended the move to `Meetings/2026-08-25 1400 Budget review with Sam.md`.
