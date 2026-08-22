# Batch 3 plan — administrator 0.0.4

Goal: make the Obsidian side solid (setup, deterministic note writing, native views) and add the two workflows the research rated highest (follow-ups, weekly). Live Outlook testing is a separate, manual step on a machine with a mail profile and is *not* in this batch — but everything here is built so that session can run all seven commands end to end.

## Agents (all Fable)

### Phase 1 — build, in parallel, disjoint files

**A. `vault-tool` — deterministic note writer (server repo, new package `administrator_vault`)**
- Location: `outlook-classic-mcp/src/administrator_vault/` (same repo, second console script `administrator-vault`), exposed as a second MCP server `vault` in plugin.json. Rationale: one uv project, one install, reuses paths/safety helpers.
- Tools: `vault_status()` → vault path, exists, folders present, Preferences present; `vault_init()` → create `Administrator/{Daily,Emails,Meetings,People,Attachments,_views}`, `Follow-ups.md`, `Preferences.md` from defaults; `vault_find(type, identity)` → path or null (searches frontmatter `internet_message_id` / `entry_id` / `occurrence_key` / `global_id` / `email`); `vault_write(type, identity, frontmatter, body, mode=create|append)` → creates with schema validation or appends `## Update <ISO>`; never overwrites human sections; `vault_append_row(file, section, row)` for Follow-ups/daily tables with dedupe on the hidden `entry_id` comment; `vault_read(path)`; `vault_list(type, since)`.
- Frontmatter schemas = `references/vault.md` + `meeting-note.md`, encoded once in Python with tests. Slug rules, filename rules, append rules all move here.
- Path rules: must be under `ADMINISTRATOR_VAULT`; refuses anything outside `Administrator/`.
- Tests: fake vault in tmp dir; create/append/dedupe/invalid frontmatter/outside-path.

**B. `setup` command + core skill rewrite (plugin)**
- `/administrator:setup`: check `ADMINISTRATOR_VAULT` and `OUTLOOK_MCP_DIR`, call `outlook_whoami` (report the profile, timezone, classic vs new Outlook error), `vault_status` → `vault_init` if needed, warn if the vault is outside `C:\Users\<you>` (export sandbox), write `Preferences.md` after asking work hours once, print an `obsidian://open?vault=…&file=Administrator/Preferences.md` link.
- Rewrite `skills/administrator/SKILL.md` + `references/vault.md` so every skill calls `vault_*` tools instead of hand-writing files; vault.md becomes the human-readable schema, no longer the procedure.
- Update inbox/save/meetings/schedule skills to use `vault_find`/`vault_write`/`vault_append_row` (mechanical edit, same agent, after A's contract is fixed in the prompt).

**C. `followups` + `weekly` (plugin, new skill `review`)**
- `/administrator:followups [days=3]`: sent mail in the last 30 days → `outlook_get_conversation` per thread → threads where the last message is mine and no reply for ≥ N days → table (who, subject, days waiting, last line I wrote) → update `Follow-ups.md` (open/close rows) → offer nudge drafts to Drafts (yes per draft).
- `/administrator:weekly [week]`: one note `Administrator/Weekly/YYYY-Www.md`: mails labelled act/reply still open, waiting items aging, meetings held (from Meetings/ notes) with unchecked action items, next week's calendar, people not contacted in 30+ days who have a person note. Read-only.
- Uses vault tools from A.

**D. Obsidian-native pieces (plugin)**
- `Administrator/_views/` shipped by `vault_init`: `People.base` (person → emails, meetings, last_contact), `Follow-ups.base`, `Meetings.base` (by week, unchecked actions), `Emails.base` (by status). Plain Bases syntax, no Dataview.
- Every command reply ends with an `obsidian://open` link to the note it wrote (vault name from the path's last segment unless `ADMINISTRATOR_VAULT_NAME` is set).
- `references/obsidian.md`: how links, Bases, and the `.msg` back-reference work; what the plugin never touches (`.obsidian/`, anything outside `Administrator/`).

**E. Server: `trim_quoted` option**
- `outlook_get_mail(trim_quoted=true)` and `get_conversation(trim_quoted=true)`: deterministic removal of quoted history (`From:` header blocks, `-----Original Message-----`, `On … wrote:`, `>` lines) and signature blocks (`-- `, `Sent from my`, last ≤12 lines after a name line matching the sender). Returns `body_trimmed` alongside `body`, plus `trimmed_chars`. Tests with 8 real-shaped samples (Outlook desktop, OWA, Gmail, iOS).
- Save skill switches to `body_trimmed` (done by B's agent after E reports).

**F. Copilot transcript prompt (plugin, `skills/meetings/references/copilot-transcript-prompt.md`)**
- Already drafted in this batch (see file). Agent wires it into `/administrator:notes`: accepts the Copilot output format (numbered speaker turns), maps speakers to People notes, and keeps the full text under `## Transcript` (collapsed callout) with `## Notes` reserved for the human summary.

### Phase 2 — integrate (one agent)
Apply SHARED FILE EDITS, check every `vault_*`/`outlook_*` name against the real tool modules, bump to 0.0.4, banned-word grep, plugin.json has both MCP servers.

### Phase 3 — verify (one agent)
`uv run pytest -q` (server + vault tool), tool counts, plugin structure, `git status`, no `huxle`.

## Ordering constraints
- A must finish before B and C edit skills → B and C start with their own files (commands, new skill), then wait on A's report for the tool contract. In the workflow: `A` runs alone first for its contract (fast: the schema is already written), then B/C/D/E/F in parallel.
- No commits by agents; I commit after verify.

## Out of this batch
- Live Outlook run (manual, your machine).
- Publishing the server to PyPI / removing `OUTLOOK_MCP_DIR`.
- Moving a whole day of meetings; on-behalf mail; Excel.
