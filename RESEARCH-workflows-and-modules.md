# Outlook workflows → reusable parts (research notes, 2026-08-22)

Four parallel research sweeps: individual knowledge-worker habits, assistant/coordinator work, automation (rules/VBA/Power Automate/add-ins/AI tools), and Outlook↔note apps (Obsidian, OneNote, Notion, Logseq). Reddit was unreachable; evidence is MS Q&A/Community, GTD forum, Obsidian forum, Slipstick, practitioner blogs, vendor docs.

## 1. What people actually do (vs. what gets recommended)

| Recommended (MS best-practices, GTD, Inbox-Zero guides) | What people keep doing |
|---|---|
| 4 D's + To-Do Bar + Quick Steps + categories + daily/weekly routine | 1–3 folders, the Archive button, search, and a flag list they don't trust |
| Flag = "do later" | "Later" is where every system dies: piles of flags, deciding twice, re-reading flagged mail on Friday |
| Categories for context | Category discipline fades: not copied on reply, stripped on send, colors run out |
| Flag → Microsoft To Do | Widely started, widely abandoned (100-item/30-day cap, primary mailbox only, sync failures) |
| Weekly review checklist | The ~20-min Friday review is the one habit people with a working system actually keep |
| Time blocking / Focus Time | Blocks get booked over; prep/travel buffers are manual or absent |
| Templates (Quick Parts/.oft) | Only repetitive-reply jobs use them; most people have 1–2 signatures and zero templates |

The pain is built-in and a decade old: email has no status field, no per-thread "waiting on them" tracking, no "has anyone replied?" query, no recurring send, no prep buffer.

## 2. Assistant / coordinator work

- **Scheduling is the biggest time sink** (~⅓ of the day): Scheduling Assistant → AutoPick → room → send. Breaks on outside attendees (no free/busy), >15 people, time zones, and it "reads the calendar, not the person" (no travel/focus/preferences).
- **Moving a whole day of meetings** is the weekly nightmare; the shared-calendar plumbing causes the worst bugs (meetings snapping back, silent cancellations, duplicate invites).
- Also recurring: mail sent on the boss's behalf, going through the boss's inbox 3× a day, minutes emails (2–4 bullets + action table), travel plans as calendar blocks, covering for another assistant, invoice routing in a shared mailbox.
- Almost everything non-trivial needs Exchange delegate permissions; a lot needs an admin. COM can read/write delegated calendars and send on behalf *if* the permissions already exist.

## 3. Automation: the building blocks

Every automation from a 2005 Slipstick macro to 2026 Copilot/Superhuman/Fyxer is built from the same ~15 pieces:

- **When**: mail arrives · about to send · user clicks · on a schedule · N days with no reply · outside event
- **If**: sender/domain/inside-vs-outside · I'm in To or Cc · keyword · message type · has attachment · flag/category state · *nobody replied to this thread* · **AI label** · too many recipients / outside domain
- **Do**: move/archive/delete · categorize/flag/mark read · forward/reply with template · hold N minutes/send later · block the send · snooze
- **Pull out**: attachment → folder · fields → spreadsheet row · parse body · **summarize** · **write a draft in my voice** · spot proposed times
- **Create elsewhere**: task · event/meeting link · chat post · approval · note/CRM entry
- **Follow through**: reminder on sent mail cleared by a reply · nudge · daily/weekly summary mail

The AI products add only three things: an AI label instead of a keyword match, *summarize*, and *draft in my voice*. Fyxer's 8 labels (To Respond, FYI, Comment, Notification, Meeting Update, Awaiting Reply, Actioned, Marketing) are a sensible default. Both Fyxer and Superhuman work through plain Outlook categories/folders/Drafts — they're AI-driven Rules + Quick Steps.

Actually common in practice: sender→folder rules, delay-send, meeting-response cleanup, mark-read+move Quick Step, save-attachments, flagged→task, forgot-attachment/reply-all warnings, export-to-Excel, no-reply follow-up.

## 4. Outlook ↔ notes: lessons

