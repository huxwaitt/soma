# find — worked examples

Two runs of `/soma:find` on 2026-08-22, `outlook_whoami` → `hux@example.com`. Both stay well under the 6-call cap.

## Example 1 — "the email where we agreed on the Q3 budget with Sam"

Step 0: `people = ["Sam"]`, `words = ["q3", "budget"]`, no date hint → `since = "2025-08-22"`, no attachment, default folders.

Step 1 (1 call):

```
outlook_find(people=["Sam"], words=["q3", "budget"], since="2025-08-22", folders=["inbox", "sent"], limit=10)
```

→ `searches: 6`, `candidates: 14`, `count: 10`. The top three items:

| score | from_address | received | subject | snippet |
| --- | --- | --- | --- | --- |
| 9 | sam.ortiz@example.com | 2026-06-12T14:05 | Re: Q3 budget — wrap-up | "Agreed then: Q3 budget stays at 180k, with the 15k contingency held by finance." |
| 8 | hux@example.com | 2026-06-11T17:30 | Q3 budget — numbers for Sam | "Here are the final numbers; if 180k works for you I'll call it agreed tomorrow." |
| 5 | jane.doe@example.com | 2026-06-03T09:14 | Q3 budget draft v2 | "Second draft attached, Sam still wants the contingency line separate." |

All three `from_address` values are different people, but only one is a Sam → no question to ask. Snippet 1 answers the sentence word for word, so no `outlook_get_conversation` is needed.

Step 5 (free): `vault_find("email", {"internet_message_id": "", "entry_id": "00000000A1…"})` → `Soma/Emails/2026-06-12 Q3 budget — wrap-up.md`; the other two are not in the vault.

Shown:

```
1. Sam Ortiz → me, 2026-06-12 14:05 — Re: Q3 budget — wrap-up
   "Agreed then: Q3 budget stays at 180k, with the 15k contingency held by finance."
   Note: [[Emails/2026-06-12 Q3 budget — wrap-up]]
   obsidian://open?vault=MyVault&file=Soma%2FEmails%2F2026-06-12%20Q3%20budget%20%E2%80%94%20wrap-up
2. me → Sam Ortiz, 2026-06-11 17:30 — Q3 budget — numbers for Sam
   "Here are the final numbers; if 180k works for you I'll call it agreed tomorrow."
3. Jane Doe → me, 2026-06-03 09:14 — Q3 budget draft v2
   "Second draft attached, Sam still wants the contingency line separate."
```

The winner already has a note, so no save offer. One `outlook_*` call in total.

## Example 2 — "the spreadsheet Maria sent with vendor pricing last month"

Step 0: `people = ["Maria"]`, `words = ["vendor", "pricing", "supplier"]`, "last month" → `since = "2026-07-01"`, `until = "2026-07-31"`, `attachment = "*.xls*"`, "sent" means Maria sent it → default folders.

Step 1 (1 call): `outlook_find(people=["Maria"], words=["vendor", "pricing", "supplier"], since="2026-07-01", until="2026-07-31", folders=["inbox", "sent"], limit=10)` → 4 items, all from `maria.klein@acme-parts.com`. Best: `Re: pricing round 2` (2026-07-18, snippet "Round 2 is the same sheet with the freight column corrected, no price changes."), then `Vendor pricing 2026` (2026-07-09, snippet "Pricing attached, valid until September.").

Step 2 (2 calls, attachment hint set):

- `outlook_search_attachments(query="*.xls*", folder="inbox", since="2026-07-01", limit=20, include_subfolders=true)` → 5 items; the 2026-07-09 mail is among them with `matches: [{index: 1, filename: "Acme_vendor_pricing_2026.xlsx", size_bytes: 48213}]`. It is already in the list → attachment mark on that item, no new row.
- `outlook_advanced_search(query="vendor pricing", scope="all", since="2026-07-01", limit=20, timeout_sec=20)` → 3 hits, `timed_out: false`, the same 2026-07-09 mail among them (the index read the sheet).

The attachment mark moves `Vendor pricing 2026` to the top. Its snippet only points at the file and the sentence asked about the pricing, so step 4 is one `outlook_extract_attachment_text(entry_id="00000000C7…", index=1, max_chars=4000)` (4th call) and the quote comes from the sheet. No thread is opened; the other snippets answer on their own.

Step 5 (free): three `vault_find` calls → nothing saved.

Shown:

```
1. Maria Klein → me, 2026-07-09 11:42 — Vendor pricing 2026
   "Pricing attached, valid until September." — (from Acme_vendor_pricing_2026.xlsx) "Bracket A12 — 4.80 EUR/unit — MOQ 500"
   Attachments: Acme_vendor_pricing_2026.xlsx
2. Maria Klein → me, 2026-07-18 16:05 — Re: pricing round 2
   "Round 2 is the same sheet with the freight column corrected, no price changes."
3. Maria Klein → me, 2026-07-02 08:50 — Pricing call Thursday?
   "Can we go through the vendor pricing on Thursday before I send the final sheet?"

Save #1 as a note? (/soma:save 00000000C7…)
```

Four `outlook_*` calls. On a yes the `save` skill takes over (it asks again before exporting the .xlsx). On no, nothing happens.

## Example 3 — a widening

"where did Bob say the offsite is" on 2026-08-22: `people = ["Bob"]`, `words = ["offsite"]` (one word only — "say" and "is" are dropped), `since = "2025-08-22"`.

First `outlook_find` → `count: 0` (Bob writes "off-site" and "away day"). Rule 1 (fewer words) cannot apply to one word, so rule 2: `since = "2024-08-22"` → still 0. That was the second call; stop. Report:

> Nothing found for Bob + "offsite" in Inbox and Sent since 2024-08-22 (2 searches). Try another word for it — "away day" or "venue" — or name the folder it might be in.
