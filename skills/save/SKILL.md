---
name: save
description: Turn one Outlook email (or the thread it belongs to) into a note in the Obsidian vault — frontmatter with stable IDs, the trimmed body without quoted history or signature, recipients, a wikilink to the sender's person note, a one-line summary, and extracted action items; optionally export the .msg and attachments into the vault. Trigger when the user says "/administrator:save", "save this email", "note this", "put that email in the vault", "keep a record of the thread with X", "file this mail", "save the attachment from Bob's email to my notes", or gives an entry_id or search terms after asking to save. Reads Outlook only; the only Outlook calls that touch disk are outlook_save_mail_as and outlook_save_attachments, both optional and both write into the vault's Attachments folder.
---

# save — one email → one vault note

This skill takes a single mail (or the mail plus its thread) out of Outlook and writes it as a durable markdown note under `<vault>/Administrator/`. It never sends mail, never moves, deletes, marks, or categorises anything in Outlook. Outlook mechanics (folders, `entry_id`, dates, `response_format`) follow the `outlook` skill; note layout follows `skills/administrator/references/vault.md`. Do not duplicate either here — read them when unsure.

Vault root: the `ADMINISTRATOR_VAULT` environment variable (absolute path). If it is unset, stop and tell the user to set it; do not guess a path.

## Steps

### 1. Resolve the target

- **An `entry_id` was given** (long opaque string, usually starts with `000000`): call `outlook_get_mail(entry_id=<id>, include_body=true, response_format="json")`. If the body comes back with `body_truncated: true`, call again with `max_body_chars=0`.
- **Search terms were given** (anything else): call `outlook_search_mails(query=<terms>, folder="inbox", limit=5, response_format="json")`. If the user named a sender rather than a subject, use `scope="from"`. If nothing comes back in Inbox, try `folder="sent"`, then ask the user for a folder.
  - One hit: proceed with it, but say which mail you picked.
  - Two to five hits: show a numbered list (`received`, `from`, `subject`, first 80 chars of `preview`) and ask the user to pick a number. Do not guess.
  - More than five: the search already capped at 5; show them and offer to narrow by `since` or `scope`.
  - Then call `outlook_get_mail` on the chosen `entry_id` as above.
- **Whole thread requested** ("save the thread", "the whole conversation"): after you have the chosen mail, call `outlook_get_conversation(entry_id=<id>, include_body=true, max_body_chars=0, limit=20)`. It returns every mail in the thread across folders (Inbox, Sent Items, sub-folders), oldest first, each with `entry_id`, `internet_message_id`, `conversation_id`, `folder`, `body`. If `truncated` is true, tell the user the thread is longer than 20 and that only the oldest 20 were saved. Call `outlook_get_mail` only for the **newest** mail (for `recipients` and `attachments`). The note is still one note, named after the newest mail; each message becomes a `### <received YYYY-MM-DD HH:MM> — <from_name>` subsection under `## Body`. Frontmatter identity fields come from the newest mail.

### 2. Check for a duplicate before writing anything

Identity is `internet_message_id` (returned by `get_mail`) when it is non-empty, otherwise `entry_id`. It is empty for drafts and on some IMAP/POP stores; then use `entry_id` and write `internet_message_id: ""`.

1. If `internet_message_id` is non-empty, grep `<vault>/Administrator/Emails/*.md` for the line `internet_message_id: "<id>"` (exact string, quotes included).
2. No hit, or the id was empty: grep the same files for `entry_id: "<entry_id>"`.
3. **Hit** → this mail is already saved. Do **not** create a new file and do **not** rewrite the existing one. Append to the end of the matching file:

   ```markdown

   ## Update 2026-08-22T10:05:13+02:00

   Saved again via /administrator:save. <what changed, e.g. "Attachments exported: [[Attachments/...]]" or "No change to the message; re-checked action items: none new.">
   ```

   Then refresh only `last_contact` in the sender's person note if this mail is newer (step 6), and report "already saved at `Emails/...`, appended an update". If the user clearly asked for attachments or the .msg this time and they are not yet linked in the note, do step 5 and list the new links inside that Update section (do not add `attachments` / `msg_file` keys to the frontmatter of an old note).
