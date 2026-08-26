---
description: Write a reply to an email thread in your own voice (one outlook_voice_sample call) and save it to Outlook Drafts as a reply in the thread. Never sends.
argument-hint: "<thread words or entry_id> [what to say]"
---

# /administrator:draft

Arguments: the thread (search words or an `entry_id`), then optionally what you want to say, after a comma, a dash, or `say` / `saying` / `tell them`.

Argument given: `$ARGUMENTS`

## Steps

1. Load the `administrator` skill, then the `draft` skill and `skills/draft/references/voice.md`. Load the `outlook` skill if it is not already loaded.
2. Call `vault_status` (run `vault_init(created_by="administrator/0.4.0")` if anything is missing) and `outlook_whoami(response_format="json")` for your own address(es) and local time.
3. Find the thread: an `entry_id` is used as is; words go to `outlook_search_mails(query, limit=5, fields=["entry_id","from","from_address","subject","received"], preview_chars=0, response_format="json")` (Inbox, then Sent). One subject → proceed. Two or three → show them and ask which. None → say so and stop.
4. `outlook_get_conversation(entry_id, include_body=true, max_body_chars=4000, limit=20, trim_quoted=true, fields=["entry_id","internet_message_id","from","from_address","to","received","body_trimmed"])`. The last mail's open questions, in order; `outlook_get_mail(entry_id, include_body=false, fields=["recipients","subject"], response_format="json")` once for the recipients and `reply_all`. If you wrote last, say so and stop unless you gave something to say.
5. `vault_wiki_search(query=<the sender's name + the subject>, brief=true, max_chars=1000)` (how they work with you, the facts the reply may state) and one `vault_wiki_read(path=<the sender's page>, sections=["notes"], max_chars=600)` for a `Voice with this person:` block, which search never reads; one `vault_wiki_search(query="", open_items=true, page=<the sender's person page>)` for the open items both ways (what they owe, what you owe them); `vault_find("email", …, fields=["status"])` for an existing note; `## Voice` in `Preferences.md`.
6. Voice: one `outlook_voice_sample(address=<sender>, n=10, max_chars=300)` call; its `stats` (greeting and sign-off counts, average length) and openings give the six facts as `voice.md` says. Hard rules in `## Voice` and a user-written `Voice with this person:` block win over the counts. No sent mail is read one by one.
7. Write the reply: answer every open question in order, then what you asked to say, one closing question at most, greeting / sign-off / length / formality from the six facts, `[fill in: …]` wherever a fact is missing. No invented dates, numbers, names or commitments.
8. Show the draft (to, reply-all or not, subject, body) and ask "Save this to Drafts?". Only on a clear yes: `outlook_reply_mail(entry_id=<last mail>, body, reply_all, html=false, save_only=true)`. "change: …" rewrites and asks again; "no" stops. Nothing is ever sent.
9. Report: thread, what the draft answers, "saved to Outlook Drafts as a reply in the thread", where the voice came from, fill-in markers left. An `obsidian://open` link only when an email note was appended.
10. If the host shows the token count of this turn, end with one line `Tokens this turn: <n>`; otherwise say nothing about it. (`draft` writes no daily note, so there is no `tokens_used` to pass on.)

## Example

```
/administrator:draft delivery schedule tom — 8 Sep is fine, ask for the packaging spec
/administrator:draft offsite venue priya
/administrator:draft 00000000B3… saying we take venue 2
```

On 2026-08-22, "delivery schedule tom" finds one thread of 4 mails; Tom asked two questions on 2026-08-21. `outlook_voice_sample("tom.lee@acme-parts.com")` counts `Hi Tom,` 8/10 and `Thanks` 9/10 at ~60 words. The draft answers the date from what you said and leaves `[fill in: Leipzig site or warehouse]` for the address; "change: warehouse" fixes it; "yes" saves it. Five Outlook calls including the save.

> Thread "Delivery schedule September", 4 mails, Tom wrote last on 2026-08-21 with 2 questions. Draft answers both and asks for the packaging spec v2. Saved to Outlook Drafts as a reply in the thread; nothing sent. Voice from 10 mails to Tom. No fill-in markers left.

The worked example in full is at the end of `skills/draft/references/voice.md`.
