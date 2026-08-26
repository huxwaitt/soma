# load-history — worked examples

Two runs of `/administrator:load-history`, call by call. Tool results are cut to what the model reads. Times are local (UTC+02:00); the vault is `C:\Users\<you>\Documents\Vault` (`vault_name: Vault`); `outlook_whoami` gave `current_user: "Hux Waitt"`, `accounts[0].smtp_address: "hux@example.com"`, `local_time: "2026-08-26T09:12:04+02:00"`. `/administrator:collect-information` has been running since Friday, so its stamps sit at Tue 25 Aug 17:41.

The batch itself is `collect-information`'s pipeline; only the calls that belong to this skill are written out in full below.

## Example 1 — the first run, one batch end to end

User: `/administrator:load-history`

1. Where it stands:

```
vault_load_history(action="status")
```

```json
{"started": false, "path": "Administrator/Wiki/_cache/history.json",
 "stamps": {"teams": "2026-08-25T17:41:00+02:00", "outlook": "2026-08-25T17:41:00+02:00", "notes": "2026-08-25T17:41:00+02:00"},
 "note": "No pass has been planned: vault_load_history(action='plan') starts one."}
```

   Nothing is planned, so one question and the turn ends:

   > Load the past since 2026-05-28? (90 days, about 39 batches of 25, one yes per batch)

   User: "yes".

2. The plan:

```
vault_load_history(action="plan", batch=25)
```

```json
{"planned": true, "path": "Administrator/Wiki/_cache/history.json", "since": "2026-05-28T00:00:00+02:00", "batch": 25, "window_days": 7,
 "until_max": {"outlook_inbox": "2026-08-25T17:41:00+02:00", "outlook_sent": "2026-08-25T17:41:00+02:00", "teams": "2026-08-25T17:41:00+02:00"},
 "days": 90, "left_days": {"outlook_inbox": 90, "outlook_sent": 90, "teams": 90}, "batches_estimate": 39,
 "started_over": false, "kept_ids": 0, "next_hint": {"source": "outlook_inbox", "since": "2026-05-28T00:00:00+02:00", "until": "2026-06-04T00:00:00+02:00"},
 "note": "Reading Outlook inbox, Outlook sent items and Teams chats from 2026-05-28 forward, 25 records per batch, about 39 batches."}
```

   One line back: "Reading the Outlook inbox, the sent items and the Teams chats from 28 May forward — 25 records per batch, about 39 batches, one yes each. Everything from 25 Aug 17:41 on is already collect-information's."

3. The window:

```
vault_load_history(action="next")
```

```json
{"batch_no": 1, "source": "outlook_inbox", "since": "2026-05-28T00:00:00+02:00", "until": "2026-06-04T00:00:00+02:00",
 "expected": 25, "skip_ids": [], "reissued": false, "issued": "2026-08-26T09:12:31+02:00",
 "list_with": "outlook_list_mails(folder=\"inbox\", since=\"2026-05-28T00:00:00+02:00\", until=\"2026-06-04T00:00:00+02:00\", limit=100, preview_chars=80, fields=[\"entry_id\", \"internet_message_id\", \"subject\", \"from\", \"from_address\", \"to\", \"received\", \"preview\"])",
 "note": "Outlook inbox, 2026-05-28–2026-06-04: list it with the call above, turn the list oldest first, drop skip_ids and automated mail, and work on the first 25."}
```

   That call, with `response_format="json"` added and nothing else changed (its `fields` already name `bulk` and `bulk_why`), returns 31 mails newest first. Turned round, one `vault_rules(action="match", items=<the 31>)` → `counts: {"bulk": 6, "never_save": 0, "kept": 25}` — two newsletters on `bulk: List-Unsubscribe header`, three on `bulk: meeting response`, one on `bulk: sender address no-reply@ci.example`. The 25 kept are worked oldest first and the batch line says "6 bulk / 0 by your rules dropped".

