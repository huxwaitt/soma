# The wiki — how pages work

This file is the schema for `Soma/Wiki/`. The vault server writes a copy of it into the vault as `Wiki/Wiki.md` when it creates the wiki, and never rewrites it afterwards: you may add notes at the bottom, and `/soma:wiki` reads them when you ask it to. The same text is what the model reads, so you and it follow one contract.

## What the wiki is

Your records — saved emails, meeting notes, Teams chats, documents read into the vault, daily and weekly notes — are never edited. They are what happened. The wiki is what is *currently true* about the people, organisations, topics and procedures those records mention: one page per subject, a short lead, a list of dated facts, and links back to the records each fact came from. When a fact changes, the old one is kept in the page's History with the date and the record that changed it. Nothing is deleted.

`Soma/Follow-ups.md` is written from the wiki too: it is the view of what other people owe you (see "Commitments").

The model reads a record, compares it with the facts already on the matching pages, and sends a short list of operations (add, update, supersede, confirm, retire, contest). Code applies them, keeps the frontmatter, regenerates the index, and writes the log. Anything code cannot decide — two records that disagree, two pages that may be one thing, a page that has gone stale — goes into `Wiki/Review.md` for you.

## The records the wiki reads

A record is one thing that happened, written once and never edited: a saved email, a meeting note, a Teams chat day, a document read into the vault, a daily note, a weekly note. Every one of them carries the same keys after `type`, written by code, then the keys of its own kind:

| Key | What it holds |
| --- | --- |
| `source` | `outlook`, `teams`, `file` or `soma` |
| `record_id` | the identity as one string: an email's `internet_message_id` (else its `entry_id`), a meeting's `occurrence_key`, a chat's `<chat_id>|<date>`, a document's first 16 hex of the file's sha256, a daily note's date, a weekly note's week. It never holds a `#`, and it never changes — a document read again after the file changed keeps the id it was born with. |
| `title` | the subject, the chat title or the file name |
| `date` | `YYYY-MM-DD` |
| `people` | links to the person pages the record is about; may be empty |
| `wiki` | the pages this record was read into, added by ingest |
| `ingested` | the date of the last ingest |
| `created_by` | the version that wrote it |

Email and document records share one body order: `# <title>`, the kind's header lines, `## Summary`, `## Action items` (`- none` when there are none), `## Content`, `## Files` (only when there is something to list), then the `## Update <timestamp>` blocks later writes append. Meeting, chat, daily and weekly records keep the sections their own templates name (see the vault reference); only their frontmatter follows the shared contract. `## Content` holds the text; when the record has more than one part, each part is a `### <locator> — <heading>` section — a thread's mails (`### m1 — 2026-08-21 09:14 jane@example.com`), a deck's slides (`### s4 — Pricing`), a pdf's pages (`### p12 — page 12`), a workbook's sheets (`### Sheet1 — Sheet1`). `vault_read(path, section="s4")` returns one such part, so a long document is read part by part instead of whole.

### Locators in `src`

A fact may name the part of the record it came from: `src:"<record_id>#<locator>"`.

| Locator | Means | Example |
| --- | --- | --- |
| `p<n>` | page `n` of a pdf, or part `n` of a Word file | `"a1b2c3d4e5f60718#p3"` |
| `s<n>` | slide `n` of a deck | `"a1b2c3d4e5f60718#s4"` |
| `<sheet>` / `<sheet>!<cell>` | a sheet of a workbook, or one row of it | `"a1b2c3d4e5f60718#Sales!A7"` |
| `m<n>` | the `n`-th mail of a saved thread | `"<7f3a9c@example.com>#m2"` |

Chats and meetings have no locator: the bare record id is the source. Write the locator of the section heading the fact came from, and only that one. The string is kept whole wherever it is shown, and everything that compares or counts sources reads it as the record alone — so a document cited from three pages, or from three facts on one page, is one source, and a fact citing `#p3` and the page's Records line for the same document count once.

## Layout

```
Soma/Wiki/
  Index.md          generated: one line per page, grouped by type — the home page
  Log.md            generated, append-only: one line per change
  Review.md         generated: open questions for you
  Wiki.md           this file
  Questions.md      yours: the questions the wiki should be able to answer, and which page answers each
  Me.md             optional: one page about you (role, team, recurring duties)
  People/<Display Name>.md
  Orgs/<slug>.md
  Topics/<slug>.md
  Decisions/<slug>.md
  Howto/<slug>.md
  _history/         rolled-over History sections and old log files
  _cache/           working files, never notes:
      search.json.gz    what the search engine read out of each page last time
      state.json        the pages as code last wrote them, so your edits are visible
      prev/<page>.md.prev  each page's text before the last write, one copy per page (not a note, so Obsidian does not list it)
      queries.log       every question asked of the wiki, newest last
      history.json      where /soma:load-history got to in each source, and the ids it has read
      (topic candidates and the last lint report live here too)
```

