# The wiki — how pages work

This file is the schema for `Administrator/Wiki/`. The vault server writes a copy of it into the vault as `Wiki/Wiki.md` when it creates the wiki, and never rewrites it afterwards: you may add notes at the bottom, and `/administrator:wiki` reads them when you ask it to. The same text is what the model reads, so you and it follow one contract.

## What the wiki is

Your records — saved emails, meeting notes, daily and weekly notes — are never edited. They are what happened. The wiki is what is *currently true* about the people, organisations, topics and procedures those records mention: one page per subject, a short lead, a list of dated facts, and links back to the records each fact came from. When a fact changes, the old one is kept in the page's History with the date and the record that changed it. Nothing is deleted.

The model reads a record, compares it with the facts already on the matching pages, and sends a short list of operations (add, update, supersede, confirm, retire, contest). Code applies them, keeps the frontmatter, regenerates the index, and writes the log. Anything code cannot decide — two records that disagree, two pages that may be one thing, a page that has gone stale — goes into `Wiki/Review.md` for you.

## Layout

```
Administrator/Wiki/
  Index.md          generated: one line per page, grouped by type — the home page
  Log.md            generated, append-only: one line per change
  Review.md         generated: open questions for you
  Wiki.md           this file
  Me.md             optional: one page about you (role, team, recurring duties)
  People/<Display Name>.md
  Orgs/<slug>.md
  Topics/<slug>.md
  Howto/<slug>.md
  _history/         rolled-over History sections and old log files
  _cache/           topic candidates and lint reports (not notes)
```

One folder level, no deeper. Filenames never change after creation, because a rename outside Obsidian breaks every link; a page that needs a better name gets the new name as `title` and the old one as an alias. Slugs are lowercase ASCII with `-`, at most 40 characters, no dates. People keep `<Display Name>.md`, as the email notes have always linked them.

## Page types — where a fact belongs

| Type | One page per | Holds | Does not hold |
| --- | --- | --- | --- |
| `person` | a real person (one email identity; other addresses and spellings are aliases) | role, organisation, what they are responsible for, how they work with you, current asks both ways | what a thread said (record), project state (topic) |
| `org` | a company, department or team you deal with | what they are to you, contacts, contract and commercial facts, their conventions | private facts about their people |
| `topic` | a subject with a timeline and an outcome: a project, a deal, a recurring decision, an open problem | current state, dated facts, who is involved, what is open, key records | the running log of every mail (records and History) |
| `howto` | a procedure you perform | steps, where, who approves, gotchas, when it was last done | why (topic) |
| `me` | you (one page, optional) | stable facts about your role, team, duties, preferences the model should know when drafting | anything that changes weekly |

Decision order when placing a fact: (1) a step-by-step way of doing something → `howto`; (2) about one person's role, responsibility, preference or relationship to you → `person`; (3) about a company or team as a whole → `org`; (4) has a timeline and an end state → `topic`; (5) otherwise it is not wiki material and stays in the record.

Two facts about the same thing never live on two pages: the page for the subject holds the fact, other pages link to it. The People list on a topic page and the Topics list on a person page are both generated from the same links, so they cannot disagree.

A topic page is created only when the same subject shows up in two or more records on two or more different days, or when you name it. Before that the records are enough. This is the main guard against bloat: a one-off mail never becomes a page.

## The page

Shown for a topic; the other types drop sections they do not need (below).

