# Plan — tools consolidated, bulk mail dropped in code, safety rails, document records (administrator 0.4.1)

Runs after the token-cuts pass (shorter tool descriptions, terse skills, smaller collect caps, lint items on request, the token estimate with calibration) is verified and committed. Two passes, each verified by a fresh agent and committed in both repos; no pause between them. Names below were confirmed by the user; plain words everywhere; the banned-word list applies.

Detailed designs: `scratchpad/designs/design-consolidation-bulk.md` (pass A) and `scratchpad/designs/design-documents.md` (pass B).

## Pass A — 18 tools, bulk mail, safety rails

### A1. Consolidation (server `src/administrator_vault/server.py`, tests, every plugin file)
34 vault tools become 18. Module functions keep their names; only the tool layer changes; every old tool name disappears from the server and the plugin (a grep for each old name must come back empty).

| New | Absorbs | Shape |
| --- | --- | --- |
| `vault_wiki_search` | `vault_wiki_match` | `pages=true` returns the old match answer (`pages[]`, `candidates`); `people`, `domains` kept for that mode |
| `vault_wiki_write` | `vault_wiki_ingest`, `vault_wiki_create`, `vault_wiki_apply` | `pages=[{path \| new: {...}, ops}]`, `record_path=None`, `src="user"`, `created_by`; with a record = ingest, without = apply, a `new:` spec with no ops = create |
| `vault_wiki_keep` | `vault_wiki_log`, `vault_wiki_review`, `vault_wiki_lint`, `vault_wiki_merge`, `vault_wiki_migrate` | `action=log \| review \| lint \| merge \| migrate`; each old tool's parameters as optional parameters with their old names (review's own `action` becomes `review_action`) |
| `vault_save` | `vault_save_email`, `vault_save_chat`, `vault_attach_transcript` | `kind=email \| chat \| transcript` (+ `document` in pass B) |
| `vault_collect` | `vault_collect_sources`, `vault_changed_notes` | `action=read \| advance \| tokens \| changed` |
| `vault_time_block` | `vault_time_block_plan`, `vault_time_block_write`, `vault_time_audit` | `action=plan \| write \| audit` |
| `vault_row` | `vault_append_row`, `vault_move_row` | `action=append \| move` |
| `vault_find` | `vault_list` | no `identity` = list |
| unchanged | `vault_status`, `vault_init`, `vault_read`, `vault_write`, `vault_rules`, `vault_inbox_prepare`, `vault_write_daily`, `vault_prep_context`, `vault_weekly_facts`, `vault_priorities_write`, `vault_wiki_read`, `vault_load_history` | |

Answers keep their shapes. Descriptions stay inside the token-cuts caps (vault total ≤ 22,000 chars; a merged tool never longer than the sum of its parts). The plugin: every command, skill, reference and example; the contract (`wiki_schema.md` = `skills/wiki/references/wiki.md`); README; `skills/administrator/SKILL.md` + `references/vault.md`. Tests: the MCP-layer tests call the new names; the tool-count test says 18.

### A2. Bulk mail dropped in code
- Outlook server (`src/outlook_mcp/client/mail.py`): every listed mail gains `bulk` (bool) and `bulk_why`. Signals, any one enough: transport headers (`PropertyAccessor`, PR_TRANSPORT_MESSAGE_HEADERS, read once per item, only when `bulk` is requested, errors → not bulk) holding `List-Unsubscribe`, `Precedence: bulk/list/junk`, `Auto-Submitted` other than `no`, `X-Auto-Response-Suppress`; a sender local part matching `no-?reply|noreply|donotreply|do-not-reply|newsletter|news|marketing|notification(s)?|mailer|bounce|alerts?|digest` or a display name holding `newsletter` / `no reply`; a message class of a meeting response, read receipt or out-of-office. Tests with the fake COM objects: each signal, the cache, a failing accessor.
- Vault server: `vault_rules(action="match")` keeps its per-item results and gains `kept[]`, `dropped[{entry_id, why: "bulk: …" \| "rule: …"}]`, `counts{bulk, never_save, kept}`.
- Plugin: `collect-information` and `load-history` list with `bulk` in `fields`, call `vault_rules(action="match")` before any preview is read, work on `kept`, report "N bulk / M by your rules dropped"; `inbox` lists `bulk` and labels those `noise` without reading; the `outlook` skill documents the field; `Rules.md` template says never-save rules apply to collect-information and load-history too.

