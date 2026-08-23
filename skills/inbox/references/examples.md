# Inbox — worked examples

Two runs on Saturday 2026-08-22, user `hux@example.com`, vault `MyVault`. Every call in the order it happens; results shortened to what the next step needs.

## Run 1 — `/administrator:inbox` at 08:31

1. `vault_status` → all flags true. `outlook_whoami(response_format="json")` → `utc_offset: "+02:00"`, `local_time: "2026-08-22T08:31:02+02:00"`.
2. `vault_list("daily", limit=1, fields=["date", "inbox_checked"])` → `[{path: "Administrator/Daily/2026-08-21.md", frontmatter: {date: "2026-08-21", inbox_checked: "2026-08-21T18:02:00+02:00"}}]`. Say: "Checking mail since Fri 21 Aug 18:02."
3. `outlook_list_mails(folder="inbox", unread_only=true, since="2026-08-21T18:02:00+02:00", limit=100, fields=["entry_id","internet_message_id","from_address","from","subject","received","preview"], preview_chars=80, response_format="json")` at 08:31:10 → `count: 23`, `has_more: false`. Each item is about 60 tokens.
4. `vault_inbox_prepare(items=<the 23 items>, date="2026-08-22")` →

   ```json
   {"to_label": [ ...15 items... ], "already_seen": ["00000000A0…"], "never_save": ["00000000A9…", "00000000B4…"],
    "labelled_by_rule": 7, "cache": "Administrator/Attachments/_cache/inbox-2026-08-22.json"}
   ```

   One mail was already in Friday's note (listed again because it is still unread), two match a never-save rule, seven carry a label from a rule (`rule: "List-Unsubscribe header"`, `rule: "Rules.md: domain vendor.example → noise"`, `rule: "meeting response"`, …) and have no `preview`. Eight items have `label: null` and a 120-character `preview`.

5. Label the eight. One is unclear — subject "FYI: Q3 numbers" from Tom Lee, preview ends in "could you" — so one read:

   `outlook_get_mail(entry_id="00000000A2…", trim_quoted=true, max_body_chars=3000, fields=["subject","body_trimmed"], response_format="json")` → `body_trimmed` asks for the revised figure by Monday.

   Output of this step, and nothing else:

   ```json
   [{"entry_id":"00000000A1…","label":"act","reason":"Sign the NDA by Friday"},
    {"entry_id":"00000000A2…","label":"reply","reason":"Asks you for the revised Q3 figure by Monday"},
    {"entry_id":"00000000A3…","label":"waiting","reason":"Support acknowledged ticket 4411, no answer yet"},
    {"entry_id":"00000000A4…","label":"fyi","reason":"Build passed"},
    {"entry_id":"00000000A5…","label":"fyi","reason":"Status update, nothing asked"},
    {"entry_id":"00000000A6…","label":"reply","reason":"Asks which offsite week works for you"},
    {"entry_id":"00000000A7…","label":"noise","reason":"Cold sales outreach"},
    {"entry_id":"00000000A8…","label":"fyi","reason":"Thread closer, thanks only (unsure)"}]
   ```

6. `vault_write_daily(date="2026-08-22", labels=<the list above>, since="2026-08-21T18:02:00+02:00", inbox_checked="2026-08-22T08:31:10+02:00", tokens_used=9800)` →

   ```json
   {"path": "Administrator/Daily/2026-08-22.md", "action": "created", "rows_written": 15, "duplicates_skipped": 0,
    "followups_added": 1, "calendar_rows": 0, "unlabelled": []}
   ```

   The note now has the 15-row table (sorted act, reply, waiting, fyi, noise; `Why` for the rule-labelled rows is the rule text; the NDA row links `[[Emails/2026-08-22 Sign the NDA by Friday]]` because `save` wrote that note earlier), `## To do` with three lines, `## Waiting on` with the ticket, and `Follow-ups.md` has a new row keyed on `00000000A3…`.

