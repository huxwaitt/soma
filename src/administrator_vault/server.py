"""FastMCP server ``vault``: the administrator plugin's note writer."""

from __future__ import annotations

import functools
import json
from typing import Annotated, Any, Callable, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from administrator_vault import history, priorities, store, timeblock, wiki, wiki_lint, wiki_migrate, wiki_search, workflows
from administrator_vault.frontmatter import FrontmatterError
from administrator_vault.notes import NoteError, SCHEMAS

INSTRUCTIONS = """\
This server writes the administrator plugin's notes into an Obsidian vault
(root = the ADMINISTRATOR_VAULT environment variable) in a fixed, checkable
way. Every path in and out is vault-relative with forward slashes, e.g.
"Administrator/Emails/2026-08-21 Q3 budget.md". Writes outside
"Administrator/" are refused. Existing body text is never edited: a second
write to the same note appends a "## Update <timestamp>" section.

Note types and identity: email (internet_message_id, else entry_id),
meeting (occurrence_key, else global_id), person (email, also aliases),
daily (date), weekly (week), chat (chat_id and date), time-block (week).
Every tool returns a JSON string.

The wiki (Administrator/Wiki/) holds pages the model keeps: person, org,
topic, decision, howto, me. A topic with an owner and a due date is a
project; a decision page (Wiki/Decisions/) records one choice and is added
to, never rewritten. vault_wiki_search answers a question with ranked facts
(brief=true stitches them into one text, pages=true finds the pages instead),
vault_wiki_read returns a page's lead and facts (with ids),
vault_wiki_write takes
op lists (add, update, supersede, confirm, retire, contest, lead, summary,
status, title, alias, related, role, open, done, reschedule, steps, due,
owner, org, outcome, milestone, risk, link, superseded_by, reversal). Open
items carry an owner and a due date, and Follow-ups.md is
written from them. vault_wiki_keep holds the rest: action=lint runs the checks
(and asks the wiki the questions the user keeps in Wiki/Questions.md),
action=merge folds one page into another (only on a yes), action=migrate
moves a 0.1.0 vault's People/ folder into the wiki (dry run first),
action=log and action=review read Log.md and the review list. What each op
does, what it refuses and how a page is laid out is the page contract,
wiki_schema.md (the plugin ships the same file as
skills/wiki/references/wiki.md); read it before writing ops.

Collecting: vault_collect keeps the "last collected" stamp per source
(teams, outlook, notes) and lists the notes modified since a time
(action=changed: records and the user's collect_folders, read only);
vault_save(kind="chat") writes a Teams chat as a day record under Teams/.
vault_load_history reads the months before that into the wiki: it hands out
one window of days at a time (Outlook inbox, then sent items, then Teams)
with the exact call to list it, remembers where it got to, and never moves a
collect stamp.

Priorities: vault_priorities_write gathers the material for a ranked
suggestion (action candidates, read only) and, after the user confirmed,
writes the numbered list into Priorities.md (action write).

# Parameters many tools share

created_by: the value written to the created_by frontmatter key; leave the
default unless the user asked for another.
today / now: today is the local date YYYY-MM-DD the answer is measured
against and defaults to the machine date; now is only for tests.
fields: which keys to return per entry; omit for all of them.
limit: how many entries to return at most.
since / until: ISO date or datetime bounds, read as local time.
max_chars: cut the text at that many characters; 0 = no cut.
path: vault-relative, forward slashes, under Administrator/.
A wiki page is named as a path, a stem or a wikilink:
Administrator/Wiki/Topics/q3-budget.md, Wiki/Topics/q3-budget or
[[Wiki/Topics/q3-budget]].
src: the source written on wiki facts: 'user' for things the user said in
chat, else a record id.
ops: the op list of the page contract, each {op, ...}; wiki_schema.md says
what every op does and what it refuses. Fact ids come from vault_wiki_read.
items: mail items as outlook_list_mails returned them (entry_id,
internet_message_id, from_address, from_name, subject, received, preview,
bulk, bulk_why; optional headers {list_unsubscribe, auto_submitted} and
message_class).
peak_hours: the hours the user works best, as ranges HH:MM-HH:MM (for
example ["09:00-12:00"]); focus blocks are placed there first.
week: an ISO week, e.g. 2026-W34. date: a local date YYYY-MM-DD.
type (note): email, meeting, person, daily, weekly, chat or time-block.

# What each tool returns

## vault_status
files includes Wiki/Questions.md, the user's list of questions the wiki
should answer.

## vault_init
Creates Administrator/ with its folders (Wiki/ with People, Orgs, Topics,
Howto and an empty Index.md / Log.md / Review.md), Follow-ups.md,
Preferences.md (from the given work hours and peak hours; peak_hours
defaults to ["09:00-12:00"]), Wiki/Questions.md (the user's questions and
the page that should answer each, with two examples shown above an empty
list) and the _views/*.base files. Existing files are kept unless
overwrite=true; Follow-ups.md, Rules.md, Priorities.md, Questions.md and the
Wiki files are always kept. overwrite rewrites Preferences.md and the
_views/*.base files only. work_start / work_end are HH:MM and
buffer_minutes the free minutes kept around existing meetings. backup in the
answer is a zip of Administrator/ under Administrator/_backup/<stamp>.zip,
made once when the vault already holds wiki pages this version has never
read back (_cache/ and _backup/ are left out), else null.

## vault_find
identity is a string, or an object with the identity keys: email
internet_message_id / entry_id; meeting occurrence_key / global_id; person
email; daily date; weekly week; chat chat_id + date, or 'chat_id|date';
time-block week. Without identity the notes of the type are listed instead,
newest first by its date key: email received, meeting start, person
last_contact, daily date, weekly start; since is a lower bound on that key,
limit caps how many come back.

## vault_write
mode 'create' names the file by the type's filename rule (' (2)' suffix on a
filename clash); 'append' adds '## Update <timestamp>' + body. On append
only status / last_contact / inbox_checked / mails_seen may change in the
frontmatter, and aliases are merged. frontmatter holds the keys and values
of the note; the required keys per type are validated. body is markdown
without frontmatter.

## vault_row
append: the '## <section>' heading and the header row are created when
missing; Follow-ups.md gets its fixed header, so header (the column names
to create the table with) is only needed when the section has no table yet.
row is one cell value per column. dedupe_key is written as a hidden
<!-- entry_id: KEY --> comment in the last cell, and a row already carrying
that key anywhere in the file returns {appended: false, reason:
'duplicate'}. key_label is the label used in that comment: 'entry_id'
(default) or 'occurrence_key'. section is the heading text without the
leading '## '.
move: the row carrying dedupe_key is cut from the table under from_section
and appended to the table under to_section (for Follow-ups Open -> Done).
set_last_cell replaces the last cell's text and keeps the hidden comment,
e.g. the Closed date.

## vault_read
{path, frontmatter, body, sections (heading texts)}.

## vault_rules
The rules of Administrator/Rules.md (created when missing) plus the built-in
ones: a List-Unsubscribe header -> fyi; auto-submitted, an 'Automatic reply'
subject and meeting responses -> noise; noreply senders -> fyi; a sender
with a person note of status fyi -> fyi. get: {path, labels, never_save,
fyi_senders}. match: {results: [{entry_id, label or null, never_save,
rule}], kept: [the items that are neither bulk nor never-save], dropped:
[{entry_id, why: 'bulk: ...' | 'rule: ...'}], counts: {bulk, never_save,
kept}}. An item's bulk field comes from outlook_list_mails.

## vault_inbox_prepare
{to_label: [the items not in any daily note of that week and not never_save,
with label/rule pre-filled where a rule matched, preview only for the rest],
already_seen: [entry_ids], never_save: [entry_ids], labelled_by_rule,
cache}.

## vault_write_daily
labels: one object per mail the model labelled, {entry_id, label
(act/reply/waiting/fyi/noise), reason (under 80 characters)}; mails a rule
labelled may be left out. events: outlook_list_events items for the day
(occurrence_key, subject, start, end, location, organizer, all_day), empty
for /administrator:inbox. watch_out: extra 'Watch out' bullets; clashes and
missing prep notes are added in code. since: the lower bound of the inbox
window, as used for outlook_list_mails. inbox_checked: the time of that
call (ISO), defaults to now. folder: the folder that was read, 'inbox'
unless the user named another. tokens_used: the token count of this turn,
stored in the frontmatter when given.
The note holds the inbox table sorted act/reply/waiting/fyi/noise with
hidden entry_id comments, To do, Waiting on (each row also becomes an open
item on the sender's page), Promised (the user's own open items due within
seven days, on the first run of the day), Calendar from events with
occurrence_key comments, and Watch out (the given bullets plus clashes and
missing prep notes). Returns {path, action (created/appended/unchanged),
rows_written, duplicates_skipped, followups_added, promised, calendar_rows,
unlabelled}.

## vault_save
kind=email. mail: the JSON from outlook_get_mail(trim_quoted=true) — entry_id,
internet_message_id, conversation_id, subject, from, from_address,
recipients[], received, attachments[], body / body_trimmed (body_trimmed is
used when present). summary: one line, 25 words or fewer. action_items:
lines like 'Send Q3 numbers by 2026-08-29 — owner: me', empty when the mail
asks for nothing. attachments_saved: paths from outlook_save_attachments
(absolute, or vault-relative under Administrator/Attachments/). msg_file:
the path from outlook_save_mail_as. status: todo / waiting / done / fyi —
the default is todo with action items, fyi without, waiting when the mail is
from self_addresses and has action items. self_addresses: the user's own
addresses from outlook_whoami, to tell 'from me' apart. company: only from
outlook_search_contacts, for a new person note.
An existing note gets an Update with the new summary. The sender's draft
person page under Wiki/People is created, or a Records line is added to it
(last_contact, aliases). When status is waiting an open item owned by the
counterpart (the first recipient of the user's own mail, else the sender)
is added to that person's page.

kind=chat. chat: the chat as teams_list_chats returned it — id, title, type,
members (names or {name, mri}), account. messages: that chat's messages in any
order, [{id, time (local ISO), sender, is_self, text}]. self_names: the
user's own display names, to tell 'from me' apart when is_self is missing.
The file is Teams/<date> <chat>.md, one record per chat per day (record_id =
chat_id|date), with '## Messages' holding one line per message, oldest
first, and hidden message ids. A second call the same day appends only the
messages whose ids are not in the file yet (under '## Update') and moves
messages / last forward. Senders that match a person page by name or alias
get a Records line and last_contact on it; senders without a page are listed
in unknown_people, and no page is made without an address. Returns {path,
action (created / appended / unchanged), date, record_id, added,
skipped_duplicates, messages, people: [{name, page}], unknown_people}; when
the messages span several days, a list with one such result per day.

kind=transcript. transcript_path is vault-relative, under
Administrator/Attachments/, and meeting_path names the meeting note. The
Copilot scaffolding is dropped, turns and speakers are counted, and
'### Transcript' is appended under '## Update' on the meeting note, with
speakers linked to attendee person notes and a collapsed callout up to 400
lines, else a link to the file. Returns {path, turns, speakers,
speaker_links, lines, appended_lines, linked, update_heading}.

## vault_prep_context
occurrence_key is global_id|start; global_id is taken from it when empty,
and subject (matched against wiki topic pages) from the existing note when
empty. attendees are SMTP strings or {name, address} objects, with the
user's own address left out. Returns {existing_note, existing_status,
previous_occurrence: {path, date, open_actions} or null, people: [{email,
name, path, last_contact, company, last_emails (up to 3 Records lines)}],
commitments: [{page, stem, type, title, owner_name, id, text, owner, due,
since, src, record, done} for the open items on the attendees' pages and the
items anywhere they own], followups_open: [one line per commitment someone
else owes, kept for one release], wiki: [{path, type, title, status, lead,
open[], facts[] (up to 8)} for the attendees' person pages and up to 3 topic
or decision pages matched on the subject, projects first, then decisions]}.

## vault_weekly_facts
Computed from the vault only: {week, start, end, open_from_inbox: [{date,
label, subject, from, entry_id, note, daily}] (act/reply rows of the week's
daily notes not ticked and with no email note of status done), waiting:
[{since, who, what, email, age_days} from the open items other people owe],
promised_overdue: [{due, what, page, id, days_over} from the user's own
items past their due date], meetings_held: [{path, subject, date,
unchecked_actions}], no_notes: [past meetings still 'upcoming'],
quiet_people: [{name, email, path, last_contact, days}] over 30 days, wiki:
{review_open, stale, uningested, candidates} counts for the '## Wiki'
section}.

## vault_wiki_search
query: the question in plain words; "quoted phrases", ids, dates and amounts
are looked up as written and /regex/ searches the raw text. kinds keeps only
those page kinds (person, org, topic, decision, howto, me). since keeps
facts dated on or after that ISO date. include_superseded also answers with
the old wording of replaced facts, always shown as superseded and always
ranked below. brief=true answers with {text, pages[], facts[], chars} — the
top pages with their lead, facts, open items and the dated facts of the
pages they link to, with such facts marked "(one source, unconfirmed since
<date>)"; max_chars caps that text. open_items=true answers with the
commitments [{page, stem, type, title, owner_name, id, text, owner, due,
since, src, record, done}], oldest since first, at most 200 of them (limit
is not used there); owner is 'me' for what the user owes or 'others' for
what other people owe the user, due_before keeps the items due before that
ISO date (that date itself is left out), include_done also answers with the
items already ticked, and page keeps to one page.
pages=true finds pages instead of facts: query is then free text (a subject
plus the first ~300 characters), people are sender / attendee addresses and
domains their sender domains, and the answer is {pages: [{path, line, score,
why}], candidates} — the topics over the 2-records-on-2-days threshold that
have no page yet.

## vault_wiki_read
sections: lead, facts, people, topics, contacts, open, records, related,
history, steps, notes; the default is lead + facts.

## vault_wiki_write
pages is one entry per page: {path, ops} for an existing page, or {new:
{type, title, aliases, lead, summary}, ops} for a new one; an empty ops list
still adds the Records line. record_path is the email, meeting or chat note
the ops come from: with it src and since default to the record's id and
date, without it to src ('user' unless another is given) and today. Per page
the answer holds the applied / refused ops with reasons, new ids and sizes;
with a record the tool also writes Records, History, the record's wiki:
link, Log.md and Index.md, and reports the topic candidate for the record's
subject (candidate.suggest_due says a record named a day, so propose an
owner and a due date). The answer is {record (null without one), pages,
candidate} and carries confirmed_decisions: [page stems] when the user
ticked an 'unconfirmed decision' line in Review.md. Every page is read back
after the write: one that does not come back as it was written keeps its
previous text and answers written: false with reason 'verify-failed'.
A new: spec with no ops is how a page is created on its own. type: person,
org, topic, decision, howto or me. title: a noun phrase, 6 words or fewer,
no dates. lead: 2-4 sentences, 80 words or fewer. summary: one line, 160
characters or fewer, used as the Index.md line. Without a record, new: also
takes facts: [{text, since, src}] written as add ops. Its other keys are the
type-specific frontmatter keys — email (person), domains (org), owner / org
/ due (topic), decided (date, required) and by (person page links, required)
for a decision; code-owned keys are refused. The page is created under
Wiki/<Type>/ with a slug filename, and refused with the matching index line
when a page with this title, alias or address exists: {created: false,
reason: 'exists', path, match}. A new decision page is written with status
current and flags [unconfirmed-decision] and gets one Review line
('unconfirmed decision: … — confirm or drop'); confirming it clears the
flag, and ticking that line in Obsidian does the same on the next lint or
write.

## vault_wiki_keep
action=log: the newest matching lines of Wiki/Log.md, {path, total, lines};
page keeps to one page's lines (stem or link).

action=review, review_action list or resolve.
item: the item's number in the Open list, or a part of its text.
resolution_ops: ops applied to the page the item names (src user), e.g. a
supersede the user decided on. list: {open: [{n, text}], done}. resolve
moves the item to Done with today's date and clears the page's contradiction
and unconfirmed-decision flags when no other open item names it.

action=lint. The checks are: index vs files, dangling links, orphans, frontmatter,
sections, oversized, stale, due in the past, open items done, duplicate
pages, records never ingested, topic candidates, History / Log rotation,
pages to ask the model about, unconfirmed facts, 19 overdue (the user's own
open items past their due date), 20 questions (how many of the questions in
Wiki/Questions.md the wiki answers) and 21 unanswered (the questions the
wiki could not answer, each asked more than once in the last 30 days).
Decision pages are left out of the stale check. Flags (orphan, stale,
oversized, possible-duplicate) and Review lines are written in both modes;
fix=true also applies the safe fixes: regenerate the index, recompute
code-owned keys, fix section order, turn dangling links in code-owned
sections into plain text, tick open items whose record action is done, set
stale topics to dormant, rotate History / Log.
Returns {date, fix, pages, counts, checks: {0..21}, flagged, review_added,
written, cache}, plus confirmed_decisions: [page stems] when the user ticked
an 'unconfirmed decision' line in Review.md (the one line a tick alone
settles). checks['0'] is the pass that reads back what the user changed by
hand in Obsidian; it runs at the start of every wiki tool that writes, and
when it took something over the answer carries adopted: [{page, changes}] —
pass that on in one line. A tool that only reads writes no page: it answers
hand_edits: n, how many files differ from what the code last wrote, and the
next writing call is what takes them over. checks['14'].ask_model lists the pages touched since the last
lint: read their facts and report pairs that cannot both be true with a
contest op. checks['20'] is {name, asked, found, misses: [{question,
expected, top}], unknown} and checks['21'] {name, count, days, items:
[{query, times, last}]} — those lists, and every other checks[n].items, come
back only with items=true; without it each check keeps its name, its count
and its flags, which is what the report needs, and the cache file always
holds the full report. Ask for items on the checks you are about to show the
user. Every run appends one Log.md line with all the counts ("questions
17/20, unanswered 3"), so action=log shows whether the wiki is getting
better.

action=merge. keep is the page that stays, drop the one folded into it. Only after the
user said the two pages are the same thing. Facts of drop are added to keep
with their since / src (same text: confirm), aliases / records / links are
merged, drop becomes a 3-line redirect page (type redirect) so links keep
resolving, other pages' links follow, and keep's History records the merge.
Returns {keep, drop, redirect, facts_added, facts_confirmed, facts_refused,
relinked, review_closed, sizes}.

action=migrate. dry_run=true returns the plan and writes nothing; false does it with a
backup. Three parts. people: Administrator/People/*.md move to Wiki/People/
as person pages following the page contract (old Emails / Meetings lines
become Records, a 'Voice with this person:' block and other user text go
under Notes), [[People/...]] links are rewritten to [[Wiki/People/...]]
everywhere including frontmatter, and the old folder goes when it is empty.
followups: the Open rows of Follow-ups.md become open items on the person
page the Who names (an unknown name lands on Wiki/Me.md with the name in the
text) and the Done rows become History lines, after which the file is
written from the pages. views: the .base views are brought up to date. A
copy of what is replaced is kept under Administrator/_backup/<stamp>/.
Returns the plan ({needed, parts: {people, followups, views}, people, links,
views, followups: {open, done, count, backup}, left, backup}) plus, after a
real run, {moved, skipped, links_rewritten, followups_moved: {open, done},
old_folder_removed, old_folder_left}.

## vault_collect
source (advance): teams, outlook or notes; omit for all three. at (advance):
the new stamp as local ISO, defaults to now. payload (tokens): {command:
'collect-information' | 'load-history', predicted_in, predicted_out,
actual_in, actual_out} — the estimate the skill showed and the counts the
host reported; the four counts must be numbers, the predicted ones 1 or
more, and anything else is an error. The stamps live in
Wiki/_cache/collect.json. read: {stamps, age_hours, ask (a stamp is missing
or older than 24 h: ask the user how far back to collect), default_since
(the oldest stamp, else today 00:00), last_collected ('Thu 21 Aug 18:10', or
'never'), tokens: {<command>: {runs, ratio_in, ratio_out}} for each command
with runs on file — multiply the estimate by the ratio when runs is 3 or
more}. advance: sets the stamp(s) to at and never moves one back (refused:
[{source, reason: 'older-than-stamp', stamp, at}]); returns {stamps,
advanced, refused}. tokens: appends the run in payload to
Wiki/_cache/tokens.json (the last 20 per command) and returns {command,
runs, ratio_in, ratio_out (the median actual/predicted over those runs, null
until one run has both numbers), last}.

changed: the markdown notes modified after since (required), oldest first,
with an excerpt each. folders: vault-relative folders to read instead of the
default set
(Administrator/Meetings, Emails, Daily, Weekly plus the collect_folders of
Preferences.md). Returns {since, count, total, capped, folders, skipped,
missing, notes: [{path, type, modified, ingested (a wiki key is present),
excerpt (the last '## Update' section when there is one, else the body),
from_update, truncated}]}, oldest first. Wiki/, Attachments/, _views/,
_backup/ and dot-folders are never read; folders outside Administrator/ are
only read, never written; paths outside the vault are refused.

## vault_load_history
since (plan): the date to start from, defaults to 90 days before today,
00:00. batch (plan): how many records one batch works on. reset (plan):
drop the running pass and start over. payload (done): {saved: [{id, path,
received}], skipped_ids: [ids left out], reached: the received time of the
last record worked (ISO), exhausted: true when nothing in the window was
left over, pages: [wiki pages touched], calls: how many tool calls the batch
took, listed: how many records the window listed before the cut (drives the
window size and the listed-vs-saved gap; defaults to saved + skipped), auto:
true when the user said "yes to all" (run the rest without asking after each
batch) and false when they took it back, cap: the tokens the whole pass may
spend or null for none, tokens: {in, out} this batch cost}.
status: the state ({started: false} before the first plan) with the collect
stamps, the days left per source and how many records each source listed
against how many were saved, so a gap shows. plan: fixes the start date, the
batch size and, per source, the day the pass stops at (that source's collect
stamp, else now) — refused while a pass is running unless reset=true;
returns {planned, since, until_max, days, left_days, batches_estimate,
note}. next: the window to list — {batch_no, source, since, until, expected,
skip_ids (ids of that window already seen), list_with (the exact
outlook_list_mails / teams_list_chats call), reissued}; turn the list oldest
first, drop skip_ids and automated mail, work on the first 'expected'
records; while a batch is open the same window is handed out again instead
of a second one. next, done, plan and status all answer auto, cap and cost
({in, out, total} so far), so a run that said "yes to all" knows when its
next batch would pass the cap and has to ask again. done: takes payload and
answers {batch, saved, skipped, listed, place, window_days, source_done,
all_done, totals, next_hint, auto, cap, cost, note}
— the ids are recorded as seen, the place moves (to until when the window
was exhausted, else to reached), the window is halved or doubled to fit the
batch size (1 to 30 days), and when every source is finished the answer
holds a summary that ends with 'Run /administrator:lint.'. The state is
Wiki/_cache/history.json and is written after plan and after every done, so
a crash costs at most one window. The collect stamps are only read, never
moved.

## vault_time_block
action=plan. events: outlook_list_events items for the week — subject, start, end,
all_day, attendee_count, is_meeting, occurrence_key, entry_id, busy_status.
today: days before it are not planned. now: local time HH:MM from
outlook_whoami.local_time; it only matters on today, where nothing is placed
before it, and omitting it plans today from work_start. peak_hours, when
given, replaces the file's peak hours for this plan only and Preferences.md
is not changed.
The plan reads Preferences.md (peak_hours, focus_block_minutes,
focus_blocks_per_day, admin_blocks_per_day, admin_block_minutes,
slack_share, work hours, buffer_minutes, no_meeting_blocks) and the
priorities (the numbered lines of Priorities.md, then the user's own open
items due by the end of the week, then active wiki topics due within 30 days
or with open items). What has a due date is placed first, in the latest free
new focus block before that day. Bookable minutes per day = (1 -
slack_share) * work minutes - meeting minutes; a day with none left is in
skipped_days with the reason. Existing [Focus] / [Admin] appointments are
kept (existing: true) and never duplicated.
Returns {week, priorities: [{rank, name, page, due}], days: [{date, day,
work_minutes, meeting_minutes, bookable_minutes, booked_minutes,
slack_minutes, blocks: [{start, end, minutes, kind, subject, priority, page,
existing}]}], totals: {focus_minutes, admin_minutes, new_blocks,
existing_blocks, slack_share_kept}, deadlines: [{name, due, page,
block_date}], unplaced, skipped_days: [{date, reason}], preferences_used,
missing_keys}.

action=write. blocks: the plan's blocks (start, end, kind, subject, priority) with the
create results merged in — occurrence_key and entry_id from
outlook_create_event; existing blocks may be passed too. The note holds a
'## Plan' table (Day | Start | End | Kind | Subject | Priority, with a
hidden occurrence_key per row), an empty '## Held' table (Day | Block |
Result | Note, which /administrator:collect-information fills with
vault_row, dedupe_key = occurrence_key, key_label = occurrence_key)
and '## Notes'. A re-plan of the same week appends the new table under
'## Update'. Returns {path, action, week, blocks, planned}.

action=audit. events: outlook_list_events items for that week — subject, start, end,
all_day, attendee_count, is_meeting, occurrence_key, busy_status. Hours per
kind: meeting = attendees or is_meeting, focus = '[Focus]', admin =
'[Admin]', other, unplanned = work hours not booked; all-day events are
skipped, and the hours are set against the work hours of Preferences.md. The
Held rows of Time-blocks/<week>.md are applied: skipped blocks count as
unplanned, moved ones keep their minutes, rows without an answer are
unanswered. Returns {week, hours, work_hours, shares, per_priority: [{name,
planned_hours, held_hours}], blocks: {planned, held, moved, skipped,
unanswered}, lines} — lines are ready for the weekly note's '## Time'
section.

## vault_priorities_write
lines (write): the confirmed priorities in rank order, 1 to 7 entries, each
up to 120 characters, a topic page link ([[Wiki/Topics/acme-contract]]) or
plain words; no headings or comments. note (write): one optional line on how
the list was chosen, kept as a comment under it. candidates (read only):
{topics: [{title, page, status, due, open_items, verified, summary}] (active
wiki topics, soonest due first then most open items, at most 10), followups:
[{since, who, what, age_days}] (open Follow-ups rows, oldest first, at most
5), weekly_open: [{subject, label, date}] (open act / reply rows of the
latest weekly note's week, at most 5), current: [the numbered lines now in
Priorities.md]}. write (only after the user confirmed the list): replaces
the numbered list under '## Priorities' (the placeholder or the previous
list) with lines plus a '<!-- suggested by administrator, confirmed <date>
-->' comment and the note as a second comment; frontmatter, the text above
the heading and every other section are kept byte for byte; a missing file
is created first. Returns {path, action: 'written', lines, previous}.
"""