One folder level, no deeper. Filenames never change after creation, because a rename outside Obsidian breaks every link; a page that needs a better name gets the new name as `title` and the old one as an alias. Slugs are lowercase ASCII with `-`, at most 40 characters, no dates. People keep `<Display Name>.md`, as the email notes have always linked them.

## Page types — where a fact belongs

| Type | One page per | Holds | Does not hold |
| --- | --- | --- | --- |
| `person` | a real person (one email identity; other addresses and spellings are aliases) | role, organisation, what they are responsible for, how they work with you, current asks both ways | what a thread said (record), project state (topic) |
| `org` | a company, department or team you deal with | what they are to you, contacts, contract and commercial facts, their conventions | private facts about their people |
| `topic` | a subject with a timeline and an outcome: a project, a deal, an open problem | current state, dated facts, who is involved, what is open, key records | the running log of every mail (records and History) |
| `decision` | one choice that was made and now stands | the choice as the first fact, what follows from it, who made it, what would reopen it | the work that follows from it (topic), the thread that led to it (record) |
| `howto` | a procedure you perform | steps, where, who approves, gotchas, when it was last done | why (topic) |
| `me` | you (one page, optional) | stable facts about your role, team, duties, preferences the model should know when drafting | anything that changes weekly |

Order when placing a fact, first match wins: (1) about one person's role, responsibility, preference or relationship to you → `person`; (2) about a company or team as a whole → `org`; (3) a choice that was made and now stands ("we agreed", "we are going with", an approval) → `decision`; (4) a step-by-step way of doing something → `howto`; (5) about you and your own duties → `me`; (6) has a timeline and an end state → `topic`; (7) otherwise it is not wiki material and stays in the record.

**A topic with an owner and a due date is a project** — there is no separate project page. Set `owner` and `due` as soon as a record gives them, and the index lists the page under Projects.

Two facts about the same thing never live on two pages: the page for the subject holds the fact, other pages link to it. The People list on a topic page and the Topics list on a person page are both generated from the same links, so they cannot disagree.

A topic page is created only when the same subject shows up in two or more records on two or more different days, or when you name it. Before that the records are enough. This is the main guard against bloat: a one-off mail never becomes a page.

## The page

Shown for a topic; the other types drop sections they do not need (below).

```markdown
---
type: topic
id: 01K3F7Q2N8Z4RVHB6MCE0TXWJ9
title: Q3 budget
aliases:
  - Budget Q3
  - Q3 forecast
summary: Final Q3 numbers due to Jane by 2026-08-29; forecast closes 2026-09-02.
status: active
owner: "[[Wiki/People/Jane Doe]]"
org: "[[Wiki/Orgs/example-gmbh]]"
due: "2026-08-29"
outcome: The forecast is closed with every team's numbers in.
created: 2026-08-22
updated: 2026-08-22T09:40:00+02:00
verified: 2026-08-22
sources: 3
open_items: 1
flags: []
created_by: soma/0.4.2
---

# Q3 budget

Jane Doe (finance) is collecting final Q3 numbers from each team lead by 2026-08-29 to close the forecast on 2026-09-02. The user owes the sales-team figures; everything else is in.

## Facts

- Deadline for the user's numbers is 2026-08-29 <!-- f:7k2q since:2026-08-22 src:"<7f3a9c@example.com>" -->
- Forecast closes 2026-09-02 <!-- f:9x1a since:2026-08-22 src:"<7f3a9c@example.com>" -->
- Numbers go into the shared sheet Budget_Q3.xlsx, tab "Sales" <!-- f:c3mm since:2026-08-20 src:"0400…|2026-08-20T13:00:00+02:00" -->

## Milestones

- [ ] Draft numbers ready — due: 2026-08-27 <!-- m:2b8k since:2026-08-22 src:"<7f3a9c@example.com>" -->

## People

- [[Wiki/People/Jane Doe]] — owns the forecast
- [[Wiki/People/Bob Lee]] — sends marketing numbers

## Open

- [ ] Send Q3 numbers to Jane — owner: me · due: 2026-08-29 — [[Emails/2026-08-22 Budget Q3]] <!-- o:7k2q since:2026-08-22 src:"<7f3a9c@example.com>" -->

## Records

- 2026-08-22 — [[Emails/2026-08-22 Budget Q3]] — Jane asks for final numbers by Friday
- 2026-08-20 — [[Meetings/2026-08-20 1300 Budget review with Jane]] — agreed the sheet layout

## Related

- [[Wiki/Topics/annual-planning]]
- [[Wiki/Orgs/example-gmbh]]

## History

- 2026-08-22 — superseded "Deadline is 2026-08-27" → "Deadline … 2026-08-29" ([[Emails/2026-08-22 Budget Q3]])
- 2026-08-20 — page created from [[Meetings/2026-08-20 1300 Budget review with Jane]]

## Notes

```

