---
name: schedule
description: Find when people are free and book meetings from classic Outlook — resolve names to addresses, get candidate times from outlook_find_meeting_times, apply the user's preferences from Administrator/Preferences.md (working hours, buffers, no-meeting blocks, daily limit), show up to five candidates, and on an explicit yes create the invite with outlook_create_event, write the meeting note, and add the meeting to the daily note; also move one existing meeting with outlook_update_event, and write a "proposed times" draft email when someone is outside the tenant. Trigger when the user says "/administrator:free", "/administrator:schedule", "when are X and I both free", "find a time with", "set up 30 min with", "book a meeting with", "schedule a call with Sam", "move my 2pm with Sam to Thursday", "reschedule the budget review", "why is Sam busy on Tuesday". Reads are free; outlook_create_event, outlook_update_event and outlook_send_mail(save_only=true) each need an explicit yes first. Never sends a plain email, never deletes events, never moves more than one meeting per request.
---

# schedule — who is free, then book it

Answers "when can we meet" and, if asked, books the meeting. The server does the free/busy work (`outlook_find_meeting_times`); you decide and ask. Outlook mechanics follow the `outlook` skill; the meeting note follows `skills/meetings/references/meeting-note.md`; preferences follow `references/preferences.md`; notes go only through the `vault_*` tools (`skills/administrator/references/vault.md`). Worked examples with every call and result: `references/examples.md` — load it when a step is unclear, not by default.

Once per session: `vault_status` (a false folder or file flag → `vault_init(created_by="administrator/0.4.0")`; vault unset or not a directory → stop and say so), `outlook_whoami(response_format="json")` for the user's address and local time, and `vault_read("Administrator/Preferences.md")` (keys `work_start`, `work_end`, `buffer_minutes`, `no_meeting_blocks`, `max_meetings_per_day`, `default_duration`, `default_location`, `preferred_days`; a missing key falls back to the template default — say which in one line; never edit the file). Re-read it only when the user says they changed it.

Three things leave the machine here, each after its own yes on the exact summary shown:

- `outlook_create_event` with attendees — the invite goes out the moment the call returns; no draft step.
- `outlook_update_event` on a meeting with attendees — the server saves and sends the updated invite in the same call (`update_sent: true`); it cannot be taken back.
- `outlook_send_mail(save_only=true)` — a draft in Drafts. Nothing is sent, but it is a change in Outlook.

Never `outlook_send_mail` without `save_only=true`; never `outlook_delete_event`, `outlook_respond_event`, `outlook_reply_mail`, `outlook_forward_mail` from this skill.

## Steps

### 1. Who, how long, when

**Who.** Split on commas, "and", "&". Per name: an SMTP address is used as is; else `outlook_resolve_name(name)` → `smtp_address` when `resolved`; else `outlook_search_contacts(query, include_directory=true, limit=5)` — one hit → use it and say so, several → numbered list and ask, none → ask for the address. `vault_find("person", <name>)` with an `email` may stand in when both fail (say the address came from the vault). Never guess or build an address. The user's own address is never in `addresses` (`include_self=true` adds it).

**How long.** "30 min", "1 h", "half an hour" → `duration_minutes`; else `default_duration`.

**When.** Local ISO strings, no offset: nothing → now rounded up to the next half hour until the end of the fifth working day; "today" → until 23:59:59; "tomorrow", a weekday, a date → that day 00:00–23:59:59; "this week" → until Friday; "next week" → Mon–Fri; "morning" / "afternoon" clamp to `work_start`–12:00 / 12:00–`work_end`. A window that ends before it starts → say so and ask.

### 2. Candidates — one call

```
outlook_find_meeting_times(addresses=[...], start, end, duration_minutes,
  work_start=<pref>, work_end=<pref>, buffer_minutes=<pref>,
  weekdays_only=true,   # false only when the user named a weekend day
  include_self=true, max_results=15)          # include_slots stays false
```

