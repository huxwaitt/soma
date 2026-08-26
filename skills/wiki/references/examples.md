# wiki — worked examples

Three ingests, call by call. Tool results are cut to what the model reads. Dates are local; `src` values are the record's `internet_message_id` or `occurrence_key`, exactly as the record's frontmatter holds them.

## Example 1 — ingest after `save`

`/administrator:save budget q3 jane` on 2026-08-22 wrote `Administrator/Emails/2026-08-22 Budget Q3.md` (`internet_message_id: <7f3a9c@example.com>`, `received: 2026-08-22T09:14:00+02:00`, sender `jane.doe@example.com`, summary "Jane asks for the final Q3 numbers by Friday so she can close the forecast."). `body_trimmed`:

> could you send me the final Q3 numbers by Friday 29 August? I need them to close the forecast on 2 September. Same sheet as last time, Sales tab.

1. Match:

```
vault_wiki_match(text="Re: Budget Q3 — could you send me the final Q3 numbers by Friday 29 August? I need them to close the forecast on 2 September. Same sheet as last time, Sales tab.",
                 people=["jane.doe@example.com"], domains=["example.com"], limit=8)
```

```json
{"pages": [
  {"path": "Administrator/Wiki/Topics/q3-budget.md", "line": "- [[Wiki/Topics/q3-budget|Q3 budget]] · active · 2026-08-20 — Q3 numbers collected by Jane; forecast closes early September.", "score": 4, "why": ["alias"]},
  {"path": "Administrator/Wiki/People/Jane Doe.md", "line": "- [[Wiki/People/Jane Doe]] · Example GmbH · 2026-08-21 — Finance lead; owns the quarterly forecast.", "score": 3, "why": ["address"]}],
 "candidates": []}
```

2. Read both (two pages, under the limit of three):

```
vault_wiki_read(path="Administrator/Wiki/Topics/q3-budget.md", sections=["lead","facts"])
```

```json
{"path": "Administrator/Wiki/Topics/q3-budget.md", "title": "Q3 budget",
 "frontmatter": {"type": "topic", "title": "Q3 budget", "status": "active", "verified": "2026-08-20", "...": "..."},
 "lead": "Jane Doe (finance) collects Q3 numbers from each team lead to close the forecast in early September.",
 "facts": [
  {"id": "7k2q", "text": "Deadline for the user's numbers is 2026-08-27", "since": "2026-08-20", "src": ["0400…|2026-08-20T13:00:00+02:00"]},
  {"id": "c3mm", "text": "Numbers go into the shared sheet Budget_Q3.xlsx, tab \"Sales\"", "since": "2026-08-20", "src": ["0400…|2026-08-20T13:00:00+02:00"]}]}
```

`vault_wiki_read("Administrator/Wiki/People/Jane Doe.md", sections=["lead","facts"])` → facts `[{"id": "a8p1", "text": "Owns the quarterly forecast", ...}]`.

3. Compare. The mail moves the deadline (27 → 29 Aug; the mail is newer, so `supersede`), states the close date (new → `add`), repeats the sheet and tab (→ `confirm`), and says nothing new about Jane beyond what the page has (→ `confirm` on `a8p1`, plus the open item).

4. One call:

```
vault_wiki_ingest(record_path="Administrator/Emails/2026-08-22 Budget Q3.md", created_by="administrator/0.4.0", pages=[
  {"path": "Administrator/Wiki/Topics/q3-budget.md", "ops": [
    {"op": "supersede", "id": "7k2q", "text": "Deadline for the user's numbers is 2026-08-29", "since": "2026-08-22", "src": "<7f3a9c@example.com>"},
    {"op": "add", "text": "Forecast closes 2026-09-02", "since": "2026-08-22", "src": "<7f3a9c@example.com>"},
    {"op": "confirm", "id": "c3mm", "src": "<7f3a9c@example.com>"},
    {"op": "open", "text": "Send Q3 numbers to Jane", "owner": "me", "due": "2026-08-29", "src": "<7f3a9c@example.com>"},
    {"op": "lead", "text": "Jane Doe (finance) is collecting final Q3 numbers from each team lead by 2026-08-29 to close the forecast on 2026-09-02. The user owes the sales-team figures."},
    {"op": "summary", "text": "Final Q3 numbers due to Jane by 2026-08-29; forecast closes 2026-09-02."}]},
  {"path": "Administrator/Wiki/People/Jane Doe.md", "ops": [
    {"op": "confirm", "id": "a8p1", "src": "<7f3a9c@example.com>"},
    {"op": "role", "page": "Wiki/Topics/q3-budget", "role": "owns the forecast"}]}])
```