### Frontmatter

| Key | Set by | Meaning |
| --- | --- | --- |
| `type` | code | `person`, `org`, `decision`, `topic`, `howto`, `me` |
| `id` | code | 26 characters, given once and never changed. It is what makes a page you rename or move in Obsidian still the same page. |
| `title` | model at creation; `title` op later (the file name stays) | a noun phrase, at most 6 words, no dates |
| `aliases` | merged by code, never removed by code | other names, spellings, addresses; what matching searches; Obsidian resolves `[[alias]]` links with them |
| `summary` | model (`summary` op), at most 160 characters | the one line in `Index.md`; the only thing read before deciding to open the page |
| `status` | model op or lint | topic: `active`, `at-risk`, `blocked`, `dormant` (no record in 60 days), `closed` (outcome reached), `draft` (created by code, no lead yet). decision: `current`, `superseded`, `dropped`, `draft`. The other types: `active`, `dormant`, `closed`, `draft`. |
| `owner` | model | optional, a quoted wikilink to a person page |
| `org` | model | optional, plain text (the company name; lint links it to the org page of that name) |
| `due` | model (`due` op) | topic only: the date the thing is due. A topic with an owner and a due date is a project. |
| `outcome` | model (`outcome` op), at most 160 characters | topic only: what "done" means here |
| `links` | model (`link` op), at most 10 | topic only: `[label](url)` for a web address, `[[path\|label]]` for a note in the vault |
| `risks` | model (`risk` op), at most 8, each at most 80 characters | topic only: what could still go wrong |
| `decided` | model at creation (required) | decision only: the date the choice was made |
| `by` | model at creation (required) | decision only: links to the person pages of who made it |
| `superseded_by` | model (`superseded_by` op) | decision only: the decision that replaced this one; setting it sets `status: superseded` and links both pages |
| `reversal` | model (`reversal` op), at most 160 characters | decision only: what would reopen the question |
| `options_rejected` | model at creation | decision only: what was considered and not taken |
| `created` | code | |
| `updated` | code, on every write | last time anything below the frontmatter changed |
| `verified` | code | date of the newest *source* that confirmed or added a fact — "accurate as of", which says more than "last written" |
| `sources` | code | count of distinct record links in Facts and Records |
| `open_items` | code | unchecked boxes under `## Open` |
| `flags` | code / lint | `contradiction`, `unconfirmed-decision`, `possible-duplicate`, `stale`, `oversized`, `orphan`; empty means clean |
| `created_by` | caller | |

`id`, `created`, `updated`, `verified`, `sources`, `open_items` and `flags` are code-owned: a create that tries to set them fails with an error naming them as code-owned. Per type: `person` adds `name` (same as the title), `email`, `org` (plain text, not a link), `last_contact`; `org` adds `domains` (matched on sender domains); `topic` adds `owner`, `org`, `due` (lint reports a `due` in the past on a live page), `outcome`, `links`, `risks`; `decision` adds `decided` and `by` (both required), `superseded_by`, `reversal`, `options_rejected`; `howto` adds `last_done`.

### Sections — fixed order, fixed meaning

| Section | Written by | Rule |
| --- | --- | --- |
| Lead (between `# Title` and the first `##`) | model, `lead` op, at most 80 words, 2–4 sentences | Stands alone: what the thing is and its current state. The one place the model replaces text. |
| `## Facts` | code, from model ops | One bullet = one claim, at most 25 words, present tense, no hedging. Each ends with a hidden comment `<!-- f:<id> since:<date> src:<record id> -->`: `since` is the date the claim became true according to the source, `src` the record's `record_id`, with `#<locator>` after it when the fact came from one named part, or `user`. Only current facts. At most 25 bullets. |
| `## People` (`## Contacts` on org pages, `## Topics` on person pages) | code | Link plus a role of at most 4 words, from the link graph and `role` ops. |
| `## Milestones` | code, from `milestone` ops | topic only. `- [ ] <text> — due: YYYY-MM-DD <!-- m:<id> since:<date> src:"…" -->`. A ticked one moves to History as `milestone reached "<text>"`. |
| `## Open` | code | One commitment per line, with who owes it and when (see "Commitments"). Ticked lines move to History on the next write and leave `Follow-ups.md`. |
| `## Records` | code | `- <date> — [[record]] — <the record's summary line>`, newest first, capped at 15. Older ones are still reachable through `find`. |
| `## Related` | code | Links to other wiki pages: from `related` ops, from pages linked in Facts, and from back-links. Symmetric. |
| `## History` | code, append-only | `- <date> — <what> ([[record]])`. Superseded and retired facts land here with old and new text; `add` and `confirm` are only in the log. At 40 lines the oldest move to `Wiki/_history/<Folder>/<name>.md`, one pointer line stays. |
| `## Notes` | you only | Code never reads or writes below this heading. If something you wrote here contradicts a Fact, lint reports it; your text wins. |