4. **No hit** → continue.

### 3. Build the note

Filename: `Emails/YYYY-MM-DD <slug>.md`, date from `received` (local date part of the ISO string).
Slug: the rule in `administrator/references/vault.md` — strip leading reply/forward prefixes (`Re:`, `Fwd:`, `FW:`, `AW:`, `WG:`, `TR:`, `SV:`, repeatedly, case-insensitive); replace each of `\ / : * ? " < > |` and control characters with `_`; collapse runs of whitespace to one space; trim spaces and trailing dots; cut to 60 characters; if empty use `(no subject)`. If the target filename already exists but belongs to a different identity (the duplicate check said "no hit"), append ` (2)`, ` (3)`, … until free.

Frontmatter (keys in this order; `entry_id`, `internet_message_id`, `conversation_id` and wikilinks always quoted):

```yaml
---
type: email
source: outlook
entry_id: "<entry_id verbatim>"
internet_message_id: "<internet_message_id verbatim, or empty>"
conversation_id: "<conversation_id>"
from: <from_address, SMTP>
from_name: <from>
from_link: "[[People/<Display Name>]]"
to:
  - <smtp>
  - <smtp>
cc:
  - <smtp>
received: <received, ISO with offset, verbatim>
status: todo | waiting | done | fyi
has_attachments: true
attachments:
  - "[[Administrator/Attachments/<YYYY-MM-DD slug>/<file>|<file>]]"
msg_file: "[[Administrator/Attachments/<YYYY-MM-DD slug>/<YYYY-MM-DD slug>.msg|<YYYY-MM-DD slug>.msg]]"
created_by: administrator/0.0.1
---
```

- `to` / `cc`: SMTP addresses from `recipients[]` where `type` is `to` / `cc`. Only if `recipients` is empty, split the flat `to` / `cc` strings on `;` and keep the part inside `<…>`. Omit `cc` if empty.
- `has_attachments: true` only when `get_mail` lists attachments; omit otherwise. Omit `attachments` and `msg_file` until step 5 adds something.
- `status`: `todo` if the body asks the user to do something (a question to them, "please", "can you", "by <date>", they are the only To recipient); `waiting` if the mail is from the user's own address (check `outlook_whoami` once per session) and asks someone else for something; `fyi` if it is a notification, newsletter, receipt, or a plain reply with nothing open; `done` only if the user says so. When in doubt, `todo` — the user can change it.
- `from_link` uses the display name after the same character cleanup as the slug (step 6 names the file identically).

Body of the note, in this order (the email note template in `administrator/references/vault.md`):

```markdown
# <subject as received>

**From:** [[People/<Display Name>]] <<smtp>>
**To:** <name> <<smtp>>, …
**Cc:** …                                  (line only when there is a Cc)
**Received:** <YYYY-MM-DD HH:MM>

## Summary

<one sentence, 25 words or fewer, what the mail is and what it wants>

## Action items

- [ ] <task, with a due date if one is stated> — owner: me | <name>
(or the single line `- none` when there are no asks)

## Body

<trimmed body, see below>

## Attachments

- [[Administrator/Attachments/<YYYY-MM-DD slug>/<file>|<file>]] (<size>)
(section present only if the mail lists attachments — if listed but not exported, write the filename as plain text and "(not exported)")
```

**Trimming the body.** Work on the plain-text `body` from `get_mail` (never request `include_html` for this).

