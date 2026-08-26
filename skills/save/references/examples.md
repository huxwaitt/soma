# save — worked examples

Four runs of `/soma:save`: one mail, the same mail again, a whole thread, a file path. The tool results are cut to what the `fields=` lists return; nothing the model does not read is shown.

## Example 1 — one mail with attachments

User: `/soma:save supplier contract jane`

Session already has `vault_status` (vault `C:\Users\<you>\Documents\Vault`, `vault_name: Vault`, `under_user_profile: true`) and `outlook_whoami` → `hux@example.com`.

1. `outlook_search_mails(query="supplier contract jane", folder="inbox", limit=5, fields=["entry_id","from","subject","received","preview"], preview_chars=80, response_format="json")` → one hit. Say: "Picked *RE: Q3 supplier contract – signature needed* from Jane Doe, 2026-08-21 16:42."

2. `outlook_get_mail(entry_id="00000000AC1F…", trim_quoted=true, response_format="json", fields=[...])`:

```json
{
  "entry_id": "00000000AC1F2B3C4D5E6F708192A3B4C5D6E7F80700A1B2C3D4E5F60718293A4B5C6D7E8F900000000010A0000A1B2C3D4E5F60718293A4B5C6D7E8F9000000000",
  "internet_message_id": "<PAXPR04MB8765A1B2C3D4E5F6@PAXPR04MB8765.eurprd04.prod.outlook.com>",
  "conversation_id": "CAFEBABE1234567890ABCDEF",
  "subject": "RE: Q3 supplier contract – signature needed",
  "from": "Jane Doe",
  "from_address": "jane.doe@acme-parts.com",
  "to": "Hux Waitt",
  "cc": "Tom Lee",
  "recipients": [
    {"name": "Hux Waitt", "address": "hux@example.com", "type": "to"},
    {"name": "Tom Lee", "address": "tom.lee@acme-parts.com", "type": "cc"}
  ],
  "received": "2026-08-21T16:42:10+02:00",
  "attachments": [
    {"index": 1, "filename": "Q3-supplier-contract-v3.pdf", "size_bytes": 184322},
    {"index": 2, "filename": "image001.png", "size_bytes": 4021}
  ],
  "body_trimmed": "Hi Hux,\n\nAttached is v3 with the payment terms changed to net 45 as we discussed. Could you sign and return it by Friday 29 August? Tom will handle the PO once it's back.\n\nOne more thing: please confirm the delivery address is still the Leipzig warehouse.",
  "body_truncated": false
}
```

3. `vault_find("email", {"internet_message_id": "<PAXPR04MB8765…>", "entry_id": "00000000AC1F…"}, fields=["status","msg_file","attachments"])` → `found: false`.
   `vault_find("person", {"email": "jane.doe@acme-parts.com"}, fields=["name"])` → `found: false`.
   `outlook_search_contacts(query="jane.doe@acme-parts.com", include_directory=true, limit=5)` → one item with that `email`, `company: "ACME Parts GmbH"`.

4. Ask (nothing else in that turn): "Export the original .msg and 1 attachment (Q3-supplier-contract-v3.pdf; image001.png is a 4 KB inline image, skipped) to Soma/Attachments/2026-08-21 Q3 supplier contract – signature needed/?" User: "yes".
   `outlook_save_mail_as(entry_id, output_dir="C:\\Users\\<you>\\Documents\\Vault\\Soma\\Attachments\\2026-08-21 Q3 supplier contract – signature needed", fmt="msg", filename="2026-08-21 Q3 supplier contract – signature needed")` → `path` ending in `….msg`.
   `outlook_save_attachments(entry_id, output_dir=<same>, attachment_index=1)` → `files: ["…\\Q3-supplier-contract-v3.pdf"]`.

5. The only text the model writes:

```
vault_save(
  kind="email",
  mail=<the step 2 JSON, unchanged>,
  summary="Jane sends contract v3 with net-45 terms and asks for a signed copy by 29 Aug plus confirmation of the Leipzig delivery address.",
  action_items=["Sign and return Q3 supplier contract v3 by 2026-08-29 — owner: me",
                "Confirm delivery address is still the Leipzig warehouse — owner: me"],
  attachments_saved=["C:\\Users\\<you>\\Documents\\Vault\\Soma\\Attachments\\2026-08-21 Q3 supplier contract – signature needed\\Q3-supplier-contract-v3.pdf"],
  msg_file="C:\\Users\\<you>\\Documents\\Vault\\Soma\\Attachments\\2026-08-21 Q3 supplier contract – signature needed\\2026-08-21 Q3 supplier contract – signature needed.msg",
  self_addresses=["hux@example.com"],
  company="ACME Parts GmbH")
```