### A3. Safety rails
- **Backup before the first rewrite**: `vault_init` (and so `setup`) zips `Administrator/` into `Administrator/_backup/<stamp>.zip` when the vault already has pages and no 0.4 state file exists yet (`Wiki/_cache/state.json` absent); `setup` reports where it is. Standard library `zipfile`; `_cache/` and `_backup/` left out of the zip.
- **Reads that write**: the reconcile pass leaves the read tools (`vault_wiki_search` in every mode, `vault_wiki_read`, `vault_wiki_keep(action=log)`, `vault_wiki_keep(action=review, review_action=list)`) — they only *detect* hand edits and answer `hand_edits: n` when the state file and the files differ; adoption happens on the next writing call (`vault_wiki_write`, `vault_wiki_keep(action=lint)`, `vault_save`, …). `readOnlyHint` becomes true only where nothing is written (the query log moves from search to `_cache` writes performed by the writing tools? — no: the query log is a cache file, not vault content; keep it and say so in the description). Tests: a hand edit followed by a read → detected, not adopted; followed by a write → adopted.
- **Pinned Teams reader**: `pyproject.toml` `teams` extra pins `ccl_chromium_reader` to the commit that installed here (`ef840de30221c4d65bc96d2f4d9057e9ef2f526d`), with a comment on how to move it.
- **`load-history` "yes for the rest"**: the per-batch question accepts "yes to all" — the skill then runs the remaining batches without stopping, still showing each batch's bullets and the running cost line, and stops on the first refusal, on a Review contradiction that needs the user, or when the estimate for the next batch exceeds a cap the user named ("yes to all, stop at 500k"). `vault_load_history` gains `auto: bool` in the state and in `done`'s answer so a re-run knows the mode; the command's argument-hint gains `all`.

### A4. Verification and commit
Full suite; a scripted run (temp vault) that calls every one of the 18 tools once through the MCP layer with the old flows (ingest, apply, create, lint, review, merge, migrate dry run, save email/chat/transcript, collect read/advance/changed/tokens, time-block plan/write/audit, row append/move, find with and without identity); the bulk flag on fake mails with each signal; `vault_rules(match)` kept/dropped; backup zip created once; hand edit + read → detected only; text checks (old tool names absent from both repos, banned words, SKILL.md ≤ 120 lines, contract identical, size caps). Then one commit per repo.

## Pass B — document records and the shared record contract