1. Cut everything from the first line that marks quoted history. A line counts as a marker when, after trimming, it matches one of:
   - `-----Original Message-----` or `-----Ursprüngliche Nachricht-----` (any dashes count ≥ 3)
   - starts with `From:` / `Von:` / `De:` and is followed within the next 4 lines by a line starting with `Sent:` / `Date:` / `Gesendet:` / `To:` / `An:`
   - matches `On .* wrote:` / `Am .* schrieb .*:` (may wrap onto two lines — join lines until the one ending in `wrote:`/`:`)
   - starts with `>` and every remaining non-blank line also starts with `>`
   - `________________________________` (≥ 20 underscores) immediately followed by a `From:` line
   The first marker wins; for a thread note, do this per message (each `items[].body` from `outlook_get_conversation`) so each subsection holds only its own new text.
2. Strip the signature: find the last occurrence of a line that is exactly `-- `, `--`, `Best regards`, `Kind regards`, `Regards`, `Thanks`, `Many thanks`, `Cheers`, `Mit freundlichen Grüßen`, `Viele Grüße`, `Sent from my iPhone`, or the sender's own display name on a line by itself. If that line sits in the last 12 lines of the remaining text, cut from it to the end. Then drop trailing lines that look like contact data (phone, `www.`, `http`, a street address line, job title followed by company) or legal boilerplate ("This email and any attachments are confidential…") even without a signature line.
3. Collapse three or more blank lines to two. Keep the rest verbatim — no rewriting, no summarising inside `## Body`.
4. If after trimming fewer than 20 characters remain (e.g. a "Thanks!" reply), keep the first 400 characters of the untrimmed body instead and note `(quoted history kept: new text was empty)`.

**Action items.** Only pull out asks that are directed at the user or that the user (as sender) gave someone else. Quote the mail's own wording shortened to one line; add a date only if the mail states one. Do not invent tasks from context. Each item also goes into `Follow-ups.md` (step 7) only when `status` is `waiting`.

### 4. Write the note

Create `<vault>/Administrator/Emails/` if missing. Write the file with UTF-8, LF line endings. Then read it back once and check: frontmatter starts and ends with `---`, `entry_id` is unchanged, the wikilink target file name matches the person note you will write in step 6.

### 5. Optional exports (ask first, once)

Offer these together in one question when the mail has attachments or the user mentioned keeping the original: "Export the original .msg and N attachment(s) to Administrator/Attachments/<YYYY-MM-DD slug>/?" Only proceed on a yes. Both write to disk inside the vault, nothing else changes. Destination folder: `<vault>\Administrator\Attachments\<YYYY-MM-DD slug>\` (same name as the note minus `.md`; the tools create it).

- `outlook_save_mail_as(entry_id=<id>, output_dir="<vault>\\Administrator\\Attachments\\<YYYY-MM-DD slug>", fmt="msg", filename="<YYYY-MM-DD slug>")` — the tool adds the extension and never overwrites (it appends ` (1)`), so use the returned `path`.
- `outlook_save_attachments(entry_id=<id>, output_dir="<vault>\\Administrator\\Attachments\\<YYYY-MM-DD slug>")` — or with `attachment_index` (1-based) for one file. Skip inline images under 20 KB (logos) unless asked; list them as "(not exported)".
- Paths must be absolute and under the user profile; if the vault lives elsewhere the tool will refuse — relay the `OUTLOOK_MCP_ALLOW_ANY_PATH=1` note from the outlook skill rather than trying another folder.
- Add the .msg as `msg_file` and every other returned file to the `attachments` frontmatter list, and list all of them in `## Attachments`, as `[[Administrator/Attachments/<YYYY-MM-DD slug>/<filename>|<filename>]]` (filename taken from the returned path). Adding these keys is allowed here only because the note was created seconds earlier in this run. Leave the files where the tool put them; do not rename after export.

### 6. Person note for the sender

File: `<vault>/Administrator/People/<Display Name>.md` where Display Name is `from` with the slug character cleanup and trimmed to 60 characters. If `from` is empty or looks like an address, use the local part of the SMTP address.

