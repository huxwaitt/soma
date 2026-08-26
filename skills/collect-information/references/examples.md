# collect-information — worked examples

Two runs of `/administrator:collect-information`, call by call. Tool results are cut to what the model reads. Times are local (UTC+02:00); the vault is `C:\Users\<you>\Documents\Vault` (`vault_name: Vault`); `outlook_whoami` gave `current_user: "Hux Waitt"`, `accounts[0].smtp_address: "hux@example.com"`, `local_time: "2026-08-25T17:40:12+02:00"`.

## Example 1 — a full run on Tuesday evening

User: `/administrator:collect-information`

1. Stamps:

```
vault_collect(action="read")
```

```json
{"stamps": {"teams": "2026-08-21T18:10:00+02:00", "outlook": "2026-08-21T18:10:00+02:00", "notes": "2026-08-21T18:10:00+02:00"},
 "age_hours": {"teams": 95.5, "outlook": 95.5, "notes": 95.5}, "ask": true,
 "default_since": "2026-08-21T18:10:00+02:00", "last_collected": "Fri 21 Aug 18:10"}
```

   `ask` is true, so the turn ends with: "Last collected: Fri 21 Aug 18:10. Collect since then, or just today?" User: "since then". `since = "2026-08-21T18:10:00+02:00"`.

2. Teams. `teams_status()` → `{"reader_installed": true, "cache_found": true, "accounts": [{"key": "…:…", "label": "Example GmbH"}], "chats": 41, "messages": 1180, "newest": "2026-08-25T17:31:04+02:00", "hint": null}`.

```
teams_list_chats(since="2026-08-21T18:10:00+02:00", include_messages=true, per_chat=12, max_chars=200, limit=15)
```

```json
{"chats": [
  {"id": "19:a1b2c3@thread.v2", "title": "Q3 budget", "type": "group",
   "members": [{"name": "Jane Doe", "mri": "8:orgid:11"}, {"name": "Tom Lee", "mri": "8:orgid:12"}, {"name": "Hux Waitt", "mri": "8:orgid:1"}],
   "count": 6, "last_time": "2026-08-25T17:31:04+02:00", "last_sender": "Jane Doe", "preview": "Great, then we close on 2 Sep as planned.", "account": "…:…",
   "messages": [
     {"id": "1756049703123", "time": "2026-08-24T09:15:03+02:00", "sender": "Jane Doe", "sender_org": "Example GmbH", "is_self": false, "text": "Morning — moved to the 29th, two teams are late. ok?", "truncated": false},
     {"id": "1756049840555", "time": "2026-08-24T09:17:20+02:00", "sender": "Hux Waitt", "sender_org": "Example GmbH", "is_self": true, "text": "Fine by me.", "truncated": false},
     {"id": "1756165864001", "time": "2026-08-25T17:31:04+02:00", "sender": "Jane Doe", "sender_org": "Example GmbH", "is_self": false, "text": "Great, then we close on 2 Sep as planned.", "truncated": false}],
   "truncated": 0},
  {"id": "19:hux_tom@unq.gbl.spaces", "title": "Tom Lee", "type": "chat", "members": [{"name": "Tom Lee", "mri": "8:orgid:12"}, {"name": "Hux Waitt", "mri": "8:orgid:1"}],
   "count": 2, "last_time": "2026-08-22T11:02:40+02:00", "last_sender": "Tom Lee", "preview": "PO goes out once the signed contract is back.", "account": "…:…",
   "messages": [
     {"id": "1755853300010", "time": "2026-08-22T10:41:40+02:00", "sender": "Tom Lee", "sender_org": "ACME Parts GmbH", "is_self": false, "text": "Did Jane's v3 reach you?", "truncated": false},
     {"id": "1755854560222", "time": "2026-08-22T11:02:40+02:00", "sender": "Tom Lee", "sender_org": "ACME Parts GmbH", "is_self": false, "text": "PO goes out once the signed contract is back.", "truncated": false}],
   "truncated": 0},
  {"id": "19:hux_priya@unq.gbl.spaces", "title": "Priya Nair", "type": "chat", "members": [{"name": "Priya Nair", "mri": "8:orgid:14"}, {"name": "Hux Waitt", "mri": "8:orgid:1"}],
   "count": 3, "last_time": "2026-08-25T12:02:11+02:00", "last_sender": "Priya Nair", "preview": "", "account": "…:…",
   "messages": [
     {"id": "1756115900001", "time": "2026-08-25T11:40:00+02:00", "sender": "Priya Nair", "sender_org": "Example GmbH", "is_self": false, "text": "lunch?", "truncated": false},
     {"id": "1756115960002", "time": "2026-08-25T11:41:00+02:00", "sender": "Hux Waitt", "sender_org": "Example GmbH", "is_self": true, "text": "12:30, the usual", "truncated": false},
     {"id": "1756117331003", "time": "2026-08-25T12:02:11+02:00", "sender": "Priya Nair", "sender_org": "Example GmbH", "is_self": false, "text": "", "truncated": false}],
   "truncated": 0}],
 "total_messages": 8, "capped": false}
```

   Nothing is truncated, so no `teams_read_chat`.

