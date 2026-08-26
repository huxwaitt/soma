---
description: Find threads where you wrote last and nobody has answered for N days, open an item on the page of whoever owes you the answer (Follow-ups.md is written from those items), tick the ones that got a reply, and offer short nudge drafts that go to Drafts only.
argument-hint: "[days]"
---

# /administrator:followups

Argument (optional): `days` — how long a thread must have been quiet to count. Default 3.

Argument given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `review` skill and its `references/examples.md`. Load the `outlook` skill if it is not already loaded.
2. Call `vault_status` (run `vault_init(created_by="administrator/0.4.0")` if anything is missing) and `outlook_whoami(response_format="json")` for the user's own address(es) and local time.
3. `outlook_awaiting_reply(days=<days>, since_days=30, limit=50)` — one call; the server finds the threads where the user wrote last, nobody answered for `days`, and returns who, subject, days waiting and the last line the user wrote. Say so when `capped` is true.
4. Show the table: who, subject, days waiting, last line written — longest wait first, values as returned.
5. `vault_wiki_search(query="", open_items=true, owner="others")` once (load the `wiki` skill first). New waiting thread (no open item carrying that key as `src`, none with the same text on that person's page) → `vault_find("person", <to[0]>, fields=["name"])`, a `vault_write("person", …, mode="create")` stub when there is none, then `vault_wiki_apply(path=<the person page>, ops=[{"op": "open", "text": <subject>, "owner": "[[Wiki/People/<name>]]", "since": <last_sent date>, "src": <internet_message_id of the user's last mail, else entry_id>}], src=<the same>)`. Open items that matched nothing: an `entry_id` `src` is checked with one `outlook_get_conversation(include_body=false, fields=["entry_id","from_address","received"])` (at most 10) and ticked with a `done` op when someone else wrote last; an `internet_message_id` `src` within the 30-day scan is ticked as "no longer waiting"; everything else stays. No row is ever written into `Follow-ups.md` — the file is written from the pages.
6. Nudge drafts one at a time, voice from `outlook_voice_sample(address=<recipient>)` (at most 5 calls; a general sample is reused), body per the `draft` skill's nudge rules (2–3 sentences: subject and date, the ask, one question). Only on a clear yes per draft: `outlook_reply_mail(entry_id=<the user's own last mail>, body, reply_all=false, html=false, save_only=true)` — in Drafts, inside the thread. Nothing is ever sent; "no" skips one, "skip all" stops.
7. Report threads checked, waiting count, items opened / already listed / closed, drafts saved, and an `obsidian://open` link to `Administrator/Follow-ups`. No other Outlook change.
8. If the host shows this turn's token count, end with `Tokens this turn: <n>`; otherwise skip the line. This command writes no daily note, so there is no `vault_write_daily` call to pass `tokens_used` into.

## Example

```
/administrator:followups
/administrator:followups 5
```

On 2026-08-22, `outlook_awaiting_reply` checks 23 threads from 39 sent mails; three are waiting (Tom Lee 6 days, Priya Nair 4, Bob Lee 3). Tom's thread already has an open item on his page (written by `prep`); Priya and Bob get one each; Carol Ng's item is ticked because she replied on 2026-08-22. Two drafts saved after two yeses.

> 23 threads checked from 39 sent mails. 3 waiting longer than 3 days. Follow-ups: 2 items opened, 1 already listed, 1 closed (Carol Ng replied on Contract draft, 2026-08-22). 2 nudge drafts saved to Drafts; nothing sent.
> obsidian://open?vault=MyVault&file=Administrator/Follow-ups

The full worked example is in `skills/review/references/examples.md`.