Find an existing note first: exact filename, else grep `People/*.md` for `email: <smtp>` or the address inside an `aliases:` list (case-insensitive). If an existing note has a different filename (e.g. "Jane Doe" vs "Doe, Jane"), link to the existing one and add the new display name to its `aliases`; never create a second note for the same address.

New note (the person template in `administrator/references/vault.md`):

```yaml
---
type: person
source: outlook
name: <Display Name>
email: <smtp>
company: <from outlook_search_contacts only, see below; omit the key otherwise>
last_contact: <received>
aliases: []
created_by: administrator/0.0.1
---

# <Display Name>

<smtp> · <company, if known>

## Emails

- <YYYY-MM-DD> — [[Emails/<YYYY-MM-DD slug>]] (<status>)
```

- `company`: call `outlook_search_contacts(query=<smtp>, include_directory=true, limit=5)` once; use `company` only from an item whose `email` equals the sender's SMTP. Never guess it from the domain.
- `aliases` holds other display names and other SMTP addresses seen for the same person; `[]` when there are none.

Existing note: do not rewrite it. Update only the `last_contact` value when `received` is later than the stored one, add a new display name or address to `aliases` if needed, and append one line to `## Emails` (create the heading at the end if missing). Anything the user wrote by hand in the note stays untouched.

Recipients other than the sender are **not** given person notes in v0.0.1; they appear as plain text on the `**To:**` / `**Cc:**` lines.

### 7. Follow-ups

If `status` is `waiting`, append one row to the bottom of the `## Open` table in `<vault>/Administrator/Follow-ups.md` (create the file from the template in `administrator/references/vault.md` if missing):

```markdown
| <YYYY-MM-DD> | [[People/<Name>]] | <what, ten words or fewer> | [[Emails/<YYYY-MM-DD slug>]] | <today> <!-- entry_id: <entry_id> --> |
```

`Who` is the person the user is waiting on (the To recipient when the mail is from the user). Skip if a row with the same `entry_id` comment or the same `[[Emails/…]]` link already exists.

### 8. Report

Two or three lines: the note path, the person note (new or updated), what was exported, and the status you chose. Ask nothing further unless the duplicate check or exports need a decision.

## Rules that apply to every run

- Running the same command twice must leave one email note and one person note; the second run only appends `## Update`.
- Never edit a note's existing text above the first `## Update`; append only.
- Never write outside `<vault>/Administrator/`.
- Never call `outlook_send_mail`, `reply_mail`, `forward_mail`, `move_mail`, `delete_mail`, `mark_mail`, `set_category`, or any `bulk_*` tool from this skill. Saving a mail does not mark it read.
- Keep datetimes exactly as Outlook returned them (local time with offset). Do not convert.
- Never put the full `html_body` or raw headers into the vault.

## Worked example

