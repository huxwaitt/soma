---
description: Collect what happened since the last run — Teams chats from the local client cache, new Inbox and Sent mail, and vault notes that changed — write the chat records (chats without work content are skipped and named) and the mails worth saving, show the wiki changes grouped by page, apply them after a yes (oldest record first), move the "last collected" stamps, then ask how today's [Focus] / [Admin] blocks went. Nothing in Outlook or Teams is changed.
argument-hint: "[since <date> | today]"
---

# /administrator:collect-information

Argument (optional): `since <YYYY-MM-DD>` or `today` to set the range up front; without it the range comes from the stamps, and the command asks when they are older than a day. Add "without wiki" to write the records and skip the proposal and the ingest.

Argument given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `collect-information` skill and its `skills/collect-information/references/examples.md`, then the `wiki` skill (plus `skills/wiki/references/examples.md` on the first ingest of a session). Load the `outlook` skill if it is not already loaded.
2. Once per session: `vault_status` (if `administrator_dir_exists` or any folder or file flag is false, `vault_init(created_by="administrator/0.3.0")` and mention `/administrator:setup`) and `outlook_whoami(response_format="json")` — `local_time` is "now", `accounts[].smtp_address` are the user's addresses, `current_user` and `accounts[].display_name` the user's own names.
3. `vault_collect_sources(action="read")`. When `ask` is true and no argument set the range, ask exactly "Last collected: <last_collected>. Collect since then, or just today?" and stop the turn. "Since then" → `since = default_since`; "just today" or `today` → today `00:00`; a date → that date `00:00`. One `since` for every source.
4. **Teams.** No `teams_*` tools, or `teams_status()` with `cache_found` or `reader_installed` false → one line with its `hint`, nothing else. Otherwise `teams_list_chats(since=<since>, include_messages=true, per_chat=20, max_chars=300, limit=15)`; a chat with `truncated` above 0 may be read whole with `teams_read_chat(chat_id, since=<since>, limit=100, max_chars=600)`, at most 3.
5. **Which chats matter.** Per chat with messages: `vault_wiki_match(text=<the messages joined, sender names included>, people=[], domains=[], limit=5)`, then the lead and facts of the hit pages before judging it — at most 3, `vault_wiki_read(path=<page>, sections=["lead","facts"], max_chars=800)` (these are the chat's page reads for step 8 too). Keep a chat that touches a matched page or candidate, or carries work content on its own (a decision, date, amount, ask, commitment, or a fact about a person's role); skip banter, jokes, thanks / ok chains, GIF or sticker exchanges, and name the skipped ones in the report in one line ("4 chats skipped: no work content — …"); they stay in Teams for `teams_search`. A fragment like "moved to the 29th" is read against the matched page's facts and becomes a `supersede` with the message time as `since`; a fragment that fits no page or candidate stays in the record only.
6. **Outlook.** `outlook_list_mails(folder="inbox", since=<since>, limit=50, preview_chars=80, response_format="json", fields=["entry_id","internet_message_id","subject","from","from_address","to","received","preview"])` and the same with `folder="sent"`. Skip plainly automated mail without a call; `vault_wiki_match(text=<subject + preview>, people=[<from_address>], domains=[<domain>], limit=3)` on the rest; open at most 8 with a page hit or a candidate (`outlook_get_mail(..., trim_quoted=true, fields=[...])` as in `save`) and write each with `vault_save_email(mail, summary, action_items, self_addresses, created_by="administrator/0.3.0")`.
7. **Notes.** `vault_changed_notes(since=<since>)`. Notes of type `email`, `meeting`, `chat` are records; daily, weekly and user-folder notes are not (a plain fact from one of them is a `vault_wiki_apply(path, ops, src="user")` line in the proposal).
8. **Records first.** `vault_save_chat(chat=<chat entry>, messages=<its messages>, self_names=<own names>, created_by="administrator/0.3.0")` per chat kept in step 5. Then per record the `wiki` skill's match and read steps (at most 3 `vault_wiki_read` per record; a chat reuses step 5's match and reads), ops drafted, records ordered by time. Chronology: a later record wins (`supersede`), an older one that disagrees goes to Review (`contest`), same time or unclear → `contest`.
9. **Proposal.** Show the changes as short bullets grouped by page, plus the Review items expected, and ask "Apply these? (name a line to drop it)". Nothing else in that turn; no `vault_wiki_ingest` before the answer. "No" leaves the records written and the stamps untouched. Skipped on "without wiki" or when there is nothing to propose (say so).
10. **Ingest.** One `vault_wiki_ingest(record_path, pages=[...], created_by="administrator/0.3.0")` per record, oldest first, with the agreed ops only; `src` and `since` default to the record (`internet_message_id`, `occurrence_key`, or the chat's `record_id`). Refusals are answers, not errors. A topic candidate over the threshold: ask in the report, create only on a yes.
11. **Stamps.** `vault_collect_sources(action="advance", source=<teams | outlook | notes>, at=<local ISO time that source was read>)` for each source that was read; a skipped source keeps its stamp.
12. **Today's blocks.** `outlook_list_events(start="<today>T00:00:00", end="<today>T23:59:59", include_recurrences=true, limit=50, fields=["subject","start","end","occurrence_key"], response_format="json")`; keep subjects starting with `[Focus]` or `[Admin]`. None, or no `Administrator/Time-blocks/<ISO week>.md` (`vault_find("time-block", {"week": <week>}, fields=[])`), or every key already in a `## Held` row of that note (`vault_read` once) → skip. Otherwise one question: "Today's blocks: <HH:MM–HH:MM subject, …> — held, moved or skipped?". Per answer: `vault_append_row(path="Administrator/Time-blocks/<week>.md", section="Held", row=["<Tue 25 Aug>", "<subject HH:MM–HH:MM>", "<held | moved | skipped>", "<note>"], dedupe_key=<occurrence_key>, key_label="occurrence_key", header=["Day","Block","Result","Note"])`.
13. **Report.** Six lines at most: Teams (with the skipped chats named), Outlook, Notes counts; pages changed with one `obsidian://open?vault=<vault_name>&file=<url-encoded path>` link each; Review count when it grew; "Last collected: <now as Thu 21 Aug 18:10>". Nothing in Outlook or Teams was changed; say so only when asked.
14. If the host shows the token count of this turn, add it as the last line of the report; otherwise say nothing about it. (This command writes no daily note, so there is no `vault_write_daily(tokens_used=…)` call here.)

## Example

```
/administrator:collect-information
/administrator:collect-information today
/administrator:collect-information since 2026-08-21
```

> Last collected: Fri 21 Aug 18:10. Collect since then, or just today?

After "since then", the proposal, a "yes" and the blocks answer:

> Teams: 3 chats, 8 messages → 3 chat records created; 1 chat skipped: no work content — Priya Nair. Outlook: 27 mails seen, 2 saved (also worth saving: Offsite venue options, Invoice 4471, Parking permit renewal). Notes: 4 changed, 1 meeting note ingested. Pages: Topics/q3-budget (deadline superseded, close date added, 1 open), Topics/acme-supplier-contract (1 contested, 2 open), People/Jane Doe, People/Tom Lee. Review: 1 open — `/administrator:wiki resolve review`. Blocks: 1 held, 1 skipped.
> Last collected: Tue 25 Aug 17:41.
> obsidian://open?vault=Vault&file=Administrator%2FWiki%2FTopics%2Fq3-budget.md

The full worked runs (one complete, one with Teams unavailable) are in `skills/collect-information/references/examples.md`.
