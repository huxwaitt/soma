# save — worked examples

Three runs of `/administrator:save`: one mail, the same mail again, a whole thread. The tool results are cut to what the `fields=` lists return; nothing the model does not read is shown.

## Example 1 — one mail with attachments

User: `/administrator:save supplier contract jane`

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

4. Ask (nothing else in that turn): "Export the original .msg and 1 attachment (Q3-supplier-contract-v3.pdf; image001.png is a 4 KB inline image, skipped) to Administrator/Attachments/2026-08-21 Q3 supplier contract – signature needed/?" User: "yes".
   `outlook_save_mail_as(entry_id, output_dir="C:\\Users\\<you>\\Documents\\Vault\\Administrator\\Attachments\\2026-08-21 Q3 supplier contract – signature needed", fmt="msg", filename="2026-08-21 Q3 supplier contract – signature needed")` → `path` ending in `….msg`.
   `outlook_save_attachments(entry_id, output_dir=<same>, attachment_index=1)` → `files: ["…\\Q3-supplier-contract-v3.pdf"]`.

5. The only text the model writes:

```
vault_save_email(
  mail=<the step 2 JSON, unchanged>,
  summary="Jane sends contract v3 with net-45 terms and asks for a signed copy by 29 Aug plus confirmation of the Leipzig delivery address.",
  action_items=["Sign and return Q3 supplier contract v3 by 2026-08-29 — owner: me",
                "Confirm delivery address is still the Leipzig warehouse — owner: me"],
  attachments_saved=["C:\\Users\\<you>\\Documents\\Vault\\Administrator\\Attachments\\2026-08-21 Q3 supplier contract – signature needed\\Q3-supplier-contract-v3.pdf"],
  msg_file="C:\\Users\\<you>\\Documents\\Vault\\Administrator\\Attachments\\2026-08-21 Q3 supplier contract – signature needed\\2026-08-21 Q3 supplier contract – signature needed.msg",
  self_addresses=["hux@example.com"],
  company="ACME Parts GmbH")
```

→ `{"path": "Administrator/Emails/2026-08-21 Q3 supplier contract – signature needed.md", "action": "created", "status": "todo", "person_path": "Administrator/People/Jane Doe.md", "person_action": "created", "followup_added": false}`

The note the helper wrote (for reference — the model never sees or types it):

```markdown
---
type: email
source: outlook
entry_id: "00000000AC1F…"
internet_message_id: "<PAXPR04MB8765A1B2C3D4E5F6@PAXPR04MB8765.eurprd04.prod.outlook.com>"
conversation_id: "CAFEBABE1234567890ABCDEF"
subject: "RE: Q3 supplier contract – signature needed"
from: jane.doe@acme-parts.com
from_name: Jane Doe
from_link: "[[People/Jane Doe]]"
to:
  - hux@example.com
cc:
  - tom.lee@acme-parts.com
received: 2026-08-21T16:42:10+02:00
status: todo
has_attachments: true
attachments:
  - "[[Administrator/Attachments/2026-08-21 Q3 supplier contract – signature needed/Q3-supplier-contract-v3.pdf|Q3-supplier-contract-v3.pdf]]"
msg_file: "[[Administrator/Attachments/2026-08-21 Q3 supplier contract – signature needed/2026-08-21 Q3 supplier contract – signature needed.msg|2026-08-21 Q3 supplier contract – signature needed.msg]]"
created_by: administrator/0.1.0
---

# RE: Q3 supplier contract – signature needed

**From:** [[People/Jane Doe]] <jane.doe@acme-parts.com>
**To:** Hux Waitt <hux@example.com>
**Cc:** Tom Lee <tom.lee@acme-parts.com>
**Received:** 2026-08-21 16:42

## Summary

Jane sends contract v3 with net-45 terms and asks for a signed copy by 29 Aug plus confirmation of the Leipzig delivery address.

## Action items

- [ ] Sign and return Q3 supplier contract v3 by 2026-08-29 — owner: me
- [ ] Confirm delivery address is still the Leipzig warehouse — owner: me

## Body

Hi Hux,

Attached is v3 with the payment terms changed to net 45 as we discussed. Could you sign and return it by Friday 29 August? Tom will handle the PO once it's back.

One more thing: please confirm the delivery address is still the Leipzig warehouse.

## Attachments

- [[Administrator/Attachments/2026-08-21 Q3 supplier contract – signature needed/2026-08-21 Q3 supplier contract – signature needed.msg|2026-08-21 Q3 supplier contract – signature needed.msg]] (original message)
- [[Administrator/Attachments/2026-08-21 Q3 supplier contract – signature needed/Q3-supplier-contract-v3.pdf|Q3-supplier-contract-v3.pdf]] (180 KB)
- image001.png (4 KB, not exported)
```