Input from `outlook_get_mail(entry_id="00000000AC1F...", include_body=true, response_format="json")`:

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
  "bcc": "",
  "recipients": [
    {"name": "Hux Waitt", "address": "huxwaitt@gmail.com", "type": "to"},
    {"name": "Tom Lee", "address": "tom.lee@acme-parts.com", "type": "cc"}
  ],
  "received": "2026-08-21T16:42:10+02:00",
  "sent": "2026-08-21T16:41:55+02:00",
  "unread": true,
  "importance": 1,
  "categories": "",
  "attachments": [
    {"index": 1, "filename": "Q3-supplier-contract-v3.pdf", "size_bytes": 184322},
    {"index": 2, "filename": "image001.png", "size_bytes": 4021}
  ],
  "body": "Hi Hux,\n\nAttached is v3 with the payment terms changed to net 45 as we discussed. Could you sign and return it by Friday 29 August? Tom will handle the PO once it's back.\n\nOne more thing: please confirm the delivery address is still the Leipzig warehouse.\n\nBest regards\nJane Doe\nKey Account Manager | ACME Parts GmbH\n+49 341 555 0123\nwww.acme-parts.com\n\nThis email and any attachments are confidential and intended solely for the addressee.\n\n-----Original Message-----\nFrom: Hux Waitt <huxwaitt@gmail.com>\nSent: Thursday, 21 August 2026 11:03\nTo: Jane Doe <jane.doe@acme-parts.com>\nSubject: Q3 supplier contract – signature needed\n\nHi Jane, can we move to net 45 before I sign? ..."
}
```

Duplicate check: grep `Emails/*.md` for `internet_message_id: "<PAXPR04MB8765A1B2C3D4E5F6@PAXPR04MB8765.eurprd04.prod.outlook.com>"` → no hit.

Slug: `RE: Q3 supplier contract – signature needed` → strip `RE:` → `Q3 supplier contract – signature needed` (38 chars, no illegal characters). Date `2026-08-21`. Attachment folder `Attachments/2026-08-21 Q3 supplier contract – signature needed/`.

`outlook_search_contacts(query="jane.doe@acme-parts.com", include_directory=true, limit=5)` → one directory item with that email, `company: "ACME Parts GmbH"`.

User said yes to exporting the .msg and the PDF (image001.png skipped as a 4 KB inline image).

Output `C:\Users\huxle\Vault\Administrator\Emails\2026-08-21 Q3 supplier contract – signature needed.md`:

```markdown
---
type: email
source: outlook
entry_id: "00000000AC1F2B3C4D5E6F708192A3B4C5D6E7F80700A1B2C3D4E5F60718293A4B5C6D7E8F900000000010A0000A1B2C3D4E5F60718293A4B5C6D7E8F9000000000"
internet_message_id: "<PAXPR04MB8765A1B2C3D4E5F6@PAXPR04MB8765.eurprd04.prod.outlook.com>"
conversation_id: "CAFEBABE1234567890ABCDEF"
from: jane.doe@acme-parts.com
from_name: Jane Doe
from_link: "[[People/Jane Doe]]"
to:
  - huxwaitt@gmail.com
cc:
  - tom.lee@acme-parts.com
received: 2026-08-21T16:42:10+02:00
status: todo
has_attachments: true
attachments:
  - "[[Administrator/Attachments/2026-08-21 Q3 supplier contract – signature needed/Q3-supplier-contract-v3.pdf|Q3-supplier-contract-v3.pdf]]"
msg_file: "[[Administrator/Attachments/2026-08-21 Q3 supplier contract – signature needed/2026-08-21 Q3 supplier contract – signature needed.msg|2026-08-21 Q3 supplier contract – signature needed.msg]]"
created_by: administrator/0.0.1
---

# RE: Q3 supplier contract – signature needed

**From:** [[People/Jane Doe]] <jane.doe@acme-parts.com>
**To:** Hux Waitt <huxwaitt@gmail.com>
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
- image001.png (4 KB, inline image, not exported)
```

Output `C:\Users\huxle\Vault\Administrator\People\Jane Doe.md` (did not exist before):

```markdown
---
type: person
source: outlook
name: Jane Doe
email: jane.doe@acme-parts.com
company: ACME Parts GmbH
last_contact: 2026-08-21T16:42:10+02:00
aliases: []
created_by: administrator/0.0.1
---

# Jane Doe

jane.doe@acme-parts.com · ACME Parts GmbH

## Emails

- 2026-08-21 — [[Emails/2026-08-21 Q3 supplier contract – signature needed]] (todo)
```

`Follow-ups.md`: untouched (status is `todo`, not `waiting`).

Report to the user:

> Saved `Emails/2026-08-21 Q3 supplier contract – signature needed.md` (status: todo, 2 action items). New person note `People/Jane Doe.md`. Exported the .msg and `Q3-supplier-contract-v3.pdf` to `Administrator/Attachments/2026-08-21 Q3 supplier contract – signature needed/`.

Running the same command again would find the `internet_message_id` line, leave both files as they are, and append `## Update 2026-08-22T…` to the email note saying "Saved again; no change."