```markdown
---
type: topic
title: Q3 budget
aliases:
  - Budget Q3
  - Q3 forecast
summary: Final Q3 numbers due to Jane by 2026-08-29; forecast closes 2026-09-02.
status: active
owner: "[[Wiki/People/Jane Doe]]"
org: "[[Wiki/Orgs/example-gmbh]]"
created: 2026-08-22
updated: 2026-08-22T09:40:00+02:00
verified: 2026-08-22
sources: 3
open_items: 1
flags: []
created_by: administrator/0.2.0
---

# Q3 budget

Jane Doe (finance) is collecting final Q3 numbers from each team lead by 2026-08-29 to close the forecast on 2026-09-02. The user owes the sales-team figures; everything else is in.

## Facts

- Deadline for the user's numbers is 2026-08-29 <!-- f:7k2q since:2026-08-22 src:"<7f3a9c@example.com>" -->
- Forecast closes 2026-09-02 <!-- f:9x1a since:2026-08-22 src:"<7f3a9c@example.com>" -->
- Numbers go into the shared sheet Budget_Q3.xlsx, tab "Sales" <!-- f:c3mm since:2026-08-20 src:"0400…|2026-08-20T13:00:00+02:00" -->

## People

- [[Wiki/People/Jane Doe]] — owns the forecast
- [[Wiki/People/Bob Lee]] — sends marketing numbers

## Open

- [ ] Send Q3 numbers to Jane by 2026-08-29 — [[Emails/2026-08-22 Budget Q3]]

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
| `type` | code | `person`, `org`, `topic`, `howto`, `me` |
| `title` | model at creation; `title` op later (the file name stays) | a noun phrase, at most 6 words, no dates |
| `aliases` | merged by code, never removed by code | other names, spellings, addresses; what matching searches; Obsidian resolves `[[alias]]` links with them |
| `summary` | model (`summary` op), at most 160 characters | the one line in `Index.md`; the only thing read before deciding to open the page |
| `status` | model op or lint | `active`, `dormant` (no record in 60 days), `closed` (outcome reached), `draft` (created by code, no lead yet) |
| `owner`, `org` | model | optional, quoted wikilinks |
| `created` | code | |
| `updated` | code, on every write | last time anything below the frontmatter changed |
| `verified` | code | date of the newest *source* that confirmed or added a fact — "accurate as of", which says more than "last written" |
| `sources` | code | count of distinct record links in Facts and Records |
| `open_items` | code | unchecked boxes under `## Open` |
| `flags` | code / lint | `contradiction`, `possible-duplicate`, `stale`, `oversized`, `orphan`; empty means clean |
| `created_by` | caller | |

`created`, `updated`, `verified`, `sources`, `open_items` and `flags` are code-owned: a create that tries to set them fails with an error naming them as code-owned. Per type: `person` adds `name` (same as the title), `email`, `org` (plain text, not a link), `last_contact`; `org` adds `domains` (matched on sender domains); `topic` adds `owner`, `org`, `due` (lint reports a `due` in the past on an active page); `howto` adds `last_done`.

### Sections — fixed order, fixed meaning

| Section | Written by | Rule |
| --- | --- | --- |
| Lead (between `# Title` and the first `##`) | model, `lead` op, at most 80 words, 2–4 sentences | Stands alone: what the thing is and its current state. The one place the model replaces text. |
| `## Facts` | code, from model ops | One bullet = one claim, at most 25 words, present tense, no hedging. Each ends with a hidden comment `<!-- f:<id> since:<date> src:<record id> -->`: `since` is the date the claim became true according to the source, `src` the record's `internet_message_id` or `occurrence_key`, or `user`. Only current facts. At most 25 bullets. |
| `## People` (`## Contacts` on org pages, `## Topics` on person pages) | code | Link plus a role of at most 4 words, from the link graph and `role` ops. |
| `## Open` | code | Checkbox lines, each linking the record it came from; mirrors `Follow-ups.md` rows and record action items that point at this page. Ticked lines move to History on the next write. |
| `## Records` | code | `- <date> — [[record]] — <the record's summary line>`, newest first, capped at 15. Older ones are still reachable through `find`. |
| `## Related` | code | Links to other wiki pages: from `related` ops, from pages linked in Facts, and from back-links. Symmetric. |
| `## History` | code, append-only | `- <date> — <what> ([[record]])`. Superseded and retired facts land here with old and new text; `add` and `confirm` are only in the log. At 40 lines the oldest move to `Wiki/_history/<Folder>/<name>.md`, one pointer line stays. |
| `## Notes` | you only | Code never reads or writes below this heading. If something you wrote here contradicts a Fact, lint reports it; your text wins. |

A page missing a section gets it added in order on the next write. A page with an unknown `## Heading` above `## Notes` is reported by lint (check 5, `unknown`) and kept, not "fixed". Per type: `person` has Facts / Topics / Open / Records / Related / History / Notes (a `Voice with this person:` block from an older vault is kept under Notes); `org` has Facts / Contacts / Topics / Records / Related / History / Notes; `howto` has `## Steps` (numbered, model-written, replaced whole by the `steps` op) before Facts / Records / Related / History / Notes; `me` has Facts / Related / History / Notes.

