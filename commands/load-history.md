---
description: Read the months before the "last collected" stamps into the wiki — the Outlook inbox, then the sent items, then the Teams chats, oldest first, 25 records per batch with one yes per batch. The server fixes the start date (90 days back by default) and the day each source stops at, hands out one window of days at a time with the exact call to list it, and remembers where it got to, so a run that stopped picks up there. Each batch is the collect-information pipeline: relevance gate, records first, bullets grouped by page, one yes, ingest oldest first; "yes to all" runs the batches that are left without asking, up to a token cap you name. Nothing in Outlook or Teams is changed and the stamps are never moved.
argument-hint: "[since | status | stop | all]"
---

# /administrator:load-history

Argument (optional): `since <YYYY-MM-DD>` starts (or restarts) the pass at that date instead of 90 days back; `status` reports where it stands and stops; `stop` ends the session with the place kept; `all` runs every batch that is left without asking after each one (`all 500k` stops when the next batch would take the pass past 500,000 tokens). Without an argument the pass carries on, or is offered when there is none yet. Add `reset` to `since` to drop a running pass and start over.

Argument given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `load-history` skill and its `skills/load-history/references/examples.md`, then the `collect-information` skill and the `wiki` skill (plus `skills/wiki/references/examples.md` on the first ingest of a session). Load the `outlook` skill if it is not already loaded.
2. Once per session: `vault_status` (if `administrator_dir_exists` or any folder or file flag is false, `vault_init(created_by="administrator/0.4.0")` and mention `/administrator:setup`) and `outlook_whoami(response_format="json")` — `local_time` is "now", `accounts[].smtp_address` are the user's addresses, `current_user` and `accounts[].display_name` the user's own names.
3. **Where it stands.** `vault_load_history(action="status")`. `{started: false}` → step 4. Otherwise read its `note` back in one line (batches done, records saved, the place per source, the window that is open when there is one). Argument `status` → stop there. Argument `stop` → say where it stands and end the turn; nothing else is called.
4. **Plan** (only when nothing is running, or the argument says `reset`). One question, then stop the turn: "Load the past since <date>? (N days, about M batches of 25, one yes per batch)". On a yes: `vault_load_history(action="plan", since=<the argument's date, else left out>, batch=25, reset=<true only when the argument says so>)` → `{planned, since, until_max, days, left_days, batches_estimate, note}`; report `note` in one line. `{planned: false, refused: "already-running"}` → do not plan again; carry on at step 5.
5. **The window.** `vault_load_history(action="next")` → `{batch_no, source, since, until, expected, skip_ids, list_with, reissued, auto, cap, cost}`. Make the call in `list_with` as it stands (`outlook_list_mails(folder="inbox" | "sent", since, until, limit=100, preview_chars=80, fields=[…])` or `teams_list_chats(since, until, include_messages=true, per_chat=12, max_chars=200, limit=15)`), adding on the mail call only `response_format="json"` (its `fields` already name `bulk` and `bulk_why`). Then turn the list oldest first, drop every id in `skip_ids`, run one `vault_rules(action="match", items=<the mails left>)` before any preview is read (a mail window only) and work on its `kept` — the batch line reports its `counts` as "N bulk / M by your rules dropped" — and take the first `expected`. `reissued: true` = the same window as last time, nothing new started.
5b. **Expected cost.** The window is listed and nothing has been opened yet. Work the batch out as the `load-history` skill's step 3b says (`in` from the records listed and opened and the page reads, `out` from the ops, records and bullets), multiplied by `ratio_in` / `ratio_out` from `vault_collect(action="read").tokens["load-history"]` (one read per session; it never moves a stamp) when it has 3 runs or more. One line before anything is opened: "Expected ~N in / ~M out for this run". In auto mode with a cap, open nothing when `cost.total + N + M` would pass `cap`: say how much is spent of the cap and ask whether to carry on.
6. **The batch.** `collect-information`'s steps, named not restated: step 3 (chats) and step 4 (mail) for the relevance gate, each as its own step runs it (the chat gate adds one `vault_wiki_search(brief=true, max_chars=1200)` for page context, the mail gate does not); step 6 for the records first (`vault_save(kind="chat")` / `vault_save(kind="email")`, `created_by="administrator/0.4.0"`) and one proposal as short bullets grouped by page with the Review items expected, ending in "Apply these? (name a line to drop it)" and nothing else in that turn; step 7 on a yes for one `vault_wiki_write` per record oldest first, the open items with their owner, the decision rule, and the second pass over each record (the `wiki` skill's ingest step 5, on by default here). Caps: 25 records, at most 3 wiki page reads per record, at most 3 whole chats read per batch, one proposal and one yes; every record that passes the gate is opened and saved, so step 4's cap of eight opened mails does not apply.
7. **Report the batch back.** `vault_load_history(action="done", payload={saved: [{id, path, received}], skipped_ids: [...], listed: <what the listing returned>, reached: <the received time of the last record worked>, exhausted: <true when nothing in the window was left over>, pages: [...], calls: <n>, tokens: {in, out}, auto: <only when the user changed it>, cap: <only then>})` → `{batch, saved, skipped, listed, place, window_days, source_done, all_done, totals, next_hint, auto, cap, cost, note}`. `reached` and `listed` come from the listing and from the records actually written; never invent them; `tokens` is the measured count when the host shows one, else step 5b's estimate.
8. **One line, then stop.** Read the answer's `note` back — "Batch n: k saved, pages …; next window <since>–<until> — continue?" — with `obsidian://open?vault=<vault_name>&file=<url-encoded path>` links for at most three pages this batch changed, and one line when `source_done` is true. Then stop the turn. A yes → step 5 again; "stop" or anything else ends the session with the place kept.
8b. **"Yes to all"** (the `all` argument, or the user saying it at any "continue?"): send `auto: true` on the next `done`, with `cap` when they named one, then run the batches that are left without stopping — each one still shows its bullets, its cost line and its one-line report, and the `note` ends "carrying on". Stop and ask again on a refusal, on a Review contradiction only the user can settle, on a merge or rename, or when step 5b says the cap is in reach. "stop" ends it and `auto: false` goes on the next `done`. The `load-history` skill's step 6 is the full rule.
9. **Finished.** `all_done: true` → read the `summary` out (records, batches, per source, pages touched) and end with "Run `/administrator:lint`" — the pass wrote many pages in one go, and lint is what checks them against each other. A finished pass does not block a new one: `since <an earlier date>` starts another and carries the ids it already read over (`kept_ids`), so the days it covered come back as `skip_ids`.
10. If the host shows the turn's token count, end the batch with `vault_collect(action="tokens", payload={"command": "load-history", "predicted_in": <the N of step 5b>, "predicted_out": <its M>, "actual_in": <in>, "actual_out": <out>})` and one line "Cost: N in / M out (expected N'/M')"; otherwise skip the call and say nothing about it. (This command writes no daily note, so there is no `vault_write_daily(tokens_used=…)` call here.)

## Example

```
/administrator:load-history
/administrator:load-history status
/administrator:load-history since 2026-01-01
/administrator:load-history stop
/administrator:load-history all
/administrator:load-history all 500k
```

> Load the past since 2026-05-28? (90 days, about 39 batches of 25, one yes per batch)

After "yes", the first window, the proposal and a second "yes":

> Batch 1: 4 saved, pages `Topics/acme-supplier-contract`, `People/Tom Lee`, `People/Jane Doe`; next window 1–8 Jun (Outlook inbox) — continue?
> obsidian://open?vault=Vault&file=Administrator%2FWiki%2FTopics%2Facme-supplier-contract.md

`status` on the next day:

> 6 batches done, 22 records saved; the Outlook inbox is at 27 Jul (30 days left), the sent items and Teams not started. Batch 7 was handed out and never reported, so it comes again unchanged.

The two full runs, call by call: `skills/load-history/references/examples.md`.
