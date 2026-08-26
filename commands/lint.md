---
description: Run the wiki's fixed checklist — index drift, dangling links, orphans, frontmatter, section order, size caps, stale pages, past due dates, ticked open items, possible duplicates, records never ingested, topic candidates, contradictions, unconfirmed facts. With "fix", the safe fixes are applied; everything else is reported or added to Wiki/Review.md.
argument-hint: "[fix]"
---

# /administrator:lint

Argument (optional): `fix` applies the safe fixes (regenerate the index, recompute code-owned keys, fix section order, move ticked open items to History, turn dangling links in code-owned sections into plain text, set stale topics to `dormant`, roll over long History sections and the log). Without it, only the flags (`orphan`, `stale`, `oversized`, `possible-duplicate`) on the pages, the Review lines, the index, one Log line and the report file under `Wiki/_cache/` are written.

Argument given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `wiki` skill.
2. `vault_status` once per session; `folders["Wiki"]` false → `vault_init(created_by="administrator/0.4.0")` and mention `/administrator:setup` (it offers the migration of an older vault).
3. One call: `vault_wiki_lint(fix=<true when the argument is "fix", else false>, created_by="administrator/0.4.0")`. The result: `counts` (one number per check: `dangling`, `orphans`, `frontmatter`, `sections`, `oversized`, `stale`, `due_past`, `open_done`, `duplicates`, `uningested`, `candidates`, `history_over`, `ask_model`, `unconfirmed`), `counts["hand_edits"]`, `checks` keyed `"0"`…`"15"` (`checks["0"]` is the pass that reads back what the user changed in Obsidian: `{name: "hand-edits", adopted: [{page, changes}], review, first_run, scanned}`) (each with `name`, its `items` / `pages` / `records` and `fixed` where a fix exists; `checks["10"].items` are the duplicate pairs `{a, b, shared}`, `checks["12"].items` the topic candidates, `checks["14"].ask_model` the pages touched since the last lint whose Facts the model should read for contradictions), `flagged` (page → flags), `review_added` (the lines), `written` (pages rewritten), and `cache` (the report file).
4. **Check 14.** For each stem in `checks["14"].ask_model` (at most 10 per run; say when more were skipped): `vault_wiki_read(path, sections=["facts"])`, read the Facts, and for each pair that cannot both be true send `vault_wiki_apply(path, ops=[{"op": "contest", "id": <the newer one>, "text": <the older text>, "src": <the older fact's src>}], created_by="administrator/0.4.0")`. No pair → nothing. Never supersede or retire from lint; Review lines only.
5. **Proposals** (checks 10 and 12) are questions, not actions: list each "merge A into B?" and "create topic `<slug>` from N records?" with its page links and ask. On a yes to a merge: `vault_wiki_merge(keep, drop, created_by="administrator/0.4.0")`. On a yes to a topic: `vault_wiki_create(type="topic", title, aliases, lead, summary, facts=[], src=<first record's id>, created_by="administrator/0.4.0")`, then offer to ingest the candidate's records (`/administrator:wiki ingest …`). One question per proposal; silence is a no.
6. Report: when `checks["0"].adopted` is not empty, one line first naming the pages read back and what changed on them; then one line per check with a count above zero (`<name>: <count>` plus `fixed` when `fix` ran), the Review lines added (verbatim, at most 10), the pages flagged, the un-ingested record count with `/administrator:weekly` as the way to ingest them in batches, then `obsidian://open?vault=<vault_name>&file=Administrator/Wiki/Review` when Review grew. Checks with a zero count are left out. No raw JSON.
7. If the host shows the turn's token count, end with `Tokens this turn: <n>`; otherwise say nothing about it.

## Example

```
/administrator:lint
/administrator:lint fix
```

> Lint 2026-08-22 (fix): index regenerated (2 lines off), 1 dangling link → plain text, 3 stale (2 topics set dormant, 1 person flagged), 1 due date past on `Topics/acme-supplier-contract`, 2 ticked open items moved to History, 1 possible duplicate, 4 records never ingested, 1 topic candidate, 0 contradictions in 3 pages read, 5 unconfirmed facts.
> Review +2: merge `Orgs/acme-parts` into `Orgs/acme-parts-gmbh`? · create topic `offsite-2026` from 3 records?
> obsidian://open?vault=Vault&file=Administrator/Wiki/Review

Running it again right after reports the same counts minus what was fixed, and adds nothing to Review twice.