`items[]` are `{start, end, free[], unknown[]}`; top-level `unknown[]` lists people with no free/busy data. Do not ask for `include_slots`, and do not call `outlook_get_free_busy` to build candidates. Then apply what the server does not know, in this order (`references/preferences.md`): drop candidates inside a `no_meeting_blocks` range; for each remaining day `outlook_list_events(start=<day 00:00>, end=<day 23:59:59>, include_recurrences=true, fields=["entry_id","subject","start","end","all_day"], response_format="json")` (at most 10 days) and drop days with `max_meetings_per_day` or more non-all-day events — events whose subject starts with `[Focus]` or `[Admin]` are the user's own time blocks and are not counted; `preferred_days` first, then earliest first; keep five.

Zero left: name the filter that removed the most, offer a wider window, a shorter duration or skipping one preference for this request. Never relax a preference silently. Someone in `unknown` on every candidate: say once, before the list, "No calendar visible for <address> — the times below only account for the others"; `free` offers a proposed-times draft, `schedule` goes to step 5.

**"Why is Sam busy on Tuesday?"** — only then: `outlook_get_free_busy(addresses=[<smtp>], start=<day 00:00>, end=<day 23:59:59>)` (`busy_blocks_only` stays true) and read `people[0].busy_blocks[]`. Never ask for `slots`.

### 3. Show the candidates

Up to five lines: `1. Tue 25 Aug 10:00–10:30 — Sam free, you free[, Jane unknown]`. `/administrator:free` stops here — no note, no event, no draft. "Book 2" afterwards continues with step 4.

### 4. Pick, summarise, ask, book

Slot = the number or time named; "just book it" = candidate 1. Subject = the user's, else `<Topic> with <First names>`, else `<Your first name> / <Their first names>` (say which). Location = the user's, else `default_location`; "Teams", "online", "call" → `is_online_meeting=true`. Attendees = the resolved addresses (unknown-calendar people too when the user wants them invited). Before asking, `outlook_list_events` for the slot with the `fields` above: an event with the same subject and attendees already there → say so and stop.

Show `Subject / When (local) / Attendees with addresses / Location`, then "Send this invite? Outlook sends it to everyone listed the moment it is created." and wait. A yes is a clear yes; "just book it" counts only if subject, attendees and location all came from the user. A yes covers only the summary shown; anything changes → show and ask again. Nothing else in the asking turn.

On yes: `outlook_create_event(subject, start, end, attendees, location, is_online_meeting, body="Booked by administrator on <date>" + agenda)` → `{status, entry_id, global_id, occurrence_key, subject, start, end, invite_sent}`. Say "Sent. Invite went to <names>." — never "created" without "sent".

### 5. Someone outside the tenant (`schedule` only)

Before step 4's summary offer two paths and wait: (a) book anyway and let them accept or decline → step 4 with them in the list; (b) proposed-times draft: show To, Subject `Proposed times — <subject>`, a body with up to five times in local time (greeting and sign-off from `skills/draft/references/voice.md`), ask "Save this as a draft in Outlook? Nothing is sent." On yes `outlook_send_mail(to, subject, body, save_only=true)`, then `vault_wiki_apply(path=<the person page>, ops=[{"op": "open", "text": "pick a time — <subject>", "owner": "[[Wiki/People/<Name>]]" or the plain name, "since": <today>, "src": "proposal:<address>"}], src="proposal:<address>")` (`vault_find("person", …)` first, a `vault_write("person", …, mode="create")` stub when there is none). It shows up in `Administrator/Follow-ups.md`, which is written from the pages and takes no rows. Report "Draft saved in Drafts — open Outlook to send it." No meeting note. "Send it" → the plugin writes drafts only.

### 6. Meeting note and daily row (after a successful create)