3. Which chats matter. One match per chat, then the pages before any judgement:

```
vault_wiki_search(query="Jane Doe: Morning — moved to the 29th, two teams are late. ok? Hux Waitt: Fine by me. Jane Doe: Great, then we close on 2 Sep as planned.", pages=true, people=[], domains=[], limit=5)
```

   → `pages: [Topics/q3-budget (score 3, word overlap: budget, close), People/Jane Doe (2, alias)]`, `candidates: []`.

```
vault_wiki_search(query="Jane Doe: Morning — moved to the 29th, two teams are late. ok? Hux Waitt: Fine by me. Jane Doe: Great, then we close on 2 Sep as planned.", brief=true, max_chars=1200)
```

   → `facts: [{page: "Wiki/Topics/q3-budget", id: "7k2q", text: "Deadline for the user's numbers is 2026-08-27", since: "2026-08-20"}, {…, id: "c3mm", text: "Numbers go into the shared sheet …"}]`. Read against the page, "moved to the 29th" is the numbers deadline: 27 → 29 Aug, a `supersede` on `7k2q` with `since` = the message time, 2026-08-24. On its own the fragment would not have been a fact. The chat is kept.

   The Tom Lee chat → `pages: [Topics/acme-supplier-contract (4, alias), People/Tom Lee (3, alias)]`; `vault_wiki_search(query=<the joined messages>, brief=true, max_chars=1200)` → fact `n30x` "Payment terms are net 30" (since 2026-08-12). "PO goes out once the signed contract is back" is a commitment on the matched topic: kept.

   The Priya Nair chat → `pages: [People/Priya Nair (2, alias)]`, `candidates: []`. The person page hit says only that Priya has a page; the messages are a lunch plan and an empty sticker line — no decision, date, amount, ask, commitment or role. Skipped: no record, no ingest, named in the report; `teams_search("lunch")` still finds it later.

4. Outlook:

