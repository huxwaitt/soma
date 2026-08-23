---
description: Build today's daily note from the inbox and today's calendar; clashes and meetings with no prep note are worked out by the vault server.
argument-hint: "[date]"
---

# /administrator:daily

Argument (optional): `date` as `YYYY-MM-DD`. Default: today in the user's local timezone.

Argument given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `inbox` skill (plus `inbox/references/examples.md` the first time this session). Load the `outlook` skill if it is not already loaded.
2. `vault_status` if not done yet this session; any folder or file flag false → `vault_init(created_by="administrator/0.2.0")` and mention `/administrator:setup`. `outlook_whoami(response_format="json")` once for the local time.
3. Inbox, as `/administrator:inbox` steps 3 to 5: `outlook_list_mails(... fields=["entry_id", "internet_message_id", "from_address", "from", "subject", "received", "preview"], preview_chars=80 ...)`, `vault_inbox_prepare(items, date=<date>)`, then label only the `label: null` entries into one JSON list `[{entry_id, label, reason}]` (`outlook_get_mail(..., fields=["subject", "body_trimmed"], trim_quoted=true)` for at most 5). Hold the batch offer for step 8.
4. `outlook_list_events(start="<date>T00:00:00", end="<date>T23:59:59", include_recurrences=true, limit=50, fields=["occurrence_key", "global_id", "subject", "start", "end", "location", "organizer", "all_day"], response_format="json")`. No per-event `vault_find`; the server checks prep notes itself.
5. Wiki, one line: `vault_wiki_review(action="list")` → `open[]` is the list of open items; N = its length, M = the items whose text contains `— stale:` (lint writes one such line per stale page). When N is above zero, add one `watch_out` bullet `Wiki: N review items open (M stale pages) — /administrator:wiki resolve review`. Nothing else from the wiki goes into the daily note; no lint, no ingest runs here.
6. One call: `vault_write_daily(date=<date>, labels=<the list>, events=<items[] from step 4>, watch_out=<the wiki bullet, plus extra bullets only when you know something the code cannot, else omit>, since=<since>, inbox_checked=<time of the list_mails call>, tokens_used=<this turn's token count if the host shows one>, created_by="administrator/0.2.0")`. The server writes the inbox table, `## To do`, `## Waiting on`, the Follow-ups rows, `## Calendar` (rows end in `<!-- occurrence_key: … -->`) and `## Watch out` with clashes and "No prep note: …"; on an existing note it appends only what is new under one `## Update <ISO>` heading. Read `action`, `rows_written`, `calendar_rows`, `unlabelled`. Close a follow-up whose reply came in as the `inbox` command does.
7. Show a short brief: inbox counts, the `act` / `reply` subjects, the agenda as one line per event, the watch-out bullets with an offer of `/administrator:prep` for meetings without a prep note, the note path, and `obsidian://open?vault=<vault_name>&file=<url-encoded path>`.
8. Rule proposal and batch offer exactly as `/administrator:inbox` steps 8 and 9. Run nothing without an explicit yes to a specific option. Nothing in this command creates, updates, or responds to calendar events.
9. Close with the turn's token count in one line ("This turn: 6.1k tokens") when the host exposes it; when it does not, say nothing about tokens.

## Example

```
/administrator:daily
/administrator:daily 2026-08-24
```

On 2026-08-22 at 15:40, after the morning inbox run: 3 new mails (1 never-save, 1 by rule, 1 by the model), 2 events. One `vault_write_daily` call appends rows 16–17, the calendar table and two watch-out bullets under `## Update 2026-08-22T15:40:05+02:00`; Carol Ng's reply closes her Follow-ups row.

> 3 new since 08:31: 1 never-save, 1 by rule, 1 by me. Carol Ng sent the contract draft → Follow-ups row moved to Done.
> Today: 09:30 Stand-up (Teams), 13:00 Budget review with Jane (Room 4). Watch out: clash 13:00–14:00 with Dentist; no prep note for the budget review — run /administrator:prep?
> Written: Daily/2026-08-22.md (appended). This turn: 6.1k tokens.
> Open: obsidian://open?vault=MyVault&file=Administrator%2FDaily%2F2026-08-22.md

The full run is in `skills/inbox/references/examples.md`.