```json
{"record": "[[Emails/2026-08-22 Budget Q3]]",
 "pages": [
  {"path": "Administrator/Wiki/Topics/q3-budget.md", "written": true,
   "applied": [{"op": "supersede", "id": "m4rt", "replaced": "7k2q"}, {"op": "add", "id": "9x1a"}, {"op": "confirm", "id": "c3mm"}, {"op": "open", "id": "b8k2", "owner": "me"}, {"op": "lead"}, {"op": "summary"}],
   "refused": [], "record_added": true, "history_added": 1, "sizes": {"lines": 41, "max_lines": 120, "chars": 1870, "max_chars": 6000}},
  {"path": "Administrator/Wiki/People/Jane Doe.md", "written": true,
   "applied": [{"op": "confirm", "id": "a8p1"}, {"op": "role", "page": "Wiki/Topics/q3-budget", "section": "Topics"}],
   "refused": [], "record_added": true, "history_added": 0, "sizes": {"lines": 28, "max_lines": 80, "chars": 1102, "max_chars": 4000}}],
 "candidate": {"subject": "Budget Q3", "records": ["Emails/2026-08-22 Budget Q3"], "days": 1, "over_threshold": false, "page": "Wiki/Topics/q3-budget"}}
```

The page now has `verified: 2026-08-22`, the History line `superseded "Deadline for the user's numbers is 2026-08-27" → "Deadline for the user's numbers is 2026-08-29"`, and the email note carries `wiki: ["[[Wiki/Topics/q3-budget]]", "[[Wiki/People/Jane Doe]]"]`.

5. Report, appended to the save report:

> Wiki: `Topics/q3-budget` (deadline 27 → 29 Aug superseded, 1 fact added, 1 confirmed, 1 open item), `People/Jane Doe` (confirmed).
> obsidian://open?vault=Vault&file=Administrator/Wiki/Topics/q3-budget

## Example 2 — ingest after `notes`, with a decision that supersedes

`/administrator:notes supplier sync` on 2026-08-25 wrote `Administrator/Meetings/2026-08-25 1300 Weekly supplier sync.md` (`occurrence_key: 0400A1…|2026-08-25T13:00:00+02:00`, attendees Jane Doe and Tom Lee of `acme-parts.com`). The notes:

> - contract: Jane ok with net 45, I'll sign tomorrow and send back
> - first Sep delivery moved to 8 Sep, Tom to send updated schedule by Wed
> - packaging spec: Jane will send the draft next week

