---
description: Write one weekly review note — what is still open from the week's inbox, what you are waiting on and for how long, meetings held with unchecked action items, next week's calendar with clashes, people you have not heard from in 30+ days, and the wiki's lint and review queue (with an offer to ingest records saved before the wiki). Read-only in Outlook.
argument-hint: "[week]"
---

# /administrator:weekly

Argument (optional): `week` as `YYYY-Www` (ISO week, Monday–Sunday), a date inside the week, `this`, or `last`. Default: the week containing today; on a Monday or Tuesday, last week.

Argument given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `review` skill and its `references/examples.md`. Load the `outlook` skill if it is not already loaded.
2. Call `vault_status` (run `vault_init(created_by="administrator/0.2.0")` if anything is missing) and `outlook_whoami(response_format="json")` for local time. Work out the ISO week and next week's Monday to Friday.
3. `vault_weekly_facts(week=<YYYY-Www>, today=<today>)` — one call returns the open act/reply rows of the week's daily notes (ticked and done ones already dropped), every open follow-up with its age, meetings held with their unchecked `- [ ]` lines, past meetings without notes, and people quiet for more than 30 days. Do not `vault_read` any of those notes.
4. `outlook_list_events(start="<next Monday>T00:00:00", end="<next Friday>T23:59:59", include_recurrences=true, limit=200, fields=["subject","start","end","location","organizer","attendees","all_day","occurrence_key","global_id"], response_format="json")`; `vault_find("meeting", {occurrence_key, global_id}, fields=[])` per non-all-day event (at most 15) for the prep-note count.
5. Wiki (load the `wiki` skill): `vault_wiki_lint(fix=true)` then `vault_wiki_review(action="list")`. List the open Review items, ask one question per topic proposal and possible duplicate (create / merge only on a yes), and offer to ingest the records that were never ingested, ten at a time (the `wiki` skill's ingest steps on each, on a yes). Skip on "without wiki".
6. One write: `vault_write("weekly", {type, source: "administrator", week, start, end, generated, created_by: "administrator/0.2.0"}, <body>, mode="upsert")`. The body lays out the results as the six fixed sections (the five from step 3–4 plus `## Wiki`: lint counts, Review items, proposals and answers, records not ingested) without rewording, then at most 3–6 bullets of your own under `## Notes` (left out when nothing stands out). A second run on the same week appends an `## Update` section to the same file.
7. Report one line per section with counts, the note path, and an `obsidian://open` link to `Administrator/Weekly/<week>`. Offer `/administrator:followups` when a waiting row is older than 7 days, `/administrator:prep` when next week has meetings without a prep note, `/administrator:wiki resolve review` when Review has open items. Nothing in Outlook is changed.
8. If the host shows this turn's token count, end with `Tokens this turn: <n>`; otherwise skip the line. This command writes no daily note, so there is no `vault_write_daily` call to pass `tokens_used` into.

## Example

```
/administrator:weekly
/administrator:weekly last
/administrator:weekly 2026-W33
```

`/administrator:weekly` on Saturday 2026-08-22 writes `Weekly/2026-W34.md` for 2026-08-17 – 2026-08-23: four inbox items still open, three follow-ups (oldest 5 days), one held meeting with two unchecked items and one meeting without notes, nine meetings next week with one clash on Tuesday, two people not heard from in over 30 days, the wiki lint (2 stale topics set dormant, 1 topic proposed, 4 records never ingested), three bullets under `## Notes`.

> Week 2026-W34 written to `Weekly/2026-W34.md`. Open from inbox: 4. Waiting on: 3 (oldest 5 days). Meetings held: 1 with 2 open items; 1 without notes. Next week: 9 meetings, 1 clash, 7 without prep. Going quiet: 2. Wiki: 2 topics set dormant, Review 1 open, topic `offsite-2026` proposed (create it?), 4 records not ingested (ingest them now?).
> obsidian://open?vault=MyVault&file=Administrator/Weekly/2026-W34

The full note is in `skills/review/references/examples.md`.