```
outlook_list_mails(folder="inbox", since="2026-08-21T18:10:00+02:00", limit=50, preview_chars=80, response_format="json",
                   fields=["entry_id","internet_message_id","subject","from","from_address","to","received","bulk","bulk_why","preview"])
```

   → 23 items; `folder="sent"` → 4 items. One `vault_rules(action="match", items=<the 27>)` before a preview is read → `counts: {"bulk": 9, "never_save": 1, "kept": 17}`, and `dropped` says why each went: `bulk: List-Unsubscribe header` for two newsletters, `bulk: meeting response` for six, `bulk: sender address no-reply@ci.example`, and `rule: Never save: promo.example (domain)` for one. The report carries it as "9 bulk / 1 by your rules dropped". `vault_wiki_search(query=<subject + preview>, pages=true, people=[<from_address>], domains=[<domain>], limit=3)` on the 17 kept; two have a hit:

   - `RE: Q3 supplier contract – signature needed` from `tom.lee@acme-parts.com`, 2026-08-22 09:05 → `pages: [Topics/acme-supplier-contract (score 4, alias), People/Tom Lee (3, address)]`.
   - `Budget close date` from `jane.doe@example.com`, 2026-08-25 08:50 → `pages: [Topics/q3-budget (4, alias), People/Jane Doe (3, address)]`.

   Both opened with `outlook_get_mail(entry_id, trim_quoted=true, response_format="json", fields=[...])` (the `save` skill's field list) and saved:

```
vault_save(kind="email", mail=<get_mail JSON>, summary="Tom confirms the PO is raised once the signed v3 comes back and repeats the net-30 terms.",
                 action_items=["Return signed v3 to Jane by 2026-08-29 — owner: me"], self_addresses=["hux@example.com"], created_by="administrator/0.4.0")
```

   → `{"path": "Administrator/Emails/2026-08-22 Q3 supplier contract – signature needed.md", "action": "created", "status": "todo", "person_path": "Administrator/Wiki/People/Tom Lee.md", "person_action": "appended", "followup_added": false}`; the second → `Administrator/Emails/2026-08-25 Budget close date.md` (`created`, `fyi`). Fifteen mails seen and not saved; three named in the report (`Offsite venue options`, `Invoice 4471`, `Parking permit renewal`).

5. Notes:

```
vault_collect(action="changed", since="2026-08-21T18:10:00+02:00")
```

```json
{"count": 4, "total": 4, "capped": false, "folders": ["Administrator/Meetings", "Administrator/Emails", "Administrator/Daily", "Administrator/Weekly"], "skipped": [], "missing": [],
 "notes": [
  {"path": "Administrator/Meetings/2026-08-22 1300 Weekly supplier sync.md", "type": "meeting", "modified": "2026-08-22T14:05:31+02:00", "ingested": false,
   "excerpt": "### Notes\n\n- Jane ok with net 45, I'll sign v3 this week\n- Tom to send the updated delivery schedule by Wed", "from_update": true, "truncated": false},
  {"path": "Administrator/Daily/2026-08-24.md", "type": "daily", "modified": "2026-08-24T08:31:10+02:00", "ingested": false, "excerpt": "…", "from_update": false, "truncated": true},
  {"path": "Administrator/Emails/2026-08-22 Q3 supplier contract – signature needed.md", "type": "email", "modified": "2026-08-25T17:41:02+02:00", "ingested": false, "excerpt": "…", "from_update": false, "truncated": false},
  {"path": "Administrator/Emails/2026-08-25 Budget close date.md", "type": "email", "modified": "2026-08-25T17:41:09+02:00", "ingested": false, "excerpt": "…", "from_update": false, "truncated": false}]}
```

   The meeting note is a record not yet ingested; the daily note is not a record and its excerpt states nothing the wiki lacks; the two emails were written in step 4.

6. Records first. Two `vault_save(kind="chat")` calls for the two chats kept in step 3 (none for Priya's):

```
vault_save(kind="chat", chat=<the "Q3 budget" entry>, messages=<its 3 messages>, self_names=["Hux Waitt"], created_by="administrator/0.4.0")
```

```json
[{"path": "Administrator/Teams/2026-08-24 Q3 budget.md", "action": "created", "date": "2026-08-24", "record_id": "19:a1b2c3@thread.v2|2026-08-24", "added": 2, "skipped_duplicates": 0, "messages": 2, "people": [{"name": "Jane Doe", "page": "Administrator/Wiki/People/Jane Doe.md"}], "unknown_people": []},
 {"path": "Administrator/Teams/2026-08-25 Q3 budget.md", "action": "created", "date": "2026-08-25", "record_id": "19:a1b2c3@thread.v2|2026-08-25", "added": 1, "skipped_duplicates": 0, "messages": 1, "people": [{"name": "Jane Doe", "page": "Administrator/Wiki/People/Jane Doe.md"}], "unknown_people": []}]
```

   The Tom Lee chat → one record `Administrator/Teams/2026-08-22 Tom Lee.md` (`created`, `people: [{"name": "Tom Lee", "page": "…/People/Tom Lee.md"}]`).

   Per record the `wiki` skill's steps. The two chat records reuse the match and the brief of step 3 (no second page match, no second search); `Topics/acme-supplier-contract`, read there for the Tom chat, serves the meeting note and Tom's mail too: fact `n30x` "Payment terms are net 30" (since 2026-08-12).

   Order by time: Tom's mail (Sat 22 09:05), Tom's chat (Sat 22 11:02), the supplier sync (Sat 22 13:00), the Q3 chat of Mon 24, Jane's mail (Tue 25 08:50), the Q3 chat of Tue 25. Tom's mail repeats net 30 on the 22nd; the meeting note the same day says net 45 — same day, so `contest`, not `supersede`.

   Proposal (the turn ends here):

   > **Topics/q3-budget** — deadline 27 → 29 Aug (supersede, Teams chat Mon 24); forecast closes 2 Sep (add, chat Tue 25, confirmed by Jane's mail); open: return the numbers by 29 Aug.
   > **Topics/acme-supplier-contract** — net 30 vs net 45 (contest: Tom's mail and the supplier sync, both Sat 22); open: sign v3 by 29 Aug; Tom's delivery schedule due Wed 27 (add, meeting).
   > **People/Jane Doe** — confirm "owns the forecast"; lead unchanged. **People/Tom Lee** — role on the contract: raises the PO (add).
   > **Review** — 1 expected (net 30 / net 45).
   > Apply these? (name a line to drop it)

   User: "yes, but drop the Tom role line".

7. Ingest, oldest first — six calls, the first one:

```
vault_wiki_write(record_path="Administrator/Emails/2026-08-22 Q3 supplier contract – signature needed.md", created_by="administrator/0.4.0", pages=[
  {"path": "Administrator/Wiki/Topics/acme-supplier-contract.md", "ops": [
    {"op": "contest", "id": "n30x", "text": "Payment terms are net 45 (contract v3)"},
    {"op": "open", "text": "Sign and return contract v3", "owner": "me", "due": "2026-08-29"}]},
  {"path": "Administrator/Wiki/People/Tom Lee.md", "ops": []}])
```

   → `pages[0].applied: [{"op": "contest", "id": "n30x", "review": 1}, {"op": "open", "id": "b8k2", "owner": "me"}]`, `pages[1].record_added: true`. The chat records go in with no `src` on the ops (it defaults to the `record_id`); the Mon 24 chat carries the `supersede` on `7k2q` with `since: "2026-08-24"`, the Tue 25 chat the `add` of the close date, Jane's mail a `confirm` on it.

8. Stamps:

```
vault_collect(action="advance", source="teams", at="2026-08-25T17:40:31+02:00")
vault_collect(action="advance", source="outlook", at="2026-08-25T17:40:48+02:00")
vault_collect(action="advance", source="notes", at="2026-08-25T17:41:15+02:00")
```

   each → `{"advanced": ["<source>"], "refused": []}`.

9. Blocks. `outlook_list_events(start="2026-08-25T00:00:00", end="2026-08-25T23:59:59", include_recurrences=true, limit=50, fields=["subject","start","end","occurrence_key"], response_format="json")` → two of five events start with the prefixes: `[Focus] ACME supplier contract` 09:00–10:30 (`occurrence_key: "0400…|2026-08-25T09:00:00+02:00"`), `[Admin] Email and small tasks` 14:00–14:45. `vault_find("time-block", {"week": "2026-W35"}, fields=[])` → found; `vault_read("Administrator/Time-blocks/2026-W35.md")` shows no Held row for either key. Question (nothing else in that turn): "Today's blocks: 09:00–10:30 [Focus] ACME supplier contract, 14:00–14:45 [Admin] Email and small tasks — held, moved or skipped? (a word each, a note is welcome)". User: "held, skipped — the sync ran over".

```
vault_row(action="append", path="Administrator/Time-blocks/2026-W35.md", section="Held", row=["Tue 25 Aug", "[Focus] ACME supplier contract 09:00–10:30", "held", ""],
                 dedupe_key="0400…|2026-08-25T09:00:00+02:00", key_label="occurrence_key", header=["Day","Block","Result","Note"])
vault_row(action="append", path="Administrator/Time-blocks/2026-W35.md", section="Held", row=["Tue 25 Aug", "[Admin] Email and small tasks 14:00–14:45", "skipped", "the sync ran over"],
                 dedupe_key="0400…|2026-08-25T14:00:00+02:00", key_label="occurrence_key", header=["Day","Block","Result","Note"])
```

   both → `{"appended": true}`.

10. Report:

> Teams: 3 chats, 8 messages → 3 chat records created; 1 chat skipped: no work content — Priya Nair. Outlook: 27 mails seen, 9 bulk / 1 by your rules dropped, 2 saved (also worth saving: Offsite venue options, Invoice 4471, Parking permit renewal). Notes: 4 changed, 1 meeting note ingested. Pages: Topics/q3-budget (deadline superseded, close date added, 1 open), Topics/acme-supplier-contract (1 contested, 2 open), People/Jane Doe, People/Tom Lee (records). Review: 1 open — `/administrator:wiki resolve review`. Blocks: 1 held, 1 skipped.
> Last collected: Tue 25 Aug 17:41.
> obsidian://open?vault=Vault&file=Administrator%2FWiki%2FTopics%2Fq3-budget.md
> obsidian://open?vault=Vault&file=Administrator%2FWiki%2FTopics%2Facme-supplier-contract.md
> Tokens this turn: 21 480

## Example 2 — Teams not available, nothing to ask

Same vault the next morning, `/administrator:collect-information today` on Wed 26 Aug 09:05 in a Claude Code session started from a laptop where the `teams` extra is not installed.

1. `vault_collect(action="read")` → `ask: false` (every stamp 15.4 h old), `default_since: "2026-08-25T17:40:31+02:00"`. The argument `today` sets `since = "2026-08-26T00:00:00+02:00"` and no question is asked.
2. The `teams_*` tools are there; `teams_status()` → `{"reader_installed": false, "cache_found": true, "hint": "install the `teams` extra: `uv sync --extra teams` in the checkout, then restart Claude Code"}`. One line in the report, the Teams stamp is left alone.
3. No chats, so nothing to judge.
4. `outlook_list_mails(folder="inbox", since="2026-08-26T00:00:00+02:00", …)` → 3 items; `vault_rules(action="match", items=<the 3>)` → `counts: {"bulk": 3, "never_save": 0, "kept": 0}`, so nothing is read. `folder="sent"` → 0. No page match, nothing saved.
5. `vault_collect(action="changed", since="2026-08-26T00:00:00+02:00")` → `{"count": 0, "total": 0, "notes": []}`.
6. Nothing to propose, so the proposal turn is skipped and the user is told so.
7. No ingest.
8. `vault_collect(action="advance", source="outlook", at="2026-08-26T09:05:20+02:00")` and the same for `notes`; `teams` is not advanced.
9. `outlook_list_events(start="2026-08-26T00:00:00", end="2026-08-26T23:59:59", …)` → one `[Focus] Q3 budget` block at 09:00–10:30, still running now. `vault_read("Administrator/Time-blocks/2026-W35.md")` shows no Held row for it. Question: "Today's block: 09:00–10:30 [Focus] Q3 budget — held, moved or skipped?". User: "still on it, ask me later". No row is written.
10. Report:

> Teams: not read — install the `teams` extra: `uv sync --extra teams` in the checkout, then restart Claude Code. Outlook: 3 mails seen, 3 bulk / 0 by your rules dropped, none saved. Notes: nothing changed since midnight. Wiki: no changes proposed. Blocks: 1 unanswered.
> Last collected: Wed 26 Aug 09:05 (Teams still Tue 25 Aug 17:40).
> Tokens this turn: 3 910
