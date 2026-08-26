---
name: find
description: Finds one email (or thread) from a plain-language description — "the email where we agreed on the Q3 budget with Sam", "the spreadsheet Maria sent with vendor pricing last month", "which email had the venue options". Reads the sentence into people, topic words, dates and an attachment hint, then makes ONE `outlook_find` call (the server runs the folder loop, dedupes by thread, ranks and returns ten snippets), adds `outlook_search_attachments` / `outlook_advanced_search` only on an attachment hint, opens at most two threads to quote the exact line, and shows up to 3 candidates with who / date / subject / the matching line / attachment names / an existing note link. Offers `/soma:save` on the winner. Hard cap 6 `outlook_*` calls. Trigger on "/soma:find", "find the email where", "which email had the", "where did X say", "the mail from X about", "the attachment Y sent", "did we ever agree on", "look for the thread about". Read-only in Outlook; writes nothing.
---

# find — one email from a sentence

The user describes an email the way they remember it. You turn the sentence into a small search object, the server does the searching and ranking, you read ten snippets and quote the line that matters. Outlook is read through the `outlook_*` tools, the vault through `vault_*`; nothing is changed or written. Outlook mechanics (`response_format`, `fields`, dates, `entry_id`) follow the `outlook` skill and `skills/soma/references/outlook.md`.

Load `references/search-plan.md` when the workflow starts (parsing rules, when to widen, the call cap). Worked runs are in `references/examples.md`; load it only when a step is unclear.

Before the first run in a session: `vault_status` once, `outlook_whoami(response_format="json")` once (the user's own address tells "sent by me" apart; `local_time` anchors "last month").

## The run

| Step | What | `outlook_*` calls |
| --- | --- | --- |
| 0 | Read the sentence into `{people, words (2–4), since, until, attachment, folders}` as `references/search-plan.md` says. Pass names as the user said them — `outlook_find` matches names as well as addresses; do not call `outlook_resolve_name` first. No words and no people → ask one question and stop. | 0 |
| 0b | One call: `vault_wiki_search(query=<the sentence>, brief=true, max_chars=1200)` → `{text, pages: [{page, title, kind, status, verified}], facts: [{page, id, text, since}], chars}`. A sentence the wiki answers ("did we ever agree on…") is answered from that text first, quoted as it stands, with the link of the page it came from. The record behind it: `vault_wiki_read(path=<the page it came from>, sections=["records"], max_chars=800)` gives the `## Records` lines, each checked with `vault_find` for the note. Only when the wiki does not hold the line the user wants, go on to step 1 with the `title` of each entry in `pages[]` added to `words`. Vault calls are free and do not count toward the cap. | 0 |
| 1 | `outlook_find(people=[…], words=[…], since, until, folders=["inbox","sent"] or the folders the user named, limit=10)` — one call. It searches every folder, merges by conversation, scores (person > words > date fit) and returns `items[]` best first with `snippet` (the sentence that holds the most search words) and `score`. | 1 |
| 2 | Only when step 0 set `attachment`: `outlook_search_attachments(query=<the one pattern>, folder="inbox", since, limit=20, include_subfolders=true)` and `outlook_advanced_search(query=<words>, scope="all", since, limit=20, timeout_sec=20)`. Their hits join the list; a hit already in step 1's items (same `entry_id` or `conversation_id`) gets an attachment mark instead of a second row. | 0–2 |
| 3 | Widen, only when step 1 (plus 2) gave fewer than 1 usable hit, or every hit's `snippet` misses the topic: one more `outlook_find` with fewer words, wider dates or extra folders — the rules in `references/search-plan.md`. Never a third. | 0–1 |
| 4 | Read the snippets. Pick the top 3 by `score`, ties to the newer `received`. When a `snippet` already answers the sentence, quote it and stop reading. Otherwise `outlook_get_conversation(entry_id, include_body=true, max_body_chars=3000, limit=10, trim_quoted=true, fields=["from_address","received","body_trimmed"])` on **at most 2** threads and quote from `body_trimmed`. | 0–2 |
| 5 | For each candidate you will show: `vault_find("email", {"internet_message_id": "", "entry_id": <entry_id>})` → a note link when found (vault calls are free and do not count). | 0 |

Hard cap: **6 `outlook_*` calls** per run, every tool counted. At the cap, show what you have and say which step was cut short. Zero hits after widening is an answer: say what was searched (folders, window, words) and suggest one change.

`outlook_extract_attachment_text(entry_id, index, max_chars=4000)` only when the question is about what the file contains and the body only points at the attachment; one file, top candidate only, counts toward the cap.

## Output

Up to three candidates, best first:

```
1. Sam Ortiz → me, 2026-06-12 14:05 — Re: Q3 budget — wrap-up
   "Agreed then: Q3 budget stays at 180k, with the 15k contingency held by finance."
   Attachments: Q3_budget_v4.xlsx
   Note: [[Emails/2026-06-12 Q3 budget — wrap-up]]
   obsidian://open?vault=MyVault&file=Soma%2FEmails%2F2026-06-12%20Q3%20budget%20%E2%80%94%20wrap-up
2. …
```

When step 0b found a page, one line comes first: `Wiki: [[Wiki/Topics/q3-budget]] — <lead sentence that answers>` (verbatim from the page), then the candidates.

Line 1: who → whom (display names; "me" for the user), `received` as local date and time, subject with reply prefixes kept; `from_address` is the user's own → "me → …". Line 2: the quoted sentence, exact words, one or two sentences. Line 3 only when there are attachments (filenames from `matches[]`). Line 4 only when a note exists: the wikilink plus an `obsidian://open?vault=<vault_status.vault_name>&file=<path, URL-encoded>` link (`skills/soma/references/obsidian.md`).

Then one line: `Save #1 as a note? (/soma:save <entry_id>)` — for the winner only, skipped when it already has a note. Say nothing is saved until they answer. `find` never calls `vault_write`; saving is the `save` skill's job after a yes.

## Rules

- Read-only: no `outlook_mark_mail`, `outlook_move_mail`, `outlook_save_*`, `outlook_send_mail`, `outlook_reply_mail`, no `vault_write`, no `vault_row`, no `vault_wiki_write`.
- Quote, do not summarise. When no snippet or body sentence holds a search word, quote the first sentence of the newest message and say "closest match".
- The snippet is the server's best sentence, not proof: read the thread when the snippet is a greeting, a signature line or says "see below".
- `outlook_advanced_search` returning nothing proves nothing (unindexed store; `count: 0` with `timed_out: false`); say "not found in the index", never "does not exist".
- `outlook_find` candidates are the newest mail per thread, which can be the user's own reply; the person points are then missing and the score is lower than it looks — read `from_address` before ranking by hand.
- Never pass `fields` or `preview_chars` to `outlook_find` (it has neither); always pass `fields` to `outlook_get_conversation`.
- No raw JSON. Three candidates at most, even when there are ten hits.
- End with the turn's token count when the host shows it; otherwise say nothing about it.