### Size caps (enforced, not advisory)

| | Max lines | Max characters |
| --- | --- | --- |
| person, org, howto | 80 | 4,000 |
| topic | 120 | 6,000 |
| Facts | 25 bullets | |
| Lead | 80 words | |
| `Index.md` | 200 lines | 25,000 |

A write that would exceed the page cap is refused (`cap`, with the measured lines and characters) and the three remedies: supersede or merge facts, move detail to a new page and leave a one-line pointer fact, or close the page. A 26th fact is refused as `facts-cap`, a fact over 25 words as `fact-too-long`, a lead over 80 words as `lead-too-long`, a summary over 160 characters as `summary-too-long`. When `Index.md` passes 200 lines (or 25,000 characters) it splits into one index per type folder plus a short root index pointing at them.

## Operations

Facts are located by id (four characters, shown in the hidden comment; the model only uses ids the read returned). Every fact op carries `src`.

| Op | Fields | What happens |
| --- | --- | --- |
| `add` | text, since, src | New bullet, new id. Text identical to an existing fact (ignoring case and spacing) is treated as `confirm` (the result says `result: confirm`). |
| `update` | id, text, src | Same claim, better wording. Id and `since` stay; `src` gains the new source (up to 3, newest first). History: `updated f:<id>`. |
| `supersede` | id, text, since, src | The claim changed: a date moved, an owner changed, a decision reversed. Allowed only when the new `since` is on or after the old one; otherwise refused (`older-than-current`) and the pair goes to Review. Old bullet moves to History as `superseded "<old>" → "<new>"`; the new bullet gets a new id. |
| `confirm` | id, src | The source repeats a known fact. `src` extended, `verified` bumped, text untouched. This is what keeps `verified` honest. |
| `retire` | id, src, reason | No longer true and nothing replaces it (a project cancelled). Moves to History as `retired "<old>" — <reason>`. |
| `contest` | id, text, src | The source disagrees with a fact but is older, same-day, or the model is unsure. Facts stay as they are; the page gets `flags: [contradiction]` and Review gets a line with both texts and both records. |

