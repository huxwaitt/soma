---
name: save
description: Turn one Outlook email (or the thread it belongs to) into a note in the Obsidian vault — frontmatter with stable IDs, the trimmed body without quoted history or signature, recipients, a wikilink to the sender's person note, a one-line summary, and extracted action items; optionally export the .msg and attachments into the vault. Trigger when the user says "/administrator:save", "save this email", "note this", "put that email in the vault", "keep a record of the thread with X", "file this mail", "save the attachment from Bob's email to my notes", or gives an entry_id or search terms after asking to save. Reads Outlook only; the only Outlook calls that touch disk are outlook_save_mail_as and outlook_save_attachments, both optional and both write into the vault's Attachments folder.
---

# save — one email → one vault note

This skill takes a single mail (or the mail plus its thread) out of Outlook and writes it as a durable markdown note under `<vault>/Administrator/`. It never sends mail, never moves, deletes, marks, or categorises anything in Outlook. Outlook mechanics (folders, `entry_id`, dates, `response_format`) follow the `outlook` skill; note layout follows `skills/administrator/references/vault.md`; the note is written with the `vault_*` tools, which pick the filename, check the frontmatter and refuse a second note for a mail that is already saved. Do not duplicate any of that here — read those files when unsure.

Vault: `vault_status` once per session; if a folder or file flag is false, `vault_init(created_by="administrator/0.0.4")`. If the vault is unset or not a directory, stop and tell the user; do not guess a path.

## Steps

### 1. Resolve the target

- **An `entry_id` was given** (long opaque string, usually starts with `000000`): call `outlook_get_mail(entry_id=<id>, include_body=true, trim_quoted=true, response_format="json")`. If the body comes back with `body_truncated: true`, call again with `max_body_chars=0`.
- **Search terms were given** (anything else): call `outlook_search_mails(query=<terms>, folder="inbox", limit=5, response_format="json")`. If the user named a sender rather than a subject, use `scope="from"`. If nothing comes back in Inbox, try `folder="sent"`, then ask the user for a folder.
  - One hit: proceed with it, but say which mail you picked.
  - Two to five hits: show a numbered list (`received`, `from`, `subject`, first 80 chars of `preview`) and ask the user to pick a number. Do not guess.
  - More than five: the search already capped at 5; show them and offer to narrow by `since` or `scope`.
  - Then call `outlook_get_mail` on the chosen `entry_id` as above.
- **Whole thread requested** ("save the thread", "the whole conversation"): after you have the chosen mail, call `outlook_get_conversation(entry_id=<id>, include_body=true, trim_quoted=true, max_body_chars=0, limit=20)`. It returns every mail in the thread across folders (Inbox, Sent Items, sub-folders), oldest first, each with `entry_id`, `internet_message_id`, `conversation_id`, `folder`, `body`. If `truncated` is true, tell the user the thread is longer than 20 and that only the oldest 20 were saved. Call `outlook_get_mail` only for the **newest** mail (for `recipients` and `attachments`). The note is still one note, named after the newest mail; each message becomes a `### <received YYYY-MM-DD HH:MM> — <from_name>` subsection under `## Body`. Frontmatter identity fields come from the newest mail.

### 2. Check for a duplicate before writing anything

Identity is `internet_message_id` (returned by `get_mail`) when it is non-empty, otherwise `entry_id`. It is empty for drafts and on some IMAP/POP stores; then write `internet_message_id: ""`.

```
vault_find("email", {"internet_message_id": <internet_message_id>, "entry_id": <entry_id>})
```

The server tries `internet_message_id` first and falls back to `entry_id` only when it is empty.

- **`found: true`** → this mail is already saved at `path`; the result also carries its `frontmatter`. Do **not** create a second note and do **not** rewrite it. Skip to step 5 with `mode="append"`: the body is `Saved again via /administrator:save. <what changed, e.g. "Attachments exported: [[Administrator/Attachments/...]]" or "No change to the message; re-checked action items: none new.">`, and the frontmatter is the one `vault_find` returned (change `status` only if the user asked for that). The server adds the `## Update <ISO>` heading. Then refresh the sender's person note if this mail is newer (step 6), and report "already saved at `Emails/...`, appended an update". If the user clearly asked for attachments or the .msg this time and they are not yet linked in the note, do step 4 first and list the new links in that update text.
- **`found: false`** → continue.

### 3. Build the note

The filename is the server's job (`Administrator/Emails/YYYY-MM-DD <slug>.md` from `received` and `subject`, ` (2)` on a collision with a different mail). You only pass the frontmatter as an object and the body as markdown.

Frontmatter (keys in this order; the server quotes what needs quoting):

```yaml
type: email
source: outlook
entry_id: <entry_id verbatim>
internet_message_id: <internet_message_id verbatim, or "">
conversation_id: <conversation_id>
subject: <subject verbatim>
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
created_by: administrator/0.0.4
```

