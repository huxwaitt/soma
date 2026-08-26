---
name: draft
description: Writes a reply to an email thread in the user's own voice and saves it to Outlook Drafts, never sends. Finds the thread by words or `entry_id`, reads it with quoted history removed and only the fields it needs, reads the sender's person page and the open items between the two of them (both directions), gets the voice from one `outlook_voice_sample(address)` call (`references/voice.md`), answers every open question in the last mail, marks missing information as `[fill in: …]`, shows the draft, and only after a yes calls `outlook_reply_mail(save_only=true)` so the draft stays in the conversation. Also holds the one voice rule set that `followups` (nudges) and `notes` (minutes) use. Trigger when the user says "/administrator:draft", "draft a reply to", "answer Tom's mail", "reply to the thread about X", "write back to Jane saying", "help me answer this", "what should I say to". Read-only in Outlook apart from the one draft the user said yes to.
---

# draft — reply in the user's voice

`/administrator:draft <thread words or entry_id> [what to say]`. Reads Outlook through the `outlook_*` tools, reads the vault only through `vault_*` tools, and changes Outlook only by saving one draft the user said yes to. The plugin never sends: `outlook_reply_mail` is called with `save_only=true` and nothing else. Outlook mechanics (folders, `entry_id`, dates, `response_format`, `fields`) follow the `outlook` skill and `skills/administrator/references/outlook.md`.

Before starting: `vault_status` once per session (run `vault_init(created_by="administrator/0.4.0")` if a folder or file flag is false) and `outlook_whoami(response_format="json")` once per session. "Self" means any `accounts[].smtp_address`, compared case-insensitively. Load `references/voice.md` the first time a draft, nudge or minutes email is written in a session; its end holds a worked example.

## 1. Find the thread

Argument parsing: the first part is the thread, the rest (after a comma, a dash, or the words `say`, `saying`, `tell them`, `answer`) is what the user wants to say. If the whole argument looks like an `entry_id` (long, no spaces, hex-like), use it as is.

- `entry_id` given → step 2.
- Words given → `outlook_search_mails(query=<words>, limit=5, fields=["entry_id","from","from_address","subject","received"], preview_chars=0, response_format="json")` in the inbox; if nothing, once more with `folder="sent"`. Group the hits by subject with reply prefixes stripped (the slug rule in `skills/administrator/references/vault.md`).
  - One subject → proceed with the newest hit.
  - Two or three → show them (`#`, from, subject, received) and ask which. Stop there; the user's pick is the next message.
  - More than three → show the newest three and ask for more words or a pick.
  - None → say "No mail matches `<words>` in Inbox or Sent" and stop.

## 2. Read the thread

`outlook_get_conversation(entry_id=<hit>, include_body=true, max_body_chars=4000, limit=20, trim_quoted=true, fields=["entry_id","internet_message_id","from","from_address","to","received","body_trimmed"])` → `items[]` oldest first. Work with the last 5 items at most; earlier ones are read only when the last mail refers to them ("as discussed below").

**The last mail** = the newest item. If it is from self, say "Your mail from <date> is the last in this thread; nothing to answer — write a nudge instead? (`/administrator:followups`)" and stop unless the user gave a `[what to say]` part, in which case write a follow-up in the same thread.

From the last mail, list the **open questions**: every sentence ending in `?`, every "could you / can you / please send / let me know" sentence, and any deadline. Keep them in order. Then `outlook_get_mail(entry_id=<last mail>, include_body=false, fields=["recipients","subject"], response_format="json")` once: `recipients[]` gives SMTP addresses per recipient, and whether anyone besides self and the sender is on `to` or `cc` decides `reply_all`.

## 3. Read what the vault knows

- One call: `vault_wiki_search(query=<the sender's name + the subject>, brief=true, max_chars=1000)` → `{text, pages: [{page, title, kind, status, verified}], facts: [{page, id, text, since}], chars}`. It holds how the sender works with the user (language, formality, responsibilities) and the topic's lead, facts and open items — the facts the reply may state. Then one `vault_wiki_read(path=<the sender's own page in `pages[]`>, sections=["notes"], max_chars=600)` for a `Voice with this person:` block or anything else the user wrote there: `## Notes` is the one part search never reads. Nothing found → nothing; `draft` creates no pages and sends no wiki ops.
- One `vault_wiki_search(query="", open_items=true, page=<the sender's person page>)` → `[{page, stem, type, title, owner_name, id, text, owner, due, since, src, record, done}]`: what they owe (`owner` is their page) and what the user owes them (`owner: me`), oldest first. Mention one only when the last mail touches it, and say the due date as it stands. Never write an op here; `draft` only reads.
- `vault_find("email", {"internet_message_id": <last mail's>, "entry_id": <last mail's>}, fields=["status"])` → when found, `vault_read` the note for its `## Action items` (what the user already committed to). Not found → skip; do not save the mail.
- `vault_read("Administrator/Preferences.md")` → the `## Voice` section if there is one (hard rules, `references/voice.md`).

