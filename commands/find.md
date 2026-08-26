---
description: Find one email or thread from a plain-language description — people, topic words, dates, attachment hints — and quote the line that answers it. One outlook_find call does the searching. Read-only; offers /soma:save on the winner.
argument-hint: "<sentence>"
---

# /soma:find

Argument (required): a sentence describing the email the way you remember it — who, what it was about, roughly when, and whether a file was attached.

Argument given: `$ARGUMENTS`

## Steps

1. Load the `soma` skill, then the `find` skill and its `references/search-plan.md` (`references/examples.md` only when a step is unclear). Load the `outlook` skill if it is not already loaded.
2. Call `vault_status` and `outlook_whoami(response_format="json")` once per session.
3. Read the sentence into `people` (names as written, no `resolve_name`), 2–4 topic `words`, `since` / `until`, one attachment pattern, folder names. No words and no people → ask one question and stop.
4. Wiki first, one call: `vault_wiki_search(query=<the sentence>, brief=true, max_chars=1200)`. What it answers is quoted first with the link of the page it came from; `vault_wiki_read(path, sections=["records"], max_chars=800)` on that page gives the records to check with `vault_find`. Stop there when the user has what they asked for. Otherwise add the `title` of each entry in `pages[]` to `words` and go on.
5. One call: `outlook_find(people, words, since, until, folders=["inbox","sent"], limit=10)`. The server runs the folder loop, merges by thread, ranks and returns ten `items[]` with a `snippet` each.
6. Attachment hint only: `outlook_search_attachments` (one glob or word set) and `outlook_advanced_search` (indexed text; empty on an unindexed store proves nothing). Mark hits that are already in the list.
7. Nothing usable: one more `outlook_find` with fewer words, wider dates or extra folders (`search-plan.md`, "Widening"). Never a third.
8. Read the snippets. Quote a snippet that answers the sentence as it is; otherwise `outlook_get_conversation(entry_id, include_body=true, max_body_chars=3000, limit=10, trim_quoted=true, fields=["from_address","received","body_trimmed"])` on at most 2 threads. `outlook_extract_attachment_text` only when the question is about what is in the file, one file, top candidate only.
9. `vault_find("email", {"internet_message_id": "", "entry_id": …})` for each candidate shown → note link when one exists.
10. Show up to 3 candidates: who → whom, date, subject, the quoted line, attachment names, note link. Offer `Save #1 as a note? (/soma:save <entry_id>)` unless the winner already has a note. Hard cap 6 `outlook_*` calls; zero hits is an answer with what was searched and one suggestion.
11. If the host shows the token count of this turn, end with one line `Tokens this turn: <n>`; otherwise say nothing about it. (`find` writes no daily note, so there is no `tokens_used` to pass on.)

Read-only: no Outlook change, no `vault_write`. Saving happens only through `/soma:save` after a yes.

## Example

```
/soma:find the email where we agreed on the Q3 budget with Sam
/soma:find the spreadsheet Maria sent with vendor pricing last month
/soma:find which email had the venue options for the offsite
```

"The email where we agreed on the Q3 budget with Sam": one `outlook_find(people=["Sam"], words=["q3","budget"], since="2025-08-22")` returns ten threads; the top snippet answers the sentence, so no thread is opened. One Outlook call.

> 1. Sam Ortiz → me, 2026-06-12 14:05 — Re: Q3 budget — wrap-up
>    "Agreed then: Q3 budget stays at 180k, with the 15k contingency held by finance."
>    Note: [[Emails/2026-06-12 Q3 budget — wrap-up]]
> 2. me → Sam Ortiz, 2026-06-11 17:30 — Q3 budget — numbers for Sam …
> 3. Jane Doe → me, 2026-06-03 09:14 — Q3 budget draft v2 …

The worked examples in full are in `skills/find/references/examples.md`.
