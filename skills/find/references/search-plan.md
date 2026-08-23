# Search plan — what `find` hands to `outlook_find`

`outlook_find(people, words, since, until, folders, include_subfolders, limit)` runs the folder loop, merges hits by conversation, scores them (person match > topic word in subject or body > date fit) and returns the best ten with a `snippet` each. The model's job is the object it receives, the decision to widen once, and the quote. Hard cap: **6 `outlook_*` calls** per run.

## Reading the sentence

| Key | What goes in | How |
| --- | --- | --- |
| `people` | Names or addresses the sentence names ("with Sam", "Maria sent", "from accounting") | Pass them as written — `outlook_find` matches display names and SMTP addresses. "Sam" is fine. Do not call `outlook_resolve_name`; if the hits show two different people with that name (two `from_address` values), ask which one and run again with the address. A team ("accounting") goes into `words` instead. |
| `words` | 2–4 topic words | Drop stop words, verbs like "agreed", "sent", "discussed", the people's names and the words "email", "mail", "thread". Keep the nouns the subject line would hold: "Q3 budget" → `["q3", "budget"]`; "vendor pricing" → `["vendor", "pricing"]`. Each word is searched on its own, so a synonym can be a fourth word (`"supplier"` next to `"vendor"`); more than four dilutes the score. |
| `since` / `until` | ISO dates from time hints | "last month" → first and last day of the previous calendar month; "in spring" → 1 March to 31 May of this year; "recently" → now − 30 days; nothing said → `since` = now − 12 months, `until` left out. Work out dates from `outlook_whoami.local_time`, never from a guess. Only a stated hint sets `until`; date fit scores only when `since`/`until` was passed. |
| `attachment` | One filename pattern, or empty | `outlook_search_attachments` takes **one** pattern per call: a glob when it holds `*` or `?`, otherwise words that must all appear in the filename. "the spreadsheet" → `*.xls*`; "the PDF" → `*.pdf`; "the deck", "the slides" → `*.pptx`; "the document", "the Word file" → `*.docx`; "the contract" → the word `contract`; a quoted or obvious filename → that filename. `*.csv` only when the sentence says csv. |
| `folders` | Folder paths, or the default | Default `["inbox", "sent"]`. "in my Invoices folder" → `outlook_list_folders(max_depth=4, response_format="json")` once per session (keep `items[].path` for later runs; it counts as one call) and pass the matching path(s). "I sent it" → `["sent"]` first, but keep `inbox` for the other side's replies. |

Show nothing yet. No words and no people ("that email") → ask one question and stop.

## Widening — one more `outlook_find`, never two

Widen only when the first call (plus the attachment calls) gave no usable hit — `count: 0`, or every `snippet` misses the topic and the subjects do not match either. Change **one** thing, in this order, and pick the first that applies:

1. **Fewer words.** Drop the most generic word (`update`, `meeting`, `numbers`, a month name); two words are the floor. Same dates, same folders.
2. **Wider dates.** `since` a further 12 months back, `until` left out. Same words.
3. **More folders.** `outlook_list_folders` once (see above) and add up to three folders whose path holds a word or a person's name or company (`Inbox/Projects/Q3`, `Inbox/Suppliers/Acme`), `include_subfolders=true`. Skip `Deleted Items`, `Junk`, `Drafts`, `Outbox`, `Sync Issues`, `RSS`.

One good hit is enough; do not widen to reach three. After the second call, stop searching whatever the count.

## The cap

Count every `outlook_*` call: `outlook_find` (1–2), `outlook_search_attachments` (0–1), `outlook_advanced_search` (0–1), `outlook_get_conversation` (0–2), `outlook_list_folders` (0–1), `outlook_extract_attachment_text` (0–1). Six is the most; a normal run is two or three. When a step would go past six, skip it and say so ("thread 2 not opened, call cap"). Vault calls (`vault_find`, `vault_status`) are free and uncounted.

Stop conditions, any one of them: the sentence is answered by a snippet; two threads were read; the second `outlook_find` is done; the cap is reached; the user answered a question with a narrower sentence (start over, counter reset).
