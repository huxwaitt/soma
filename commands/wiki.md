---
description: Read a wiki page, answer a question from the wiki, add or change a fact from chat (pinned as yours), or ingest a record that was saved before the wiki existed. Reads the vault only; writes wiki pages through the vault_wiki_* tools.
argument-hint: "<page | question | add/update/close … | ingest <record path>>"
---

# /soma:wiki

Argument (required), one of:

- a page name or path (`jane doe`, `q3 budget`, `Wiki/Topics/q3-budget`) → show the page;
- a question ("what do we know about the ACME contract", "who owns the forecast") → answer from the wiki with links;
- a statement starting with `add`, `update`, `close`, `retire`, `alias`, `note` ("add: Jane is on leave until 2026-09-08", "close q3 budget", "the deadline moved to 29 Aug") → an op on a page, written with `src: user`;
- something somebody owes ("Tom owes me the schedule by Friday", "I promised Jane the numbers", "that one is done", "push the contract to 9 Sep") → an `open`, `done` or `reschedule` op on the page it is about;
- a decision the user states ("we decided to go with net 45") → a decision page, confirmed by the same sentence, so no `unconfirmed-decision` question is asked;
- `ingest <record path or words>` → run the ingest step on an existing email or meeting note;
- `review` / `resolve review` → list `Wiki/Review.md` items, then apply the user's answers;
- `schema` → read the user's notes at the end of `Wiki/Wiki.md` and say what they add.

Argument given: `$ARGUMENTS`

## Steps

1. Load the `soma` skill, then the `wiki` skill (`skills/wiki/references/examples.md` only for `ingest`).
2. `vault_status` once per session; `folders["Wiki"]` false → `vault_init(created_by="soma/0.4.2")` and mention `/soma:setup` (it offers the migration of an older vault).
3. **Question.** One call: `vault_wiki_search(query=<argument>, brief=true, max_chars=1500)` → `{text, pages, facts, chars}`; answer in 2–5 lines from that text, each claim followed by the link of the page it came from; quote facts, do not reword them. Empty → say so and offer `/soma:find`. An id, a date or a `"quoted phrase"` in the argument is matched as written, so `f:7k2q` or `2026-08-29` finds its fact.
3b. **A page named.** `vault_wiki_search(query=<argument>, pages=true, limit=8)`. One clear hit (exact title or alias) → `vault_wiki_read(path, sections=["lead","facts","open","records"], max_chars=1500)` and show: title, status, `verified`, the lead, Facts as bullets (no ids), open items, the three newest records. Several hits → the index lines as a numbered list and a question; none → step 3. Never read `Index.md` whole.
4. **Statement.** Match the page as in step 3b (ask when unclear), `vault_wiki_read(path, sections=["facts"])` (add `"open"` for a commitment), pick the op (`add` / `update` / `supersede` / `retire` / `status` / `alias` / `lead`; `open` / `done` / `reschedule` for a commitment, with `owner` and `due` when the user named them; `due` / `outcome` / `milestone` / `risk` / `link` on a topic), show it in one line ("Supersede `Deadline … 2026-08-27` → `Deadline … 2026-08-29` on Topics/q3-budget, src: user — ok?") and on a yes: `vault_wiki_write(pages=[{"path": …, "ops": [...]}], created_by="soma/0.4.2")` (`src` defaults to `user`). `since` = today unless the user gave a date. A `note:` statement is refused: `## Notes` is the user's section in Obsidian, the plugin never writes it. A decision the user states is `vault_wiki_write(pages=[{"new": {"type": "decision", …, "decided": …, "by": [...]}}])`, and the Review line it writes is resolved in the same turn (`resolution_ops=[{"op": "confirm", "id": <the first fact>}]`), because the user just said it. On a decision page every rewriting op comes back `append-only`: say so and offer a new decision or a fact on the topic.
5. **Ingest.** Find the record (`vault_find("email", …)` / `vault_find("meeting", …)` with `fields=["wiki","subject","received","from","internet_message_id","occurrence_key","attendees"]`, or `vault_find` on words), `vault_read` it once for the body, then the ingest steps of the `wiki` skill. A record that already has a `wiki:` key → say so and ask before ingesting again.
6. **Review.** `vault_wiki_keep(action="review")` → `{open: [{n, text}], done}`; show the open lines numbered. For each answer the user gives: `vault_wiki_keep(action="review", review_action="resolve", item="<n>", resolution_ops=[...], created_by="soma/0.4.2")` (a `confirm` with `src: user` on the fact that holds, a `supersede` with `src: user` when the other text is right; `{"op": "confirm", "id": <the first fact>}` for an "unconfirmed decision" line, or `{"op": "status", "value": "dropped"}` to drop it; `done` / `reschedule` for an "overdue" line; no ops when the answer needs none, e.g. "leave it dormant"). A merge yes → `vault_wiki_keep(action="merge", keep, drop, created_by="soma/0.4.2")`, which moves the line to Done itself. One item per question; never resolve without an answer.
7. Report in 2–5 lines; every page changed gets `obsidian://open?vault=<vault_name>&file=Soma/Wiki/<type>/<name>`. If the host shows the turn's token count, end with `Tokens this turn: <n>`; otherwise say nothing about it.

## Example

```
/soma:wiki q3 budget
/soma:wiki who owns the supplier contract at ACME
/soma:wiki add: Jane is out of office until 2026-09-08
/soma:wiki ingest Emails/2026-08-12 Net 30 terms
/soma:wiki resolve review
```

> **Q3 budget** — active, verified 2026-08-22. Jane Doe (finance) is collecting final Q3 numbers from each team lead by 2026-08-29 to close the forecast on 2026-09-02. The user owes the sales-team figures.
> Facts: deadline for my numbers 2026-08-29 · forecast closes 2026-09-02 · numbers go into Budget_Q3.xlsx, tab Sales.
> Open: send Q3 numbers to Jane — owner: me · due 2026-08-29. Records: 2026-08-22 Budget Q3, 2026-08-20 Budget review with Jane.
> obsidian://open?vault=Vault&file=Soma/Wiki/Topics/q3-budget