### B1. Record contract (server `notes.py`, `workflows.py`, `wiki.py`; contract text)
Core frontmatter for every record kind after `type`: `source`, `record_id`, `title`, `date`, `people`, `wiki`, `ingested`, `created_by`, then the kind's own keys as today. `record_id` written by code from the kind's identity (email message id else entry id; meeting occurrence key; chat `<chat_id>|<date>`; document 16 hex of the file's sha256; daily `date`; weekly `week`). `ingested` set by `vault_wiki_write` with a record. Body order: `# Title` · header lines · `## Summary` · `## Action items` · `## Content` (sections `### <locator> — <heading>` when there is more than one part) · `## Files` · `## Update <ISO>` blocks. Email writer: `## Body` → `## Content`, `## Attachments` → `## Files`; a thread's mails become `### m<n> — <date> <from>` sections. `store.find` identity unchanged. Fixtures and tests updated to the new headings.

### B2. Locators
`src:"<record_id>#<locator>"` — `p<n>`, `s<n>`, `<sheet>!<cell>` / `<sheet>`, `m<n>`. Parsing keeps the string; `_record_src_id`, `count_sources`, `stream_of`, lint check 4 and the search engine's source counting strip from `#` on. The contract documents the grammar; the wiki skill says when to add one (the section heading of the record part that holds the fact).

### B3. Documents (`src/administrator_vault/documents.py`, `workflows.save_document`, `vault_save(kind="document")`)
- `extract(path)` → `{format, sections[{locator, heading, text, chars}], parts, chars, empty}`: PDF via `pypdf` (missing → a VaultError naming the `search` extra), `.docx` / `.pptx` / `.xlsx` via `zipfile` + `xml.etree` (paragraphs and tables in order; slide titles, text frames, notes; sheets as rows with the first cell's address), `.txt` / `.md` / `.csv` as they are; anything else refused; a PDF without a text layer → `empty: true` and the record says so.
- Record `Administrator/Documents/<date> <slug>.md` (`date` = file mtime, or the email's received date when `from_email` is given); kind keys `path`, `hash`, `format`, `parts`, `chars`, `from_email`, `text_file`. `## Content` up to `DOCUMENT_CHARS = 40000`; beyond that the full text goes to `Attachments/<slug>/text.md` and the record keeps each section's heading and first 300 chars with a link. Same hash again → `unchanged`; same path, new hash → `## Update` with the new sections, `hash`/`parts`/`chars` replaced. Answer `{path, action, record_id, format, parts, chars, empty, text_file, sections[{locator, heading, chars}]}`.
- `vault_read(path, section=<locator or heading>)` returns one `###` section, so a long deck is read part by part.
- Email attachments: `save` offers "ingest the attachments too?"; on a yes, export (`outlook_save_attachments`) then one `vault_save(kind="document", path, from_email=<email record>)` per file; the email's `## Files` line gains the document link; the document's `## Files` links the email.
- `document_folders` in `Preferences.md` (default `[]`): `vault_collect(action="changed")` lists new or changed files there as `{path, kind: "document", modified, size, format}` without extracting; `collect-information` saves the ones the gate matches (name + first section) and ingests them like any record.
- Search stays wiki-only (decided): documents are found through the pages that cite them.

### B4. Plugin
`/administrator:save <file path>` (argument may be a path; extract, show the section list, run the wiki step on at most 5 matched sections, cite locators); `skills/save` + examples (document run, attachment offer); `skills/wiki/SKILL.md` (locators); `skills/collect-information` + command (documents from `document_folders`); `skills/administrator/SKILL.md` + `references/vault.md` (one record-contract table for every kind, `Documents/`); `skills/schedule/references/preferences.md` (`document_folders`); `commands/setup.md` (`Documents/` created); README ("Documents" paragraph); `plugin.json` 0.4.1; `CREATED_BY` "administrator/0.4.1" everywhere.

### B5. Tests and verification
`tests/test_documents.py`: docx / pptx / xlsx generated in the test with `zipfile`; PDF through `pypdf` when installed (skipped otherwise); txt / md / csv; the cap and the text file; unchanged and updated saves; `from_email` linked both ways; `vault_read(section=)`; a fact with `src:"<doc>#p3"` counted once against the Records line; `document_folders` in `changed`; the record contract on every kind; the MCP round trip. Scripted end-to-end on a temp vault: save a generated deck → sections → ingest two facts citing slides → the topic page shows the document under Records and the facts carry `#s2` / `#s5`; an email with an attachment → both records linked; a changed file in a watched folder shows up in `changed`. Text checks as in A4. One commit per repo; then `CHANGELOG.md` in both repos summarising 0.4.0 → 0.4.1 and a local tag `v0.4.1`.

## Order
1. Token-cuts pass: fix the verifier's findings, commit.
2. Pass A (A1 ∥ A2 ∥ A3 as three builders on disjoint files where possible — A1 owns `server.py` and all plugin tool-name edits; A2 owns `mail.py`, `rules_match` and the three skills' mail steps; A3 owns `store.init`, `wiki_reconcile` hooks, `pyproject.toml`, `history.py` auto mode and the load-history skill — then a reviewer, a verifier, fixes, commit).
3. Pass B (one server builder for B1–B3, one plugin builder for B4, reviewer, verifier, fixes, commit, CHANGELOG, tag).
