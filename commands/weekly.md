---
description: Write one weekly review note — what is still open from the week's inbox, what you are waiting on and for how long, meetings held with unchecked action items, next week's calendar with clashes, people you have not heard from in 30+ days, where the week's hours went against your priorities (vault_time_block audit), and the wiki's lint and review queue (with an offer to ingest records saved before the wiki). Read-only in Outlook.
argument-hint: "[week]"
---

# /soma:weekly

Argument (optional): `week` as `YYYY-Www` (ISO week, Monday–Sunday), a date inside the week, `this`, or `last`. Default: the week containing today; on a Monday or Tuesday, last week.

Argument given: `$ARGUMENTS`

## Steps

1. Load the `soma` skill, then the `review` skill and its `references/examples.md`. Load the `outlook` skill if it is not already loaded.
2. Call `vault_status` (run `vault_init(created_by="soma/0.4.2")` if anything is missing) and `outlook_whoami(response_format="json")` for local time. Work out the ISO week and next week's Monday to Friday.
3. `vault_weekly_facts(week=<YYYY-Www>, today=<today>)` — one call returns the open act/reply rows of the week's daily notes (ticked and done ones already dropped), every open item other people owe with its age, the user's own items past their due date, meetings held with their unchecked `- [ ]` lines, past meetings without notes, and people quiet for more than 30 days. Do not `vault_read` any of those notes.
4. `outlook_list_events(start="<next Monday>T00:00:00", end="<next Friday>T23:59:59", include_recurrences=true, limit=200, fields=["subject","start","end","location","organizer","attendees","all_day","occurrence_key","global_id"], response_format="json")`; `vault_find("meeting", {occurrence_key, global_id}, fields=[])` per non-all-day event (at most 15) for the prep-note count.
5. Time: one more `outlook_list_events(start="<the review week's Monday>T00:00:00", end="<its Sunday>T23:59:59", include_recurrences=true, limit=200, fields=["subject","start","end","all_day","attendee_count","is_meeting","occurrence_key","busy_status"], response_format="json")`, then `vault_time_block(action="audit", week=<YYYY-Www>, events=<items[]>)` → its `lines` (hours per kind, blocks held / moved / skipped / unanswered, hours per priority) go into `## Time` as they came. No `Time-blocks/` note for the week → the section still gets line 1 and `Blocks: none planned this week.`
6. Wiki (load the `wiki` skill): `vault_wiki_keep(action="lint", fix=true, items=true)` then `vault_wiki_keep(action="review")`. List the open Review items, ask one question per topic proposal and possible duplicate (create / merge only on a yes), and offer to ingest the records that were never ingested, ten at a time (the `wiki` skill's ingest steps on each, on a yes). Skip on "without wiki".
7. One write: `vault_write("weekly", {type, source: "soma", week, start, end, generated, created_by: "soma/0.4.2"}, <body>, mode="upsert")`. The body lays out the results as the seven fixed sections (the five from step 3–4, with the `promised_overdue` entries under `**Past due from me**` inside `## Waiting on`, `## Time` from step 5 between `## People going quiet` and `## Wiki`, then `## Wiki`: lint counts, Review items, proposals and answers, records not ingested) without rewording, then at most 3–6 bullets of your own under `## Notes` (left out when nothing stands out). A second run on the same week appends an `## Update` section to the same file.
8. Report one line per section with counts, the note path, and an `obsidian://open` link to `Soma/Weekly/<week>`. Offer `/soma:followups` when a waiting item is older than 7 days or something of the user's own is past due, `/soma:prep` when next week has meetings without a prep note, `/soma:wiki resolve review` when Review has open items, `/soma:time-block` when the audit's `blocks.planned` is 0 or its `shares.unplanned` is above the `slack_share` in `Preferences.md`. Nothing in Outlook is changed.
9. If the host shows this turn's token count, end with `Tokens this turn: <n>`; otherwise skip the line. This command writes no daily note, so there is no `vault_write_daily` call to pass `tokens_used` into.

## Example

```
/soma:weekly
/soma:weekly last
/soma:weekly 2026-W33
```

`/soma:weekly` on Saturday 2026-08-22 writes `Weekly/2026-W34.md` for 2026-08-17 – 2026-08-23: four inbox items still open, three open items other people owe (oldest 5 days) and one of the user's own two days past due, one held meeting with two unchecked items and one meeting without notes, nine meetings next week with one clash on Tuesday, two people not heard from in over 30 days, the week's hours (9 h meetings, 3 h focus of 4.5 h planned, 24.2 h unplanned), the wiki lint (2 stale topics set dormant, 1 topic proposed, 4 records never ingested), three bullets under `## Notes`.

> Week 2026-W34 written to `Weekly/2026-W34.md`. Open from inbox: 4. Waiting on: 3 (oldest 5 days), 1 of mine past due. Meetings held: 1 with 2 open items; 1 without notes. Next week: 9 meetings, 1 clash, 7 without prep. Going quiet: 2. Time: meetings 9 h, focus 3 h of 4.5 h planned, unplanned 24.2 h — 6 blocks: 3 held, 1 moved, 1 skipped, 1 unanswered. Wiki: 2 topics set dormant, Review 1 open, topic `offsite-2026` proposed (create it?), 4 records not ingested (ingest them now?).
> obsidian://open?vault=MyVault&file=Soma/Weekly/2026-W34

The full note is in `skills/review/references/examples.md`.
