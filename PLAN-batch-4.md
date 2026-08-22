# Batch 4 plan — find, draft, attachments (administrator 0.0.5)

Four agents, one pass. Nothing else.

## 1. `draft` skill — reply in the user's voice (plugin)

`/administrator:draft <thread | search words> [intent]`
- `outlook_get_conversation(trim_quoted=true)` on the thread; person note for the sender; the user's last 20 sent mails to that person (or in general) as the voice sample — sign-off, greeting, sentence length, formality.
- Writes the reply body, shows it, and on a yes saves it with `outlook_send_mail(save_only=true)` (reply-all recipients built from the thread). Never sends. Reply-in-thread needs a server addition: `reply_mail(save_only=true)` so the draft keeps the conversation headers — add it (small).
- Also used by `followups` (nudges) and `notes` (minutes) so there is one voice rule set.

## 2. `find` skill — "the email where we agreed on X with Sam" (plugin)

`/administrator:find <sentence>`
- Pull out: people (→ SMTP via `resolve_name`/`search_contacts`/People notes), topic words (2–4, with synonyms), time hints, attachment hints ("the spreadsheet", "the PDF").
- Search plan, run in order until enough candidates: `search_mails` scope `from` and `subject_body` in Inbox, Sent, then sub-folders (`list_folders` once, cached in the daily note); `outlook_advanced_search` (below) for body/attachment text; `search_attachments` for filename hints.
- Rank: people match > topic words in `body_trimmed` > date fit. `get_conversation` on the top 3, read trimmed bodies, quote the exact line that answers the sentence.
- Output: 1–3 candidates with who / when / the matching line / attachment names, `obsidian://` link if a note already exists, offer `save`.

## 3. Server: attachment search + indexed search

- `outlook_search_attachments(query, folder="inbox", since, limit=50, include_subfolders=true)` — iterate mails with `has_attachments`, match `Attachments[i].FileName` (case-insensitive, words or glob), return mail summary + matching attachment `{index, filename, size_bytes}`.
- `outlook_advanced_search(query, scope="all", since, limit=50, timeout_sec=20)` — `Application.AdvancedSearch(scope, "@SQL=... ci_phrasematch ...", True, tag)`; wait on `AdvancedSearchComplete` (or poll `Search.Results.Count` until stable) inside the STA thread; returns mail summaries. Uses Windows Search, so attachment *contents* (PDF/Word/Excel) match. Gotcha entry: needs Outlook indexing on; returns nothing for unindexed stores; result order is not by date — sort ourselves.
- Fallback tool `outlook_extract_attachment_text(entry_id, index, max_chars)` — save to a temp dir under the profile, extract text (pdf via pypdf, docx via zipfile+xml, xlsx via openpyxl read-only, txt/csv raw), delete the temp file. Optional deps in a `[search]` extra.
- `reply_mail(save_only=true)` for the draft skill.
- Tests with fakes as before. Tool count goes 40 → 44.

## 4. Reviewer + verifier as in batch 3.

Out: cleanup, rules suggestions, email→task. Build only if asked after use.

---

# v0.5 — token budget and determinism

Principle: the model should decide, not transport. Every byte that is only moved from Outlook to the vault, or compared, or formatted, should go through code. Target: each command under ~15k tokens for a normal day; today `inbox` on 100 mails is 60–100k because the model reads every preview and writes every row.

## Per workflow

| Workflow | Where tokens go today | Deterministic replacement |
|---|---|---|
| `inbox` | Model reads 100 summaries, writes a 100-row table by hand, greps the vault for duplicates | Server: `list_mails` gains `fields=[...]` to return only `entry_id, from_address, subject, received, preview(80)`. Vault: `vault_inbox_prepare(since)` returns the list already minus mails seen in earlier daily notes and minus `never_save` matches. Model only emits `{entry_id: label, reason}` JSON; `vault_write_daily(labels)` renders the table. Pre-labelling by rules (sender in People with status fyi, newsletter headers `List-Unsubscribe`, auto-replies, meeting responses, "noreply@") happens in code before the model sees anything; the model labels only the remainder. |
| `save` | Full body + quoted history + model re-writes the body into the note | `body_trimmed` always; note body is copied by `vault_write` from the tool output, the model only supplies summary + action items (≤ 80 tokens). Attachments/person stubs handled inside one `vault_save_email(entry_id)` call that fetches, trims, writes, links. |
| `daily` | Runs inbox + lists events + formats | Calendar section rendered by `vault_write_daily` from `list_events` JSON; model adds only the "watch out" bullets. |
| `prep` | Five tool calls per meeting, whole threads read | Server: `get_conversation(fields=..., last_n=3, trim_quoted=true)`. Vault: `vault_prep_context(occurrence_key, attendees)` returns existing note, previous occurrence's open actions, follow-up rows, person summaries in one call. Model writes the Prep bullets only. |
| `notes` | Transcript pasted through the model twice (input + written back) | Transcript goes to disk via the host Write tool once; `vault_attach_transcript(path)` parses speakers, counts turns, builds the callout. Model extracts decisions/actions from the transcript (unavoidable) but does not re-emit the text. |
| `free` / `schedule` | Free/busy slots as JSON | Already code-side. Add `fields` to return only candidate times, not the per-person slot arrays (those are 30-min granules for 5 days × N people = thousands of tokens). |
| `followups` | One `get_conversation` per sent thread, bodies included | Server: `outlook_awaiting_reply(days, since, limit)` does the whole computation in code (last item from me, no later reply) and returns only the waiting threads with the last line I wrote. Model writes nudges only. |
| `weekly` | Reads every daily/meeting/person note | `vault_weekly_facts(week)` computes open items, unchecked actions, quiet people in code; model writes the narrative (or none — a plain rendered note is fine). |
| `find` | Broad searches, many bodies | Search plan executed by code: `outlook_find(people, words, since, until)` runs the folder loop, dedupes by conversation, returns top 10 by score with the matching sentence extracted by regex; model reads 10 snippets, not 10 bodies. |
| `draft` | Voice sample = 20 full sent mails | Server: `outlook_voice_sample(address, n=10, trim_quoted=true, max_chars=300)` returns trimmed first paragraphs + sign-offs only. |

## Cross-cutting

- **Field selection everywhere**: `fields=` on list/search/get/conversation; `preview_chars`. Default JSON is the largest cost.
- **Skill text is a fixed cost per turn**: the five skills are 200–350 lines each and the core skill loads always. Move worked examples to reference files, keep SKILL.md under 120 lines, and have commands say which reference to load. Measure with `/context`.
- **Never re-read the vault through the model**: `vault_find`, `vault_list` return frontmatter only; add `fields=` there too.
- **Rules before model**: a small rule file (`Administrator/Rules.md`, parsed by the vault tool) for sender→label, domain→never_save, subject→fyi. Every rule hit is one mail the model never reads. Same mechanism gives the "suggest rules" feature for free: log what the model labelled, propose rules for senders it labelled the same way 5+ times.
- **Caching**: daily note stores `inbox_checked`; follow-ups stores `last_run`; `find` caches the folder list. No tool call repeats within a day unless asked.
- **Measurement**: each command ends with the token count of its turn from the host if available; log into the daily note frontmatter (`tokens_used`) so regressions are visible.

Expected effect: inbox 100 mails ~80k → ~10k; prep per meeting ~15k → ~4k; followups ~40k → ~5k.