A page missing a section gets it added in order on the next write. A page with an unknown `## Heading` above `## Notes` is reported by lint (check 5, `unknown`) and kept, not "fixed". Per type: `topic` has Facts / Milestones / People / Open / Records / Related / History / Notes; `person` has Facts / Topics / Open / Records / Related / History / Notes (a `Voice with this person:` block from an older vault is kept under Notes, and its `## Topics` lists the decisions it links to as well); `org` has Facts / Contacts / Topics / Records / Related / History / Notes; `decision` has Facts / People / Open / Records / Related / History / Notes; `howto` has `## Steps` (numbered, model-written, replaced whole by the `steps` op) before Facts / Records / Related / History / Notes; `me` has Facts / Open / Related / History / Notes.

### Size caps (enforced, not advisory)

| | Max lines | Max characters |
| --- | --- | --- |
| person, org, howto, me | 80 | 4,000 |
| topic | 120 | 6,000 |
| decision | 60 | 3,000 |
| Facts | 25 bullets (8 on a decision) | |
| `risks` | 8 entries | |
| `links` | 10 entries | |
| Lead | 80 words | |
| `Index.md` | 200 lines | 25,000 |

A write that would exceed the page cap is refused (`cap`, with the measured lines and characters) and the three remedies: supersede or merge facts, move detail to a new page and leave a one-line pointer fact, or close the page. A 26th fact (a 9th on a decision) is refused as `facts-cap`, a fact over 25 words as `fact-too-long`, a lead over 80 words as `lead-too-long`, a summary over 160 characters as `summary-too-long`, a 9th risk as `risks-cap`, an 11th link as `links-cap`. When `Index.md` passes 200 lines (or 25,000 characters) it splits into one index per type folder plus a short root index pointing at them.

## Operations

Facts are located by id (four characters, shown in the hidden comment; the model only uses ids the read returned). Every fact op carries `src`.

| Op | Fields | What happens |
| --- | --- | --- |
| `add` | text, since, src | New bullet, new id. Text identical to an existing fact (ignoring case and spacing) is treated as `confirm` (the result says `result: confirm`). Text that names a day or an amount where a fact about the same thing already names a different one is refused as `conflicts-with` (see below). |
| `update` | id, text, src | Same claim, better wording. Id and `since` stay; `src` gains the new source (up to 3, newest first). History: `updated f:<id>`. |
| `supersede` | id, text, since, src | The claim changed: a date moved, an owner changed, a decision reversed. Allowed only when the new `since` is on or after the old one; otherwise refused (`older-than-current`) and the pair goes to Review. Old bullet moves to History as `superseded "<old>" → "<new>"`; the new bullet gets a new id. |
| `confirm` | id, src | The source repeats a known fact. `src` extended, `verified` bumped, text untouched. This is what keeps `verified` honest. |
| `retire` | id, src, reason | No longer true and nothing replaces it (a project cancelled). Moves to History as `retired "<old>" — <reason>`. |
| `contest` | id, text, src | The source disagrees with a fact but is older, same-day, or the model is unsure. Facts stay as they are; the page gets `flags: [contradiction]` and Review gets a line with both texts and both records. |