1. `vault_wiki_match(text="Weekly supplier sync — contract: Jane ok with net 45 … packaging spec: Jane will send the draft next week", people=["jane.doe@acme-parts.com","tom.lee@acme-parts.com"], domains=["acme-parts.com"])` → `Wiki/Topics/acme-supplier-contract` (alias hit "supplier contract"), `Wiki/Orgs/acme-parts` (domain), `Wiki/People/Jane Doe`, `Wiki/People/Tom Lee`. Four hits; read the topic, the org and Tom (Jane's page was read this session and has no fact about delivery or packaging).

2. `vault_wiki_read("Administrator/Wiki/Topics/acme-supplier-contract.md", sections=["lead","facts"])` →

```json
{"facts": [
  {"id": "d2f8", "text": "Payment terms are net 30", "since": "2026-08-12", "src": "<b77e1@acme-parts.com>"},
  {"id": "q5hh", "text": "First September delivery is on 2026-09-01", "since": "2026-08-18", "src": "0400A1…|2026-08-18T13:00:00+02:00"}]}
```

`vault_wiki_read("Administrator/Wiki/People/Tom Lee.md", …)` → facts `[{"id": "r1ke", "text": "Handles purchase orders and delivery scheduling at ACME Parts", ...}]`; the org page holds nothing about terms.

3. Compare. Net 45 replaces net 30 (the meeting is newer → `supersede`, `since` = meeting date). 8 Sep replaces 1 Sep (→ `supersede`). Tom's schedule and Jane's packaging draft are open items, not facts. Tom's role is confirmed by the schedule ask. The packaging spec has a timeline but appeared in one record only: no page, it stays in the meeting note.

4. One call:

```
vault_wiki_ingest(record_path="Administrator/Meetings/2026-08-25 1300 Weekly supplier sync.md", created_by="administrator/0.4.0", pages=[
  {"path": "Administrator/Wiki/Topics/acme-supplier-contract.md", "ops": [
    {"op": "supersede", "id": "d2f8", "text": "Payment terms are net 45", "since": "2026-08-25", "src": "0400A1…|2026-08-25T13:00:00+02:00"},
    {"op": "supersede", "id": "q5hh", "text": "First September delivery is on 2026-09-08", "since": "2026-08-25", "src": "0400A1…|2026-08-25T13:00:00+02:00"},
    {"op": "open", "text": "Sign contract v3 and return it to Jane", "owner": "me", "due": "2026-08-26", "src": "0400A1…|2026-08-25T13:00:00+02:00"},
    {"op": "open", "text": "Updated delivery schedule", "owner": "[[Wiki/People/Tom Lee]]", "due": "2026-08-27", "src": "0400A1…|2026-08-25T13:00:00+02:00"},
    {"op": "lead", "text": "Supply contract with ACME Parts for the Leipzig warehouse, now at v3 with net-45 terms and the first September delivery on 2026-09-08. Waiting on the user's signature and Tom's updated schedule."}]},
  {"path": "Administrator/Wiki/People/Tom Lee.md", "ops": [
    {"op": "confirm", "id": "r1ke", "src": "0400A1…|2026-08-25T13:00:00+02:00"}]},
  {"path": "Administrator/Wiki/People/Jane Doe.md", "ops": []},
  {"path": "Administrator/Wiki/Orgs/acme-parts.md", "ops": []}])
```

The two empty op lists still add a Records line (and a `seen` History line) to Jane's and the org's page. Result: the topic's `applied` holds five entries with two new ids, History gets both `superseded` lines with old and new text; `Log.md` gets four lines (one per page).

5. Report line: "Wiki: `Topics/acme-supplier-contract` (net 30 → net 45, delivery 1 → 8 Sep, 2 open items), Tom Lee confirmed; Jane Doe and ACME Parts got the record link."

## Example 3 — an older mail that contradicts the page → Review

On 2026-08-26 the user says "save the thread with Jane about the budget timing". The newest mail in that thread was received 2026-08-19 (`internet_message_id: <e41c2@example.com>`) and says:

> Let's keep 27 August as the hard deadline for your numbers.

The save writes `Administrator/Emails/2026-08-19 Budget timing.md`. Ingest:

1. `vault_wiki_match(...)` → `Wiki/Topics/q3-budget`.
2. `vault_wiki_read(...)` → fact `m4rt` "Deadline for the user's numbers is 2026-08-29", `since: 2026-08-22`.
3. Compare. The mail disagrees, but it is dated 2026-08-19, before the current fact's `since` of 2026-08-22. The 29 Aug fact came from a later mail, so it very likely still holds — but the model does not decide that. `contest`, not `supersede`:

```
vault_wiki_ingest(record_path="Administrator/Emails/2026-08-19 Budget timing.md", created_by="administrator/0.4.0", pages=[
  {"path": "Administrator/Wiki/Topics/q3-budget.md", "ops": [
    {"op": "contest", "id": "m4rt", "text": "Deadline for the user's numbers is 2026-08-27", "src": "<e41c2@example.com>"}]}])
```

```json
{"record": "[[Emails/2026-08-19 Budget timing]]",
 "pages": [{"path": "Administrator/Wiki/Topics/q3-budget.md", "written": true, "applied": [{"op": "contest", "id": "m4rt", "result": "review"}], "refused": [], "record_added": true, "history_added": 0, "sizes": {"...": "..."}}],
 "candidate": {"...": "..."}}
```

Facts are unchanged; the page now carries `flags: [contradiction]`. `Review.md` gains, under `## Open`:

```
- [ ] [[Wiki/Topics/q3-budget]] — f:m4rt "Deadline for the user's numbers is 2026-08-29" vs "Deadline for the user's numbers is 2026-08-27" ("<7f3a9c@example.com>" / [[Emails/2026-08-19 Budget timing]])
```

Had the model sent `supersede` with `since: "2026-08-19"` instead, the result would have been `refused: [{"op": "supersede", "id": "m4rt", "reason": "older-than-current", "current_since": "2026-08-22", "since": "2026-08-19", "detail": "…"}]` and a Review line of the form `f:m4rt "…2026-08-29" (since 2026-08-22) vs older "…2026-08-27" (since 2026-08-19) ([[Emails/2026-08-19 Budget timing]])` — same outcome, one wasted op.

4. Report: "Wiki: `Topics/q3-budget` — the 19 Aug mail says 27 Aug, the page says 29 Aug from a later mail; sent to Review (1 open item). Say `resolve review` when you know which holds."

When the user answers "29 is right, 27 was the old plan":

```
vault_wiki_review(action="resolve", item="1", resolution_ops=[{"op": "confirm", "id": "m4rt", "src": "user"}], created_by="administrator/0.4.0")
```

→ `{"resolved": "- [ ] [[Wiki/Topics/q3-budget]] — f:m4rt …", "page": "Wiki/Topics/q3-budget", "applied": {...}}`. The Review line moves to `## Done` with the date, the `contradiction` flag is cleared, and `m4rt` gains `user` as its newest source — which now pins it (`user-pin`) against any later record that tries to supersede it.

## Example 4 — a decision, written from the record's own words

The same meeting note says "we agreed to go with net 45 for the whole contract; the 2 % early-payment discount was dropped". That is a choice that now stands, so the decision page goes into the same ingest, without asking:

```
vault_wiki_ingest(record_path="Administrator/Meetings/2026-08-25 1300 Weekly supplier sync.md", created_by="administrator/0.4.0", pages=[
  {"new": {"type": "decision", "title": "Net 45 terms", "aliases": ["net-45"],
           "lead": "The ACME Parts contract runs on net 45 from v3 on. The 2 % early-payment discount was dropped in exchange.",
           "summary": "ACME Parts contract runs on net 45; the early-payment discount is dropped.",
           "decided": "2026-08-25", "by": ["[[Wiki/People/Jane Doe]]"], "options_rejected": ["net 30 with a 2 % early-payment discount"]},
   "ops": [{"op": "add", "text": "The ACME Parts contract runs on net 45"},
           {"op": "add", "text": "The 2 % early-payment discount is dropped"},
           {"op": "related", "page": "Wiki/Topics/acme-supplier-contract"}]}])
```

→ the page is written as `Wiki/Decisions/net-45-terms` with `status: current`, `flags: ["unconfirmed-decision"]`, and one line in `Review.md`: `- [ ] [[Wiki/Decisions/net-45-terms]] — unconfirmed decision: "The ACME Parts contract runs on net 45" — confirm or drop ([[Meetings/2026-08-25 1300 Weekly supplier sync]])`. The report says so in one line: "Decision `Decisions/net-45-terms` written from the meeting — confirm or drop it (`/administrator:wiki resolve review`)."

Later, when the user says "yes, that one stands": `vault_wiki_review(action="resolve", item="net-45-terms", resolution_ops=[{"op": "confirm", "id": "f2np"}])` → the flag goes and the line moves to `## Done`. Dropping it instead is `resolution_ops=[{"op": "status", "value": "dropped"}]`. A later `{"op": "add", …}` on that page comes back `refused: [{"op": "add", "reason": "append-only", "detail": "A decision page is never rewritten. …"}]` — the consequence goes on the topic page, or into a new decision linked with `superseded_by`.

## What the model never does in these runs

- Invents a fact id, a `since` date, or a `src` value; all three come from the read result and the record's frontmatter.
- Adds a fact from the record's summary line rather than its body, or a fact the record does not state.
- Creates a topic page for a subject seen in one record.
- Sends `supersede` for an older record, or resolves a contradiction without the user.
- Writes below `## Notes`, or touches a wiki page with `vault_write` or the host file tools.
- Rewrites a decision page, or writes a row into `Follow-ups.md`: what somebody owes is an `open` op on the page it is about.

## Example 5 — one open item, one `conflicts-with`, one unconfirmed fact

Three short pieces the skill file points at.

**An open item on a person page.** What Jane owes, opened from the mail that asked for it (the `## Open` line format itself is in `wiki.md`):

```
vault_wiki_apply(path="Wiki/People/Jane Doe", ops=[{"op": "open", "text": "Send the signed contract", "owner": "[[Wiki/People/Jane Doe]]", "due": "2026-09-02", "since": "2026-08-25", "src": "<7f3a9c@example.com>"}], src="<7f3a9c@example.com>")
```

Closing it later is `{"op": "done", "id": <the item's `o:` id>, "src": "user"}`, a new date `{"op": "reschedule", "id": …, "due": "2026-09-09", "src": …}`. `Administrator/Follow-ups.md` is written from these lines and refuses rows.

**A `conflicts-with` refusal.** The record says the numbers are due on 2 September; the page already holds "Deadline for the user's numbers is 2026-08-29". The `add` comes back:

```json
{"op": "add", "reason": "conflicts-with", "id": "m4rt", "current": "Deadline for the user's numbers is 2026-08-29", "since": "2026-08-22"}
```

Only that op was dropped; the rest of the call went through. Decide which one holds and resend the single op — never the whole call. The record is the newer one → `{"op": "supersede", "id": "m4rt", "text": <your text>, "since": …, "src": …}`. The record is older, same-day, or you are unsure → `{"op": "contest", "id": "m4rt", "text": …, "src": …}`, which puts both sides in Review. Two genuinely different things (the refusal is a rule, not a reading) → `contest` as well, and the Review line sorts it out. Say in one line which you chose.

**An unconfirmed fact in an answer.** A `brief=true` line ending `(one source, unconfirmed since 2026-01-14)` is never stated flat. Say where it stands — "one mail from January says the deadline is 29 August — worth checking" — or ask the user, or read the record it came from. In a draft, hedge it or leave it out.
