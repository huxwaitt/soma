# Worked examples — `/administrator:prep` and `/administrator:notes`

Three runs on the same meeting, in order. Tool results are shortened to the keys the step uses; every value comes from a tool result or the user. User: Hux Waitt <hux@example.com>, vault name `Vault`.

## Example 1 — prep

User: `/administrator:prep supplier sync` on 2026-08-25 08:40.

1. `outlook_list_events(start="2026-08-25T00:00:00", end="2026-09-01T23:59:59", include_recurrences=true, fields=["entry_id","global_id","occurrence_key","subject","start","end","location","organizer","organizer_address","attendees","is_recurring","all_day"], response_format="json")` → one subject match:

   ```json
   {"entry_id": "00000000E1…", "global_id": "0400…", "occurrence_key": "0400…|2026-08-25T13:00:00+02:00",
    "subject": "Weekly supplier sync", "start": "2026-08-25T13:00:00+02:00", "end": "2026-08-25T14:00:00+02:00",
    "location": "Room 4", "organizer": "Jane Doe", "organizer_address": "jane.doe@acme-parts.com",
    "attendees": [{"name": "Jane Doe", "address": "jane.doe@acme-parts.com", "type": "required", "response": "organizer"},
                  {"name": "Hux Waitt", "address": "hux@example.com", "type": "required", "response": "accepted"},
                  {"name": "Tom Lee", "address": "tom.lee@acme-parts.com", "type": "optional", "response": "none"}],
    "is_recurring": true, "all_day": false}
   ```

2. `vault_prep_context(occurrence_key="0400…|2026-08-25T13:00:00+02:00", global_id="0400…", attendees=[{"name": "Jane Doe", "address": "jane.doe@acme-parts.com"}, {"name": "Tom Lee", "address": "tom.lee@acme-parts.com"}])` →

   ```json
   {"existing_note": null, "existing_status": null,
    "previous_occurrence": {"path": "Administrator/Meetings/2026-08-18 1300 Weekly supplier sync.md", "date": "2026-08-18",
                            "open_actions": ["- [ ] Send revised forecast to Jane — owner: me", "- [ ] Confirm Leipzig delivery address — owner: Tom Lee"]},
    "people": [{"email": "jane.doe@acme-parts.com", "name": "Jane Doe", "path": "Administrator/People/Jane Doe.md", "last_contact": "2026-08-21T16:42:10+02:00", "company": "ACME Parts GmbH", "last_emails": ["- 2026-08-21 — [[Emails/2026-08-21 Q3 supplier contract – signature needed]] (todo)"]},
               {"email": "tom.lee@acme-parts.com", "name": "Tom Lee", "path": null, "last_contact": "", "company": "", "last_emails": []}],
    "followups_open": ["| 2026-08-21 | [[People/Jane Doe]] | Contract draft | [[Emails/2026-08-21 Contract draft]] | 2026-08-22 <!-- entry_id: 00000000AC… --> |"]}
   ```