`People/Jane Doe.md` was created with `company: ACME Parts GmbH`, `last_contact: 2026-08-21T16:42:10+02:00` and the line `- 2026-08-21 — [[Emails/2026-08-21 Q3 supplier contract – signature needed]] (todo)`. `Follow-ups.md` untouched (status `todo`).

6. Report:

> Saved `Emails/2026-08-21 Q3 supplier contract – signature needed.md` (todo, 2 action items). New person note `People/Jane Doe.md`. Exported the .msg and `Q3-supplier-contract-v3.pdf` to `Administrator/Attachments/2026-08-21 Q3 supplier contract – signature needed/`.
> obsidian://open?vault=Vault&file=Administrator%2FEmails%2F2026-08-21%20Q3%20supplier%20contract%20%E2%80%93%20signature%20needed.md

## Example 2 — the same command again

Steps 1–2 as above. Step 3: `vault_find("email", …, fields=["status","msg_file","attachments"])` → `found: true`, frontmatter shows `msg_file` and `attachments` already set → no export question. `vault_find("person", …)` → `found: true`, so no `outlook_search_contacts`.

`vault_save_email(mail, summary=<same two sentences>, action_items=<same>, self_addresses=[...])` → `action: "appended"`. The helper put `Saved again via /administrator:save.` plus `### Summary` / `### Action items` under a `## Update 2026-08-22T…` heading; the `## Body` and frontmatter stay as they were. The person note got one new `## Emails` line under its own `## Update` heading only because `last_contact` did not change — the helper decides.

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

   The newest item is the mail already fetched, so `mail` stays. Replace `mail.body_trimmed` with:

```markdown
### 2026-08-20 09:15 — Hux Waitt

Hi Jane,

before I sign: can we move the payment terms to net 45? Everything else in v2 is fine.

### 2026-08-21 11:03 — Jane Doe

Hi Hux,

net 45 works. I'll send v3 this afternoon.

### 2026-08-21 16:42 — Jane Doe

Hi Hux,

Attached is v3 with the payment terms changed to net 45 as we discussed. …
```

   Each section is that item's `body_trimmed` verbatim; nothing else from the thread goes in.

3–4. As in example 1 (identity and attachments are the newest mail's).

5. `vault_save_email(mail=<newest mail with the thread body>, summary="Jane agreed to net 45 and sent contract v3; she asks for a signed copy by 29 Aug and confirmation of the Leipzig delivery address.", action_items=[...same two...], ..., self_addresses=["hux@example.com"])` → one note, `Emails/2026-08-21 Q3 supplier contract – signature needed.md`, whose `## Body` holds the three dated sections. One person note (Jane), none for the user's own sent mail.

6. Report as in example 1, plus "3 mails in the thread (Sent Items, Inbox)".

## What the model never does in these runs

- Types the frontmatter, the `**From:**` / `**To:**` lines, the body of a single mail, or the `## Attachments` list — `vault_save_email` builds them from `mail`.
- Reads `vault_read` on the email or person note — `vault_find(fields=...)` is enough.
- Calls `vault_write`, `vault_append_row` or `outlook_search_contacts` when the helper or an earlier `vault_find` already covers it.
