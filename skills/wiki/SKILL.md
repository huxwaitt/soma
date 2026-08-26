---
name: wiki
description: Keeps the vault's internal wiki — one page per person, organisation, topic (a subject with a timeline and an outcome) and how-to under `Administrator/Wiki/`, written only through the `vault_wiki_*` tools. Load it for the ingest step at the end of `save`, `notes`, `weekly` and `collect-information` (the record is written first, then its facts go onto the pages they belong to), for the read step in `prep`, `find` and `draft`, and for `/administrator:wiki` (read a page, answer a question from the wiki, add or change a fact from chat, ingest an older record) and `/administrator:lint` (the fixed checklist). Trigger phrases: "what does the wiki say about", "what do we know about X", "add to the wiki", "the deadline moved to", "close the topic", "lint the wiki", "ingest that note". Never edits a page file by hand; every change is an op applied by code.
---

# wiki — facts on pages, records stay records

Records (`Emails/`, `Meetings/`, `Teams/`, `Daily/`, `Weekly/`) are never edited. The wiki holds what is *currently true* about the people, organisations, topics and procedures those records mention. The model decides which facts a record adds, changes or confirms; code keeps the pages, the index (`Wiki/Index.md`), the log, and the review queue (`Wiki/Review.md`). The full page contract, op list and refusal meanings: `references/wiki.md` (also in the vault as `Wiki/Wiki.md`). Worked runs with exact calls: `references/examples.md` — load it the first time an ingest runs in a session.

Skip phrase: "save without wiki" (or "no wiki") on any command → write the record, skip the ingest, say so in one line.

## Where a fact goes (the placement table, in order)

1. A step-by-step way of doing something → `howto`.
2. One person's role, responsibility, preference, or how they work with the user → `person`.
3. A company or team as a whole (contract, address, policy, who does what there) → `org`.
4. Something with a timeline and an end state (deadline, decision, deliverable, problem being resolved) → `topic`.
5. Anything else is not wiki material. It stays in the record and is reachable through `find`.

The page for the *subject* holds the fact; other pages link to it. A `topic` page is created only when the same subject appears in 2+ records on 2+ different days (code tracks candidates and says when one crosses the line), or when the user names it. One-off mails never become pages.

## Ingest (after a record is written)

1. `vault_wiki_match(text=<subject + first 300 chars>, people=[<sender or attendee addresses>], domains=[<sender domains>], limit=8)` → `{pages: [{path, line, score, why}], candidates: [{subject, records, days, over_threshold}]}`: index lines of matching pages (`why`: alias, address, words, domain) plus topic candidates over the threshold with no page.
2. `vault_wiki_read(path, sections=["lead","facts"])` for at most 3 matched pages → `{path, title, frontmatter, lead, facts: [{id, text, since, src: [...]}]}`; use those ids, never invent one. A merged page answers with its target and `redirected_from`.
3. For each matched page, compare the record with the Facts list. Emit ops only for what the record adds, changes, or confirms. One bullet per claim, at most 25 words, present tense, no hedging, with `since` from the record date unless the text states another date. Do not restate the record's summary; do not add facts the record does not contain. A fact you cannot place with the table above stays out.
4. One call: `vault_wiki_ingest(record_path=<path>, pages=[{path | new: {type, title, aliases, lead, summary}, ops: [...]}], created_by="administrator/0.4.0")`. `src` and `since` default to the record's id and date (`internet_message_id`, `occurrence_key`, or a chat record's `record_id` = `<chat_id>|<date>`), so leave them out unless the text states another date. An empty op list is fine: code still adds the Records and History lines. The result is `{record, pages: [{path, written, applied: [{op, id, …}], refused: [{op, reason, …}], record_added, history_added, sizes}], candidate}`; refusals are answers, not errors (see below). The record gets a `wiki:` key linking the pages.
5. A candidate over the threshold with no page (`candidates` from the match, or `candidate.over_threshold` in the ingest result): propose the page in the same turn ("Create topic `q3-budget` from these 2 records?"); create it with `vault_wiki_create(type, title, aliases, lead, summary, facts=[{text, since, src}], src, created_by, extra={email | domains | owner, org, due})` only on a yes, or right away when the user named the subject.

## Ops