Use `global_id`, `occurrence_key`, `start`, `end` straight from the create result; `outlook_get_event(entry_id, fields=["global_id","occurrence_key","start","end","attendees"], response_format="json")` only when `global_id` came back empty (then the key is `<entry_id>|<start>` with `global_id: ""`). Per attendee: `vault_find("person", {"email": <address>})` → `vault_write("person", …, mode="create")` for a stub (`last_contact: ""`, `aliases: []`, `org` only from `outlook_search_contacts`, body `- <date> — [[Meetings/<note name>]]`, which the server puts under `## Records` of a `draft` wiki page) or `mode="append"` with that line. Then one `vault_write("meeting", frontmatter, body, mode="upsert")` per `meeting-note.md` "Note written by `schedule`": `entry_id`, `global_id`, `occurrence_key`, `subject`, `start`, `end`, `location`, `organizer` = the user, `organizer_link: ""`, `attendees`, `attendee_links`, `is_recurring: false`, `status: upcoming`, `created_by: administrator/0.4.0`; body = header lines, `## Prep` `_(booked by /administrator:schedule on <date>; no prep was run)_` plus the agenda as bullets, `## Notes` `_(none yet)_`, `## Action items` / `## Waiting on` / `## Related emails` `- none`. `action: appended` → the note existed (re-run after a timeout); say "update appended".

`vault_find("daily", {"date": <meeting date>})` found → `vault_append_row(<path>, "Calendar", ["HH:MM", "HH:MM", <subject>, <location>, "me"], dedupe_key=<occurrence_key>, key_label="occurrence_key", header=["Start","End","Subject","Location","Organizer"])`; `duplicate` is fine. No daily note → nothing; `daily` picks it up.

### 7. Move one meeting ("move my 2pm with Sam to Thursday")

One event per request; "move my whole day" → say so and ask which one.

1. `outlook_list_events(start=<day 00:00>, end=<day 23:59:59>, include_recurrences=true, fields=["entry_id","subject","start","end","organizer_address","attendees","is_recurring"], response_format="json")` (default today). Match on time and subject or attendee names; one → say which, several → list and ask, none → ask. Those fields already say whether it is recurring and who organises it, so `outlook_get_event` is only needed when `global_id` is missing from the item (`fields=["global_id","recurrence_state"]`).
2. An occurrence of a series → stop: "I cannot move a single occurrence yet — move it in Outlook." Organizer not the user → stop: "<Name> organised this one; only the organiser can move it. Want me to draft a reply asking to move it?" (step 5 path b, addressed to the organizer).
3. Steps 1–3 with the attendees' addresses (minus the user), the event's duration and the new window; drop candidates overlapping the event itself.
4. Show `Move / From / To / Attendees — the meeting moves for everyone and each attendee gets an updated invite.` and ask "Move it?". Wait.
5. On a clear yes `outlook_update_event(entry_id, start, end)` → `{status: "updated", entry_id, update_sent}`. "Moved, and <names> have been sent the updated invite." `update_sent: false` → "saved locally only".
6. `vault_find("meeting", {"global_id": <id>})` (`vault_find("meeting", <entry_id>)` when empty) found → `vault_write("meeting", <frontmatter as found>, "- Moved from <old> to <new> (new occurrence_key: <global_id>|<new start>)", mode="append")` — never renamed, `start`/`end` untouched. Daily note of the old day found → `vault_write("daily", <frontmatter as found>, "- Moved: <subject> → <new time>", mode="append")`; of the new day → the row from step 6.

### 8. Report

Two or three lines: what was sent or drafted, to whom, note paths, and `obsidian://open?vault=<vault_name>&file=<url-encoded path>` for every note written. `free`: the list and the unknown-calendar warning, nothing else. No raw JSON.

## Rules for every run

- Reads are free: `outlook_find_meeting_times`, `outlook_get_free_busy`, `outlook_list_events`, `outlook_get_event`, `outlook_resolve_name`, `outlook_search_contacts`, `outlook_whoami`, every `vault_*` read.
- `outlook_create_event`, `outlook_update_event`, `outlook_send_mail(save_only=true)`: a clear yes in this conversation after the full summary; one ask per turn, nothing else in it.
- Never invent an address, time, `entry_id` or `global_id`. Every value in a note comes from a tool result, the preferences or the user.
- Never rewrite `Preferences.md`, a meeting note above its first `## Update`, or anything outside `<vault>/Administrator/`; never touch a vault file with the host's file tools.
- Show at most five candidates, local time as returned, never an `EX:/O=` address (display name only).
- Free/busy tools fail (Exchange unreachable, offline) → say so and offer the user's own calendar for the window instead of guessing.