→ `{"path": "Soma/Emails/2026-08-21 Q3 supplier contract – signature needed.md", "action": "created", "status": "todo", "person_path": "Soma/Wiki/People/Jane Doe.md", "person_action": "created", "followup_added": false}`

The note the helper wrote (for reference — the model never sees or types it):

```markdown
---
type: email
source: outlook
record_id: "<PAXPR04MB8765A1B2C3D4E5F6@PAXPR04MB8765.eurprd04.prod.outlook.com>"
title: "RE: Q3 supplier contract – signature needed"
date: "2026-08-21"
people:
  - "[[Wiki/People/Jane Doe]]"
wiki: []
ingested: ""
created_by: soma/0.4.1
entry_id: "00000000AC1F…"
internet_message_id: "<PAXPR04MB8765A1B2C3D4E5F6@PAXPR04MB8765.eurprd04.prod.outlook.com>"
conversation_id: "CAFEBABE1234567890ABCDEF"
subject: "RE: Q3 supplier contract – signature needed"
from: jane.doe@acme-parts.com
from_name: Jane Doe
from_link: "[[Wiki/People/Jane Doe]]"
to:
  - hux@example.com
cc:
  - tom.lee@acme-parts.com
received: 2026-08-21T16:42:10+02:00
status: todo
has_attachments: true
attachments:
  - "[[Soma/Attachments/2026-08-21 Q3 supplier contract – signature needed/Q3-supplier-contract-v3.pdf|Q3-supplier-contract-v3.pdf]]"
msg_file: "[[Soma/Attachments/2026-08-21 Q3 supplier contract – signature needed/2026-08-21 Q3 supplier contract – signature needed.msg|2026-08-21 Q3 supplier contract – signature needed.msg]]"
---

# RE: Q3 supplier contract – signature needed

**From:** [[Wiki/People/Jane Doe]] <jane.doe@acme-parts.com>
**To:** Hux Waitt <hux@example.com>
**Cc:** Tom Lee <tom.lee@acme-parts.com>
**Received:** 2026-08-21 16:42

## Summary

Jane sends contract v3 with net-45 terms and asks for a signed copy by 29 Aug plus confirmation of the Leipzig delivery address.

## Action items

- [ ] Sign and return Q3 supplier contract v3 by 2026-08-29 — owner: me
- [ ] Confirm delivery address is still the Leipzig warehouse — owner: me

## Content

Hi Hux,

Attached is v3 with the payment terms changed to net 45 as we discussed. Could you sign and return it by Friday 29 August? Tom will handle the PO once it's back.

One more thing: please confirm the delivery address is still the Leipzig warehouse.

## Files

- [[Soma/Attachments/2026-08-21 Q3 supplier contract – signature needed/2026-08-21 Q3 supplier contract – signature needed.msg|2026-08-21 Q3 supplier contract – signature needed.msg]] (original message)
- [[Soma/Attachments/2026-08-21 Q3 supplier contract – signature needed/Q3-supplier-contract-v3.pdf|Q3-supplier-contract-v3.pdf]] (180 KB)
- image001.png (4 KB, not exported)
```

`Wiki/People/Jane Doe.md` was created with `company: ACME Parts GmbH`, `last_contact: 2026-08-21T16:42:10+02:00` and the line `- 2026-08-21 — [[Emails/2026-08-21 Q3 supplier contract – signature needed]] (todo)`. No open item (status `todo`), so `Follow-ups.md` does not change.

6. One exported attachment can be read in as its own record, so ask once, nothing else in that turn: "Read `Q3-supplier-contract-v3.pdf` into the vault too, so its text can go on the pages?" User: "yes".

```
vault_save(kind="document",
  path="C:\\Users\\<you>\\Documents\\Vault\\Soma\\Attachments\\2026-08-21 Q3 supplier contract – signature needed\\Q3-supplier-contract-v3.pdf",
  summary="Supplier contract v3: net 45 payment terms, delivery to the Leipzig warehouse, signature due 29 Aug.",
  action_items=["Sign and return contract v3 by 2026-08-29 — owner: me"],
  from_email="Soma/Emails/2026-08-21 Q3 supplier contract – signature needed.md")
```

