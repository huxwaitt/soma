---
name: wiki
description: Keeps the vault's internal wiki under `Administrator/Wiki/` - one page per person, organisation, decision, topic, how-to and one for the user, written only through the `vault_wiki_*` tools. Load it for the ingest step ending `save`, `notes`, `weekly` and `collect-information`, for the read step in `prep`, `find` and `draft`, for the open items other people owe (`Follow-ups.md` is written from them), and for `/administrator:wiki` and `/administrator:lint`. Trigger phrases: "what does the wiki say about", "add to the wiki", "the deadline moved to", "we decided to", "lint the wiki", "ingest that note". Never edits a page by hand; every change is an op applied by code.
---

# wiki - facts on pages, records stay records

Records (`Emails/`, `Meetings/`, `Teams/`, `Documents/`, `Daily/`, `Weekly/`) are never edited. The wiki holds what is *currently true* about the people, organisations, decisions, topics and procedures they name. The model decides which facts a record adds, changes or confirms; code keeps the pages, the index, the log, Review and `Follow-ups.md`. Page contract, ops and refusals in full: `references/wiki.md` (in the vault as `Wiki/Wiki.md`); worked runs: `references/examples.md`, on the first ingest of a session.

Skip phrase: "save without wiki" (or "no wiki") → write the record, skip the ingest, say so in one line. Open and done items still go, as an ingest with no fact ops.

## Where a fact goes (first match wins)

1. A person's role, responsibility, preference or way of working → `person`.
2. A company or team as a whole (contract, policy, who does what) → `org`.
3. A choice made that now stands ("we agreed", an approval) → `decision`.
4. A step-by-step way of doing something → `howto`.
5. The user's own role, duties and standing preferences → `me`.
6. Something with a timeline and an end state (deadline, deliverable, problem) → `topic`.
7. Anything else is not wiki material: it stays in the record, found by `find`.

**A topic with an owner and a due date is a project** - there is no project page; send `owner` and `due` as soon as a record names them (`candidate.suggest_due: true` means one named a day) and the index lists it under Projects. The page for the *subject* holds the fact, others link to it. A `topic` page is created only when the same subject appears in 2+ records on 2+ days (code counts, and says when) or the user names it.

## Ingest (after a record is written)

1. `vault_wiki_search(query=<subject + first 300 chars>, pages=true, people=[<sender or attendee addresses>], domains=[<sender domains>], limit=8)` → the index line of each matching page and the topic candidates that have none (`subject`, `records`, `days`, `over_threshold`).
2. `vault_wiki_read(path, sections=["lead","facts"])` on at most 3 matched pages → the lead and `facts: [{id, text, since, src}]`; use those ids, never invent one. Add `"open"` when the record closes or moves something owed.
3. Compare the record with each page's Facts; emit ops only for what it adds, changes or confirms. One bullet per claim, at most 25 words, present tense, no hedging, `since` from the record date unless the text says otherwise. Do not restate the summary or add what the record does not hold; an unplaceable fact stays out.
4. One call: `vault_wiki_write(record_path=<path>, pages=[{path | new: {type, title, aliases, lead, summary}, ops: [...]}], created_by="administrator/0.4.1")`. `src` and `since` default to the record's id and date (its `internet_message_id`, `occurrence_key`, or a chat's `<chat_id>|<date>`). An empty op list is fine: code still writes the Records and History lines. Back come `applied` and `refused` per page (refusals are answers, not errors), `candidate` and `confirmed_decisions`; the record gets its `wiki:` key.
5. **Second pass, same turn.** With the record still in front of you, answer one question: *which facts in it are not on the pages yet?* Read your ops, and the `refused` ones, against the record and list what is missing - a date, a name, a number, a promise. A non-empty list is a second, smaller `vault_wiki_write` with the same `record_path`, before you reply. Never ask whether the first was good, only what it left out. Every time in `collect-information` and `load-history`; in `save` and `notes` over 1500 characters.
6. A candidate over the threshold with no page: propose it in the same turn ("Create topic `q3-budget` from these 2 records?") and create it with `vault_wiki_write(pages=[{new: {type, title, aliases, lead, summary, facts, …}}], src, created_by)` on a yes, or at once when the user named it.