- Required by the server: `type`, `source`, `internet_message_id`, `entry_id`, `conversation_id`, `subject`, `from`, `from_name`, `from_link`, `to`, `cc`, `received`, `status`, `created_by`. Pass `cc: []` when there is no Cc.
- `to` / `cc`: SMTP addresses from `recipients[]` where `type` is `to` / `cc`. Only if `recipients` is empty, split the flat `to` / `cc` strings on `;` and keep the part inside `<…>`.
- `has_attachments: true` only when `get_mail` lists attachments; omit otherwise. `attachments` and `msg_file` are present only when step 4 exported something before the note was written; omit them otherwise.
- `status`: `todo` if the body asks the user to do something (a question to them, "please", "can you", "by <date>", they are the only To recipient); `waiting` if the mail is from the user's own address (check `outlook_whoami` once per session) and asks someone else for something; `fyi` if it is a notification, newsletter, receipt, or a plain reply with nothing open; `done` only if the user says so. When in doubt, `todo` — the user can change it.
- `from_link` uses the display name with the filename character cleanup (`\ / : * ? " < > |` → `_`, trimmed, 60 characters at most). Step 6 lets the server create the person note from the same name, so the link target matches.

Body of the note, in this order (the email note template in `administrator/references/vault.md`); no frontmatter fences, the server adds them:

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

**Trimming the body.** Work on plain text only (never request `include_html` for this).

If the `get_mail` / `get_conversation` result has a `body_trimmed` field (the server was asked for `trim_quoted=true` and supports it), use `body_trimmed` as is; it already has the quoted history and the signature removed, and `trimmed_chars` says how much went. Only when `body_trimmed` is missing, trim `body` yourself:

1. Cut everything from the first line that marks quoted history. A line counts as a marker when, after trimming, it matches one of:
   - `-----Original Message-----` or `-----Ursprüngliche Nachricht-----` (any dashes count ≥ 3)
   - starts with `From:` / `Von:` / `De:` and is followed within the next 4 lines by a line starting with `Sent:` / `Date:` / `Gesendet:` / `To:` / `An:`
   - matches `On .* wrote:` / `Am .* schrieb .*:` (may wrap onto two lines — join lines until the one ending in `wrote:`/`:`)
   - starts with `>` and every remaining non-blank line also starts with `>`
   - `________________________________` (≥ 20 underscores) immediately followed by a `From:` line
   The first marker wins; for a thread note, do this per message (each `items[].body` from `outlook_get_conversation`) so each subsection holds only its own new text.
2. Strip the signature: find the last occurrence of a line that is exactly `-- `, `--`, `Best regards`, `Kind regards`, `Regards`, `Thanks`, `Many thanks`, `Cheers`, `Mit freundlichen Grüßen`, `Viele Grüße`, `Sent from my iPhone`, or the sender's own display name on a line by itself. If that line sits in the last 12 lines of the remaining text, cut from it to the end. Then drop trailing lines that look like contact data (phone, `www.`, `http`, a street address line, job title followed by company) or legal boilerplate ("This email and any attachments are confidential…") even without a signature line.
3. Collapse three or more blank lines to two. Keep the rest verbatim — no rewriting, no summarising inside `## Body`.

Either way: if fewer than 20 characters remain (e.g. a "Thanks!" reply), keep the first 400 characters of the untrimmed `body` instead and note `(quoted history kept: new text was empty)`.

**Action items.** Only pull out asks that are directed at the user or that the user (as sender) gave someone else. Quote the mail's own wording shortened to one line; add a date only if the mail states one. Do not invent tasks from context. Each item also goes into `Follow-ups.md` (step 7) only when `status` is `waiting`.

### 4. Optional exports (ask first, once, before the note is written)

The server never adds keys to an existing note's frontmatter, so the export question comes before the write. When the mail has attachments or the user mentioned keeping the original, ask in one short message ending in a question and nothing else in that turn: "Export the original .msg and N attachment(s) to Administrator/Attachments/<YYYY-MM-DD slug>/?" Only proceed on a clear yes; on no, silence or a change of topic go to step 5 without exports (a later "yes, export it" is handled by the duplicate path in step 2). Both tools write to disk inside the vault, nothing else changes. Destination folder: `<vault>\Administrator\Attachments\<YYYY-MM-DD slug>\` — `<YYYY-MM-DD slug>` is the date part of `received` plus the subject with `Re:`/`FW:`/`AW:`/`WG:`/`TR:`/`SV:` prefixes stripped, illegal characters replaced by `_`, trimmed to 60 characters (the same slug the server uses for the note; check the returned note `path` in step 5 and say so if it differs). `<vault>` is `vault` from `vault_status`.

