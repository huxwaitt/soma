---
description: Write a prep brief into a meeting note for today's meetings (or one meeting named by date or words) — previous occurrence, carried-over action items, attendee person notes, related email threads, open follow-ups. Read-only in Outlook.
argument-hint: "[date | event words]"
---

# /soma:prep

Argument (optional): a date (`2026-08-25`, `tomorrow`, `Monday`) for all meetings that day, or words that match one event (`supplier sync`, `jane`, `1pm`). Nothing → today.

Argument given: `$ARGUMENTS`

## Steps

1. Load the `soma` skill, then the `meetings` skill and its `references/meeting-note.md`. Load the `outlook` skill if it is not already loaded. Open `skills/meetings/references/examples.md` only if a shape is unclear.
2. `vault_status` if not done yet this session (any folder or file flag false → `vault_init(created_by="soma/0.4.1")`); `outlook_whoami(response_format="json")` once for the user's own address.
3. `outlook_list_events(start=<day 00:00>, end=<day 23:59:59>, include_recurrences=true, fields=["entry_id","global_id","occurrence_key","subject","start","end","location","organizer","organizer_address","attendees","is_recurring","all_day"], response_format="json")`. With words: today plus 7 days, matched against subject, attendee names, location and start time; one hit → take it, several → numbered list and ask, none → say so and stop. Skip all-day and `Canceled:` events unless named.
4. Per event, as the `meetings` skill describes:
   - `vault_prep_context(occurrence_key, global_id, attendees=[{name, address}…], subject=<event subject>)` — one call gives `existing_note`, `previous_occurrence.open_actions` (carried over), `people[]` (person pages, `company`, `last_contact`), `commitments[]` (the open items on the attendees' pages and the items anywhere they own, both directions: `{page, stem, type, title, owner_name, id, text, owner, due, since, src, record, done}`) and `wiki[]` (`path, type, title, status, lead, open[], facts[]` for the attendees' person pages and up to 3 topic or decision pages the search engine matched on the subject, projects first, then decisions). Do not `vault_find` / `vault_read` / `vault_wiki_read` / `vault_wiki_search` for any of that; `wiki[]` becomes a `### Wiki` block in the Prep and the suggested points start from the topic lead and its open items.
   - `outlook_find(people=[attendee addresses, max 6], since=<now − 30 days>, limit=5)` — the related threads, best first, with a `snippet` each. No `outlook_get_conversation` unless the user asks about a thread.
   - A person stub (`vault_write("person", …, mode="create")`, which the server turns into a `draft` wiki page) only for `people[]` entries with `path: null`; the meeting's Records line on existing person pages (`mode="append"`) only when the meeting note is new.
   - `vault_write("meeting", frontmatter, body, mode="upsert")`: new note with `## Prep` (Previous meeting / Carried over / People / Open follow-ups with them / Wiki / Recent threads / Suggested points), empty `## Notes`, `## Action items`, `## Waiting on`, and `## Related emails`; existing note → `mode="append"` with `### Prep` holding only what is new.
5. Report one or two lines per event (path, new / existing / moved, carried-over count, threads, follow-ups) with `obsidian://open?vault=<vault_name>&file=<url-encoded path>`, and the suggested points for the next meeting. No Outlook tool that changes anything; prep is read-only.
6. If the host shows the turn's token count, end with `Tokens this turn: N`; otherwise skip the line silently. `prep` does not call `vault_write_daily`; when a later command in this session does, pass the number as `tokens_used`.

## Example

```
/soma:prep
/soma:prep tomorrow
/soma:prep supplier sync
```

`/soma:prep supplier sync` on 2026-08-25: one event, one `vault_prep_context` call (previous occurrence 2026-08-18 with two open actions, Jane Doe has a note, Tom Lee does not, one open follow-up), one `outlook_find` call (three threads), one person stub, one `vault_write`:

> Prep written: `Meetings/2026-08-25 1300 Weekly supplier sync.md` (previous: 2026-08-18, 2 items carried over, 3 threads, 1 open follow-up). New person note `Wiki/People/Tom Lee.md`.
> obsidian://open?vault=Vault&file=Soma%2FMeetings%2F2026-08-25%201300%20Weekly%20supplier%20sync.md
> Points: sign the contract or say what blocks it; answer Tom on the 8 Sep delivery; packaging spec; Leipzig address.

Running it again appends `## Update 2026-08-25T…` with "Nothing new since the last prep." and reports "existing note found". Full example: `skills/meetings/references/examples.md`.
