---
name: load-history
description: Reads the months *before* the "last collected" stamps into the wiki, one window of days at a time — Outlook inbox, then Outlook sent items, then the Teams chats — 25 records per batch with one yes per batch, each batch run through the `collect-information` pipeline. `vault_load_history` fixes the start date and the upper bound per source, hands out the exact call to list each window, and remembers the place each source got to, so a run that stopped picks up there. Trigger when the user says "/administrator:load-history", "load the last three months", "load my history into the wiki", "fill the wiki from old mail", "read the past into the wiki", "start the wiki from my old mail", "continue loading the past", "carry on with the history", or "how far did the history get". Reads Outlook and Teams only; nothing in either is changed, and the "last collected" stamps are only read, never moved.
---

# load-history — the months before the stamps, one window at a time

`/administrator:collect-information` covers the stamps forward to now. This covers what lies before them, so a new wiki starts full instead of empty. `vault_load_history` fixes a start date (90 days back by default) and, per source, the day the pass stops at (that source's collect stamp, else now); then it hands out one window of days at a time together with the exact call that lists it, and writes the place it got to after every batch.

Every batch *is* `collect-information`'s pipeline. This skill names that skill's steps by number and does not restate them. Load `skills/collect-information/SKILL.md` and `skills/wiki/SKILL.md` before the first batch (plus their `references/examples.md` on the first run of a session). A full first batch and a run that picked up where it stopped: `references/examples.md`.

Once per session: `vault_status` (any folder or file flag false → `vault_init(created_by="administrator/0.4.0")`; vault unset or not a directory → stop and tell the user) and `outlook_whoami(response_format="json")` — `local_time` is "now", `accounts[].smtp_address` are `self_addresses`, `current_user` and `accounts[].display_name` are `self_names`.

## Caps (fixed, say when one is hit)

`expected` records per batch (25 by default); at most 3 wiki page reads per record; at most 3 whole chats read with `teams_read_chat` per batch; one proposal and one yes per batch; one listing call per window, exactly the `list_with` text. Step 4's cap of eight mails opened per run does not apply here — every record that passes the gate is opened and saved, up to `expected`. What a window holds beyond `expected` is left for the next window — the place moves only as far as `reached`. Everything else is `collect-information`'s caps.

## Steps

### 1. Where the pass stands

`vault_load_history(action="status")` first, always. Either `{started: false, path, stamps, note}` — no pass yet, go to step 2 — or the whole state: `since`, `batch`, `window_days`, `until_max` per source, `sources` (`place`, `done`, `listed`, `saved`, `until_max`, `left_days`, `gap`), `current` (the window open right now, or `null`), `batches_done`, `records_saved`, `pages_touched` (the 40 most recent; `totals.pages` is the count), `seen_counts`, `left_days`, `totals`, `next_hint`, `finished`, `note`. Read `note` out in one line. `gap` is that source's `listed` minus its `saved` — mostly mail that touched no page, so it is normally large; mention it only when several batches in a row saved next to nothing. `finished` set → step 8.

### 2. A first run: one question, then plan

Ask exactly one question and stop the turn: **"Load the past since <date>? (N days, about M batches of 25, one yes per batch)"** — `<date>` is 90 days back, or the date the user named.

On a yes: `vault_load_history(action="plan", since=<ISO date, or left out for 90 days back>, batch=25)` → `{planned: true, path, since, batch, window_days, until_max, stamps, days, left_days, batches_estimate, sources, started_over, kept_ids, next_hint, note}`. Report `note` in one line, with `batches_estimate` as the number of yeses ahead. (Asking before planning means N and M are your own estimate; take the real ones from the answer and correct the line if they differ.)

`{planned: false, refused: "already-running", note, status}` means a pass is running: do not plan again — say where it stands and go to step 3, or, when the user asks to start over, `plan(reset=true)`. No stamp at all (`note` says so) → mention that each source stops at now and that `/administrator:collect-information` keeps its own stamps.

### 3. The window to list

`vault_load_history(action="next")` → `{batch_no, source, since, until, expected, skip_ids, list_with, reissued, issued, note}`. Make the call in `list_with` as it stands — it is `outlook_list_mails(folder="inbox" | "sent", since, until, limit=100, preview_chars=80, fields=[…])` or `teams_list_chats(since, until, include_messages=true, per_chat=12, max_chars=200, limit=15)`, with the window, the limit and the fields already in it. Change nothing in it; the one thing to add is `response_format="json"` on the mail call, which the text leaves out and which every other skill passes. Then:

- turn the list round so the **oldest** record is first;
- drop every id in `skip_ids` (already read by an earlier batch) and every plainly automated mail (no-reply senders, newsletters, meeting responses, out-of-office) without opening it;
- work on the first `expected` of what is left.

`reissued: true` means this window was handed out before and never reported — the same window, unchanged; nothing new was started. Report it with `done` before asking for another.

### 3b. Expected cost

The window is listed and nothing has been opened yet. Work the batch out first (tokens = chars ÷ 4):

> in ≈ Teams min(total_messages, chats × per_chat) × (max_chars × 0.6 + 40) ÷ 4 + Outlook listed × 60 + opened × 900 + notes count × max_chars ÷ 4 + records × 3 × 200 (page reads); out ≈ ops × 45 + records × 60 + bullets × 25 + 300

A mail window has no Teams part and a Teams window no Outlook part; there are no notes here, and `records` is what survived `skip_ids`, at most `expected`. One `vault_collect_sources(action="read")` per session — it reads, it never moves a stamp — carries `tokens: {"load-history": {runs, ratio_in, ratio_out}}`, the last 20 batches measured against their estimates: when `runs` is 3 or more, multiply `in` by `ratio_in` and `out` by `ratio_out`. Show one line before anything is opened: "Expected ~N in / ~M out for this run". When the host shows the turn's token count, end the batch with `vault_collect_sources(action="tokens", payload={"command": "load-history", "predicted_in": N, "predicted_out": M, "actual_in": <in>, "actual_out": <out>})` and one line "Cost: N in / M out (expected N'/M')"; when it does not, skip the call.

### 4. The batch

For the records that survived step 3, `collect-information`'s own steps, in order:

- **step 3** for chats and **step 4** for mail — the relevance gate exactly as each of those steps runs it (a chat's `vault_wiki_match` is followed by one `vault_wiki_search(brief=true, max_chars=1200)` for its page context; a mail's is not): keep what touches a page or a candidate or carries work content on its own, skip banter and name it;
- **step 6** — the records first (`vault_save_chat`, or the `save` skill's `outlook_get_mail` then `vault_save_email`, both with `created_by="administrator/0.4.0"`), then one proposal as short bullets grouped by page with the Review items expected, and **one** question: "Apply these? (name a line to drop it)". Nothing else happens in that turn;
- **step 7** — on a yes, one `vault_wiki_ingest` per record oldest first, the open items with their owner, the decision rule, and the second pass over each record (the `wiki` skill's ingest step 5, on by default here) as a second smaller ingest in the same turn.

A "no" to the proposal leaves the records written; report the batch with `saved` naming only what was actually saved.

### 5. Report the batch back

One call, still in the same turn:

```
vault_load_history(action="done", payload={
  "saved": [{"id": "<internet_message_id, entry_id, or <chat_id>|<date>>",
             "path": "Emails/2026-06-02 Kickoff.md", "received": "2026-06-02T09:14:00+02:00"}, …],
  "skipped_ids": ["<the ids left out: automated, banter, no work content>"],
  "listed": <how many records the listing call returned>,
  "reached": "<the received time of the last record you worked>",
  "exhausted": <true when nothing in the window was left over: every record it listed was worked or dropped>,
  "pages": ["Wiki/Topics/q3-budget", …], "calls": <tool calls this batch took>})
```

`reached` is the truthful mark: the place moves there, so everything after it is handed out again next time. `exhausted: true` moves the place to `until` instead, and then `reached` may be left out. Both bounds of a window are inclusive, so the record sitting exactly on `since` comes back in the next listing and is dropped as a `skip_id`; a record between two windows is never lost. The answer is `{batch, source, saved, skipped, listed, place, window_days, source_done, all_done, totals, next_hint, note}` — `window_days` may have halved or doubled (1 to 30 days) to fit the batch size.

### 6. One line, then stop the turn

Read the answer's `note` back as it stands — **"Batch n: k saved, pages …; next window <since>–<until> — continue?"** — and stop. One yes per batch: on a yes, step 3 again; anything else ends the session. Add `obsidian://open` links only for the pages this batch changed, at most three, and one line naming the source that just finished when `source_done` is true.

### 7. Stopping and picking up again

"stop", "enough", "later" → say where it stands in one line ("stopped after batch 7 of about 34; the Outlook inbox is at 2026-06-14") and end the turn. Nothing is lost: the state is written after `plan` and after every `done`. A later run starts at step 1, and `next` carries on from the place each source got to; a window that was never reported is handed out again unchanged. Reading a record twice is harmless — `vault_save_email` adds an update instead of a second note, `vault_save_chat` drops message ids it already has, and an ingest skips a page whose Records already name the record.

### 8. When every source is finished

`all_done: true` (or `status.finished`) → read the `summary` out: how many records in how many batches, per source, how many pages touched, ending with **"Run /administrator:lint."** — the pass touched many pages at once, and lint is what checks them against each other. A finished pass does not block a new one: `plan` with an earlier `since` starts another, and `kept_ids` says how many ids it carried over — it walks the covered days again, but they come back as `skip_ids` instead of being read twice. `plan(reset=true)` is the one thing that forgets them.

## Rules

- Nothing in Outlook or Teams is changed: no mark, move, category, reply, or event. The vault is written only through `vault_*` tools, wiki pages only through `vault_wiki_*`.
- The "last collected" stamps are read at plan time to fix each source's upper bound and are never moved — `vault_collect_sources(action="advance")` is not called here.
- One question per turn: the plan question, each batch's proposal, and each "continue?" are separate turns and are never folded together.
- No `vault_wiki_ingest` before that batch's proposal was answered; no `vault_wiki_create` or `vault_wiki_merge` without a yes.
- Never invent `reached`, `listed` or an id: they come from the listing result and from the records you actually wrote.
- Never call `next` twice for one batch, and never list a window with anything other than its `list_with` text.
