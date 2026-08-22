---
description: Write one weekly review note — what is still open from the week's inbox, what you are waiting on and for how long, meetings held with unchecked action items, next week's calendar with clashes, and people you have not heard from in 30+ days. Read-only in Outlook.
argument-hint: "[week]"
---

# /administrator:weekly

Argument (optional): `week` as `YYYY-Www` (ISO week, Monday–Sunday), a date inside the week, `this`, or `last`. Default: the week containing today; on a Monday or Tuesday, last week.

Argument given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `review` skill. Load the `outlook` skill if it is not already loaded.
2. Call `vault_status` (run `vault_init(created_by="administrator/0.0.4")` if anything is missing) and `outlook_whoami(response_format="json")` for local time. Work out the week's Monday and Sunday and next week's Monday to Friday.
3. **Still open from inbox**: `vault_list("daily", since=<Monday>)`, `vault_read` each note dated in the week, keep `act` / `reply` rows that are not ticked in `## To do` and whose email note (if any, via `vault_find("email", …)`) is not `status: done`.
4. **Waiting on**: `vault_read("Administrator/Follow-ups.md")`, every `## Open` row with its age in days.
5. **Meetings held**: `vault_list("meeting", since=<Monday>)`, notes in the week with `status: held`; `vault_read` each for unchecked `- [ ]` lines under `## Action items`. Past meetings still `upcoming` are listed as "no notes taken".
6. **Next week**: `outlook_list_events(start="<next Monday>T00:00:00", end="<next Friday>T23:59:59", include_recurrences=true, limit=200, response_format="json")`; one table per day; clashes and meetings with no prep note (`vault_find("meeting", {occurrence_key, global_id})`) under **Watch out**.
7. **People going quiet**: `vault_list("person")`, notes with a non-empty `last_contact` older than 30 days, oldest first, at most 20.
8. One write: `vault_write("weekly", {type, source: "administrator", week, start, end, generated, created_by: "administrator/0.0.4"}, <body with the five sections>, mode="upsert")`. A second run on the same week appends an `## Update` section to the same file.
9. Report one line per section with counts, the note path, and an `obsidian://open` link to `Administrator/Weekly/<week>`. Offer `/administrator:followups` when a waiting row is older than 7 days, `/administrator:prep` when next week has meetings without a prep note. Nothing in Outlook is changed.

## Example

```
/administrator:weekly
/administrator:weekly last
/administrator:weekly 2026-W33
```

`/administrator:weekly` on Saturday 2026-08-22 writes `Weekly/2026-W34.md` for 2026-08-17 – 2026-08-23: four inbox items still open, three follow-ups (oldest 5 days), one held meeting with two unchecked items and one meeting without notes, nine meetings next week with one clash on Tuesday, two people not heard from in over 30 days.

> Week 2026-W34 written to `Weekly/2026-W34.md`. Open from inbox: 4. Waiting on: 3 (oldest 5 days). Meetings held: 1 with 2 open items; 1 without notes. Next week: 9 meetings, 1 clash, 7 without prep. Going quiet: 2.
> obsidian://open?vault=MyVault&file=Administrator/Weekly/2026-W34

The full note is in `skills/review/SKILL.md`.