Fact ops, every one with `src` (the record's `internet_message_id` / `occurrence_key` / `record_id` for a chat, or `user`): `add` (text, since, src), `update` (id, text, src — better wording, same claim), `supersede` (id, text, since, src — the claim changed; old text moves to History), `confirm` (id, src — the source repeats a known fact), `retire` (id, src, reason — no longer true, no replacement), `contest` (id, text, src — contradiction you should not resolve alone; goes to Review).

Page ops: `lead` (text, ≤ 80 words, 2–4 sentences — the one text the model rewrites freely; a `draft` page becomes `active`), `summary` (text, ≤ 160 chars; the index line), `status` (value: `active` / `dormant` / `closed`), `title` (text), `alias` (text; add only), `related` (page), `role` (page, role ≤ 4 words), `open` (text, src), `steps` (text; howto only; whole section), `due` (value, topic only), `owner` (value), `org` (value). Ops without `src` are refused except `lead`, `summary`, `title`, `related`, `role` (at ingest `src` defaults to the record, so this only matters for `vault_wiki_apply`, where it defaults to `user`).

Pick the op by this rule: same claim, same meaning → `confirm`; same claim, clearer wording → `update`; the claim changed and the record is newer → `supersede`; the claim changed but the record is older or same-day, or you are unsure → `contest`; new claim → `add`.

## Refusals and what they mean

| Refusal | Meaning | What to do |
| --- | --- | --- |
| `older-than-current` | Your `supersede` carried a `since` before the current fact's `since`. Code wrote the pair to Review instead. | Nothing; say "older source, sent to Review". |
| `user-pin` | The fact has `src:user`; a record may not supersede, update or retire it. Routed to Review. | Say so; the user resolves it. |
| `cap` (with `lines`, `chars`, `max_lines`, `max_chars`) | The page would exceed its line/char cap; none of the ops were written. | Send a smaller op set: supersede or merge facts, move detail to a new page with a one-line pointer, or close the page. |
| `facts-cap`, `fact-too-long`, `lead-too-long`, `summary-too-long`, `role-too-long`, `title-too-long` | 26th fact; fact over 25 words; lead over 80 words; summary over 160 chars; role over 4 words; title over 6 words. Only that op is dropped. | Shorten and resend that op. |
| `unknown-id` | The id is not on the page (`known` lists the ids). | Re-read the page; use the returned ids. |
| `duplicate` | An `open` item with the same text is already on the page. (An `add` whose text equals an existing fact is not refused: it is applied as `result: confirm`.) | Nothing. |
| `no-such-page`, `self-link`, `wrong-type`, `bad-status`, `bad-date`, `bad-text`, `missing-text`, `unknown-op` | The `page` of a `related` / `role` / `owner` / `org` op does not exist or is the page itself; `steps` on a non-howto or `due` on a non-topic; a status outside active / dormant / closed / draft; a `since` / `due` that is not `YYYY-MM-DD`; text holding `<!--` or a heading; empty text; an op name not in the list. | Fix the op. |
| `verify-failed` (with `problems`; the page's `written` is `false`) | The page did not read back as it was written, so its previous text was put back and none of the ops stand. | Say the page was left as it was and that a Review line names what differed. Do not resend the same ops blindly. |
| `exists` (`vault_wiki_create`, `created: false`) | A page with that title, alias or address exists; `path` and its index line (`match`) are returned. | Use that page. |

Setting a code-owned key (`created`, `updated`, `verified`, `sources`, `open_items`, `flags`) in `vault_wiki_create(extra=…)` or an ingest `new` spec is a tool error, not a refusal: drop the key and call again.

## Read step (prep, find, draft, a question in chat)

One call, not a match and three reads: `vault_wiki_search(query=<the question in the user's own words>, brief=true, max_chars=1200)` → `{text, pages: [{page, title, kind, status, verified}], facts: [{page, id, text, since}], chars}`. The `text` is the answer material — the best three pages with their lead, their facts (each with `f:<id>` and its date), their open items, then the dated decisions on the pages they link to. Answer from it before searching Outlook: quote facts as they stand, never reworded, each with the link of the page it sits on. Empty `text` → say the wiki has nothing on this yet and go on.

Leave `brief` out to get the facts as a list: `vault_wiki_search(query, kinds=["topic"], limit=10, since=<ISO date>, page=<one page>)` → `[{page, kind, title, fact_id, text, since, src, score, why[], superseded, streams, confirmed}]`, best first, at most three facts per page. Ids, dates, amounts, `"quoted phrases"` and `/regex/` are matched as written, so `f:7k2q` or `2026-08-29` finds its fact; a misspelled name still finds the person. `include_superseded=true` also answers with wordings that were replaced (`superseded: true`, always ranked below the current fact). `open_items=true` answers with the unticked `## Open` lines as `[{page, title, text, record, line}]`. `## Notes` is never read.

Never read `Index.md` or `Log.md` whole — `vault_wiki_match` and `vault_wiki_log(since, page, limit)` return slices.

## Rules

- Pages change only through `vault_wiki_*`. Never the host file tools, never `vault_write` on a wiki path.
- Nothing is deleted; a wrong fact is superseded, retired, or contested. Contradictions go to Review, never resolved silently.
- `## Notes` on any page belongs to the user. Do not read it for facts unless `draft` needs voice lines; never write it.
- Merges (`vault_wiki_merge(keep, drop)`) and topic creation from a lint proposal happen only after a yes.
- An answer carrying `adopted: [{page, changes}]` means the user edited pages by hand in Obsidian and the code read those edits back; say so in one line ("read back your edits to Topics/q3-budget: 1 new fact, 1 fact changed") before the rest of the reply. `vault_wiki_search`'s list answers come back as `{hits, adopted}` when there was anything.
- Every reply that changed pages lists them with `obsidian://open` links, one per page, plus the Review count when it grew.
