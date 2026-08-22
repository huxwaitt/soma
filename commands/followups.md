---
description: Find threads where you wrote last and nobody has answered for N days, update Follow-ups.md (open new rows, close answered ones), and offer short nudge emails that go to Drafts only.
argument-hint: "[days]"
---

# /administrator:followups

Argument (optional): `days` — how long a thread must have been quiet to count. Default 3.

Argument given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `review` skill. Load the `outlook` skill if it is not already loaded.
2. Call `vault_status` (run `vault_init(created_by="administrator/0.0.4")` if anything is missing) and `outlook_whoami(response_format="json")` for the user's own address(es) and local time.
3. `outlook_list_mails(folder="sent", since=<now − 30 days>, limit=100, response_format="json")`, one more page with `offset=100` if `has_more`. Skip calendar responses, auto-replies and read receipts.
4. Newest first, one `outlook_get_conversation(entry_id, include_body=true, max_body_chars=2000, limit=50)` per thread not yet covered by an earlier result; at most 60 conversations.
5. A thread is waiting when its last message is from the user, is at least `days` old, and went to someone other than the user. For each: `outlook_get_mail(entry_id, include_body=false, response_format="json")` for the recipients' SMTP addresses; the last line the user wrote from the trimmed body.
6. Show the table: who, subject, days waiting, last line written — longest wait first.
7. `vault_read("Administrator/Follow-ups.md")`. For each waiting thread not already in `## Open` (by key comment, or by the same `Who` + `What`): `vault_append_row(..., "Open", [since, who, what, email link or empty, today], dedupe_key=<internet_message_id of the user's last mail, else entry_id>, key_label=...)`. For each `## Open` row whose key belongs to a thread where someone else wrote last: `vault_move_row(..., "Open", "Done", <key>, set_last_cell=<reply date>)`.
8. Offer nudge drafts one at a time (2–3 sentences: the original subject and date, the ask, a question). Only on a clear yes per draft: `outlook_send_mail(to=[...], subject="Re: <subject>", body, save_only=true)`. Nothing is ever sent; "no" skips one, "skip all" stops.
9. Report threads checked, waiting count, rows opened / already listed / closed, drafts saved, and an `obsidian://open` link to `Administrator/Follow-ups`. No other Outlook change.

## Example

```
/administrator:followups
/administrator:followups 5
```

On 2026-08-22, 39 sent mails in 23 threads; three are waiting (Tom Lee 6 days, Priya Nair 4, Bob Lee 3). Tom's thread is already in `Follow-ups.md` (written by `prep`); Priya and Bob get new rows; Carol Ng's row moves to Done because she replied on 2026-08-22. Two drafts saved after two yeses.

> 23 threads checked from 39 sent mails. 3 waiting longer than 3 days. Follow-ups: 2 rows added, 1 already listed, 1 closed (Carol Ng replied on Contract draft, 2026-08-22). 2 nudge drafts saved to Drafts; nothing sent.
> obsidian://open?vault=MyVault&file=Administrator/Follow-ups

The full worked example is in `skills/review/SKILL.md`.