## 4. Get the voice

One call: `outlook_voice_sample(address=<from_address of the last mail>, n=10, max_chars=300)`. It returns the opening and the last two lines of the user's last ten sent mails to that person (or of sent mail overall when fewer than 3 exist — `used_address: false`), already trimmed, plus `stats` with counted greetings, sign-offs and average length. Turn the stats into the six facts as `references/voice.md` says. Precedence: `## Voice` hard rules → a `Voice with this person:` block in the person note → the sample → plain neutral voice. Do not read sent mails one by one; the sample is the whole voice read.

## 5. Write the reply

Rules, in this order:

1. **Answer every open question** from step 2, in the order asked. One sentence or one short paragraph each. A question the user's `[what to say]` part does not cover and the vault does not answer gets `[fill in: <what is needed, e.g. the date you can deliver>]` in its place — never a guessed answer.
2. Then what the user asked to add, in their words where they gave them.
3. At most one question or next step at the end.
4. Greeting, sign-off, length, formality, shape and habits from the six facts. Language of the other person's last mail.
5. **Never invent facts.** No dates, prices, names, numbers, commitments or "attached" that did not come from the thread, the wiki pages read in step 3, the vault, or the user. A wiki fact is quoted as it stands; a fact on a page flagged `contradiction` or `stale` becomes `[fill in: …]` instead. No attachments unless the user named a file; then pass its absolute path in `attachments`.
6. Plain text. No HTML unless the thread is HTML and the sample shows formatting (`html=false` by default).
7. Do not repeat the other person's mail back to them; Outlook quotes it below the reply anyway.

`reply_all` = true when the last mail had another recipient besides self and the sender; false for a two-person thread. Say which in the preview.

## 6. Show it, then one yes

```
Draft reply → Tom Lee <tom.lee@acme-parts.com> (reply all: also Priya Nair)
Subject: Re: Delivery schedule September

Hi Tom,

8 Sep works for the first delivery. The address is [fill in: Leipzig site address — not in the thread or Tom's note].

Could you send the packaging spec v2 before then so the team can check it?

Thanks
Hux

Save this to Drafts? (yes / no / change: …)
```

- "change: …" → rewrite, show again, ask again.
- Only on a clear yes: `outlook_reply_mail(entry_id=<last mail entry_id>, body=<text>, reply_all=<as shown>, html=false, save_only=true)` → `{status: "saved", reply_all, in_reply_to, entry_id, subject}` (`entry_id` is the draft's). Report: "Saved to Outlook Drafts as a reply in the thread; send it from Outlook." If the body still holds `[fill in: …]`, say so in the same line: "It has 1 fill-in marker."
- "no" → stop; nothing is written anywhere.
- Never call `outlook_reply_mail` without `save_only=true`, never `outlook_send_mail` without `save_only=true`, never `outlook_forward_mail`. If the user says "send it", say the plugin only saves to Drafts and they can send from Outlook.

When an email note exists for the last mail (step 3), append one line after a successful save: `vault_write("email", <that note's frontmatter>, "Reply draft saved to Drafts via /administrator:draft.", mode="append")`. No note → nothing; do not create one.

## 7. Report

Two to four lines: thread found (subject, how many mails, who wrote last), what the draft answers, whether it went to Drafts, fill-in markers if any, where the voice came from ("10 mails to Tom" or "sent mail overall"). End with an `obsidian://open?vault=<vault_status.vault_name>&file=<path>` line only for a note that was appended. If the host shows the token count of this turn, add one line `Tokens this turn: <n>`; otherwise say nothing about it.

## The nudge and minutes variants

`followups` (nudges) and `notes` (minutes) write their email bodies with the same sample call and the same rules from `references/voice.md`, "The three variants". They keep their own save calls: `outlook_send_mail(save_only=true)` as their skills say; a nudge may instead use `outlook_reply_mail(entry_id=<the user's own last mail>, save_only=true)` to stay in the thread — either way nothing is sent. One `outlook_voice_sample` per person per session; nudges to several people reuse the overall sample (`address=None`) when a person has fewer than 3 mails.

## Rules

- Reads are free. The single Outlook write is `outlook_reply_mail(save_only=true)` after the draft was shown and the user said yes, once per run.
- Never call `outlook_mark_mail`, `outlook_move_mail`, `outlook_delete_mail`, any `bulk_*` tool, `outlook_create_event`, `outlook_update_event`.
- The vault is only written through `vault_write(mode="append")` on an existing email note after a save; nothing is created, nothing outside `Administrator/`. The plugin no longer writes voice blocks; one the user wrote is still honoured.
- Always pass `fields` to `search_mails`, `get_conversation` and `get_mail`; never re-type a body, a snippet or a sample into your reply to the user.
- No raw JSON in the reply. The draft is shown as plain text in a code block.
- Run twice on the same thread with the same answer: the second run saves a second draft only if the user says yes again.
