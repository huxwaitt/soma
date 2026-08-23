# Voice — writing the way the user writes

One rule set for every piece of text the plugin writes in the user's name: a reply (`draft`), a nudge (`followups`), a minutes email (`notes`). The goal is that the user can send it from Drafts without touching it. A voice profile is six facts, read from the user's own sent mail through one tool call, and nothing else.

## The one call

```
outlook_voice_sample(address=<the other person's SMTP>, n=10, max_chars=300)
```

The server reads the Sent folder, keeps the last `n` mails to that address (`matched`, out of `scanned` ≤ 300), removes quoted history and signatures, skips calendar responses and auto-replies, and returns:

| Key | What it holds |
| --- | --- |
| `used_address` | `true` when 3 or more mails to that person exist and the sample is per person; `false` when the server fell back to the last `n` sent mails overall. Pass `address=None` to ask for the overall sample directly (nudges to several people, minutes). |
| `items[]` | One per mail: `to`, `subject`, `sent`, `opening` (first `max_chars` characters of the trimmed body), `closing` (the last 2 non-empty lines). |
| `stats.greeting_counts` | `{"Hi Tom,": 8, "Hello Tom,": 1, "": 1}` — the first line's opening words, counted. An empty key means the mail started with the first sentence. |
| `stats.signoff_counts` | `{"Thanks": 9, "Best regards": 1}` — the short line before the name, counted. |
| `stats.avg_chars` | Average length of the trimmed body in characters. |
| `count` | Mails in the sample. `0` → the Sent folder is empty; write in a plain neutral voice (`Hi <first name>,` … `Thanks` + the user's first name from `outlook_whoami`) and say so. |

Ten openings of 300 characters are under a page. Do not ask for more, do not re-type them anywhere, and never read sent mails one by one for the voice.

## The six facts — from the stats to the rules

| Fact | Where it comes from | Rule |
| --- | --- | --- |
| Greeting | `greeting_counts` | The key with the highest count, written exactly (punctuation included), with the other person's first name in place of the sampled one. Ties → the greeting of the newest `items[]` entry. Top key `""` → no greeting; start with the first sentence. |
| Sign-off | `signoff_counts` + the last line of `closing` | The top sign-off plus the name line under it (the user's first name, full name, or none — read it off `closing[1]` of the newest item). |
| Length | `avg_chars` | `avg_chars ÷ 6` ≈ words, rounded to 25: 360 chars → "~60 words". Stay within ±50% of that. |
| Formality | The `opening` texts | Contractions (`I'll`, `can't`), first names vs surnames in the greeting, `please` / `could you` vs plain imperatives, exclamation marks → `informal` / `neutral` / `formal`. |
| Shape | The `opening` texts | Bullets or numbered lists vs prose; one paragraph or several; how long the first sentence is. |
| Habits | `opening` and `closing` | Phrases that recur in 3 or more items (`quick one`, `let me know`, `happy to`), whether the answer comes first, whether a question closes the mail. |

Also note the **language** of the items (English, German, mixed). The reply is written in the language the other person used in their last mail; the sample shows what the user is comfortable with.

Count, do not guess: `greeting_counts` and `signoff_counts` are already counts, use them as they are. When `used_address` is true the per-person values win over anything you remember from an overall sample earlier in the session. Keep the result as six short bullets in your working memory for the rest of the session:

```
- Greeting: "Hi Tom," (8/10)
- Sign-off: "Thanks" + "Hux" (9/10)
- Length: ~60 words
- Formality: informal, contractions, first names
- Shape: prose, one or two short paragraphs, bullets only for lists of dates
- Habits: answers first, one question at the end, "let me know" to close
```

## Where the profile lives

The plugin does not store the profile: one `outlook_voice_sample` call per person per session is cheaper than a stored block and never goes stale. Two places can still hold user-written rules:

- **`Administrator/Preferences.md`, `## Voice`** — plain bullets, same six facts, free text, written by the user only. It can hold hard rules the sample cannot show: "never use exclamation marks", "always sign with full name to external people", "write German to colleagues at Example GmbH". The plugin reads it (`vault_read("Administrator/Preferences.md")`) and never writes it. When a draft is shown and no `## Voice` exists yet, offer the six bullets once per session with "paste this into Preferences.md under `## Voice` if it looks right" — then drop it.
- **`Voice with this person:` in a person note** — a block the user (or an earlier plugin version) wrote. When `vault_read` of the person note shows one, it wins over the counted sample for that person. The plugin no longer appends these blocks.

Order of precedence when writing: hard rules in `## Voice` → `Voice with this person:` block → the six facts from the sample → plain neutral voice.

## Applying it

- Greeting and sign-off exactly as the facts say, including punctuation. "None" → start with the first sentence.
- Stay within ±50% of the length unless the content does not fit; then shorter is better than longer.
- Match formality and shape. Informal → contractions allowed, first names. Formal → no contractions, full sign-off.
- Reuse at most one habit phrase per draft. Copying three makes it read like an imitation.
- Never copy a sentence from an `opening`. The sample is for form, not content.
- Language: the language of the other person's last mail. If the sample shows the user never writes that language, say so and write in the user's language instead.
- Facts: only what the thread, the person note, `Follow-ups.md` or the user said. Anything missing becomes `[fill in: what is missing]` in the body, and the draft is shown with that marker in it. Never fill a date, a number, a price, a name or a promise from guesswork.

## The three variants

All three use the same facts and the same rules above; they differ in what goes into the body.

| Variant | Used by | Sample call | Body |
| --- | --- | --- | --- |
| **reply** | `draft` | `address=<sender>` | Answer every open question in the other person's last mail, in the order asked; then anything the user said to add; then one question or next step at most. |
| **nudge** | `followups` | `address=<the person waited on>`; several people → one call with `address=None` for all of them, unless one person has their own 3+ mails | 2–3 sentences: the original subject and date, the ask repeated in one sentence from `last_line` of `outlook_awaiting_reply`, one closing question. No apology, no "just checking in", nothing the original mail did not ask. |
| **minutes** | `notes` | `address=None` (overall) | Greeting, one line saying which meeting, then `Decisions` and `Action items` (owner, what, by when) as bullets even in a prose profile — these are lists — then the sign-off. Nothing that is not in the meeting note. |

A nudge or minutes email shown to the user carries the same `[fill in: …]` markers when something is missing, and the same "save to Drafts only after a yes" rule as a reply.

## Worked example — `/administrator:draft delivery schedule tom — 8 Sep is fine, ask for the packaging spec`

2026-08-22, `outlook_whoami` → `hux@example.com`.

1. `outlook_search_mails(query="delivery schedule tom", limit=5, fields=["entry_id","from","from_address","subject","received"], preview_chars=0, response_format="json")` → 2 hits, both `Re: Delivery schedule September` → one thread.
2. `outlook_get_conversation(entry_id="00000000B3…", include_body=true, max_body_chars=4000, limit=20, trim_quoted=true, fields=["entry_id","internet_message_id","from","from_address","to","received","body_trimmed"])` → 4 items. Last: Tom Lee, 2026-08-21: "Hi Hux, does 8 Sep work for the first delivery? And which address should the driver use — the Leipzig site or the warehouse? Thanks, Tom". Open questions: (a) 8 Sep, (b) which address. `outlook_get_mail(entry_id="00000000B3…", include_body=false, fields=["recipients","subject"], response_format="json")` → only `hux@example.com` on `to` → `reply_all: false`.
3. `vault_find("person", {"email": "tom.lee@acme-parts.com"})` → found, `vault_read` → `## Notes` says Tom prefers dates in ISO. `Follow-ups.md` → one `## Open` row "Tom Lee / Delivery schedule September". `vault_find("email", …)` → not found. `Preferences.md` has no `## Voice`.
4. `outlook_voice_sample(address="tom.lee@acme-parts.com", n=10, max_chars=300)` → `used_address: true`, `count: 10`, `stats: {avg_chars: 350, greeting_counts: {"Hi Tom,": 8, "Tom,": 2}, signoff_counts: {"Thanks": 9, "Best": 1}}`; the openings are prose, contractions throughout, each ends with one question. Facts: `Hi Tom,` / `Thanks` + `Hux` / ~60 words / informal / prose / one question at the end.
5. (a) answered by the user; (b) not in the thread, the note or the argument → `[fill in: Leipzig site or warehouse — you didn't say]`. The packaging spec becomes the closing question.

Shown as in `SKILL.md` step 6. User: "change: warehouse" → "The driver should use the warehouse address." User: "yes" → `outlook_reply_mail(entry_id="00000000B3…", body=<text>, reply_all=false, html=false, save_only=true)` → `{status: "saved", entry_id: "00000000C9…"}`.

> Thread "Delivery schedule September", 4 mails, Tom wrote last on 2026-08-21 with 2 questions. Draft answers both and asks for the packaging spec v2. Saved to Outlook Drafts as a reply in the thread; nothing sent. Voice from 10 mails to Tom. No fill-in markers left.

Five `outlook_*` calls, the last one the save. A group thread (someone else on `to`) differs only in `reply_all: true` and "(reply all: also Bob Lee)" in the preview; a sender with fewer than 3 sent mails differs only in `used_address: false` and "Voice from sent mail overall" in the report.