Page-level ops: `lead` (text), `summary` (text), `status` (value), `title` (text; the old title becomes an alias), `alias` (text; add only), `related` (page; add a link), `role` (page, role), `open` (text, src), `steps` (text; howto only), `due` (value; topic only), `owner` (value), `org` (value). All but `lead`, `summary`, `title`, `related`, `role` need a `src` (at ingest it defaults to the record's id, so it is never missing there). An empty op list is a valid "nothing new": code still adds the Records line and a `seen` History line if the record was new to the page.

Two rules from this: **later wins, only if later** — a freshly saved *older* mail can never overwrite a newer fact; and **nothing is deleted** — every superseded or retired line is in History and in the log with both texts, the date and the record. Reverting is a new supersede the other way.

### Your pins

Anything under `## Notes`, and any fact with `src:user` (you said it in chat and the model wrote it through `vault_wiki_apply`), outranks what the model learns from records: a `supersede`, `update` or `retire` on a `src:user` fact from a record is refused (`user-pin`) and goes to Review instead.

### Contradictions

Code cannot see that two sentences cannot both be true; the model can, but it does not settle it alone. If the newer record contradicts a fact, the model supersedes (logged, old text kept). If the contradicting record is older or same-day, or the model is unsure, it contests. `Review.md` then holds a line like

```
- [ ] [[Wiki/Topics/q3-budget]] — f:7k2q "Deadline for the user's numbers is 2026-08-29" vs "Deadline is 2026-08-27" ("<7f3a9c@example.com>" / [[Emails/2026-08-19 Budget timing]])
```

(the current fact's sources in quotes, then the contesting record's link). A refused `supersede` writes a similar line with `(since <date>) vs older "<text>" (since <date>)`; a refused change to a user fact writes `user fact "<text>" vs "<text>"`. Say "resolve review" in chat; the fix is an ordinary op from your answer. Resolved lines move to `## Done` with the date (ticking the box in Obsidian alone changes nothing).

## Index, log, review

**`Wiki/Index.md`** is generated from frontmatter after every write, so it cannot drift from the files. One line per page: link with title, status (or organisation for people), the `verified` date, the summary. Grouped by type; `active` before `draft` before `dormant` before `closed` (closed pages beyond 20 collapse to a count); newest `verified` first, so the top of each group is what matters now. It is the home page in Obsidian. The model never reads it whole; `vault_wiki_match` returns the few lines that match a subject, sender or domain.

```markdown
## Topics (12)
- [[Wiki/Topics/q3-budget|Q3 budget]] · active · 2026-08-22 — Final Q3 numbers due to Jane by 2026-08-29; forecast closes 2026-09-02.

## People (18)
- [[Wiki/People/Jane Doe]] · Example GmbH · 2026-08-22 — Finance lead; owns the quarterly forecast; prefers short mails.
```

**`Wiki/Log.md`** is append-only: `- [2026-08-22T09:40:00+02:00] ingest | Wiki/Topics/q3-budget | [[Emails/2026-08-22 Budget Q3]] | add 2, supersede 1`. One line per page per ingest (`ingest`), per chat change (`apply`), per page created (`create`), per person page touched by a saved mail (`record`), per resolved review item (`review`), one per lint run (`lint`), merge (`merge`) and migration (`migrate`). At 500 lines it rolls over to `Wiki/_history/Log-YYYY.md`.

**`Wiki/Review.md`** is the checklist of what code could not decide, under `## Open` (resolved lines move to `## Done`): contradictions, pages that may be duplicates ("merge A into B?"), stale pages, refused supersedes and refused changes to your facts. Topic proposals from candidates are not written here; `vault_wiki_match`, ingest and lint check 12 report them. Every line links the page. `/administrator:weekly` lists the open count; `/administrator:lint` adds to it.

**`_views/Wiki.base`** gives you Obsidian tables over the wiki: active topics by `verified`, stale pages, the review queue (pages with flags), people by organisation. Bases read frontmatter, which is exactly what code maintains, so the views are never stale.

## Lint

`/administrator:lint` (and `weekly`, with `fix`) runs a fixed list. Flags (`orphan`, `stale`, `oversized`, `possible-duplicate`) and Review lines are written in both modes; the fixes in the last column only with `fix`. Everything else is reported.

| # | Check | With `fix` |
| --- | --- | --- |
| 1 | Index and files agree | regenerated |
| 2 | Dangling `[[links]]` under `Wiki/` | link becomes plain text, only in code-owned sections |
| 3 | Orphans: no inbound link from any page or record | flagged `orphan`, reported |
| 4 | Frontmatter: missing, extra or mistyped keys; code-owned keys edited by hand | code-owned keys recomputed; the rest reported |
| 5 | Section order, unknown or duplicate headings | order fixed; unknown headings kept and reported |
| 6 | Oversized page | flagged `oversized`, the three remedies shown |
| 7 | Stale: active, `verified` older than 60 days (topic, howto) or 120 days (person, org, me) | flagged `stale` and one Review line; topics set to `dormant` |
| 8 | `due` in the past on an active topic | reported |
| 9 | Open items whose record action item is ticked | moved to History |
| 10 | Possible duplicates: a shared alias, address or domain, or titles equal once case, punctuation and `the/a/of` are ignored | flagged on both; Review line "merge A into B?" — merged only on your yes |
| 11 | Records never ingested (no `wiki:` key, newer than the last ingest) | counted and listed (up to 50); `weekly` offers to ingest ten at a time |
| 12 | Topic candidates over the threshold with no page | proposed |
| 13 | History over 40 lines, log over 500 | rolled over |
| 14 | Contradictions on pages touched since the last lint | the model reads them; Review line only |
| 15 | Facts older than 180 days with a single source, on active pages | reported as "unconfirmed", at most 20 |

A merge (`vault_wiki_merge(keep, drop)`) moves the facts, aliases, records and links of `drop` onto `keep`, keeps `drop`'s full old text under `Wiki/_history/`, and leaves a short redirect page (`type: redirect`) in `drop`'s place, so no link breaks; a read of the old page follows the redirect. It only ever runs after you say the two pages are the same thing; a similar name alone only produces the question.

## What the model never does here

Edit a page file directly; set a code-owned key; delete a fact; overwrite a newer fact with an older record; resolve a contradiction on its own; merge two pages without your yes; create a topic page from one mail; read or write below `## Notes`.

## Your notes on this schema

Add anything below this line. `/administrator:wiki` reads it when you ask ("what does my Wiki.md say"); no other command does.