4. The batch — `collect-information` step 4 (the relevance gate for mail): one `vault_wiki_search(query=<subject + preview>, pages=true, people=[<from_address>], domains=[<domain>], limit=3)` per mail. Four have a page hit or a candidate: the ACME kickoff thread (2), one from Jane Doe about the Q3 sheet, one from Tom Lee about payment terms. The other 21 are counted, not opened. The four are read with the `save` skill's `outlook_get_mail(..., trim_quoted=true, fields=[...])` and written with `vault_save(kind="email", ..., created_by="administrator/0.4.1")`.

   Then step 6 — the proposal, and nothing else in that turn:

   > **Topics/acme-supplier-contract** — new page from 2 records: kickoff 28 May, ACME to send the draft contract (open, owner Tom Lee, due 12 Jun). **People/Tom Lee** — "handles the ACME purchase orders" (add). **People/Jane Doe** — "owns the Q3 forecast sheet" (add); last contact 2 Jun. **Review** — 1 expected: net 30 in the 2 Jun mail against net 45 on the page. Apply these? (name a line to drop it)

   User: "yes". Step 7: one `vault_wiki_write(record_path=…, pages=[…], created_by="administrator/0.4.1")` per record, oldest first, then the second pass per record (the `wiki` skill's ingest step 5) — the 2 Jun mail also names the delivery week, which goes straight into a second, smaller ingest for that record.

5. Reporting the batch back:

```
vault_load_history(action="done", payload={
  "saved": [{"id": "<0528kick@acme.example>", "path": "Emails/2026-05-28 ACME kickoff.md", "received": "2026-05-28T11:04:00+02:00"},
            {"id": "<0529draft@acme.example>", "path": "Emails/2026-05-29 Draft contract.md", "received": "2026-05-29T08:47:00+02:00"},
            {"id": "<0601sheet@example.com>", "path": "Emails/2026-06-01 Q3 sheet.md", "received": "2026-06-01T14:22:00+02:00"},
            {"id": "<0601terms@acme.example>", "path": "Emails/2026-06-01 Payment terms.md", "received": "2026-06-01T16:20:00+02:00"}],
  "skipped_ids": ["<...21 ids...>"], "listed": 31,
  "reached": "2026-06-01T16:20:00+02:00", "exhausted": false,
  "pages": ["Wiki/Topics/acme-supplier-contract", "Wiki/People/Tom Lee", "Wiki/People/Jane Doe"], "calls": 14})
```

```json
{"batch": 1, "source": "outlook_inbox", "saved": 4, "skipped": 21, "listed": 31, "place": "2026-06-01T16:20:00+02:00",
 "window_days": 7, "source_done": false, "all_done": false,
 "totals": {"batches": 1, "records": 4, "pages": 3, "calls": 14,
            "sources": {"outlook_inbox": {"listed": 31, "saved": 4, "done": false, "left_days": 86}, "outlook_sent": {"listed": 0, "saved": 0, "done": false, "left_days": 90}, "teams": {"listed": 0, "saved": 0, "done": false, "left_days": 90}}},
 "next_hint": {"source": "outlook_inbox", "since": "2026-06-01T16:20:00+02:00", "until": "2026-06-08T16:20:00+02:00"},
 "note": "Batch 1: 4 saved, pages Wiki/Topics/acme-supplier-contract, Wiki/People/Tom Lee, Wiki/People/Jane Doe; next window 2026-06-01–2026-06-08 (Outlook inbox) — continue?"}
```

   `listed` is 31, between half a batch and two batches, so the window stays at seven days. The place stopped at the last record worked, not at the end of the window: everything after 1 Jun 16:20 is handed out again.

6. One line, then the turn ends:

   > Batch 1: 4 saved, pages `Topics/acme-supplier-contract`, `People/Tom Lee`, `People/Jane Doe`; next window 1–8 Jun (Outlook inbox) — continue?
   > obsidian://open?vault=Vault&file=Administrator%2FWiki%2FTopics%2Facme-supplier-contract.md

   User: "yes" → step 3 again. User: "stop" → "Stopped after batch 1 of about 39; the Outlook inbox is at 1 Jun 16:20. `/administrator:load-history` picks it up there." User: "yes to all, stop at 500k" → example 3.

## Example 2 — picking up where it stopped

The evening before, the session ended between `next` and `done`: batch 7 was handed out and never reported. Next morning the user says "continue loading the past".

1. Where it stands:

```
vault_load_history(action="status")
```

```json
{"started": "2026-08-26T09:12:20+02:00", "since": "2026-05-28T00:00:00+02:00", "batch": 25, "window_days": 7,
 "batches_done": 6, "records_saved": 22, "calls": 79, "finished": null,
 "current": {"n": 7, "source": "outlook_inbox", "since": "2026-07-27T15:05:00+02:00", "until": "2026-08-03T15:05:00+02:00", "expected": 25, "issued": "2026-08-26T18:44:02+02:00"},
 "sources": {"outlook_inbox": {"place": "2026-07-27T15:05:00+02:00", "done": false, "listed": 188, "saved": 22, "until_max": "2026-08-25T17:41:00+02:00", "left_days": 30, "gap": 166},
             "outlook_sent": {"place": null, "done": false, "listed": 0, "saved": 0, "until_max": "2026-08-25T17:41:00+02:00", "left_days": 90, "gap": 0},
             "teams": {"place": null, "done": false, "listed": 0, "saved": 0, "until_max": "2026-08-25T17:41:00+02:00", "left_days": 90, "gap": 0}},
 "seen_counts": {"outlook": 188, "teams": 0}, "left_days": {"outlook_inbox": 30, "outlook_sent": 90, "teams": 90},
 "next_hint": {"source": "outlook_inbox", "since": "2026-07-27T15:05:00+02:00", "until": "2026-08-03T15:05:00+02:00"},
 "note": "Batch 7 is open (Outlook inbox 2026-07-27–2026-08-03): list it again with action='next', then report it with action='done'."}
```

   One line: "6 batches done, 22 records saved; batch 7 (Outlook inbox, 27 Jul – 3 Aug) was handed out yesterday and never reported, so it comes again unchanged. Carry on?" — the user already said to carry on, so no second question.

2. The same window again:

```
vault_load_history(action="next")
```

```json
{"batch_no": 7, "source": "outlook_inbox", "since": "2026-07-27T15:05:00+02:00", "until": "2026-08-03T15:05:00+02:00",
 "expected": 25, "reissued": true, "issued": "2026-08-26T18:44:02+02:00",
 "skip_ids": ["<0727pol@example.com>", "<0727ship@acme.example>", "<0727note@example.com>"],
 "list_with": "outlook_list_mails(folder=\"inbox\", since=\"2026-07-27T15:05:00+02:00\", until=\"2026-08-03T15:05:00+02:00\", limit=100, preview_chars=80, fields=[\"entry_id\", \"internet_message_id\", \"subject\", \"from\", \"from_address\", \"to\", \"received\", \"preview\"])",
 "note": "Batch 7 is still open, so this is the same window again. Report it with action='done' before asking for another one."}
```

   `reissued: true`, so nothing new was started. The three `skip_ids` are the 27 July mails batch 6 already worked; they are dropped from the listing without a call. The listing gives 12; three are skipped as seen and `vault_rules(action="match")` drops one on `bulk: out-of-office reply`, so eight are worked — fewer than the 25 expected, so the window is exhausted.

   The batch runs as in example 1. Two mails match pages, both saved, ingested after one yes.

3. Reporting it:

```
vault_load_history(action="done", payload={
  "saved": [{"id": "<0729spec@acme.example>", "path": "Emails/2026-07-29 Packaging spec.md", "received": "2026-07-29T10:11:00+02:00"},
            {"id": "<0731po@acme.example>", "path": "Emails/2026-07-31 PO 4471.md", "received": "2026-07-31T13:02:00+02:00"}],
  "skipped_ids": ["<0727pol@example.com>", "<0727ship@acme.example>", "<0727note@example.com>", "<0730ooo@example.com>", "<...6 more...>"],
  "listed": 12, "exhausted": true,
  "pages": ["Wiki/Topics/acme-supplier-contract", "Wiki/Orgs/acme-parts-gmbh"], "calls": 9})
```

```json
{"batch": 7, "source": "outlook_inbox", "saved": 2, "skipped": 10, "listed": 12, "place": "2026-08-03T15:05:00+02:00",
 "window_days": 14, "source_done": false, "all_done": false,
 "next_hint": {"source": "outlook_inbox", "since": "2026-08-03T15:05:00+02:00", "until": "2026-08-17T15:05:00+02:00"},
 "note": "Batch 7: 2 saved, pages Wiki/Topics/acme-supplier-contract, Wiki/Orgs/acme-parts-gmbh; next window 2026-08-03–2026-08-17 (Outlook inbox) — continue?"}
```

   `exhausted: true`, so the place went to the end of the window rather than to a record's time, and `reached` was left out. Twelve records is under half a batch, so the window doubled to fourteen days — the next one covers twice as much ground.

   > Batch 7: 2 saved, pages `Topics/acme-supplier-contract`, `Orgs/acme-parts-gmbh`; next window 3–17 Aug (Outlook inbox) — continue?

4. Batches 8 and 9 finish the inbox (`source_done: true`, one extra line: "The Outlook inbox is done; the sent items are next"), and the pass moves to `outlook_sent` and then to `teams` on its own — the model only keeps answering `next` → batch → `done`.

5. The last batch:

```json
{"batch": 34, "source": "teams", "saved": 1, "skipped": 4, "listed": 5, "place": "2026-08-25T17:41:00+02:00",
 "window_days": 14, "source_done": true, "all_done": true, "finished": "2026-08-27T11:26:40+02:00",
 "summary": "All sources are done: 96 records saved in 34 batches (Outlook inbox 41, Outlook sent items 22, Teams chats 33), 61 pages touched. Run /administrator:lint.",
 "note": "Batch 34: 1 saved, pages Wiki/Topics/q3-budget. All sources are done: 96 records saved in 34 batches (Outlook inbox 41, Outlook sent items 22, Teams chats 33), 61 pages touched. Run /administrator:lint."}
```

   > Done: 96 records over 34 batches (inbox 41, sent 22, Teams 33), 61 pages touched. The wiki now holds 28 May to 25 Aug; `/administrator:collect-information` carries on from there. Run `/administrator:lint` — 61 pages were written in one go and it is what checks them against each other.

A `plan` with an earlier `since` starts another pass. It walks the whole range from that date forward again, but its answer carries a `kept_ids` count — the ids the finished pass read come with it, so the days already covered come back as `skip_ids` and nothing is read twice. `plan(reset=true)` is what forgets them.

## Example 3 — "yes to all, stop at 500k"

The user answers the "continue?" of batch 1 with it. Batch 2 runs as usual, and its `done` carries the mode and what the batch cost:

```json
{"saved": [...], "skipped_ids": [...], "listed": 27, "reached": "2026-06-07T11:40:00+02:00",
 "exhausted": false, "pages": ["Wiki/Topics/acme-supplier-contract"], "calls": 12,
 "tokens": {"in": 38000, "out": 5200}, "auto": true, "cap": 500000}
```

The answer's `note` ends "carrying on, 43200 tokens spent of 500000" instead of "continue?", so batch 3 starts in the same turn. Each batch still shows its bullets grouped by page, its "Expected ~N in / ~M out" line and its one-line report; no question is asked between them. `next` answers `{… "auto": true, "cap": 500000, "cost": {"in": 38000, "out": 5200, "total": 43200}}`, and step 3b adds the next estimate to `cost.total`: at batch 11 that sum passes 500000, so nothing is opened and the run asks once —

> Batch 10 done, 462,000 tokens spent of the 500,000 cap; the next batch looks like ~44,000 more. Carry on?

A "no" ends the session (`auto: false` on the next `done`); a "yes, make it 800k" sends `cap: 800000` and the run goes on. A refusal, a Review contradiction only the user can settle, or a merge stops it the same way, at that point and no later.