No good bridge exists. Four routes, each crippled: drag .msg (classic only, can't tell which occurrence of a recurring meeting), VBA/COM (dies with new Outlook), Graph (correct but tenant consent usually blocked, tokens in plaintext), ICS (calendar only, stale, often disabled). Everyone hits the same problems: duplicates, notes overwritten by re-sync, dead `outlook:` EntryID links, HTML→Markdown mess, work mail in a personal vault.

What the people who got it right do:
1. **Stable IDs** — Internet Message-ID / conversation_id / web link, never EntryID (tied to the mailbox store, dies on reinstall). A per-occurrence key for recurring meetings.
2. **Save on purpose, don't sync** — pick an email → save headers + trimmed body. Syncing all flagged mail just dumps an unsorted inbox into the vault.
3. **Source note stays untouched; thoughts go elsewhere** — the email/meeting note is the record; tasks and comments go in daily/meeting notes that link to it, so re-saving never wipes human text.
4. **Lists of links in frontmatter** (`attendees: ["[[Jane]]"]`, `from: "[[Jane]]"`) so Bases/Dataview person pages work; flat date-prefixed folders + `type:` property beat deep PARA trees.
5. **Work vault kept separate, on employer storage, no personal sync** — said out loud in the docs.

## 5. What this means for `soma`

- **Classic Outlook COM is the only no-admin path that works at most companies** (Graph consent blocked, EWS shuts down Oct 2026/Apr 2027) — *and* it's on a clock (new Outlook). So: keep the Outlook layer thin and swappable.
- **Build for the habits that survive**, not the guru system: few folders + search + a trustworthy "waiting on me / waiting on them" view + a weekly summary note. The most useful thing we can add is what Outlook lacks: **a status per thread** (to reply / waiting / done) kept in the vault and worked out from the conversation itself.
- **Asking before sending matters more than features**: anything that sends (mail, invites, updates to attendees) is what users regret. Writing to the Drafts folder is the safe default (Superhuman does exactly this).
- **Summarize and draft-in-voice are table stakes**; what makes them good is feeding them vault context (person notes, earlier threads, meeting history).

## 6. Breaking it into reusable parts

Four layers. Each part does one job, has a fixed input/output, and can be used by any workflow.

### Layer 0 — Outlook connector (`outlook-classic-mcp`, swappable)
Raw verbs only: read (list/search/get/export), change (move/mark/delete/send/save), calendar, contacts, IDs. Additions needed for the layers above:
- `internet_message_id` (PR_INTERNET_MESSAGE_ID 0x1035001F) on every mail → stable ID
- `get_conversation(conversation_id)` → whole thread in one call (follow-ups, thread summaries)
- `get_free_busy(addresses, start, end)` (`Recipient.FreeBusy`) → scheduling
- `mark_mail` with a flag due date; `list_events` on a named (shared) calendar
- `send_mail(on_behalf_of=…)` — only if the delegate permission exists

### Layer 1 — Building blocks (skill reference modules; no side effects unless stated)
| Part | In → out | Used by |
|---|---|---|
| `ids` | mail → `{message_id, conversation_id, entry_id}`; event → `{ical_uid, occurrence_key}`; duplicate rules | every note writer |
| `find` | plain request → list/search params (`since`, `from`, `unread`, `has_attachments`, folder) | inbox, save, summary, follow-ups |
| `label` | mail (+vault context) → `{label from the 8, urgency, needs_reply, why}` | inbox, summary, suggest-rules |
| `thread-status` | conversation → `{last_from_me, last_from_them, days_waiting, status}` | follow-ups, inbox, person notes |
| `summarize` | thread/day/set of events → bullets citing message_ids | save, meeting prep, summary, minutes |
| `draft` | intent + thread + voice (learned from Sent) + person note → body; always lands in Drafts | reply, nudge, on-behalf, minutes |
| `pull-out` | mail → attachments to vault path, fields → row, body → trimmed Markdown (quotes/signature stripped) | save, invoices, export |
| `tidy` | decision → move/categorize/flag/mark read via bulk tools; never delete without a yes | inbox, cleanup, suggest-rules |
| `people` | address/name ↔ `People/<name>.md`; link lists; last-contact date | save, meeting prep, draft |
| `slots` | attendees + constraints (+ preferences from vault) → candidate times via free/busy; buffers | scheduling, moving a day |
| `vault` | note writers with fixed schemas: email / meeting / person / daily / weekly; append-only when the ID already exists | every workflow |
| `rules` | what needs a yes (read / local change / anything that sends), what never goes into the vault, run-twice safety | all |

### Layer 2 — Workflows (skills/commands; short compositions)
- **inbox** = find → label → tidy (proposal only) → vault.daily
- **save email** = ids → pull-out → people → vault.email
- **follow-ups** = find(sent) → thread-status → vault.Follow-ups → draft(nudge)
- **meeting prep** = calendar → people → find(related threads) → summarize → vault.meeting
- **minutes email** = vault.meeting → summarize → draft (to attendees)
- **daily / weekly summary** = find + thread-status + calendar → summarize → vault.daily/weekly
- **schedule** = people → slots → create_event (needs a yes)
- **move a day's meetings** = calendar(day) → slots × n → update_event (needs a yes, one at a time)
- **reply on someone's behalf** = thread-status → draft(voice=boss) → Drafts in their mailbox
- **suggest rules** = label over 30 days → propose sender/subject rules (user creates them)
- **cleanup** = find(old/large/newsletters) → tidy (bulk) with preview

### Layer 3 — Commands and templates
`/soma:inbox`, `save`, `daily`, `followups`, `prep`, `weekly`, plus the main skill and note templates. No logic lives here.

### v0.0.1 cut
Parts: `ids`, `find`, `label`, `pull-out`, `tidy`, `people`, `vault`, `rules`. Workflows: inbox, save email, daily.
v0.0.2: `thread-status`, `summarize`, `draft` → follow-ups, meeting prep (needs `get_conversation` + `internet_message_id` in the connector).
v0.1+: scheduling and on-behalf mail (needs free/busy, delegate permissions, careful confirmation flow).