→ `{"path": "Soma/Documents/2026-08-21 Q3-supplier-contract-v3.md", "action": "created", "record_id": "76350e982c42c7c0", "format": "pdf", "parts": 12, "chars": 18422, "empty": false, "text_file": null, "sections": [{"locator": "p1", "heading": "page 1", "chars": 812}, …], "from_email": "[[Emails/2026-08-21 Q3 supplier contract – signature needed]]", "linked": true}`

`linked: true` means the two records now name each other: the mail's `## Files` gained the document link through an `## Update`, and the document's `## Files` names the mail. The wiki step of step 7 then runs on the mail *and* on the document, with a `#p<n>` locator on every fact that came from one page of the pdf.

7. Report:

> Saved `Emails/2026-08-21 Q3 supplier contract – signature needed.md` (todo, 2 action items). New person note `Wiki/People/Jane Doe.md`. Exported the .msg and `Q3-supplier-contract-v3.pdf` to `Soma/Attachments/2026-08-21 Q3 supplier contract – signature needed/`.
> Read `Q3-supplier-contract-v3.pdf` into `Documents/2026-08-21 Q3-supplier-contract-v3.md` (pdf, 12 parts, 18422 characters); the two records link to each other.
> obsidian://open?vault=Vault&file=Soma%2FEmails%2F2026-08-21%20Q3%20supplier%20contract%20%E2%80%93%20signature%20needed.md

## Example 2 — the same command again

Steps 1–2 as above. Step 3: `vault_find("email", …, fields=["status","msg_file","attachments"])` → `found: true`, frontmatter shows `msg_file` and `attachments` already set → no export question. `vault_find("person", …)` → `found: true`, so no `outlook_search_contacts`.

`vault_save(kind="email", mail, summary=<same two sentences>, action_items=<same>, self_addresses=[...])` → `action: "appended"`. The helper put `Saved again via /soma:save.` plus `### Summary` / `### Action items` under a `## Update 2026-08-22T…` heading; the `## Content` and frontmatter stay as they were. The person page is unchanged apart from `last_contact`; its `## Records` line was already there, so it is not doubled — the helper decides.

> Already saved at `Emails/2026-08-21 Q3 supplier contract – signature needed.md`; appended an update. Nothing exported again.
> obsidian://open?vault=Vault&file=…

## Example 3 — the whole thread

User: "save the thread with Jane about the supplier contract"

1. Search as in example 1 → the newest mail in Inbox is the one above (`entry_id` `00000000AC1F…`).
2. `outlook_get_mail(...)` as above, then
   `outlook_get_conversation(entry_id="00000000AC1F…", include_body=true, trim_quoted=true, max_body_chars=0, limit=20, preview_chars=0, fields=["entry_id","from","received","folder","body_trimmed"])` →

```json
{"conversation_id": "CAFEBABE1234567890ABCDEF", "truncated": false, "count": 3, "fields": ["entry_id","from","received","folder","body_trimmed"],
 "items": [
  {"entry_id": "00000000AB10…", "from": "Hux Waitt", "received": "2026-08-20T09:15:00+02:00", "folder": "Sent Items",
   "body_trimmed": "Hi Jane,\n\nbefore I sign: can we move the payment terms to net 45? Everything else in v2 is fine."},
  {"entry_id": "00000000AB2F…", "from": "Jane Doe", "received": "2026-08-21T11:03:00+02:00", "folder": "Inbox",
   "body_trimmed": "Hi Hux,\n\nnet 45 works. I'll send v3 this afternoon."},
  {"entry_id": "00000000AC1F…", "from": "Jane Doe", "received": "2026-08-21T16:42:10+02:00", "folder": "Inbox",
   "body_trimmed": "Hi Hux,\n\nAttached is v3 with the payment terms changed to net 45 as we discussed. …"}
 ]}
```

   The newest item is the mail already fetched, so `mail` stays; the whole `items[]` list goes to `vault_save` as `thread=`, unchanged. The helper sorts it oldest first and writes one section per mail:

```markdown
### m1 — 2026-08-20 09:15 Hux Waitt

Hi Jane,

before I sign: can we move the payment terms to net 45? Everything else in v2 is fine.

### m2 — 2026-08-21 11:03 Jane Doe

Hi Hux,

net 45 works. I'll send v3 this afternoon.

### m3 — 2026-08-21 16:42 Jane Doe

Hi Hux,

Attached is v3 with the payment terms changed to net 45 as we discussed. …
```

   Each section is that item's `body_trimmed` verbatim; nothing else from the thread goes in. A fact taken from the second mail cites `src: "<record_id>#m2"`.

3–4. As in example 1 (identity and attachments are the newest mail's).

5. `vault_save(kind="email", mail=<the newest mail>, thread=<the items[] above>, summary="Jane agreed to net 45 and sent contract v3; she asks for a signed copy by 29 Aug and confirmation of the Leipzig delivery address.", action_items=[...same two...], ..., self_addresses=["hux@example.com"])` → one note, `Emails/2026-08-21 Q3 supplier contract – signature needed.md`, whose `## Content` holds the three numbered sections. One person note (Jane), none for the user's own sent mail.

6. Report as in example 1, plus "3 mails in the thread (Sent Items, Inbox)".

## Example 4 — a file instead of a mail

User: `/soma:save C:\Users\<you>\Downloads\ACME-kickoff.pptx`

1. The argument is a path, not an `entry_id` and not search terms, so there is no Outlook call at all.

2. One call:

```
vault_save(kind="document", path="C:\\Users\\<you>\\Downloads\\ACME-kickoff.pptx",
  summary="", action_items=[])
```

   → `{"path": "Soma/Documents/2026-08-24 ACME-kickoff.md", "action": "created", "record_id": "3f9c1ad2b7e40518", "format": "pptx", "parts": 18, "chars": 9140, "empty": false, "text_file": null, "sections": [{"locator": "s1", "heading": "ACME kickoff", "chars": 61}, {"locator": "s2", "heading": "Scope", "chars": 640}, …, {"locator": "s7", "heading": "Pricing", "chars": 980}, …], "from_email": "", "linked": false}`

   The summary was left empty on purpose: the parts are only known after the read. Show the list — "18 slides: 1 ACME kickoff, 2 Scope, … 7 Pricing, …" — and offer the wiki step.

3. `vault_wiki_search(query="ACME kickoff scope pricing", pages=true, limit=8)` → `Topics/acme-supplier-contract` and a candidate `acme kickoff`. Read the slides that match, largest first, at most five: `vault_read("Soma/Documents/2026-08-24 ACME-kickoff.md", section="s7")` → `{"section": {"locator": "s7", "heading": "Pricing", "text": "Net 45 from 1 September. Volume tier 2 …", "chars": 980}, …}`, then `s2`, then `s11`.

4. `vault_wiki_read("Wiki/Topics/acme-supplier-contract", sections=["lead","facts"])`, then one call:

```
vault_wiki_write(record_path="Soma/Documents/2026-08-24 ACME-kickoff.md",
  pages=[{"path": "Wiki/Topics/acme-supplier-contract",
          "ops": [{"op": "add", "text": "Net 45 payment terms run from 1 September.", "src": "3f9c1ad2b7e40518#s7"},
                  {"op": "confirm", "id": "b2k9", "src": "3f9c1ad2b7e40518#s2"}]}],
  created_by="soma/0.4.1")
```

   The `src` of each op is the record id plus the slide the fact was read on; without one, the bare record id is used. The document is one source however many facts cite it.

5. Report:

> Read `Downloads/ACME-kickoff.pptx` into `Documents/2026-08-24 ACME-kickoff.md` (pptx, 18 slides, 9140 characters). Wiki: `Topics/acme-supplier-contract` (net 45 from 1 Sep added from slide 7, scope confirmed from slide 2). Topic candidate `acme kickoff` — create a page for it?
> obsidian://open?vault=Vault&file=Soma%2FDocuments%2F2026-08-24%20ACME-kickoff.md

## What the model never does in these runs

- Types the frontmatter, the `**From:**` / `**To:**` lines, the body of a single mail, or the `## Files` list — `vault_save` builds them from `mail`.
- Types the text of a document, or reads the whole record back to get at one part — `vault_read(path, section=…)` returns the part.
- Reads `vault_read` on the email or person note — `vault_find(fields=...)` is enough.
- Calls `vault_write`, `vault_row` or `outlook_search_contacts` when the helper or an earlier `vault_find` already covers it.