3. `outlook_find(people=["jane.doe@acme-parts.com", "tom.lee@acme-parts.com"], since="2026-07-26T00:00:00", limit=5)` → 3 items, best first, each with `entry_id, subject, from_address, received, score, snippet, folder`. No `get_conversation`.
4. Tom has no note: `outlook_search_contacts(query="tom.lee@acme-parts.com", include_directory=true, limit=5)` → `company: "ACME Parts GmbH"` → `vault_write("person", {type: person, source: outlook, name: "Tom Lee", email: "tom.lee@acme-parts.com", company: "ACME Parts GmbH", last_contact: "", aliases: [], created_by: "administrator/0.1.0"}, "# Tom Lee\n\ntom.lee@acme-parts.com · ACME Parts GmbH\n\n## Emails\n\n- none yet\n\n## Meetings\n\n- 2026-08-25 — [[Meetings/2026-08-25 1300 Weekly supplier sync]] (upcoming)", mode="create")`. Jane's note exists and the meeting note is new → one `vault_write("person", <her frontmatter>, "- 2026-08-25 — [[Meetings/2026-08-25 1300 Weekly supplier sync]] (upcoming)", mode="append")`.
5. `vault_write("meeting", frontmatter, body, mode="upsert")` → `{"path": "Administrator/Meetings/2026-08-25 1300 Weekly supplier sync.md", "action": "created"}`. Frontmatter:

   ```yaml
   type: meeting
   source: outlook
   entry_id: 00000000E1…
   global_id: 0400…
   occurrence_key: 0400…|2026-08-25T13:00:00+02:00
   subject: Weekly supplier sync
   start: 2026-08-25T13:00:00+02:00
   end: 2026-08-25T14:00:00+02:00
   location: Room 4
   organizer: jane.doe@acme-parts.com
   organizer_link: "[[People/Jane Doe]]"
   attendees:
     - jane.doe@acme-parts.com
     - tom.lee@acme-parts.com
   attendee_links:
     - "[[People/Jane Doe]]"
     - "[[People/Tom Lee]]"
   is_recurring: true
   status: upcoming
   created_by: administrator/0.1.0
   ```

   Body:

   ```markdown
   # Weekly supplier sync

   **When:** 2026-08-25 13:00–14:00
   **Where:** Room 4
   **Organizer:** [[People/Jane Doe]] <jane.doe@acme-parts.com>
   **Attendees:** [[People/Jane Doe]] (required, organizer), [[People/Tom Lee]] (optional, no reply)

   ## Prep

   **Previous meeting:** [[Meetings/2026-08-18 1300 Weekly supplier sync]] (2026-08-18)

   ### Carried over

   - [ ] Send revised forecast to Jane — owner: me (from 2026-08-18)
   - [ ] Confirm Leipzig delivery address — owner: Tom Lee (from 2026-08-18)

   ### People

   - [[People/Jane Doe]] — ACME Parts GmbH — last contact 2026-08-21
   - [[People/Tom Lee]] — ACME Parts GmbH — no email on record

   ### Open follow-ups with them

   | Since | Who | What | Email | Last checked |
   | --- | --- | --- | --- | --- |
   | 2026-08-21 | [[People/Jane Doe]] | Contract draft | [[Emails/2026-08-21 Contract draft]] | 2026-08-22 <!-- entry_id: 00000000AC… --> |

   ### Recent threads

   1. **RE: Q3 supplier contract – signature needed** (Jane Doe, 2026-08-21) — Jane sent v3 with net-45 terms, wants it signed by 29 Aug. <!-- entry_id: 00000000B5… -->
   2. **Delivery schedule September** (Tom Lee, 2026-08-19) — Tom proposes moving the first delivery to 8 Sep; no reply from me yet. <!-- entry_id: 00000000B3… -->
   3. **Re: Supplier sync agenda** (Jane Doe, 2026-08-17) — Jane adds "packaging spec" to this week's agenda. <!-- entry_id: 00000000B1… -->

   ### Suggested points

   - Sign the contract or say what still blocks it (item 1, carried over: forecast)
   - Answer Tom on the 8 Sep delivery (item 2)
   - Packaging spec, Jane's agenda item (item 3)
   - Carried over: Leipzig address

   ## Notes

   _(none yet)_

   ## Action items

   - none

   ## Waiting on

   - none

   ## Related emails

   - 2026-08-21 — RE: Q3 supplier contract – signature needed (Jane Doe) <!-- entry_id: 00000000B5… -->
   - 2026-08-19 — Delivery schedule September (Tom Lee) <!-- entry_id: 00000000B3… -->
   - 2026-08-17 — Re: Supplier sync agenda (Jane Doe) <!-- entry_id: 00000000B1… -->
   ```

Report:

> Prep written: `Meetings/2026-08-25 1300 Weekly supplier sync.md` (previous: 2026-08-18, 2 items carried over, 3 threads, 1 open follow-up). New person note `People/Tom Lee.md`.
> obsidian://open?vault=Vault&file=Administrator%2FMeetings%2F2026-08-25%201300%20Weekly%20supplier%20sync.md
> Points: sign the contract or say what blocks it; answer Tom on the 8 Sep delivery; packaging spec; Leipzig address.

Five tool calls. Run again: `vault_prep_context` answers `existing_note: "Administrator/Meetings/2026-08-25 1300 Weekly supplier sync.md"`, `outlook_find` returns the same three `entry_id`s (compare with the note read once with `vault_read`), `vault_write(..., mode="append")` adds `## Update 2026-08-25T…` with "Prep re-run via /administrator:prep." and "Nothing new since the last prep."; report "existing note found".

## Example 2 — notes (plain notes)

User, 2026-08-25 14:18: `/administrator:notes supplier sync` followed by:

```
- contract: Jane ok with net 45, I'll sign tomorrow and send back
- Tom confirmed Leipzig is still the delivery address
- first Sep delivery moved to 8 Sep, Tom to send updated schedule by Wed
- packaging spec: Jane will send the draft next week
- forecast still owed by me
```

1. `outlook_list_events` for today (same `fields`) → the 13:00 "Weekly supplier sync", ended. `vault_prep_context(occurrence_key, global_id, attendees=[…])` → `existing_note` = the note from example 1, `existing_status: "upcoming"`, `people[]` now both with a `path` (Tom `last_contact: ""`), `followups_open` as before. Five lines, no turn pattern → plain notes.
2. Pulled out: four action items (two owned by Tom Lee and Jane Doe → waiting), one closed item ("Tom confirmed Leipzig" matches the carried-over line; no Follow-ups row exists for it, so nothing moves). `vault_write("meeting", <frontmatter as found, status: held>, body, mode="append")` → `{"action": "appended", "update_heading": "Update 2026-08-25T14:18:02+02:00", "frontmatter_changed": ["status"]}`, body:

   ```markdown
   Notes added via /administrator:notes.

   ### Notes

   - contract: Jane ok with net 45, I'll sign tomorrow and send back
   - Tom confirmed Leipzig is still the delivery address
   - first Sep delivery moved to 8 Sep, Tom to send updated schedule by Wed
   - packaging spec: Jane will send the draft next week
   - forecast still owed by me

   ### Action items

   - [ ] Sign contract v3 and send back by 2026-08-26 — owner: me
   - [ ] Send updated September delivery schedule by 2026-08-27 — owner: Tom Lee
   - [ ] Send packaging spec draft (next week) — owner: Jane Doe
   - [ ] Send revised forecast to Jane — owner: me

   ### Waiting on

   - [[People/Tom Lee]] — Updated September delivery schedule (since 2026-08-25) → also in [[Follow-ups]]
   - [[People/Jane Doe]] — Packaging spec draft (since 2026-08-25) → also in [[Follow-ups]]

   ### Closed

   - Confirm Leipzig delivery address (carried over from 2026-08-18) — Tom confirmed it in this meeting
   ```

3. Two rows: `vault_append_row("Administrator/Follow-ups.md", "Open", ["2026-08-25", "[[People/Tom Lee]]", "Updated September delivery schedule", "[[Meetings/2026-08-25 1300 Weekly supplier sync]]", "2026-08-25"], dedupe_key="0400…|2026-08-25T13:00:00+02:00 # Updated September delivery schedule", key_label="occurrence_key")` and the same for "Packaging spec draft" → both `appended: true`.
4. `last_contact`: Tom `""` and Jane `2026-08-21T…` are both earlier than `start` → one `vault_write("person", <frontmatter, last_contact: "2026-08-25T13:00:00+02:00">, "- 2026-08-25 — [[Meetings/2026-08-25 1300 Weekly supplier sync]] (held)", mode="append")` each.
5. `outlook_voice_sample(address="jane.doe@acme-parts.com", n=10, max_chars=300)` once (greeting "Hi", sign-off "Thanks" + first name). Draft shown, then: "Save this as a draft email to Jane Doe, Tom Lee? (goes to Drafts, nothing is sent)"

   ```
   To: jane.doe@acme-parts.com; tom.lee@acme-parts.com
   Subject: Minutes: Weekly supplier sync (2026-08-25)

   Hi both,

   Notes from Weekly supplier sync, 2026-08-25 13:00.

   - Net 45 agreed; I sign contract v3 and return it tomorrow.
   - Leipzig stays the delivery address.
   - First September delivery moves to 8 Sep.
   - Packaging spec draft to follow from Jane next week.

   Action items:
   - Sign contract v3 and send back — Hux — 2026-08-26
   - Send updated September delivery schedule — Tom Lee — 2026-08-27
   - Send packaging spec draft — Jane Doe — next week
   - Send revised forecast — Hux — no date

   Sent from my notes; corrections welcome.

   Thanks
   Hux
   ```

   User: "yes" → `outlook_send_mail(to=["jane.doe@acme-parts.com","tom.lee@acme-parts.com"], subject="Minutes: Weekly supplier sync (2026-08-25)", body=<above>, save_only=true)`, then `vault_write("meeting", <frontmatter as found>, "### Minutes draft\n\nSaved to Drafts 2026-08-25T14:20:31+02:00.\n\n<body>", mode="append")`.

Report:

> Notes added to `Meetings/2026-08-25 1300 Weekly supplier sync.md` (status: held). 4 action items, 2 waiting on (Tom Lee, Jane Doe) → 2 rows in Follow-ups.md; carried-over "Leipzig address" closed. `last_contact` updated on Jane Doe and Tom Lee. Minutes saved to Drafts — send it from Outlook when you are happy with it.
> obsidian://open?vault=Vault&file=Administrator%2FMeetings%2F2026-08-25%201300%20Weekly%20supplier%20sync.md

## Example 3 — notes (transcript)

Same meeting, the user pastes instead:

```
PART 1 of 1
[13:02] Jane Doe: Let's start with the contract. Are you fine with net 45?
[13:03] Hux Waitt: Yes. I'll sign version 3 tomorrow and send it back.
[13:04] Jane Doe: Good, so we agreed on net 45, that stays in.
[13:05] Tom Lee: One thing from my side, the delivery address. I checked, it is still Leipzig, confirmed.
[13:06] Hux Waitt: Thanks, that closes that one.
[13:10] Tom Lee: About September. The first delivery on the first of September is too tight for us.
[13:11] Jane Doe: Let's go with 8 September then. Tom, can you send the updated schedule by Wednesday?
[13:12] Tom Lee: Will do.
[13:14] Priya: I'll send the packaging spec draft next week, once legal has seen it.
END OF TRANSCRIPT
Speakers:
Jane Doe
Hux Waitt
Tom Lee
Priya
```

1. Step 1 as in example 2. Nine turn lines and `END OF TRANSCRIPT` → transcript.
2. Host Write tool: `C:\Users\<you>\Documents\Vault\Administrator\Attachments\2026-08-25 1300 Weekly supplier sync\transcript.md` with the paste exactly as above. Then `vault_attach_transcript(meeting_path="Administrator/Meetings/2026-08-25 1300 Weekly supplier sync.md", transcript_path="Administrator/Attachments/2026-08-25 1300 Weekly supplier sync/transcript.md")` →

   ```json
   {"path": "Administrator/Meetings/2026-08-25 1300 Weekly supplier sync.md", "turns": 9,
    "speakers": ["Jane Doe", "Hux Waitt", "Tom Lee", "Priya"],
    "speaker_links": ["[[People/Jane Doe]]", "Hux Waitt", "[[People/Tom Lee]]", "Priya"],
    "lines": 9, "appended_lines": 17, "linked": false, "update_heading": "Update 2026-08-25T14:18:02+02:00"}
   ```

   The note now holds `### Transcript` with the speaker line and the collapsed callout; the model wrote none of it.
3. From the text already in context: `vault_write("meeting", <frontmatter as found, status: held>, body, mode="append")` with

   ```markdown
   Decisions and actions from the transcript.

   ### Decisions

   - Net 45 stays in the contract ([13:04])
   - First September delivery moves to 8 September ([13:11])

   ### Action items

   - [ ] Sign contract v3 and send back by 2026-08-26 — owner: me ([13:03])
   - [ ] Send updated September delivery schedule by 2026-08-27 — owner: Tom Lee ([13:11])
   - [ ] Send packaging spec draft (next week) — owner: ? ([13:14])

   ### Waiting on

   - [[People/Tom Lee]] — updated September delivery schedule (since 2026-08-25) → also in [[Follow-ups]]
   - Priya — packaging spec draft (since 2026-08-25) → also in [[Follow-ups]]

   ### Closed

   - Confirm Leipzig delivery address (carried over from 2026-08-18) — Tom confirmed it ([13:05])
   ```

   No `### Notes`: the user did not say "summarise", so `## Notes` still reads `_(none yet)_`.
4. Two `vault_append_row` calls as in example 2; the second row's `Who` is the plain text `Priya` (not an attendee, no person note). Steps 5–6 as in example 2; the minutes bullets come from the two decisions and three action items.

Report:

> Transcript filed for `Meetings/2026-08-25 1300 Weekly supplier sync.md` (9 turns, 4 speakers: Jane Doe, Tom Lee linked; Priya is not an attendee), stored in the note. 2 decisions, 3 action items (owner of "packaging spec draft" unknown — Priya is not on the invite), 2 waiting on → 2 rows in Follow-ups.md; carried-over "Leipzig address" closed. `## Notes` left for you — say "summarise" if you want 3–6 bullets from the transcript. Draft minutes shown above; save to Drafts?
