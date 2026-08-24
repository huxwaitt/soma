# collect-information — worked examples

Two runs of `/administrator:collect-information`, call by call. Tool results are cut to what the model reads. Times are local (UTC+02:00); the vault is `C:\Users\<you>\Documents\Vault` (`vault_name: Vault`); `outlook_whoami` gave `current_user: "Hux Waitt"`, `accounts[0].smtp_address: "hux@example.com"`, `local_time: "2026-08-25T17:40:12+02:00"`.

## Example 1 — a full run on Tuesday evening

User: `/administrator:collect-information`

1. Stamps:

```
vault_collect_sources(action="read")
```

```json
{"stamps": {"teams": "2026-08-21T18:10:00+02:00", "outlook": "2026-08-21T18:10:00+02:00", "notes": "2026-08-21T18:10:00+02:00"},
 "age_hours": {"teams": 95.5, "outlook": 95.5, "notes": 95.5}, "ask": true,
 "default_since": "2026-08-21T18:10:00+02:00", "last_collected": "Fri 21 Aug 18:10"}
```

   `ask` is true, so the turn ends with: "Last collected: Fri 21 Aug 18:10. Collect since then, or just today?" User: "since then". `since = "2026-08-21T18:10:00+02:00"`.

2. Teams. `teams_status()` → `{"reader_installed": true, "cache_found": true, "accounts": [{"key": "…:…", "label": "Example GmbH"}], "chats": 41, "messages": 1180, "newest": "2026-08-25T17:31:04+02:00", "hint": null}`.

```
teams_list_chats(since="2026-08-21T18:10:00+02:00", include_messages=true, per_chat=20, max_chars=300, limit=15)
```

```json
{"chats": [
  {"id": "19:a1b2c3@thread.v2", "title": "Q3 budget", "type": "group",
   "members": [{"name": "Jane Doe", "mri": "8:orgid:11"}, {"name": "Tom Lee", "mri": "8:orgid:12"}, {"name": "Hux Waitt", "mri": "8:orgid:1"}],
   "count": 6, "last_time": "2026-08-25T17:31:04+02:00", "last_sender": "Jane Doe", "preview": "Great, then we close on 2 Sep as planned.", "account": "…:…",
   "messages": [
     {"id": "1756049703123", "time": "2026-08-24T09:15:03+02:00", "sender": "Jane Doe", "sender_org": "Example GmbH", "is_self": false, "text": "Morning — can we move the numbers deadline to Friday 29 Aug? Two teams are late.", "truncated": false},
     {"id": "1756049840555", "time": "2026-08-24T09:17:20+02:00", "sender": "Hux Waitt", "sender_org": "Example GmbH", "is_self": true, "text": "Fine by me.", "truncated": false},
     {"id": "1756165864001", "time": "2026-08-25T17:31:04+02:00", "sender": "Jane Doe", "sender_org": "Example GmbH", "is_self": false, "text": "Great, then we close on 2 Sep as planned.", "truncated": false}],
   "truncated": 0},
  {"id": "19:hux_tom@unq.gbl.spaces", "title": "Tom Lee", "type": "chat", "members": [{"name": "Tom Lee", "mri": "8:orgid:12"}, {"name": "Hux Waitt", "mri": "8:orgid:1"}],
   "count": 2, "last_time": "2026-08-22T11:02:40+02:00", "last_sender": "Tom Lee", "preview": "PO goes out once the signed contract is back.", "account": "…:…",
   "messages": [
     {"id": "1755853300010", "time": "2026-08-22T10:41:40+02:00", "sender": "Tom Lee", "sender_org": "ACME Parts GmbH", "is_self": false, "text": "Did Jane's v3 reach you?", "truncated": false},
     {"id": "1755854560222", "time": "2026-08-22T11:02:40+02:00", "sender": "Tom Lee", "sender_org": "ACME Parts GmbH", "is_self": false, "text": "PO goes out once the signed contract is back.", "truncated": false}],
   "truncated": 0}],
 "total_messages": 8, "capped": false}
```

   Nothing is truncated, so no `teams_read_chat`.

3. Outlook:

```
outlook_list_mails(folder="inbox", since="2026-08-21T18:10:00+02:00", limit=50, preview_chars=80, response_format="json",
                   fields=["entry_id","internet_message_id","subject","from","from_address","to","received","preview"])
```

   → 23 items; 9 are automated (no-reply, two newsletters, six meeting responses) and skipped without a call. `folder="sent"` → 4 items. `vault_wiki_match(text=<subject + preview>, people=[<from_address>], domains=[<domain>], limit=3)` on the 18 others; two have a hit:

   - `RE: Q3 supplier contract – signature needed` from `tom.lee@acme-parts.com`, 2026-08-22 09:05 → `pages: [Topics/acme-supplier-contract (score 4, alias), People/Tom Lee (3, address)]`.
   - `Budget close date` from `jane.doe@example.com`, 2026-08-25 08:50 → `pages: [Topics/q3-budget (4, alias), People/Jane Doe (3, address)]`.

   Both opened with `outlook_get_mail(entry_id, trim_quoted=true, response_format="json", fields=[...])` (the `save` skill's field list) and saved:

```
vault_save_email(mail=<get_mail JSON>, summary="Tom confirms the PO is raised once the signed v3 comes back and repeats the net-30 terms.",
                 action_items=["Return signed v3 to Jane by 2026-08-29 — owner: me"], self_addresses=["hux@example.com"], created_by="administrator/0.3.0")
```

   → `{"path": "Administrator/Emails/2026-08-22 Q3 supplier contract – signature needed.md", "action": "created", "status": "todo", "person_path": "Administrator/Wiki/People/Tom Lee.md", "person_action": "appended", "followup_added": false}`; the second → `Administrator/Emails/2026-08-25 Budget close date.md` (`created`, `fyi`). Sixteen mails seen and not saved; three named in the report (`Offsite venue options`, `Invoice 4471`, `Parking permit renewal`).

4. Notes:

```
vault_changed_notes(since="2026-08-21T18:10:00+02:00")
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

   The meeting note is a record not yet ingested; the daily note is not a record and its excerpt states nothing the wiki lacks; the two emails were written in step 3.

5. Records first. Two `vault_save_chat` calls:

```
vault_save_chat(chat=<the "Q3 budget" entry>, messages=<its 3 messages>, self_names=["Hux Waitt"], created_by="administrator/0.3.0")
```

```json
[{"path": "Administrator/Teams/2026-08-24 Q3 budget.md", "action": "created", "date": "2026-08-24", "record_id": "19:a1b2c3@thread.v2|2026-08-24", "added": 2, "skipped_duplicates": 0, "messages": 2, "people": [{"name": "Jane Doe", "page": "Administrator/Wiki/People/Jane Doe.md"}], "unknown_people": []},
 {"path": "Administrator/Teams/2026-08-25 Q3 budget.md", "action": "created", "date": "2026-08-25", "record_id": "19:a1b2c3@thread.v2|2026-08-25", "added": 1, "skipped_duplicates": 0, "messages": 1, "people": [{"name": "Jane Doe", "page": "Administrator/Wiki/People/Jane Doe.md"}], "unknown_people": []}]
```

   The Tom Lee chat → one record `Administrator/Teams/2026-08-22 Tom Lee.md` (`created`, `people: [{"name": "Tom Lee", "page": "…/People/Tom Lee.md"}]`).

   Per record the `wiki` skill's steps: `vault_wiki_match(text="Q3 budget — Morning — can we move the numbers deadline to Friday 29 Aug? …", limit=8)` → `Topics/q3-budget`; `vault_wiki_read("Administrator/Wiki/Topics/q3-budget.md", sections=["lead","facts"])` → facts `7k2q` "Deadline for the user's numbers is 2026-08-27" (since 2026-08-20), `c3mm` "Numbers go into the shared sheet …". `Topics/acme-supplier-contract` read once for the Tom chat, the meeting note and Tom's mail: fact `n30x` "Payment terms are net 30" (since 2026-08-12).

   Order by time: Tom's mail (Sat 22 09:05), Tom's chat (Sat 22 11:02), the supplier sync (Sat 22 13:00), the Q3 chat of Mon 24, Jane's mail (Tue 25 08:50), the Q3 chat of Tue 25. Tom's mail repeats net 30 on the 22nd; the meeting note the same day says net 45 — same day, so `contest`, not `supersede`.

   Proposal (the turn ends here):

   > **Topics/q3-budget** — deadline 27 → 29 Aug (supersede, Teams chat Mon 24); forecast closes 2 Sep (add, chat Tue 25, confirmed by Jane's mail); open: return the numbers by 29 Aug.
   > **Topics/acme-supplier-contract** — net 30 vs net 45 (contest: Tom's mail and the supplier sync, both Sat 22); open: sign v3 by 29 Aug; Tom's delivery schedule due Wed 27 (add, meeting).
   > **People/Jane Doe** — confirm "owns the forecast"; lead unchanged. **People/Tom Lee** — role on the contract: raises the PO (add).
   > **Review** — 1 expected (net 30 / net 45).
   > Apply these? (name a line to drop it)

   User: "yes, but drop the Tom role line".

6. Ingest, oldest first — six calls, the first one:

```
vault_wiki_ingest(record_path="Administrator/Emails/2026-08-22 Q3 supplier contract – signature needed.md", created_by="administrator/0.3.0", pages=[
  {"path": "Administrator/Wiki/Topics/acme-supplier-contract.md", "ops": [
    {"op": "contest", "id": "n30x", "text": "Payment terms are net 45 (contract v3)"},
    {"op": "open", "text": "Sign and return contract v3 by 2026-08-29"}]},
  {"path": "Administrator/Wiki/People/Tom Lee.md", "ops": []}])
```

   → `pages[0].applied: [{"op": "contest", "id": "n30x", "review": 1}, {"op": "open"}]`, `pages[1].record_added: true`. The chat records go in with no `src` on the ops (it defaults to the `record_id`); the Mon 24 chat carries the `supersede` on `7k2q` with `since: "2026-08-24"`, the Tue 25 chat the `add` of the close date, Jane's mail a `confirm` on it.

7. Stamps:

```
vault_collect_sources(action="advance", source="teams", at="2026-08-25T17:40:31+02:00")
vault_collect_sources(action="advance", source="outlook", at="2026-08-25T17:40:48+02:00")
vault_collect_sources(action="advance", source="notes", at="2026-08-25T17:41:15+02:00")
```

   each → `{"advanced": ["<source>"], "refused": []}`.

8. Blocks. `outlook_list_events(start="2026-08-25T00:00:00", end="2026-08-25T23:59:59", include_recurrences=true, limit=50, fields=["subject","start","end","occurrence_key"], response_format="json")` → two of five events start with the prefixes: `[Focus] ACME supplier contract` 09:00–10:30 (`occurrence_key: "0400…|2026-08-25T09:00:00+02:00"`), `[Admin] Email and small tasks` 14:00–14:45. `vault_find("time-block", {"week": "2026-W35"}, fields=[])` → found; `vault_read("Administrator/Time-blocks/2026-W35.md")` shows no Held row for either key. Question (nothing else in that turn): "Today's blocks: 09:00–10:30 [Focus] ACME supplier contract, 14:00–14:45 [Admin] Email and small tasks — held, moved or skipped? (a word each, a note is welcome)". User: "held, skipped — the sync ran over".

```
vault_append_row(path="Administrator/Time-blocks/2026-W35.md", section="Held", row=["Tue 25 Aug", "[Focus] ACME supplier contract 09:00–10:30", "held", ""],
                 dedupe_key="0400…|2026-08-25T09:00:00+02:00", key_label="occurrence_key", header=["Day","Block","Result","Note"])
vault_append_row(path="Administrator/Time-blocks/2026-W35.md", section="Held", row=["Tue 25 Aug", "[Admin] Email and small tasks 14:00–14:45", "skipped", "the sync ran over"],
                 dedupe_key="0400…|2026-08-25T14:00:00+02:00", key_label="occurrence_key", header=["Day","Block","Result","Note"])
```

   both → `{"appended": true}`.

9. Report:

> Teams: 2 chats, 5 messages → 3 chat records created. Outlook: 27 mails seen, 2 saved (also worth saving: Offsite venue options, Invoice 4471, Parking permit renewal). Notes: 4 changed, 1 meeting note ingested. Pages: Topics/q3-budget (deadline superseded, close date added, 1 open), Topics/acme-supplier-contract (1 contested, 2 open), People/Jane Doe, People/Tom Lee (records). Review: 1 open — `/administrator:wiki resolve review`. Blocks: 1 held, 1 skipped.
> Last collected: Tue 25 Aug 17:41.
> obsidian://open?vault=Vault&file=Administrator%2FWiki%2FTopics%2Fq3-budget.md
> obsidian://open?vault=Vault&file=Administrator%2FWiki%2FTopics%2Facme-supplier-contract.md
> Tokens this turn: 21 480

## Example 2 — Teams not available, nothing to ask

Same vault the next morning, `/administrator:collect-information today` on Wed 26 Aug 09:05 in a Claude Code session started from a laptop where the `teams` extra is not installed.

1. `vault_collect_sources(action="read")` → `ask: false` (every stamp 15.4 h old), `default_since: "2026-08-25T17:40:31+02:00"`. The argument `today` sets `since = "2026-08-26T00:00:00+02:00"` and no question is asked.
2. The `teams_*` tools are there; `teams_status()` → `{"reader_installed": false, "cache_found": true, "hint": "install the `teams` extra: `uv sync --extra teams` in the checkout, then restart Claude Code"}`. One line in the report, the Teams stamp is left alone.
3. `outlook_list_mails(folder="inbox", since="2026-08-26T00:00:00+02:00", …)` → 3 items, all automated; `folder="sent"` → 0. No `vault_wiki_match` call, nothing saved.
4. `vault_changed_notes(since="2026-08-26T00:00:00+02:00")` → `{"count": 0, "total": 0, "notes": []}`.
5. Nothing to propose, so the proposal turn is skipped and the user is told so.
6. No ingest.
7. `vault_collect_sources(action="advance", source="outlook", at="2026-08-26T09:05:20+02:00")` and the same for `notes`; `teams` is not advanced.
8. `outlook_list_events(start="2026-08-26T00:00:00", end="2026-08-26T23:59:59", …)` → one `[Focus] Q3 budget` block at 09:00–10:30, still running now. `vault_read("Administrator/Time-blocks/2026-W35.md")` shows no Held row for it. Question: "Today's block: 09:00–10:30 [Focus] Q3 budget — held, moved or skipped?". User: "still on it, ask me later". No row is written.
9. Report:

> Teams: not read — install the `teams` extra: `uv sync --extra teams` in the checkout, then restart Claude Code. Outlook: 3 mails seen, all automated, none saved. Notes: nothing changed since midnight. Wiki: no changes proposed. Blocks: 1 unanswered.
> Last collected: Wed 26 Aug 09:05 (Teams still Tue 25 Aug 17:40).
> Tokens this turn: 3 910
