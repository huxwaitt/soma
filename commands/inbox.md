---
description: Go through the inbox, sort each mail into act / reply / waiting / fyi / noise, and have the vault render today's daily note. Offers (never runs) batch clean-up.
argument-hint: "[folder] [since]"
---

# /administrator:inbox

Arguments (both optional, in this order):

- `folder` — Outlook folder to read. Default `inbox`. Accepts a well-known name or a slash path (see the `outlook` skill).
- `since` — ISO-8601 date or datetime. Default: the `inbox_checked` value of the most recent daily note (`vault_list("daily", limit=1, fields=["date", "inbox_checked"])`; that note's date at 00:00 if the key is missing); if there is no daily note, 24 hours ago.

Arguments given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `inbox` skill (plus `inbox/references/examples.md` the first time this session). Load the `outlook` skill if it is not already loaded.
2. `vault_status` if not done yet this session. Vault unset or not a directory: stop and tell the user how to set `ADMINISTRATOR_VAULT` (see README) or to run `/administrator:setup`. Any folder or file flag false: `vault_init(created_by="administrator/0.4.0")`. `outlook_whoami(response_format="json")` once for the local time.
3. `outlook_list_mails(folder=<folder>, unread_only=true, since=<since>, limit=100, fields=["entry_id", "internet_message_id", "from_address", "from", "subject", "received", "preview"], preview_chars=80, response_format="json")`. Note the call time; it is `inbox_checked`. Page only if the user asks.
4. `vault_inbox_prepare(items=<items[]>, date=<today>)`. It drops what earlier daily notes this week already hold and what a never-save rule excludes, and fills `label` where a rule decided.
5. Label only the `to_label[]` entries with `label: null`, by the `inbox` skill's rules. Output one JSON list `[{entry_id, label, reason}]`, reasons of at most 12 words. `outlook_get_mail(entry_id, trim_quoted=true, max_body_chars=3000, fields=["subject", "body_trimmed"], response_format="json")` only where subject and preview cannot settle it, at most 5.
6. `vault_write_daily(date=<today>, labels=<the list>, since=<since>, inbox_checked=<call time>, folder=<folder if not inbox>, tokens_used=<this turn's token count if the host shows one>, created_by="administrator/0.4.0")`. The server renders the table, links existing notes, writes `## To do` / `## Waiting on`, adds the Follow-ups rows, and on a second run appends only new rows. Read `action`, `rows_written`, `followups_added`, `unlabelled` (label those and call again). When a fresh mail is a reply from the `Who` of an open follow-up, `vault_read("Administrator/Follow-ups.md")` once and `vault_move_row(..., "Open", "Done", <row key>, set_last_cell=<today>)`.
7. Report in a few lines: counts per label (rules and already-seen included), the `act` / `reply` subjects, Follow-ups rows added or closed, the note path, and `obsidian://open?vault=<vault_name>&file=<url-encoded path>`.
8. If one sender got the same label from you 5 or more times this run and `vault_rules(action="get")` has no row for it, propose one `Rules.md` line; only on a yes, `vault_append_row("Administrator/Rules.md", "Labels", [match, field, label])`.
9. Offer the batch changes as a numbered list with counts and subjects: mark fyi/noise read (`outlook_bulk_mark_mails(read=true)`), move noise (`outlook_bulk_move_mails` to a path from `outlook_list_folders`), tag by label (only names from `outlook_list_categories`), flag act (`flagged=true`). Run nothing without an explicit yes to a specific option. After one runs, report `failed` by subject and record it with `vault_write("daily", <frontmatter from vault_find>, "Done <ISO>: <what ran>", mode="append")`. Never delete, never send.
10. Close with the turn's token count in one line ("This turn: 9.8k tokens") when the host exposes it; when it does not, say nothing about tokens.

## Example

```
/administrator:inbox
/administrator:inbox Inbox/Invoices 2026-08-18
```

On 2026-08-22, 23 unread since Friday 18:02: 1 already in Friday's note, 2 never-save, 7 labelled by rules, 8 by the model (1 opened). One `vault_write_daily` call writes the 15-row note and one Follow-ups row.

> 23 unread since Fri 18:02: 1 already noted, 2 never-save, 7 by rules, 8 by me. act 1, reply 2, waiting 1, fyi 6, noise 5.
> To do: Sign the NDA by Friday (Jane Doe); Re: Q3 numbers (Tom Lee); Re: offsite dates (Bob Lee). Follow-ups: +1.
> Written: Daily/2026-08-22.md (created). This turn: 9.8k tokens.
> Open: obsidian://open?vault=MyVault&file=Administrator%2FDaily%2F2026-08-22.md
>
> 1. Mark 11 fyi/noise as read: Nightly build passed, Weekly status, … and 6 more. Go ahead?

The full run, call by call, is in `skills/inbox/references/examples.md`.