## Ops

Fact ops, each with `src` (the record's `internet_message_id` / `occurrence_key` / `record_id`, or `user`): `add` (text, since), `update` (id, text - same claim, better wording), `supersede` (id, text, since - the claim changed; old text to History), `confirm` (id), `retire` (id, reason), `contest` (id, text - a contradiction you must not settle alone; it goes to Review). Pick between them: same meaning → `confirm`; clearer wording → `update`; changed and the record is newer → `supersede`; changed but older, same-day or unclear → `contest`; new claim → `add`. When the part of the record the fact came from carries a locator — a document's `### p3`, `### s7` or `### Sheet1` section, a saved thread's `### m2` — write it into the src as `"<record_id>#<locator>"`, only that one, so the fact points at the page, slide, sheet or mail it was read on; the record still counts as one source however many facts cite it.

Page ops: `lead` (≤ 80 words, the one text the model rewrites freely; a `draft` page becomes `active`), `summary` (≤ 160 chars, the index line), `status` (topic: `active` / `at-risk` / `blocked` / `dormant` / `closed`; decision: `current` / `superseded` / `dropped`, the last only from the user; others drop the first two), `title`, `alias` (add only), `related`, `role` (page, ≤ 4 words), `steps` (howto only), `owner`, `org`. Topic only: `due`, `outcome` (what "done" means), `milestone` (text, due), `risk` (8 at most), `link` (url **or** page, label, 10 at most). Decision only: `superseded_by`, `reversal`.

Commitments, on any page with an `## Open` section: `open` (text, owner, due, since), `done` (id), `reschedule` (id, due). Ops without `src` are refused except `lead`, `summary`, `title`, `related` and `role`; with a `record_path` `src` defaults to the record, so this bites in a write without one, where it defaults to `user`.

## Commitments

One `## Open` line is one commitment, with an owner (`me`, a person page, or a plain name; `me` by default), a `due` date and its record - the line format is in `references/wiki.md`, a call in `references/examples.md`. Put it on the page of the **subject** it is about; with no such page, on the **counterpart's person page**, which holds both what they owe and what the user owes them.

Close one by reading it back with `vault_wiki_search(open_items=true, owner="others", page=<page>)` and sending `done` with its id and `src: user`; a new date is `reschedule` with a `due`. `Follow-ups.md` is generated from these lines (`## Open` = what others owe, `## Done` = the newest 50 closed) and rewritten after every wiki write; never put rows in it - `vault_row` refuses it.

## Decisions

When a record is explicit - "we agreed", "we are going with", "approved" - write the decision page in the same ingest, without asking: a `new` spec of type `decision` whose **first fact** is the choice in one sentence, then what follows from it (at most 8 facts), with `decided` (ISO date) and `by` (person pages that exist) required. Code sets `status: current`, flags it `unconfirmed-decision` and writes one Review line; say in one line that it was written and waits for a yes. The user confirms with "resolve review" (`vault_wiki_keep(action="review", review_action="resolve", item=…, resolution_ops=[{"op": "confirm", "id": <first fact>}])`) or by ticking that line, and drops it with a `status` op of `dropped`.

A decision page is added to, never rewritten: what turned out differently is a **new** decision linked with `superseded_by`, or a fact on the topic page. The whole run, call by call: `references/examples.md`.

## Refusals and what they mean

| Refusal | Meaning | What to do |
| --- | --- | --- |
| `older-than-current` | `supersede` older than the current fact; the pair went to Review. | Say "older source, sent to Review". |
| `user-pin` | The fact is `src:user`; no record may change it. | Say so; the user resolves it. |
| `conflicts-with` (`id`, `current`, `since`) | Your `add` names a day or an amount the page already names differently; only that op was dropped. | Resend one op: newer record → `supersede` with the returned id, else `contest`. Say which. Example in `references/examples.md`. |
| `append-only` | A decision page takes no fact op, `status`, `due`, `steps` or topic op. | A new decision with `superseded_by`, or the change on the topic page. |
| `cap` (`lines`, `chars`, `max_lines`, `max_chars`) | The page would pass its size cap; nothing was written. | Merge or supersede facts, move detail to a new page with a pointer, or close it. |
| `facts-cap`, `fact-too-long`, `lead-too-long`, `summary-too-long`, `role-too-long`, `title-too-long`, `outcome-too-long`, `risk-too-long`, `reversal-too-long` | One op over a size cap - 26 facts a page, 9 on a decision, and the per-field limits in `references/wiki.md`. | Shorten it, resend. |
| `risks-cap`, `links-cap` | A 9th risk, an 11th link. | Say the page holds as many as it may. |
| `unknown-id` | The id is not on the page; `known` lists them. | Re-read the page, use those ids. |
| `duplicate` | The same `open` wording or record twice, or a repeated milestone, risk or link (two things the *user* said are two items). | Nothing; an `add` equal to a fact applies as `confirm`. |
| `no-such-page`, `bad-owner`, `self-link`, `wrong-type`, `bad-status`, `bad-date`, `bad-text`, `missing-text`, `missing-src`, `bad-src`, `bad-title`, `unknown-op` | A page link missing or self-referential; a bad owner; an op on the wrong page type; a status that type lacks; a date that is not `YYYY-MM-DD`; text with `<!--`, a heading or nothing; a fact op without a `src` or with one that is not a record id or `user`; a title over 6 words or empty; an unknown op. | Fix the op. |
| `verify-failed` | The page did not read back as written; the old text is back, no op stands. | Say so - a Review line names what differed - and do not resend blindly. |
| `exists` | That title, alias or address already has a page; `path` and `match` come back. | Use that page. |

A code-owned key (`created`, `updated`, `verified`, `sources`, `open_items`, `flags`) in a `new` spec is a tool error, not a refusal: drop it and call again. So is a decision without `decided` or `by`.

## Read step (prep, find, draft, a chat question)

One call, not a match and three reads: `vault_wiki_search(query=<the question in the user's own words>, brief=true, max_chars=1200)`. Its `text` is the answer material: the best three pages with their lead, their facts (each with `f:<id>` and its date), their open items, then the dated decisions on the pages they link to. Answer from it before searching Outlook, quoting facts as they stand, never reworded, each with its page link. Empty `text` → the wiki has nothing on this yet.

A fact whose line ends **`(one source, unconfirmed since <date>)`** rests on one kind of source and nothing has confirmed it since. Never state it flat: say where it stands, ask the user, or read the record it came from; in a draft, hedge it or leave it out. Wording in `references/examples.md`.

Without `brief` the call returns the ranked facts as a list (`kinds`, `limit`, `since`, `page`, `include_superseded`), best first, at most three per page; `open_items=true` returns the commitments instead (`owner="me" | "others"`, `due_before`, `page`, `include_done`), oldest first, at most 200, `others` being what people owe the user. Ids, dates, amounts, `"quoted phrases"` and `/regex/` match as written. `## Notes` is never read, `Index.md` and `Log.md` never whole - `vault_wiki_search(pages=true)` and `vault_wiki_keep(action="log")` return slices. Fields: `references/wiki.md`.

## Rules

- Pages change only through `vault_wiki_*`: never the host file tools, never `vault_write` on a wiki path, never a row in `Follow-ups.md`.
- Nothing is deleted; a wrong fact is superseded, retired or contested, and contradictions go to Review, never settled silently.
- `## Notes` belongs to the user: read it only when `draft` needs voice lines, never write it.
- Merges (`vault_wiki_keep(action="merge", keep, drop)`, refused on a decision) and topic creation from a lint proposal happen only after a yes.
- An answer carrying `adopted: [{page, changes}]` means the user edited pages by hand and a writing call read those edits back; say so in one line first, naming the page and what changed. A read tool says `hand_edits: n` instead — no page is rewritten by a read; say how many and carry on, the next write adopts them.
- Every reply that changed pages lists them with `obsidian://open` links, one per page, plus the Review count when it grew.