- `outlook_save_mail_as(entry_id=<id>, output_dir="<vault>\\Administrator\\Attachments\\<YYYY-MM-DD slug>", fmt="msg", filename="<YYYY-MM-DD slug>")` — the tool adds the extension and never overwrites (it appends ` (1)`), so use the returned `path`.
- `outlook_save_attachments(entry_id=<id>, output_dir="<vault>\\Administrator\\Attachments\\<YYYY-MM-DD slug>")` — or with `attachment_index` (1-based) for one file. Skip inline images under 20 KB (logos) unless asked; list them as "(not exported)".
- Paths must be absolute and under the user profile; `vault_status.under_user_profile` false means the tool will refuse — say so, mention `OUTLOOK_MCP_ALLOW_ANY_PATH=1` from the outlook skill, and skip the export rather than trying another folder.
- Put the .msg in `msg_file` and every other returned file in the `attachments` frontmatter list, and list all of them in `## Attachments`, as `[[Administrator/Attachments/<YYYY-MM-DD slug>/<filename>|<filename>]]` (filename taken from the returned path). Leave the files where the tool put them; do not rename after export.

### 5. Write the note

```
vault_write("email", <frontmatter>, <body>, mode="upsert")
```

The result is `{path, action: "created" | "appended", identity}`. `created` with the path `Administrator/Emails/YYYY-MM-DD <slug>.md` is the normal case; `appended` means the duplicate check in step 2 was stale (a parallel run) — report it as "already saved". An error from the tool (missing key, bad value) is yours to fix: correct the frontmatter and call again; never fall back to writing the file by hand.

### 6. Person note for the sender

Display Name = `from` with the filename character cleanup, trimmed to 60 characters. If `from` is empty or looks like an address, use the local part of the SMTP address.

```
vault_find("person", {"email": <smtp>})
```

matches `email:` and `aliases:` case-insensitively, so one address never gets two notes. Then:

**`found: false`** — create, with `company` only from `outlook_search_contacts(query=<smtp>, include_directory=true, limit=5)` (one call; use `company` only from an item whose `email` equals the sender's SMTP; never guess it from the domain; omit the key otherwise):

```yaml
type: person
source: outlook
name: <Display Name>
email: <smtp>
company: <see above, or omit>
last_contact: <received>
aliases: []
created_by: administrator/0.0.4
```

```markdown
# <Display Name>

<smtp> · <company, if known>

## Emails

- <YYYY-MM-DD> — [[Emails/<YYYY-MM-DD slug>]] (<status>)
```

`vault_write("person", frontmatter, body, mode="create")`. The server names the file `Administrator/People/<Display Name>.md`.

**`found: true`** — the note is at `path` (its filename may differ from Display Name, e.g. "Doe, Jane"; link to that one: `from_link` in step 3 must use the found note's name, so do this lookup before step 5). Call `vault_write("person", frontmatter, body, mode="append")` with the frontmatter `vault_find` returned, `last_contact` replaced when `received` is later, and `aliases` extended with the new display name or address if it is not the name or address on the note; body = `- <YYYY-MM-DD> — [[Emails/<YYYY-MM-DD slug>]] (<status>)`. The server changes only `last_contact` and merges `aliases`; the line lands under a `## Update <ISO>` heading it adds — the `## Emails` list written at creation and anything the user wrote by hand stay untouched. Skip the call entirely when `last_contact` would not change and the email line is already in the note (check the `body` from `vault_read`).

Recipients other than the sender are **not** given person notes by this skill; they appear as plain text on the `**To:**` / `**Cc:**` lines.

### 7. Follow-ups

If `status` is `waiting`:

```
vault_append_row("Administrator/Follow-ups.md", "Open",
                 [<YYYY-MM-DD>, "[[People/<Name>]]", <what, ten words or fewer>, "[[Emails/<YYYY-MM-DD slug>]]", <today>],
                 dedupe_key=<entry_id>)
```

`Who` is the person the user is waiting on (the To recipient when the mail is from the user). `appended: false, reason: "duplicate"` means the row is already there; leave it.

### 8. Report

Two or three lines: the note path, the person note (new or updated), what was exported, and the status you chose. End with `obsidian://open?vault=<vault_name>&file=<url-encoded path>` (`vault_name` from `vault_status`, `path` from `vault_write`, `/` and spaces encoded). Ask nothing further unless the duplicate check or exports need a decision.

## Rules that apply to every run

- Running the same command twice must leave one email note and one person note; the second run only appends `## Update`.
- Every note goes through `vault_write`; never write or edit a vault file with the host's file tools. The server never edits existing text; it appends.
- Never write outside `<vault>/Administrator/` (the server refuses any other path anyway).
- Never call `outlook_send_mail`, `reply_mail`, `forward_mail`, `move_mail`, `delete_mail`, `mark_mail`, `set_category`, or any `bulk_*` tool from this skill. Saving a mail does not mark it read.
- Keep datetimes exactly as Outlook returned them (local time with offset). Do not convert.
- Never put the full `html_body` or raw headers into the vault.

## Worked example

Input from `outlook_get_mail(entry_id="00000000AC1F...", include_body=true, trim_quoted=true, response_format="json")`:

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
    {"name": "Hux Waitt", "address": "hux@example.com", "type": "to"},
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
  "body": "Hi Hux,\n\nAttached is v3 with the payment terms changed to net 45 as we discussed. Could you sign and return it by Friday 29 August? Tom will handle the PO once it's back.\n\nOne more thing: please confirm the delivery address is still the Leipzig warehouse.\n\nBest regards\nJane Doe\nKey Account Manager | ACME Parts GmbH\n+49 341 555 0123\nwww.acme-parts.com\n\nThis email and any attachments are confidential and intended solely for the addressee.\n\n-----Original Message-----\nFrom: Hux Waitt <hux@example.com>\nSent: Thursday, 21 August 2026 11:03\nTo: Jane Doe <jane.doe@acme-parts.com>\nSubject: Q3 supplier contract – signature needed\n\nHi Jane, can we move to net 45 before I sign? ...",
  "body_trimmed": "Hi Hux,\n\nAttached is v3 with the payment terms changed to net 45 as we discussed. Could you sign and return it by Friday 29 August? Tom will handle the PO once it's back.\n\nOne more thing: please confirm the delivery address is still the Leipzig warehouse.",
  "trimmed_chars": 512
}
```

Duplicate check: `vault_find("email", {"internet_message_id": "<PAXPR04MB8765A1B2C3D4E5F6@PAXPR04MB8765.eurprd04.prod.outlook.com>", "entry_id": "00000000AC1F…"})` → `found: false`.

`vault_find("person", {"email": "jane.doe@acme-parts.com"})` → `found: false`. `outlook_search_contacts(query="jane.doe@acme-parts.com", include_directory=true, limit=5)` → one directory item with that email, `company: "ACME Parts GmbH"`.

Ask: "Export the original .msg and 1 attachment (Q3-supplier-contract-v3.pdf; image001.png is a 4 KB inline image, skipped) to Administrator/Attachments/2026-08-21 Q3 supplier contract – signature needed/?" User: "yes" → both export tools run; returned paths end in `2026-08-21 Q3 supplier contract – signature needed.msg` and `Q3-supplier-contract-v3.pdf`.

`vault_write("email", frontmatter, body, mode="upsert")` with:

```yaml
type: email
source: outlook
entry_id: 00000000AC1F2B3C4D5E6F708192A3B4C5D6E7F80700A1B2C3D4E5F60718293A4B5C6D7E8F900000000010A0000A1B2C3D4E5F60718293A4B5C6D7E8F9000000000
internet_message_id: <PAXPR04MB8765A1B2C3D4E5F6@PAXPR04MB8765.eurprd04.prod.outlook.com>
conversation_id: CAFEBABE1234567890ABCDEF
subject: RE: Q3 supplier contract – signature needed
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
created_by: administrator/0.0.4
```

```markdown
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
- image001.png (4 KB, inline image, not exported)
```

Result: `{"path": "Administrator/Emails/2026-08-21 Q3 supplier contract – signature needed.md", "action": "created", ...}`.

`vault_write("person", {type: person, source: outlook, name: "Jane Doe", email: "jane.doe@acme-parts.com", company: "ACME Parts GmbH", last_contact: "2026-08-21T16:42:10+02:00", aliases: [], created_by: "administrator/0.0.4"}, "# Jane Doe\n\njane.doe@acme-parts.com · ACME Parts GmbH\n\n## Emails\n\n- 2026-08-21 — [[Emails/2026-08-21 Q3 supplier contract – signature needed]] (todo)", mode="create")` → `Administrator/People/Jane Doe.md`.

`Follow-ups.md`: untouched (status is `todo`, not `waiting`).

Report to the user:

> Saved `Emails/2026-08-21 Q3 supplier contract – signature needed.md` (status: todo, 2 action items). New person note `People/Jane Doe.md`. Exported the .msg and `Q3-supplier-contract-v3.pdf` to `Administrator/Attachments/2026-08-21 Q3 supplier contract – signature needed/`.
> obsidian://open?vault=Vault&file=Administrator%2FEmails%2F2026-08-21%20Q3%20supplier%20contract%20%E2%80%93%20signature%20needed.md

Running the same command again: `vault_find` answers `found: true`, nothing is exported again, and `vault_write(..., mode="append")` adds `## Update 2026-08-22T…` with "Saved again via /administrator:save. No change." to the email note. Both files otherwise stay as they are.
