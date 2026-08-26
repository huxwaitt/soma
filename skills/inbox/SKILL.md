---
name: inbox
description: Go through the user's new Outlook mail, label each message as act / reply / waiting / fyi / noise, have the vault server render today's daily note in the Obsidian vault (a waiting mail also opens an item on the sender's wiki page, and the first run of the day lists what the user promised), and then offer (never run unasked) batch clean-up in Outlook. Trigger on /administrator:inbox, /administrator:daily, "go through my inbox", "what's new in my inbox", "anything urgent?", "what do I need to reply to", "what came in since yesterday", "sort my mail", "clear my inbox", "what's today". Requires the outlook_* and vault_* tools and ADMINISTRATOR_VAULT.
---

# Inbox

The model decides, the tools move the bytes. You read a short list, label what no rule could, and hand the labels back; `vault_write_daily` renders the note, links existing email notes, opens an item on the sender's page for every `waiting` mail, lists the user's own items due within seven days under `## Promised` on the first run of the day, and (for `daily`) adds the calendar, clashes and missing prep notes. You never write a table row, never compare `entry_id`s, never copy text a tool already holds. Reads are free. Nothing that changes Outlook runs without an explicit yes.

Vault conventions live in the core `administrator` skill and `administrator/references/vault.md` ("Workflow helpers" section); Outlook mechanics in the `outlook` skill and `administrator/references/outlook.md`. Label rules: `references/labels.md`. A full run, call by call: `references/examples.md` — load it the first time you run this workflow in a session, not before.

## Inputs

- `folder` (optional, default `inbox`) — any folder reference the `outlook` skill accepts.
- `since` (optional) — ISO-8601 lower bound. If absent, see step 1.
- `date` (`daily` only, default today) and, for `daily`, the day's events.
- A working vault: `vault_status` once per session; if `administrator_dir_exists` or any folder or file flag is false (including `Rules.md`), call `vault_init(created_by="administrator/0.4.1")` and mention `/administrator:setup`. Vault unset or not a directory: stop and tell the user; do not guess a path.

## Steps

### 1. Find the window

`vault_find("daily", limit=1, fields=["date", "inbox_checked"])` → `since` = that note's `inbox_checked` (its `date` at 00:00 local when the key is missing). User gave `since` → use it. No daily note → now minus 24 hours. `outlook_whoami(response_format="json")` once per session for `utc_offset` and `local_time`. Say in one line which window you use: "Checking mail since Thu 21 Aug 17:05."

### 2. List the mail — one call, small fields

```
outlook_list_mails(folder=<folder>, unread_only=true, since=<since>, limit=100,
    fields=["entry_id", "internet_message_id", "from_address", "from", "subject", "received", "bulk", "bulk_why", "preview"],
    preview_chars=80, response_format="json")
```

Remember the time of this call; it is `inbox_checked`. Never ask for more fields or a longer preview here — step 4 reads the few bodies that matter.

- **0 mails:** `vault_write_daily(date, labels=[], items=[], since, inbox_checked, created_by="administrator/0.4.1")` still runs so the window moves on; tell the user "nothing new since <since>" and stop. No batch offer.
- **`has_more`:** label the 100 you have; say "More than 100 unread since <since>; the newest 100 are in the note" and ask before paging (`offset=100`), never page on your own.

### 3. Let the rules go first

```
vault_inbox_prepare(items=<the items[] exactly as returned>, date=<today>)
```

Back come `to_label[]` (only mails not yet in any daily note of this ISO week and not on a never-save rule; `label` and `rule` already filled where a built-in or `Rules.md` rule decided; `preview` only where not), `already_seen[]`, `never_save[]`, `labelled_by_rule`. The list is cached on disk, so you never pass items back. Do not re-check, overrule or re-read the rule-labelled ones: a rule hit is a mail you do not read.

### 4. Label the rest

Only for `to_label[]` entries with `label: null`. An entry whose `entry_id` came back `bulk: true` in the listing is `noise` with nothing opened — a machine wrote it, and `bulk_why` names the signal in the reason ("bulk: meeting response"). Work from `from_name`, `from_address`, `subject`, `received`, `preview`, using `references/labels.md` (short form: **act** do something, **reply** write back, **waiting** they owe me, **fyi** read, **noise** ignore; when torn take the more demanding label — a wrong `noise` costs the most). Your whole output for this step is one compact JSON list, nothing else:

```json
[{"entry_id": "00000000A2…", "label": "reply", "reason": "Asks you for the revised Q3 figure"}]
```

`reason` is at most 12 words, plain, starts with what the sender wants. Do not echo subjects, previews or addresses back.

Open a mail only when subject and preview cannot settle it between two labels, at most **5 per run**:

```
outlook_get_mail(entry_id, trim_quoted=true, max_body_chars=3000, fields=["subject", "body_trimmed"], response_format="json")
```

Past the cap, or still unsure: `reply` when a person wrote and the preview addresses the user, else `fyi`, with the reason ending in "(unsure)". `vault_find("person", <from_address>, fields=["name", "status"])` is allowed for a sender you cannot place, not for every sender.

### 5. Write the note — one call

```
vault_write_daily(date=<today>, labels=<the JSON from step 4>, since=<since>, inbox_checked=<time of step 2>,
    folder=<folder unless inbox>, events=<daily only, step 6>, watch_out=<daily only, extra bullets or omitted>,
    tokens_used=<the turn's token count when the host shows one, else omit>, created_by="administrator/0.4.1")
```

Items come from the cache; rule-labelled mails need no entry in `labels`. The server sorts the table, writes the `<!-- entry_id -->` comments, links the `Note` column to existing email notes, fills `## To do` and `## Waiting on` (each `waiting` mail also opens an item on the sender's page, owned by them), writes `## Promised` on the first run of the day, and on a second run today appends only new rows under `## Update <ISO>` (the only frontmatter key that moves is `inbox_checked`). Read the result: `action` (`created` / `appended` / `unchanged`), `rows_written`, `duplicates_skipped`, `followups_added`, `promised`, `unlabelled[]` (fix: label them and call again — they were left out of the note). `unchanged` means nothing was written; say so.

Closing a follow-up: when a fresh mail is a reply from someone who owes an open item on the same subject, `vault_wiki_search(query="", open_items=true, owner="others", page=<their person page>)` once, then `vault_wiki_write(pages=[{"path": <the item's page>, "ops": [{"op": "done", "id": <the item's id>, "src": "user"}]}])`. Say so in the report. Skip the search when no fresh mail is a reply from a person. Never write a row into `Follow-ups.md`; the file is written from the pages.

### 6. `daily` only — the calendar

Before step 5: `outlook_list_events(start="<date>T00:00:00", end="<date>T23:59:59", include_recurrences=true, limit=50, fields=["occurrence_key", "global_id", "subject", "start", "end", "location", "organizer", "all_day"], response_format="json")` and pass `items[]` as `events`. Clashes and "No prep note" are computed in code; `watch_out` is only for something the user should hear that the code cannot know (a deadline from an `act` mail that falls today, a meeting with no location). Do not call `vault_find("meeting", …)` per event. `## Calendar` and `## Watch out` are never written by `/administrator:inbox`.

### 7. Report, then offer batch actions

Three to five lines: counts per label (including `labelled_by_rule` and `already_seen`), the `act` and `reply` subjects, the open items added or closed, the note path, and `obsidian://open?vault=<vault_name>&file=<url-encoded path>` (`vault_name` from `vault_status`, `path` from `vault_write_daily`). No raw JSON. For `daily`, add the agenda lines and the watch-out bullets.

Then offer, as a numbered list, only the actions that apply, each with count and subjects (first 10 plus "and N more"):

1. Mark `fyi` and `noise` as read — `outlook_bulk_mark_mails(entry_ids=[...], read=true)`.
2. Move `noise` to a folder — ask for the folder, check it with `outlook_list_folders`, pass the returned `path` verbatim to `outlook_bulk_move_mails`. Never create folders.
3. Tag by label — `outlook_bulk_mark_mails(entry_ids=[...], categories=[...])` only with names from `outlook_list_categories`; none match → say so, skip. `categories` replaces the list.
4. Flag `act` items — `outlook_bulk_mark_mails(entry_ids=[...], flagged=true)`.

One yes per item; "yes" to 1 is not yes to 2. Ask with one short message ending in a question and wait. A yes covers only the list shown; if you re-ran `list_mails`, ask again. After a bulk call read `failed` and name failed subjects. Record it: `vault_write("daily", <frontmatter from vault_find("daily", {"date": …})>, "Done <ISO>: marked 2 as read", mode="append")`. Never `outlook_delete_mail` / `outlook_bulk_delete_mails` from here, even for "get rid of" — move instead and say so. Nothing in this skill sends mail.

### 8. Propose a rule (after the note, before the batch offer)

Count, in this run's `to_label[]`, the mails you labelled yourself per `from_address` (or per domain for automated senders) and label. When one sender got the same label **5 or more times**, and `vault_rules(action="get")` has no row for it yet, propose one line: "You labelled 6 mails from news@vendor.example as noise. Add the rule `news@vendor.example → noise` to Rules.md so they skip the model next time?" Only on a clear yes:

```
vault_row(action="append", path="Administrator/Rules.md", section="Labels", row=[<match>, <field: from | domain | name | subject>, <label>])
```

No `dedupe_key` (the `Rules.md` parser reads plain cells); the `vault_rules` check is the duplicate guard. `never_save` rules are never proposed — the user writes those by hand. One proposal per run.

## Edge cases

- `vault_*` tools missing → vault server not running: point to `/administrator:setup`, write nothing. `outlook_*` missing → the `outlook` skill's setup notes; no daily note.
- `since` unparsable or in the future: say so, fall back to 24 hours.
- Duplicate delivery (same `entry_id` twice): `vault_inbox_prepare` collapses it.
- Mail from self: `fyi`, unless it is a note-to-self with a verb in it, then `act`.
- Another folder: pass `folder=<path>`; the server writes `## Inbox (<folder>, since …)`.
- `vault_write_daily` raises "no cached list": step 3 did not run for this date; run it and call again.

## References

- `references/labels.md` — decision rules per label, tie-break order, when to open a mail.
- `references/examples.md` — a normal run and a second run the same day, every call and result.