Page-level ops: `lead` (text), `summary` (text), `status` (value), `title` (text; the old title becomes an alias), `alias` (text; add only), `related` (page; add a link), `role` (page, role), `steps` (text; howto only), `owner` (value), `org` (value); the commitments (`open`, `done`, `reschedule`), the project ops on a topic (`due`, `outcome`, `milestone`, `risk`, `link`) and the decision ops (`superseded_by`, `reversal`) are below. All but `lead`, `summary`, `title`, `related`, `role` need a `src` (at ingest it defaults to the record's id, so it is never missing there). An empty op list is a valid "nothing new": code still adds the Records line and a `seen` History line if the record was new to the page.

### Two facts that disagree — `conflicts-with`

A page may not hold two facts stating different days or different amounts for the same thing. An `add` is refused as `conflicts-with` when its text names a value (an ISO date, a number with a unit or a currency on either side of it — `€500`, `500€` and `500 EUR` are one and the same amount — or a bare number of four digits or more; `net 45` on its own is not one), a fact already on the page names a value too, the two share no value, and the two share at least two of the words they are about. The refusal carries `id`, `current`, `since` and the one line the model needs: use `supersede` when the new one is the newer, `contest` when it is the older or you are unsure. Only `add` is checked; a decision page never is, because it is added to, never corrected.

### Commitments — the `## Open` lines

One line is one thing somebody owes somebody, on the page of the thing it is about (the topic or decision the record matched, otherwise the other person's page):

```
- [ ] <text> — owner: me | [[Wiki/People/Name]] | <plain name> · due: YYYY-MM-DD — [[record]] <!-- o:<id> since:<date> src:"…" -->
```

`owner` says who does it (`me` by default), `due` says when, `since` is the day it started, and the link names the record it came from. Both `owner` and `due` may be left out; a line written before 0.4.0 gets an id, `since` and `owner: me` on the next write.

| Op | Fields | What happens |
| --- | --- | --- |
| `open` | text, owner, due, since, src | A new line, on a page whose contract has an `## Open` section (person, topic, decision, me; anywhere else it is refused as `wrong-type`). `owner` is `me`, a link to a page that exists, or a plain name (`no-such-page` / `bad-owner` otherwise); `due` is an ISO date (`bad-date`). The same wording, or the same record twice, is refused as `duplicate` — two things *you* said are two items, because `user` is not a record. |
| `done` | id, src | Ticks it. It leaves `Follow-ups.md` and History keeps `done "<text>" — owner: … · since <date>`. `unknown-id` when there is no such line. |
| `reschedule` | id, due, src | Moves the due date; History keeps `rescheduled "<text>" <old> → <new>`. |

`vault_wiki_search(open_items=true, owner="me"|"others", due_before, page, include_done)` reads them back, oldest first: `[{page, stem, type, title, owner_name, id, text, owner, due, since, src, record, done}]`.

**`Soma/Follow-ups.md` is generated** from these lines: `## Open` is what other people owe you (`owner` is not `me`), `## Done` the newest 50 `done` lines out of the pages' History, in the five columns the file has always had. It is rewritten after every wiki write, so it never disagrees with the pages. Edit or tick the item **on its page** (or say "done" in chat); `vault_row` refuses the file.

### Projects — the extra ops on a topic

`due` (value), `outcome` (text, at most 160 characters), `milestone` (text, due, src → one `## Milestones` line; the same wording twice is refused as `duplicate`), `risk` (text, at most 80 characters, src → one entry in `risks`, a History line, at most 8) and `link` (url **or** page, label → one entry in `links`, at most 10). All five are refused with `wrong-type` on a page that is not a topic.

### Decisions

A decision page is written once and added to, never rewritten. `vault_wiki_write` with a `new:` spec of type `decision` needs `decided` (the date it was made) and `by` (links to the person pages of who made it); code sets `status: current`, `flags: [unconfirmed-decision]` and writes one line in `Review.md`:

```
- [ ] [[Wiki/Decisions/new-stack]] — unconfirmed decision: "The rebuild runs on the new stack" — confirm or drop ([[Emails/2026-08-18 Rebuild]])
```

Nobody was asked before it was written, so that line is how you see it. Confirm it in chat ("resolve review"), or tick it in Obsidian — this is the one line where ticking the box on its own does something: the next lint or ingest clears the flag and moves the line to Done. To drop it instead: `status: dropped`, which only you can set.

Afterwards `add`, `update`, `supersede`, `retire`, `contest`, `status`, `due`, `steps` and the project ops are refused with `append-only`. What is allowed: `confirm`, `superseded_by` (a link to the decision that replaced this one: it sets `status: superseded`, writes the History line and links both pages), `reversal`, `open` / `done` / `reschedule`, `related`, `role`, `alias`, `summary`, `lead`, `title`. A decision is never merged either.

When something later turns out differently, that is a **new decision** (linked with `superseded_by`) or a fact on the topic page — never a rewrite of what was decided.

Two rules from this: **later wins, only if later** — a freshly saved *older* mail can never overwrite a newer fact; and **nothing is deleted** — every superseded or retired line is in History and in the log with both texts, the date and the record. Reverting is a new supersede the other way.

### Every write is read back

After a page is written the file is read again and compared with what was meant: the facts with their ids, dates and sources in order, the lead, the title, every line of every section, the code-owned keys, the size caps and the index line. If anything differs, the text the page had before the write (kept in `_cache/prev/`) goes straight back, a Review line and a `restore` line in the log say what differed, and the tool answers `written: false` with every op refused as `verify-failed`. A half-written page is never left behind.

### Your pins

Anything under `## Notes`, and any fact with `src:user` (you said it in chat and the model wrote it through `vault_wiki_write` without a record), outranks what the model learns from records: a `supersede`, `update` or `retire` on a `src:user` fact from a record is refused (`user-pin`) and goes to Review instead.

### Contradictions

Code cannot see that two sentences cannot both be true; the model can, but it does not settle it alone. If the newer record contradicts a fact, the model supersedes (logged, old text kept). If the contradicting record is older or same-day, or the model is unsure, it contests. `Review.md` then holds a line like

```
- [ ] [[Wiki/Topics/q3-budget]] — f:7k2q "Deadline for the user's numbers is 2026-08-29" vs "Deadline is 2026-08-27" ("<7f3a9c@example.com>" / [[Emails/2026-08-19 Budget timing]])
```

(the current fact's sources in quotes, then the contesting record's link). A refused `supersede` writes a similar line with `(since <date>) vs older "<text>" (since <date>)`; a refused change to a user fact writes `user fact "<text>" vs "<text>"`. Say "resolve review" in chat; the fix is an ordinary op from your answer. Resolved lines move to `## Done` with the date. Ticking the box in Obsidian alone changes nothing — the one exception is an "unconfirmed decision" line, where a tick is your confirm.

## Editing pages by hand

Obsidian writes the same files the code writes, so you may edit a page yourself. At the start of every wiki tool call the code reads back what changed since it last wrote (it remembers each page in `_cache/state.json`) and takes your edit over. Nothing you typed is thrown away.

Taken over without asking:

| What you did | What happens |
| --- | --- |
| Typed a new bullet under `## Facts` | It becomes a fact of yours: a new id, `since` = the day you saved the file, `src: user` — so a record may not overwrite it (see Your pins). |
| Reworded a fact | Your wording stays, `src` gains `user`, History keeps the old text (`updated f:<id> "…" → "…" — edited by hand`). |
| Deleted a fact | Retired: gone from Facts, its text in History (`retired "…" — removed by hand`). |
| Ticked a box under `## Open` | The item is done, it moves to History and leaves `Follow-ups.md`. |
| Ticked a box under `## Milestones` | The milestone is reached and moves to History. |
| Ticked an "unconfirmed decision" line in `Review.md` | The decision is confirmed: the flag goes and the line moves to Done. Every other Review line needs an answer in chat. |
| Changed the `# Title` line | The new title is used; the old one is kept as an alias. |
| Rewrote the lead | Kept as you wrote it. |
| Renamed the file, or moved it into another type's folder | The page keeps its `id`, so it is still the same page: every link to it on the other pages, in the records' `wiki:` keys, in Follow-ups and in Review is rewritten, the index is regenerated, and the folder decides the new type. |
| Made a new `.md` file in a wiki folder | It becomes a page: the folder gives the type, the `# Title` line (or the filename) the title, your bullets become facts of yours, and the frontmatter the contract asks for is filled in. |
| Changed a code-owned key | Recomputed; `id` and `created` are put back as they were. |

Put back, with a line in Review:

- Text under a heading the contract does not know moves under `## Notes` behind a `### <Heading> (moved <date>)` marker.
- A `## History` section you shortened comes back (the lines the code last wrote are kept in `_cache/state.json`, older ones in the copy under `_cache/prev/`). Say "drop it" if you meant to shorten it. A line no copy holds is reported in Review instead of put back.

Asked about, never done on its own:

- A page you deleted: one Review line naming how many links still point at it, asked once. The copy under `_cache/prev/` is what puts it back.
- A file that is a sync copy of a page (`… (1).md`, or `conflict` in the name, same `id`): not read, one Review line.
- A page you wrote by hand whose name a page already has: one Review line ("merge them or rename one?"), your file untouched.

The pass runs at the start of every tool that writes. Every change taken over is one `adopt` line in `Wiki/Log.md`, and the tool that ran the pass answers with `adopted: [{page, changes}]`, so the model tells you in one line what it read back; `vault_wiki_keep(action="lint")` reports the same under `checks["0"]`. A tool that only reads never rewrites a page: `vault_wiki_search` in every mode, `vault_wiki_read`, `vault_wiki_keep(action="log")` and `vault_wiki_keep(action="review", review_action="list")` count the files that differ and answer `hand_edits: n`, and the next writing call is what adopts them. A file that is being written at that moment is left for the next call.

The first run of this version reads every page once: each gets an `id`, bullets you had typed become facts of yours, and one `migrate` line in the log says how many.

## Finding things

`vault_wiki_search(query, kinds, limit, since, include_superseded, brief, max_chars, open_items, owner, due_before, page, include_done)` reads the pages themselves and ranks the facts on them, so a fact is found by what it says and not only by the name of the page it sits on. Ids, dates, amounts, `"quoted phrases"` and `/regex/` are looked up as written; a misspelled name still finds the person; the pages a good hit links to are pulled in with it. Each hit is `{page, kind, title, fact_id, text, since, src, score, why[], superseded, streams, confirmed}`, best first, at most three facts per page. Old wordings kept in History come back only with `include_superseded=true`, always below the current fact. `## Notes` is never read.

`brief=true` answers with one stitched text instead of a list — the best three pages with their lead, their facts (with ids), their open items, then the decisions and dated facts of the pages they link to, under `max_chars` — as `{text, pages[], facts[], chars}`. `open_items=true` answers with the commitments (see "Commitments"), oldest first, at most 200 of them. Every question is written to `_cache/queries.log`, which is what lint check 21 reads.

How well a fact is backed comes with it: `streams` is how many kinds of source say it (mail, meeting, chat, you) and `confirmed` how many days ago the newest of them was. One source and nothing for more than 180 days, and the brief writes it out — `- Deadline is 2026-08-29 (f:abcd, 2026-01-04) (one source, unconfirmed since 2026-01-04)` — so the model hedges or asks you instead of stating it flat.

`vault_wiki_search(pages=true)` is unchanged — the index lines that match a subject, sender or domain — and runs on the same engine.

## Index, log, review

**`Wiki/Index.md`** is generated from frontmatter after every write, so it cannot drift from the files. One line per page: link with title, status (or organisation for people), the `verified` date, the summary. Grouped by type; `active` before `draft` before `dormant` before `closed` (closed pages beyond 20 collapse to a count); newest `verified` first, so the top of each group is what matters now. Topics with a `due` date are the **Projects** group, soonest first, above the other topics, and their line reads owner, due date and status instead of the `verified` date; the decisions come between the projects and the other topics. Before it is rewritten the lines it had are compared with the lines it should have: a line that differs for a page nobody just wrote means the file was changed by hand, and that goes to the log as `index-repaired`. It is the home page in Obsidian. The model never reads it whole; `vault_wiki_search(pages=true)` returns the few lines that match a subject, sender or domain.

```markdown
## Projects (3)
- [[Wiki/Topics/q3-budget|Q3 budget]] · Jane Doe · 2026-08-29 · active — Final Q3 numbers due to Jane by 2026-08-29; forecast closes 2026-09-02.

## Decisions (4)
- [[Wiki/Decisions/new-stack|New stack]] · current · 2026-08-18 — The rebuild runs on the new stack.

## Topics (12)
- [[Wiki/Topics/expense-policy|Expense policy]] · active · 2026-08-22 — Receipts within 30 days; anything over 200 EUR needs Jane's yes.

## People (18)
- [[Wiki/People/Jane Doe]] · Example GmbH · 2026-08-22 — Finance lead; owns the quarterly forecast; prefers short mails.
```

**`Wiki/Log.md`** is append-only: `- [2026-08-22T09:40:00+02:00] ingest | Wiki/Topics/q3-budget | [[Emails/2026-08-22 Budget Q3]] | add 2, supersede 1`. One line per page per ingest (`ingest`), per chat change (`apply`), per page created (`create`), per person page touched by a saved mail (`record`), per resolved review item (`review`), per page read back after you edited it in Obsidian (`adopt`), one per lint run (`lint`), merge (`merge`), migration (`migrate`), write that did not come back as written (`restore`) and index put right (`index-repaired`). At 500 lines it rolls over to `Wiki/_history/Log-YYYY.md`.

**`Wiki/Review.md`** is the checklist of what code could not decide, under `## Open` (resolved lines move to `## Done`): contradictions, decisions written from a record and not yet confirmed, items of your own past their due date, pages that may be duplicates ("merge A into B?"), stale pages, two pages that disagree about each other, projects with no update in 90 days, pages still on one record after 60 days, refused supersedes and refused changes to your facts. Topic proposals from candidates are not written here; `vault_wiki_search(pages=true)`, a write with a record and lint check 12 report them. Every line links the page. `/soma:weekly` lists the open count; `/soma:lint` adds to it.

**`_views/Wiki.base`** gives you Obsidian tables over the wiki: projects (topics with a due date), decisions, active topics by `verified`, stale pages, the review queue (pages with flags), people by organisation. Bases read frontmatter, which is exactly what code maintains, so the views are never stale.

## Questions.md

`Wiki/Questions.md` is yours: the questions you want the wiki to be able to answer, and the page that should answer each one. It is created with an empty list and two examples above it (they sit in a code block, so nothing asks the wiki about them), and never overwritten.

```markdown
## Questions

- When are the Q3 numbers due? → [[Wiki/Topics/q3-budget]]
- What did we agree with the supplier? → [[Wiki/Decisions/acme-terms]] f:a1b2
```

One line per question: the question, an arrow (`→` or `->`), and a link to the page. Add `f:<id>` after the link when one particular fact is the answer and nothing else will do; without it, any hit on that page counts. Lint check 20 asks the wiki every question and counts the answers — the page (or the named fact) has to come back in the first three hits — and reports the misses with what came back instead. A line pointing at a page that does not exist yet is listed and not counted. The score goes into the log line of every lint run (`questions 17/20`), so you can watch it move. Anything you write outside the `## Questions` list is left alone. The one thing code ever writes in this file: when a page is renamed or moved, the link in your question follows it, like every other link in the vault.

Check 21 reads the other side of the same coin: the questions the wiki was actually asked and could not answer at all. Asked at least twice in the last 30 days, each becomes one Review line — no page answers "…" — create one? — so gaps turn into pages.

## Lint

`/soma:lint` (and `weekly`, with `fix`) runs a fixed list. Flags (`orphan`, `stale`, `oversized`, `possible-duplicate`) and Review lines are written in both modes; the fixes in the last column only with `fix`. Everything else is reported.

| # | Check | With `fix` |
| --- | --- | --- |
| 0 | The pages you changed in Obsidian since the last write | read back and taken over (see "Editing pages by hand"); reported as `checks["0"]` |
| 1 | Index and files agree | regenerated |
| 2 | Dangling `[[links]]` under `Wiki/` | link becomes plain text, only in code-owned sections |
| 3 | Orphans: no inbound link from any page or record | flagged `orphan`, reported |
| 4 | Frontmatter: missing, extra or mistyped keys; code-owned keys edited by hand | code-owned keys recomputed; the rest reported |
| 5 | Section order, unknown or duplicate headings | order fixed; unknown headings kept and reported |
| 6 | Oversized page | flagged `oversized`, the three remedies shown |
| 7 | Stale: live (`active`, `at-risk`, `blocked`), `verified` older than 60 days (topic, howto) or 120 days (person, org, me); decisions are never stale | flagged `stale` and one Review line; topics set to `dormant` |
| 8 | `due` in the past on an active topic | reported |
| 9 | Open items whose record action item is ticked | moved to History |
| 10 | Possible duplicates: a shared alias, address or domain, or titles equal once case, punctuation and `the/a/of` are ignored | flagged on both; Review line "merge A into B?" — merged only on your yes |
| 11 | Records never ingested (no `wiki:` key, newer than the last ingest) | counted and listed (up to 50); `weekly` offers to ingest ten at a time |
| 12 | Topic candidates over the threshold with no page | proposed |
| 13 | History over 40 lines, log over 500 | rolled over |
| 14 | Contradictions on pages touched since the last lint | the model reads them; Review line only |
| 15 | Facts older than 180 days with a single source, on live pages | reported as "unconfirmed", at most 20 |
| 16 | Consistency: a person's `org` against that org page's `## Contacts`; an `owner` on a topic or howto that is not a person page; a `due` against a fact on the same page naming another day for the same thing; one-way links between `## Related`, `## People`, `## Topics` and `## Contacts` | the missing side of a link is written on the other page, and an owner that is a plain name a person page carries becomes a link; a real disagreement gets a Review line quoting both sides |
| 17 | A topic with a due date and nothing new for 90 days (a page you already closed or left dormant is not asked about again: check 7 put that question and the status is the answer) | one Review line "no update in 90 days: close it?" |
| 18 | A topic, org or howto still standing on one record 60 days after it was created (person, decision, the me page and anything closed or dormant are left out) | one Review line "one record after 60 days: merge or retire?" |
| 19 | Overdue: an item of your own (`owner: me`) past its due date | one Review line "done, reschedule, or drop" |
| 20 | Questions: every line of `Questions.md` asked of the wiki | the score, and the questions whose page did not come back in the first three hits |
| 21 | Questions the wiki could not answer: no hit at all, asked at least twice in the last 30 days | one Review line: no page answers "…" — create one? |

Every run adds one line to `Wiki/Log.md` carrying all of these counts (`… questions 17/20, unanswered 3, …`), so the log shows whether the wiki is getting better or worse from week to week.

A merge (`vault_wiki_keep(action="merge", keep, drop)`) moves the facts, aliases, records and links of `drop` onto `keep`, keeps `drop`'s full old text under `Wiki/_history/`, and leaves a short redirect page (`type: redirect`) in `drop`'s place, so no link breaks; a read of the old page follows the redirect. It only ever runs after you say the two pages are the same thing; a similar name alone only produces the question.

## What the model never does here

Edit a page file directly; set a code-owned key; delete a fact; overwrite a newer fact with an older record; resolve a contradiction on its own; merge two pages without your yes; create a topic page from one mail; rewrite or drop a decision on its own; write rows into `Follow-ups.md`; read or write below `## Notes`.

## Your notes on this schema

Add anything below this line. `/soma:wiki` reads it when you ask ("what does my Wiki.md say"); no other command does.