# Module-level aliases: with ``from __future__ import annotations`` every hint
# is a string resolved against module globals when FastMCP builds the schema.
NoteType = Annotated[str, Field(description="Note type.")]
Identity = Annotated[Any, Field(description="The note's identity keys; omit to list the type.")]
VaultPath = Annotated[str, Field(min_length=1)]
Frontmatter = Annotated[dict[str, Any], Field(description="Frontmatter keys and values.")]
Body = Annotated[str, Field(description="Markdown body, no frontmatter.")]
WriteMode = Annotated[str, Field(description="create, append or upsert.")]
Section = Annotated[str, Field(min_length=1, description="Heading text, no '## '.")]
Row = Annotated[list[str], Field(min_length=1, description="One cell per column.")]
DedupeKey = Annotated[Optional[str], Field(description="Key of the row's hidden comment.")]
Header = Annotated[Optional[list[str]], Field(description="Column names for a new table.")]
KeyLabel = Annotated[str, Field(description="entry_id or occurrence_key.")]
SetLastCell = Annotated[Optional[str], Field(description="New text for the last cell.")]
Since = Annotated[Optional[str], Field(description="Lower bound on the type's date key.")]
Limit = Annotated[int, Field(ge=1, le=2000)]
WorkStart = Annotated[str, Field(description="Work day start, HH:MM.")]
WorkEnd = Annotated[str, Field(description="Work day end, HH:MM.")]
BufferMinutes = Annotated[int, Field(ge=0, le=120, description="Minutes kept around meetings.")]
PeakHours = Annotated[Optional[list[str]], Field(description="Best hours, HH:MM-HH:MM.")]
Overwrite = Annotated[bool, Field(description="Rewrite Preferences.md and the views.")]
CreatedBy = str
Fields = Optional[list[str]]
Items = Annotated[
    list[dict[str, Any]],
    Field(description="Mail items from outlook_list_mails."),
]
DateStr = Annotated[str, Field(description="Local date YYYY-MM-DD.")]
Labels = Annotated[
    list[dict[str, Any]],
    Field(description="One {entry_id, label, reason} per mail labelled."),
]
Events = Annotated[
    Optional[list[dict[str, Any]]],
    Field(description="outlook_list_events items for the day."),
]
WatchOut = Annotated[Optional[list[str]], Field(description="Extra 'Watch out' bullets.")]
Mail = Annotated[dict[str, Any], Field(description="The JSON from outlook_get_mail.")]
Attendees = Annotated[Optional[list[Any]], Field(description="SMTP strings or {name, address}.")]
WikiPage = Annotated[str, Field(min_length=1, description="Wiki page: path, stem or wikilink.")]
WikiOps = Annotated[
    list[dict[str, Any]],
    Field(description="Ops from the page contract, each {op, ...}."),
]
WikiSrc = Annotated[str, Field(description="'user', else a record id.")]
RowAction = Annotated[str, Field(description="append or move.")]
SaveKind = Annotated[str, Field(description="email, chat or transcript.")]
KeepAction = Annotated[str, Field(description="log, review, lint, merge or migrate.")]
CollectAction = Annotated[str, Field(description="read, advance, tokens or changed.")]
BlockAction = Annotated[str, Field(description="plan, write or audit.")]


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _guard(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Turn vault / note errors into RuntimeError so the host marks isError."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (store.VaultError, NoteError, FrontmatterError) as exc:
            raise RuntimeError(str(exc)) from exc

    return wrapper


# Keywords whose value is a map of *names* to schemas: their keys are
# parameter names, never schema metadata, so they are recursed into but never
# filtered. A page spec really does hold a key called "title".
_SCHEMA_MAPS = ("properties", "$defs", "definitions", "patternProperties")
_SCHEMA_LISTS = ("anyOf", "oneOf", "allOf", "prefixItems")
_SCHEMA_VALUES = ("items", "additionalProperties", "not", "contains")


def _drop_titles(schema: Any) -> Any:
    """Strip pydantic's generated "title" metadata from a parameter schema.

    Pydantic titles a field by title-casing its own name ("max_chars" ->
    "Max Chars") and the argument model after the tool, so every one of them
    repeats a name the schema already carries. Dropping them says nothing
    less. Validation reads the argument model, not this dict, so nothing
    about what a tool accepts changes.
    """
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "title":
            continue
        if key in _SCHEMA_MAPS and isinstance(value, dict):
            out[key] = {name: _drop_titles(sub) for name, sub in value.items()}
        elif key in _SCHEMA_LISTS and isinstance(value, list):
            out[key] = [_drop_titles(sub) for sub in value]
        elif key in _SCHEMA_VALUES and isinstance(value, dict):
            out[key] = _drop_titles(value)
        else:
            out[key] = value
    return out


def _trim_schemas(mcp: FastMCP) -> None:
    for tool in mcp._tool_manager.list_tools():
        tool.parameters = _drop_titles(tool.parameters)


def _wiki_write_pages(pages: Any, src: str, created_by: str) -> dict[str, Any]:
    """vault_wiki_write without a record: create and apply, page by page.

    The answer is the shape a write with a record has, so a caller reads one
    result either way; ``record`` and ``candidate`` are null because there is
    no record to name.
    """
    results: list[dict[str, Any]] = []
    adopted: list[Any] = []
    for spec in pages or []:
        if not isinstance(spec, dict):
            results.append({"written": False, "refused": [{"reason": "bad-page-spec"}]})
            continue
        ops = spec.get("ops") or []
        new = spec.get("new")
        if isinstance(new, dict):
            fixed = ("type", "title", "aliases", "lead", "summary", "facts", "extra")
            extra = {k: v for k, v in new.items() if k not in fixed}
            extra.update(new.get("extra") or {})
            res = wiki.create(
                new.get("type") or "", new.get("title") or "", new.get("aliases"),
                new.get("lead") or "", new.get("summary") or "", new.get("facts"),
                src, created_by, extra or None,
            )
            adopted += res.pop("adopted", [])
            if res.get("created") and ops:
                more = wiki.apply(res["path"], ops, created_by, src)
                adopted += more.pop("adopted", [])
                res.update(
                    applied=res["applied"] + more["applied"],
                    refused=res["refused"] + more["refused"],
                    written=more["written"],
                    sizes=more["sizes"],
                )
            elif res.get("created"):
                res["written"] = True
            results.append(res)
            continue
        res = wiki.apply(spec.get("path") or "", ops, created_by, src)
        adopted += res.pop("adopted", [])
        results.append(res)
    out: dict[str, Any] = {"record": None, "pages": results, "candidate": None}
    if adopted:
        out["adopted"] = adopted
    return out


def build_server() -> FastMCP:
    mcp = FastMCP("vault", instructions=INSTRUCTIONS)
    register(mcp)
    return mcp


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="vault_status",
        annotations={"title": "Vault status", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_status() -> str:
        """Report where the vault is and which Administrator/ folders and files exist. Never fails on a missing vault; read the flags."""
        return _json(store.status())

    @mcp.tool(
        name="vault_init",
        annotations={"title": "Create the Administrator/ tree", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_init(
        work_start: WorkStart = "09:00",
        work_end: WorkEnd = "17:00",
        buffer_minutes: BufferMinutes = 15,
        overwrite: Overwrite = False,
        created_by: CreatedBy = "administrator-vault",
        peak_hours: PeakHours = None,
    ) -> str:
        """Create the Administrator/ tree: its folders, Follow-ups.md, Preferences.md, Wiki/Questions.md and the _views/*.base files. Returns what was created and what was kept."""
        return _json(store.init(work_start, work_end, buffer_minutes, overwrite, created_by, peak_hours))

    @mcp.tool(
        name="vault_find",
        annotations={"title": "Find or list notes", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_find(
        type: NoteType,
        identity: Identity = None,
        fields: Fields = None,
        limit: Limit = 200,
        since: Since = None,
    ) -> str:
        """Find the note of a type with this identity by reading frontmatter, not filenames: {found, path, frontmatter, matches}; a global_id-only meeting identity returns the newest occurrence first. Without identity it lists the type's notes instead, newest first by its date key."""
        if not identity:
            return _json(store.list_notes(type, since, limit, fields))
        return _json(store.find(type, identity, fields))

    @mcp.tool(
        name="vault_write",
        annotations={"title": "Create or append a note", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    @_guard
    def vault_write(type: NoteType, frontmatter: Frontmatter, body: Body, mode: WriteMode = "create") -> str:
        """Write a note: create a new file, append '## Update <timestamp>' + body to the note with this identity, or upsert (create if missing, else append). Existing body text is never edited; returns {path, action, identity, ...}."""
        return _json(store.write(type, frontmatter, body, mode))

    @mcp.tool(
        name="vault_row",
        annotations={"title": "Append or move a table row", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_row(
        action: RowAction,
        path: VaultPath,
        section: Optional[Section] = None,
        row: Optional[Row] = None,
        dedupe_key: DedupeKey = None,
        header: Header = None,
        key_label: KeyLabel = "entry_id",
        from_section: Optional[Section] = None,
        to_section: Optional[Section] = None,
        set_last_cell: SetLastCell = None,
    ) -> str:
        """Append a markdown table row under a '## <section>' heading, creating the heading and the header row when missing (append; dedupe_key leaves out a row already in the file), or move the row carrying dedupe_key between two sections' tables, for Follow-ups Open -> Done. Returns {appended, ...} / {moved, ...}."""
        if action == "append":
            if not section or row is None:
                raise RuntimeError("append needs section and row.")
            return _json(store.append_row(path, section, row, dedupe_key, header, key_label))
        if action == "move":
            if not from_section or not to_section or not dedupe_key:
                raise RuntimeError("move needs from_section, to_section and dedupe_key.")
            return _json(store.move_row(path, from_section, to_section, dedupe_key, set_last_cell))
        raise RuntimeError("action must be 'append' or 'move'.")

    @mcp.tool(
        name="vault_read",
        annotations={"title": "Read a note", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_read(path: VaultPath) -> str:
        """Read one note under Administrator/: {path, frontmatter, body, sections (heading texts)}."""
        return _json(store.read(path))

    # ---------------------------------------------------------------- v0.5 helpers

    @mcp.tool(
        name="vault_rules",
        annotations={"title": "Read or apply Administrator/Rules.md", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_rules(
        action: Annotated[str, Field(description="get or match.")] = "get",
        items: Optional[Items] = None,
    ) -> str:
        """Read the labelling rules of Administrator/Rules.md plus the built-in ones, or apply them to mail items. get returns the parsed rules; match returns one result per item plus kept (the items left to read), dropped ({entry_id, why}) for bulk mail and never-save rules, and counts."""
        if action == "get":
            return _json(workflows.rules_get())
        if action == "match":
            return _json(workflows.rules_match(items or []))
        raise RuntimeError("action must be 'get' or 'match'.")

    @mcp.tool(
        name="vault_inbox_prepare",
        annotations={"title": "Prepare an inbox list for labelling", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_inbox_prepare(items: Items, date: DateStr) -> str:
        """Take outlook_list_mails items and return only what the model still has to label, with the label pre-filled where a rule matched. Returns {to_label, already_seen, never_save, labelled_by_rule, cache}; the list is cached so vault_write_daily can be called without items."""
        return _json(workflows.inbox_prepare(items, date))

    @mcp.tool(
        name="vault_write_daily",
        annotations={"title": "Render and write the daily note", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_write_daily(
        date: DateStr,
        labels: Labels,
        items: Optional[Items] = None,
        events: Events = None,
        watch_out: WatchOut = None,
        since: Annotated[str, Field(description="Lower bound of the inbox window.")] = "",
        inbox_checked: Annotated[str, Field(description="Time of the mail call; now by default.")] = "",
        tokens_used: Annotated[Optional[int], Field(description="Token count of this turn.")] = None,
        folder: Annotated[str, Field(description="Folder that was read.")] = "inbox",
        created_by: CreatedBy = workflows.CREATED_BY,
    ) -> str:
        """Render Daily/YYYY-MM-DD.md from labels + items (items default to the vault_inbox_prepare cache): the inbox table sorted act/reply/waiting/fyi/noise, To do, Waiting on, Promised, Calendar and Watch out; a second run the same day appends only the new rows. Returns {path, action, rows_written, duplicates_skipped, followups_added, promised, calendar_rows, unlabelled}."""
        return _json(workflows.write_daily(date, labels, items, events, watch_out, since, inbox_checked, tokens_used, folder, created_by))

    @mcp.tool(
        name="vault_save",
        annotations={"title": "Save an email, chat or transcript", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    @_guard
    def vault_save(
        kind: SaveKind,
        mail: Optional[Mail] = None,
        summary: Annotated[str, Field(description="Email: one line, 25 words or fewer.")] = "",
        action_items: Annotated[Optional[list[str]], Field(description="Email: action item lines.")] = None,
        attachments_saved: Annotated[Optional[list[str]], Field(description="Email: paths from outlook_save_attachments.")] = None,
        msg_file: Annotated[Optional[str], Field(description="Email: path from outlook_save_mail_as.")] = None,
        status: Annotated[Optional[str], Field(description="Email: todo, waiting, done or fyi.")] = None,
        self_addresses: Annotated[Optional[list[str]], Field(description="Email: the user's own addresses.")] = None,
        company: Annotated[Optional[str], Field(description="Email: company for a new person note.")] = None,
        chat: Annotated[Optional[dict[str, Any]], Field(description="Chat: the chat from teams_list_chats.")] = None,
        messages: Annotated[Optional[list[dict[str, Any]]], Field(description="Chat: that chat's messages, any order.")] = None,
        self_names: Annotated[Optional[list[str]], Field(description="Chat: the user's own display names.")] = None,
        meeting_path: Annotated[Optional[str], Field(description="Transcript: the meeting note.")] = None,
        transcript_path: Annotated[Optional[str], Field(description="Transcript: its vault-relative path.")] = None,
        created_by: CreatedBy = workflows.CREATED_BY,
    ) -> str:
        """Write one record. email: build the note from outlook_get_mail JSON, upsert it, then create the sender's person page under Wiki/People or add a Records line to it; returns {path, action, status, person_path, person_action, followup_added}. chat: write or extend Teams/<date> <chat>.md, one record per chat per day, appending only the messages not in the file yet. transcript: drop the Copilot scaffolding and append a '### Transcript' section under '## Update' on the meeting note."""
        if kind == "email":
            if not mail:
                raise RuntimeError("kind 'email' needs mail.")
            return _json(workflows.save_email(mail, summary, action_items, attachments_saved, msg_file, status, self_addresses, company, created_by))
        if kind == "chat":
            if not chat:
                raise RuntimeError("kind 'chat' needs chat.")
            return _json(workflows.save_chat(chat, messages or [], self_names, created_by))
        if kind == "transcript":
            if not meeting_path or not transcript_path:
                raise RuntimeError("kind 'transcript' needs meeting_path and transcript_path.")
            return _json(workflows.attach_transcript(meeting_path, transcript_path, created_by))
        raise RuntimeError("kind must be 'email', 'chat' or 'transcript'.")

    @mcp.tool(
        name="vault_prep_context",
        annotations={"title": "Vault context for a meeting prep", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_prep_context(
        occurrence_key: Annotated[str, Field(description="The event's occurrence_key.")],
        global_id: Annotated[str, Field(description="The event's global_id.")] = "",
        attendees: Attendees = None,
        subject: Annotated[str, Field(description="The event's subject.")] = "",
    ) -> str:
        """Everything the vault knows for a meeting prep in one call: the existing note, the previous occurrence, the attendees' person pages, the open commitments on and owned by them, and up to 3 topic or decision pages matched on the subject. Returns {existing_note, existing_status, previous_occurrence, people, commitments, followups_open, wiki}."""
        return _json(workflows.prep_context(occurrence_key, global_id, attendees, subject))

    @mcp.tool(
        name="vault_weekly_facts",
        annotations={"title": "Facts for the weekly review", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_weekly_facts(
        week: Annotated[str, Field(description="ISO week, e.g. 2026-W34.")],
        today: Annotated[Optional[str], Field(description="Local date.")] = None,
    ) -> str:
        """The facts for a weekly review, computed from the vault only. Returns {week, start, end, open_from_inbox, waiting, promised_overdue, meetings_held, no_notes, quiet_people, wiki}."""
        return _json(workflows.weekly_facts(week, today))

    # ---------------------------------------------------------------- wiki (0.2.0)

    @mcp.tool(
        name="vault_wiki_search",
        annotations={"title": "Search the wiki for facts or pages", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_wiki_search(
        query: Annotated[str, Field(description="The question in plain words.")],
        kinds: Annotated[Optional[list[str]], Field(description="Keep only these page kinds.")] = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
        since: Annotated[Optional[str], Field(description="Only facts dated on or after it.")] = None,
        include_superseded: Annotated[bool, Field(description="Also answer with replaced wording.")] = False,
        brief: Annotated[bool, Field(description="Answer with one stitched text.")] = False,
        max_chars: Annotated[int, Field(ge=200, le=8000)] = 1500,
        open_items: Annotated[bool, Field(description="Answer with commitments, not facts.")] = False,
        owner: Annotated[Optional[str], Field(description="Open items: 'me' or 'others'.")] = None,
        due_before: Annotated[Optional[str], Field(description="Open items: due before this date.")] = None,
        page: Annotated[Optional[str], Field(description="Keep to this one page.")] = None,
        include_done: Annotated[bool, Field(description="Open items: also the ticked ones.")] = False,
        pages: Annotated[bool, Field(description="Answer with matching pages, not facts.")] = False,
        people: Annotated[Optional[list[str]], Field(description="Pages: sender / attendee addresses.")] = None,
        domains: Annotated[Optional[list[str]], Field(description="Pages: sender domains.")] = None,
    ) -> str:
        """Ranked facts read from the wiki pages themselves, best first, at most three per page: [{page, kind, title, fact_id, text, since, src, score, why, superseded, streams, confirmed}]. streams is how many kinds of source back the fact and confirmed how many days ago it was last confirmed: streams 1 with confirmed over 180 means one source and nothing since, so say it with a hedge or ask. brief=true answers with one stitched text instead, open_items=true with the commitments. Notes are never read; nothing is written but the query log (a cache file). hand_edits: n = pages changed by hand, taken over by the next writing call. pages=true answers instead with the pages whose title, aliases, email or domains match query, people and domains, ranked alias hit > address > word overlap > domain, plus the topic candidates with no page yet."""
        if pages:
            return _json(wiki.match(query, people, domains, limit))
        return _json(wiki_search.search_tool(query, kinds, limit, since, include_superseded, brief, max_chars, open_items, owner, due_before, page, include_done))

    @mcp.tool(
        name="vault_wiki_read",
        annotations={"title": "Read a wiki page", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_wiki_read(
        path: WikiPage,
        sections: Annotated[Optional[list[str]], Field(description="Which parts; lead + facts by default.")] = None,
        max_chars: Annotated[int, Field(ge=0, le=20000)] = 2000,
    ) -> str:
        """Frontmatter plus the requested parts of one page; facts come as [{id, text, since, src}] so ops can name them by id."""
        return _json(wiki.read(path, sections, max_chars))

    @mcp.tool(
        name="vault_wiki_write",
        annotations={"title": "Write to wiki pages", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    @_guard
    def vault_wiki_write(
        pages: Annotated[list[dict[str, Any]], Field(description="One {path, ops} or {new, ops} per page.")],
        record_path: Annotated[Optional[str], Field(description="The record note the ops come from.")] = None,
        src: WikiSrc = "user",
        created_by: CreatedBy = wiki.CREATED_BY,
    ) -> str:
        """Apply op lists to wiki pages. With record_path the record is the source (src and since default to its id and date) and Records, History, the record's wiki: link, Log.md and Index.md are written; without it the ops are the user's own (src 'user', since today). Each entry of pages is {path, ops} for a page that exists or {new: {...}, ops} for one to create; a new: spec with no ops just creates the page. Answers {record (null without one), pages, candidate}: per page the applied and refused ops, their reasons, the new ids and the sizes. Every page is read back after the write: one that does not come back as written keeps its previous text and answers written: false."""
        if record_path:
            return _json(wiki.ingest(record_path, pages, created_by))
        return _json(_wiki_write_pages(pages, src, created_by))

    @mcp.tool(
        name="vault_wiki_keep",
        annotations={"title": "Keep the wiki in shape", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    )
    @_guard
    def vault_wiki_keep(
        action: KeepAction,
        since: Annotated[Optional[str], Field(description="log: ISO date or datetime lower bound.")] = None,
        page: Annotated[Optional[str], Field(description="log: only lines of this page.")] = None,
        limit: Annotated[int, Field(ge=1, le=500)] = 50,
        review_action: Annotated[str, Field(description="review: list or resolve.")] = "list",
        item: Annotated[Optional[str], Field(description="review: the item's number or text.")] = None,
        resolution_ops: Annotated[Optional[list[dict[str, Any]]], Field(description="review: ops for the item's page.")] = None,
        fix: Annotated[bool, Field(description="lint: also apply the safe fixes.")] = False,
        items: Annotated[bool, Field(description="lint: add the per-check lists to the answer.")] = False,
        keep: Annotated[Optional[str], Field(description="merge: the page that stays.")] = None,
        drop: Annotated[Optional[str], Field(description="merge: the page folded into keep.")] = None,
        dry_run: Annotated[bool, Field(description="migrate: return the plan and write nothing.")] = True,
        created_by: CreatedBy = wiki.CREATED_BY,
    ) -> str:
        """Keep the wiki in shape. log: the newest matching lines of Wiki/Log.md. review: list the items of Wiki/Review.md, or resolve one (review_action) by applying resolution_ops to the page it names and moving it to Done. lint: run the checks 0 to 21, writing the flags and the Review lines, with fix=true also applying the safe fixes. merge: fold one page into another, only after the user said the two are the same thing; drop becomes a redirect. migrate: bring a 0.1.0 vault up to date, dry_run first. Each action answers as it did before."""
        if action == "log":
            return _json(wiki.log(since, page, limit))
        if action == "review":
            if review_action not in ("list", "resolve"):
                raise RuntimeError("review_action must be 'list' or 'resolve'.")
            return _json(wiki.review(review_action, item, resolution_ops, created_by))
        if action == "lint":
            return _json(wiki_lint.lint(fix, items, created_by))
        if action == "merge":
            if not keep or not drop:
                raise RuntimeError("merge needs keep and drop.")
            return _json(wiki_lint.merge(keep, drop, created_by))
        if action == "migrate":
            return _json(wiki_migrate.migrate(dry_run, created_by))
        raise RuntimeError("action must be 'log', 'review', 'lint', 'merge' or 'migrate'.")

    # ---------------------------------------------------------------- collect (0.3.0)

    @mcp.tool(
        name="vault_collect",
        annotations={"title": "Collect stamps, token runs and changed notes", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_collect(
        action: CollectAction = "read",
        source: Annotated[Optional[str], Field(description="advance: teams, outlook or notes.")] = None,
        at: Annotated[Optional[str], Field(description="advance: the new stamp; now by default.")] = None,
        now: Annotated[Optional[str], Field(description="Only for tests.")] = None,
        payload: Annotated[Optional[dict], Field(description="tokens: one run's predicted and actual counts.")] = None,
        since: Annotated[Optional[str], Field(description="changed: notes modified after it are returned.")] = None,
        folders: Annotated[Optional[list[str]], Field(description="changed: folders to read instead of the default set.")] = None,
        max_chars: Annotated[int, Field(ge=0, le=20000)] = 1200,
        limit: Annotated[int, Field(ge=1, le=200)] = 20,
    ) -> str:
        """read: the 'last collected' stamp per source, with its age and the token ratios. advance: move the stamps, never back. tokens: file what a run predicted against what it cost, and answer with that command's ratios. changed: the markdown notes modified after since, oldest first, with an excerpt each; Wiki/, Attachments/, _views/, _backup/ and dot-folders are never read."""
        if action == "changed":
            if not since:
                raise RuntimeError("changed needs since.")
            return _json(workflows.changed_notes(since, folders, max_chars, limit))
        return _json(workflows.collect_sources(action, source, at, now, payload))

    @mcp.tool(
        name="vault_load_history",
        annotations={"title": "Read the past into the wiki", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    @_guard
    def vault_load_history(
        action: Annotated[str, Field(description="status, plan, next or done.")] = "status",
        since: Annotated[Optional[str], Field(description="plan: the date to start from.")] = None,
        batch: Annotated[int, Field(ge=1, le=100, description="plan: records per batch.")] = 25,
        payload: Annotated[Optional[dict[str, Any]], Field(description="done: what the batch saved and reached.")] = None,
        reset: Annotated[bool, Field(description="plan: drop the pass and start over.")] = False,
        now: Annotated[Optional[str], Field(description="Only for tests.")] = None,
    ) -> str:
        """Read the months before the 'last collected' stamps into the wiki, one window of days at a time, in the order Outlook inbox, Outlook sent items, Teams chats. status reports where the pass stands, plan starts one, next hands out the window to list with the exact call for it, and done files a listed window and moves the place."""
        return _json(history.load_history(action, since, batch, payload, reset, now))

    # ---------------------------------------------------------------- time blocks (0.3.0)

    @mcp.tool(
        name="vault_time_block",
        annotations={"title": "Plan, write or audit the week's blocks", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    @_guard
    def vault_time_block(
        action: BlockAction,
        week: Annotated[str, Field(min_length=1, description="ISO week, e.g. 2026-W35.")],
        events: Annotated[Optional[list[dict[str, Any]]], Field(description="plan / audit: outlook_list_events items for the week.")] = None,
        today: Annotated[Optional[str], Field(description="plan: days before it are not planned.")] = None,
        now: Annotated[Optional[str], Field(description="plan: local time HH:MM; only matters on today.")] = None,
        peak_hours: PeakHours = None,
        blocks: Annotated[Optional[list[dict[str, Any]]], Field(description="write: the plan's blocks, with the create results.")] = None,
        created_by: CreatedBy = workflows.CREATED_BY,
    ) -> str:
        """plan: focus and admin blocks for the working days of week from today on, from Preferences.md and the priorities, what has a due date first — nothing is booked, so the model creates the appointments after a yes. write: Time-blocks/<week>.md once they exist, its '## Plan' table and an empty '## Held' one. audit: hours per kind against the work hours, with the note's Held rows applied."""
        if action == "plan":
            return _json(timeblock.time_block_plan(week, events or [], today, now, peak_hours))
        if action == "write":
            return _json(timeblock.write(week, blocks or [], created_by))
        if action == "audit":
            return _json(timeblock.time_audit(week, events or []))
        raise RuntimeError("action must be 'plan', 'write' or 'audit'.")

    @mcp.tool(
        name="vault_priorities_write",
        annotations={"title": "Suggest or write the ranked priorities", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_priorities_write(
        action: Annotated[str, Field(description="candidates or write.")] = "candidates",
        lines: Annotated[Optional[list[str]], Field(description="write: the confirmed priorities, in rank order.")] = None,
        note: Annotated[Optional[str], Field(description="write: one line on how they were chosen.")] = None,
        created_by: CreatedBy = workflows.CREATED_BY,
    ) -> str:
        """Gather the material for a ranked suggestion, or write the list the user confirmed. candidates (read only) returns {topics, followups, weekly_open, current}; write replaces the numbered list under '## Priorities' and returns {path, action, lines, previous}."""
        return _json(priorities.priorities_write(action, lines, note, created_by))

    _trim_schemas(mcp)


__all__ = ["build_server", "register", "SCHEMAS"]