7. No fresh mail is a reply from the `Who` of an open follow-up (Carol Ng's contract draft is still open, nothing from her came in) → `Follow-ups.md` is not read.
8. Report:

   > 23 unread since Fri 18:02: 1 already in Friday's note, 2 never-save, 7 labelled by rules, 8 by me (1 opened). act 1, reply 2, waiting 1, fyi 6, noise 5.
   > To do: Sign the NDA by Friday (Jane Doe); Re: Q3 numbers (Tom Lee); Re: offsite dates (Bob Lee). Follow-ups: +1 (Acme Support, ticket 4411).
   > Written: Daily/2026-08-22.md (created). This turn: 9.8k tokens.
   > Open: obsidian://open?vault=MyVault&file=Administrator%2FDaily%2F2026-08-22.md
   >
   > 1. Mark 11 fyi/noise as read: Nightly build passed, Weekly status, August newsletter, … and 6 more. Go ahead?

   Five `noise` mails came from `news@vendor.example` with the same label — fewer than 5 were labelled by the model (two were rule hits), so no rule is proposed.

9. User: "yes" → `outlook_bulk_mark_mails(entry_ids=[11 ids], read=true)` → `failed: 0`. Then `vault_find("daily", {"date": "2026-08-22"})` and `vault_write("daily", <that frontmatter>, "Done 2026-08-22T08:34:00+02:00: marked 11 as read", mode="append")`.

Calls: 9 (10 with the bulk action). Tokens in the turn: about 10k, of which the list is 1.5k, the prepare result 1k, the labels 0.3k, skill text the rest.

## Run 2 — `/administrator:daily` at 15:40, same day

1. `vault_list("daily", limit=1, fields=["date","inbox_checked"])` → `inbox_checked: "2026-08-22T08:31:10+02:00"` (the only key the morning run changed).
2. `outlook_list_mails(... since="2026-08-22T08:31:10+02:00" ...)` at 15:40:05 → 3 items.
3. `vault_inbox_prepare(items, date="2026-08-22")` → `to_label` has 2 (one `label: "noise"` by rule, one `label: null`), `already_seen: []`, `never_save: ["…"]`.
4. Label the one: Carol Ng, "Re: Contract draft", preview "attached the draft, let me know" → `[{"entry_id":"00000000B1…","label":"fyi","reason":"Sent the draft; wait is over"}]`.
5. `outlook_list_events(start="2026-08-22T00:00:00", end="2026-08-22T23:59:59", include_recurrences=true, limit=50, fields=["occurrence_key","global_id","subject","start","end","location","organizer","all_day"], response_format="json")` → 2 events.
6. `vault_write_daily(date="2026-08-22", labels=<one entry>, events=<2 items>, since="2026-08-22T08:31:10+02:00", inbox_checked="2026-08-22T15:40:05+02:00", tokens_used=6100)` →

   ```json
   {"path": "Administrator/Daily/2026-08-22.md", "action": "appended", "rows_written": 2, "duplicates_skipped": 0,
    "followups_added": 0, "calendar_rows": 2, "unlabelled": []}
   ```

   Under `## Update 2026-08-22T15:40:05+02:00` the server wrote `### Inbox (since 2026-08-22T08:31:10+02:00)` with rows 16 and 17, `### To do` / `### Waiting on` only if needed, `### Calendar` with two rows (each ending in `<!-- occurrence_key: … -->`) and `### Watch out` with "Clash: Budget review with Jane (13:00–14:00) overlaps Dentist (13:30–14:30)" and "No prep note: Budget review with Jane" — both computed in code, nothing passed as `watch_out`.

7. Carol Ng replied on a subject with an open row → `vault_read("Administrator/Follow-ups.md")`, the row's comment is `<!-- entry_id: 00000000AC… -->` → `vault_move_row("Administrator/Follow-ups.md", "Open", "Done", "00000000AC…", set_last_cell="2026-08-22")` → `moved: true`.
8. Report:

   > 3 new since 08:31: 1 never-save, 1 by rule, 1 by me. Carol Ng sent the contract draft → Follow-ups row moved to Done.
   > Today: 09:30 Stand-up (Teams), 13:00 Budget review with Jane (Room 4). Watch out: clash 13:00–14:00 with Dentist; no prep note for the budget review — run /administrator:prep?
   > Written: Daily/2026-08-22.md (appended). This turn: 6.1k tokens.
   > Open: obsidian://open?vault=MyVault&file=Administrator%2FDaily%2F2026-08-22.md
   >
   > 1. Mark 1 noise as read: Webinar invite. Go ahead?

A third run with nothing new returns `action: "unchanged"` from `vault_write_daily`; say "nothing new since 15:40" and offer nothing.

## Rule proposal — how it looks

Monday run: 14 `to_label` items with `label: null`, six of them from `alerts@monitoring.example`, all labelled `fyi` by the model. `vault_rules(action="get")` → no `labels[]` row with that match. After the report:

> You labelled 6 mails from alerts@monitoring.example as fyi. Add the rule `alerts@monitoring.example → fyi` to Rules.md so they skip the model next time?

User: "yes" → `vault_append_row("Administrator/Rules.md", "Labels", ["alerts@monitoring.example", "from", "fyi"])` → `appended: true`. Say: "Rule added; edit Administrator/Rules.md to change it." No `dedupe_key`, no other change to the file. "no" or silence → nothing is written and the proposal is not repeated this run.
