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
(brief=true stitches them into one text), vault_wiki_match finds pages,
vault_wiki_read returns a page's lead and facts (with ids),
vault_wiki_ingest / vault_wiki_apply take
op lists (add, update, supersede, confirm, retire, contest, lead, summary,
status, title, alias, related, role, open, done, reschedule, steps, due,
owner, org, outcome, milestone, risk, link, superseded_by, reversal). Open
items carry an owner and a due date, and Follow-ups.md is
written from them. vault_wiki_lint runs its checks (and asks the wiki the
questions the user keeps in Wiki/Questions.md), vault_wiki_merge folds one page
into another (only on a yes), vault_wiki_migrate moves a 0.1.0 vault's
People/ folder into the wiki (dry run first).

Collecting: vault_collect_sources keeps the "last collected" stamp per
source (teams, outlook, notes), vault_save_chat writes a Teams chat as a day
record under Teams/, vault_changed_notes lists the notes modified since a
time (records and the user's collect_folders, read only).
vault_load_history reads the months before that into the wiki: it hands out
one window of days at a time (Outlook inbox, then sent items, then Teams)
with the exact call to list it, remembers where it got to, and never moves a
collect stamp.

Priorities: vault_priorities_write gathers the material for a ranked
suggestion (action candidates, read only) and, after the user confirmed,
writes the numbered list into Priorities.md (action write).
"""

# Module-level aliases: with ``from __future__ import annotations`` every hint
# is a string resolved against module globals when FastMCP builds the schema.
NoteType = Annotated[
    str,
    Field(description="Note type: email, meeting, person, daily, weekly, chat or time-block."),
]
Identity = Annotated[
    Any,
    Field(
        description=(
            "Identity of the note: a string, or an object with the identity keys "
            "(email: internet_message_id / entry_id; meeting: occurrence_key / global_id; "
            "person: email; daily: date; weekly: week; chat: chat_id + date, or 'chat_id|date'; time-block: week)."
        )
    ),
]
VaultPath = Annotated[
    str,
    Field(min_length=1, description="Vault-relative path with forward slashes, under Administrator/."),
]
Frontmatter = Annotated[
    dict[str, Any],
    Field(description="Frontmatter keys and values. Required keys per type are validated."),
]
Body = Annotated[str, Field(description="Markdown body (without frontmatter).")]
WriteMode = Annotated[
    str,
    Field(description="'create' (error if the identity exists), 'append' (requires existing), or 'upsert'."),
]
Section = Annotated[str, Field(min_length=1, description="Heading text without the leading '## '.")]
Row = Annotated[list[str], Field(min_length=1, description="Cell values, one per column.")]
DedupeKey = Annotated[
    Optional[str],
    Field(description="Key written as a hidden <!-- entry_id: KEY --> comment in the last cell; an existing row with the same comment is not added again."),
]
Header = Annotated[
    Optional[list[str]],
    Field(description="Column names to create the table with when the section has no table yet (not needed for Follow-ups.md)."),
]
KeyLabel = Annotated[
    str,
    Field(description="Label used in the hidden comment: 'entry_id' (default) or 'occurrence_key'."),
]
SetLastCell = Annotated[
    Optional[str],
    Field(description="New text for the last cell (the hidden comment is kept), e.g. the Closed date."),
]
Since = Annotated[Optional[str], Field(description="ISO date or datetime lower bound on the type's date key.")]
Limit = Annotated[int, Field(ge=1, le=2000, description="Max notes to return.")]
WorkStart = Annotated[str, Field(description="Work day start, HH:MM.")]
WorkEnd = Annotated[str, Field(description="Work day end, HH:MM.")]
BufferMinutes = Annotated[int, Field(ge=0, le=120, description="Free minutes kept around existing meetings.")]
PeakHours = Annotated[
    Optional[list[str]],
    Field(description="The hours the user works best, as ranges HH:MM-HH:MM (for example [\"09:00-12:00\"]); focus blocks are placed there first."),
]
Overwrite = Annotated[bool, Field(description="Rewrite Preferences.md and the _views/*.base files. Follow-ups.md is never overwritten.")]
CreatedBy = Annotated[str, Field(description="Value for the created_by key in the files vault_init writes.")]
Fields = Annotated[
    Optional[list[str]],
    Field(description="Frontmatter keys to return; omit for all of them."),
]
Items = Annotated[
    list[dict[str, Any]],
    Field(description="Mail items as outlook_list_mails returned them (entry_id, internet_message_id, from_address, from_name, subject, received, preview; optional headers {list_unsubscribe, auto_submitted} and message_class)."),
]
DateStr = Annotated[str, Field(description="Local date YYYY-MM-DD.")]
Labels = Annotated[
    list[dict[str, Any]],
    Field(description="One object per mail the model labelled: {entry_id, label (act/reply/waiting/fyi/noise), reason (under 80 characters)}. Mails a rule labelled may be left out."),
]
Events = Annotated[
    Optional[list[dict[str, Any]]],
    Field(description="outlook_list_events items for the day (occurrence_key, subject, start, end, location, organizer, all_day). Empty for /administrator:inbox."),
]
WatchOut = Annotated[Optional[list[str]], Field(description="Extra 'Watch out' bullets; clashes and missing prep notes are added in code.")]
Mail = Annotated[dict[str, Any], Field(description="The JSON from outlook_get_mail(trim_quoted=true): entry_id, internet_message_id, conversation_id, subject, from, from_address, recipients[], received, attachments[], body / body_trimmed.")]
Attendees = Annotated[
    Optional[list[Any]],
    Field(description="Attendees as SMTP strings or {name, address} objects (the user's own address left out)."),
]
WikiPage = Annotated[str, Field(min_length=1, description="Wiki page as a path, stem or wikilink: Administrator/Wiki/Topics/q3-budget.md, Wiki/Topics/q3-budget or [[Wiki/Topics/q3-budget]].")]
WikiOps = Annotated[
    list[dict[str, Any]],
    Field(description="Ops, each {op, ...}: add {text, since, src}; update {id, text, src}; supersede {id, text, since, src}; confirm {id, src}; retire {id, src, reason}; contest {id, text, src}; lead {text}; summary {text}; status {value}; title {text}; alias {text}; related {page}; role {page, role}; open {text, owner ('me' by default, a [[Wiki/People/…]] link or a plain name), due, since, src}; done {id, src}; reschedule {id, due, src}; steps {text}; due {value}; owner {value}; org {value}. Topic pages only: outcome {text}; milestone {text, due, src}; risk {text, src}; link {url or page, label}. Decision pages only: superseded_by {page}; reversal {text} — everything that would rewrite a decision (add, update, supersede, retire, contest, due, steps and the topic ops) is refused with 'append-only'. Ids come from vault_wiki_read."),
]
WikiSrc = Annotated[str, Field(description="Source written on the facts: 'user' for things the user said, else a record id.")]


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
        """Report where the vault is and which Administrator/ folders and files exist (files includes Wiki/Questions.md, the user's list of questions the wiki should answer). Never fails on a missing vault; read the flags."""
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
        """Create Administrator/ with its folders (Wiki/ with People, Orgs, Topics, Howto and an empty Index.md / Log.md / Review.md), Follow-ups.md, Preferences.md (from the given work hours and peak hours; peak_hours defaults to ["09:00-12:00"]), Wiki/Questions.md (the user's questions and the page that should answer each, with two examples shown above an empty list) and the _views/*.base files. Existing files are kept unless overwrite=true (Follow-ups.md, Rules.md, Priorities.md, Questions.md and the Wiki files are always kept)."""
        return _json(store.init(work_start, work_end, buffer_minutes, overwrite, created_by, peak_hours))

    @mcp.tool(
        name="vault_find",
        annotations={"title": "Find a note by identity", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_find(type: NoteType, identity: Identity, fields: Fields = None) -> str:
        """Find the note of a type with this identity by reading frontmatter, not filenames. Returns {found, path, frontmatter, matches}; a global_id-only meeting identity returns the newest occurrence first. fields limits the frontmatter keys returned."""
        return _json(store.find(type, identity, fields))

    @mcp.tool(
        name="vault_write",
        annotations={"title": "Create or append a note", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    @_guard
    def vault_write(type: NoteType, frontmatter: Frontmatter, body: Body, mode: WriteMode = "create") -> str:
        """Write a note. create: new file named by the type's filename rule (' (2)' suffix on a filename clash). append: find the note by identity and add '## Update <timestamp>' + body; only status / last_contact / inbox_checked / mails_seen may change in the frontmatter (aliases are merged). upsert: create if missing, else append. Existing body text is never edited."""
        return _json(store.write(type, frontmatter, body, mode))

    @mcp.tool(
        name="vault_append_row",
        annotations={"title": "Append a table row", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_append_row(
        path: VaultPath,
        section: Section,
        row: Row,
        dedupe_key: DedupeKey = None,
        header: Header = None,
        key_label: KeyLabel = "entry_id",
    ) -> str:
        """Append one markdown table row under the '## <section>' heading (the heading and the header row are created when missing; Follow-ups.md gets its fixed header). With dedupe_key, a hidden comment is added to the last cell and a row already carrying that key anywhere in the file returns {appended: false, reason: 'duplicate'}."""
        return _json(store.append_row(path, section, row, dedupe_key, header, key_label))

    @mcp.tool(
        name="vault_move_row",
        annotations={"title": "Move a table row between sections", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_move_row(
        path: VaultPath,
        from_section: Section,
        to_section: Section,
        dedupe_key: Annotated[str, Field(min_length=1, description="Key in the row's hidden comment.")],
        set_last_cell: SetLastCell = None,
    ) -> str:
        """Cut the row carrying dedupe_key from the table under from_section and append it to the table under to_section (for Follow-ups Open -> Done). set_last_cell replaces the last cell's text, keeping the hidden comment."""
        return _json(store.move_row(path, from_section, to_section, dedupe_key, set_last_cell))

    @mcp.tool(
        name="vault_read",
        annotations={"title": "Read a note", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_read(path: VaultPath) -> str:
        """Read one note under Administrator/: {path, frontmatter, body, sections (heading texts)}."""
        return _json(store.read(path))

    @mcp.tool(
        name="vault_list",
        annotations={"title": "List notes of a type", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_list(type: NoteType, since: Since = None, limit: Limit = 200, fields: Fields = None) -> str:
        """List notes of a type, newest first by its date key (email: received, meeting: start, person: last_contact, daily: date, weekly: start): [{path, frontmatter}]. fields limits the frontmatter keys returned."""
        return _json(store.list_notes(type, since, limit, fields))

    # ---------------------------------------------------------------- v0.5 helpers

    @mcp.tool(
        name="vault_rules",
        annotations={"title": "Read or apply Administrator/Rules.md", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_rules(
        action: Annotated[str, Field(description="'get' returns the parsed rules; 'match' applies them to items.")] = "get",
        items: Optional[Items] = None,
    ) -> str:
        """Rules from Administrator/Rules.md (created when missing) plus the built-in ones: List-Unsubscribe header -> fyi; auto-submitted, 'Automatic reply' subject, meeting responses -> noise; noreply senders -> fyi; sender with a person note of status fyi -> fyi. get: {path, labels, never_save, fyi_senders}. match: {results: [{entry_id, label or null, never_save, rule}]}."""
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
        """Take outlook_list_mails items and return only what the model still has to label: {to_label: [items not in any daily note of that week and not never_save, with label/rule pre-filled where a rule matched, preview only for the rest], already_seen: [entry_ids], never_save: [entry_ids], labelled_by_rule, cache}. The list is cached so vault_write_daily can be called without items."""
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
        since: Annotated[str, Field(description="Lower bound of the inbox window (ISO), as used for outlook_list_mails.")] = "",
        inbox_checked: Annotated[str, Field(description="Time of the outlook_list_mails call (ISO); defaults to now.")] = "",
        tokens_used: Annotated[Optional[int], Field(description="Token count of this turn, stored in the frontmatter when given.")] = None,
        folder: Annotated[str, Field(description="Folder that was read; 'inbox' unless the user named another.")] = "inbox",
        created_by: CreatedBy = workflows.CREATED_BY,
    ) -> str:
        """Render Daily/YYYY-MM-DD.md from labels + items (items default to the vault_inbox_prepare cache): inbox table sorted act/reply/waiting/fyi/noise with hidden entry_id comments, To do, Waiting on (each row also becomes an open item on the sender's page), Promised (the user's own open items due within seven days, on the first run of the day), Calendar from events with occurrence_key comments, Watch out (given bullets + clashes + missing prep notes). A second run on the same day appends only the new rows under '## Update'. Returns {path, action (created/appended/unchanged), rows_written, duplicates_skipped, followups_added, promised, calendar_rows, unlabelled}."""
        return _json(workflows.write_daily(date, labels, items, events, watch_out, since, inbox_checked, tokens_used, folder, created_by))

    @mcp.tool(
        name="vault_save_email",
        annotations={"title": "Save one email as a note", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_save_email(
        mail: Mail,
        summary: Annotated[str, Field(description="One line, 25 words or fewer.")],
        action_items: Annotated[Optional[list[str]], Field(description="Action item lines ('Send Q3 numbers by 2026-08-29 — owner: me'); empty when the mail asks for nothing.")] = None,
        attachments_saved: Annotated[Optional[list[str]], Field(description="Paths returned by outlook_save_attachments (absolute or vault-relative under Administrator/Attachments/).")] = None,
        msg_file: Annotated[Optional[str], Field(description="Path returned by outlook_save_mail_as.")] = None,
        status: Annotated[Optional[str], Field(description="todo / waiting / done / fyi; default todo with action items, fyi without, waiting when the mail is from self_addresses and has action items.")] = None,
        self_addresses: Annotated[Optional[list[str]], Field(description="The user's own addresses from outlook_whoami, to tell 'from me' apart.")] = None,
        company: Annotated[Optional[str], Field(description="Company for a new person note, only from outlook_search_contacts.")] = None,
        created_by: CreatedBy = workflows.CREATED_BY,
    ) -> str:
        """Build the email note from outlook_get_mail JSON (body_trimmed when present), write it (upsert: an existing note gets an Update with the new summary), create the sender's draft person page under Wiki/People or add a Records line to it (last_contact, aliases), and, when status is waiting, add an open item owned by the counterpart (the first recipient of the user's own mail, else the sender) to that person's page. Returns {path, action, status, person_path, person_action, followup_added}."""
        return _json(workflows.save_email(mail, summary, action_items, attachments_saved, msg_file, status, self_addresses, company, created_by))

    @mcp.tool(
        name="vault_prep_context",
        annotations={"title": "Vault context for a meeting prep", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_prep_context(
        occurrence_key: Annotated[str, Field(description="occurrence_key of the event (global_id|start).")],
        global_id: Annotated[str, Field(description="global_id of the event; taken from occurrence_key when empty.")] = "",
        attendees: Attendees = None,
        subject: Annotated[str, Field(description="The event's subject; matched against wiki topic pages. Taken from the existing note when empty.")] = "",
    ) -> str:
        """Everything the vault knows for a prep in one call: {existing_note, existing_status, previous_occurrence: {path, date, open_actions} or null, people: [{email, name, path, last_contact, company, last_emails (up to 3 Records lines)}], commitments: [{page, stem, type, title, owner_name, id, text, owner, due, since, src, record, done} for the open items on the attendees' pages and the items anywhere they own], followups_open: [one line per commitment someone else owes, kept for one release], wiki: [{path, type, title, status, lead, open[], facts[] (up to 8)} for the attendees' person pages and up to 3 topic or decision pages matched on the subject, projects first, then decisions]}."""
        return _json(workflows.prep_context(occurrence_key, global_id, attendees, subject))

    @mcp.tool(
        name="vault_weekly_facts",
        annotations={"title": "Facts for the weekly review", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_weekly_facts(
        week: Annotated[str, Field(description="ISO week, e.g. 2026-W34.")],
        today: Annotated[Optional[str], Field(description="Local date YYYY-MM-DD; defaults to the machine date.")] = None,
    ) -> str:
        """Computed from the vault only: {week, start, end, open_from_inbox: [{date, label, subject, from, entry_id, note, daily}] (act/reply rows of the week's daily notes not ticked and with no email note of status done), waiting: [{since, who, what, email, age_days} from the open items other people owe], promised_overdue: [{due, what, page, id, days_over} from the user's own items past their due date], meetings_held: [{path, subject, date, unchecked_actions}], no_notes: [past meetings still 'upcoming'], quiet_people: [{name, email, path, last_contact, days}] over 30 days, wiki: {review_open, stale, uningested, candidates} counts for the '## Wiki' section}."""
        return _json(workflows.weekly_facts(week, today))

    @mcp.tool(
        name="vault_attach_transcript",
        annotations={"title": "Attach a transcript file to a meeting note", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    @_guard
    def vault_attach_transcript(
        meeting_path: VaultPath,
        transcript_path: Annotated[str, Field(description="Vault-relative path of the transcript file under Administrator/Attachments/.")],
        created_by: CreatedBy = workflows.CREATED_BY,
    ) -> str:
        """Read a transcript file, drop the Copilot scaffolding, count turns and speakers, and append '### Transcript' (speakers linked to attendee person notes; a collapsed callout up to 400 lines, else a link to the file) under '## Update' on the meeting note. Returns {path, turns, speakers, speaker_links, lines, appended_lines, linked, update_heading}."""
        return _json(workflows.attach_transcript(meeting_path, transcript_path, created_by))

    # ---------------------------------------------------------------- wiki (0.2.0)

    @mcp.tool(
        name="vault_wiki_match",
        annotations={"title": "Find wiki pages for a text / people / domains", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_wiki_match(
        text: Annotated[str, Field(description="Free text: subject plus the first ~300 characters.")],
        people: Annotated[Optional[list[str]], Field(description="Sender / attendee addresses.")] = None,
        domains: Annotated[Optional[list[str]], Field(description="Sender domains.")] = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 8,
    ) -> str:
        """Index lines of the wiki pages whose title, aliases, email or domains match (alias hit > address > word overlap > domain), plus topic candidates over the 2-records-on-2-days threshold that have no page yet: {pages: [{path, line, score, why}], candidates: [{subject, records, days}]}."""
        return _json(wiki.match(text, people, domains, limit))

    @mcp.tool(
        name="vault_wiki_search",
        annotations={"title": "Search the wiki for facts", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_wiki_search(
        query: Annotated[str, Field(description="The question in plain words. \"quoted phrases\", ids, dates and amounts are looked up as written; /regex/ searches the raw text.")],
        kinds: Annotated[Optional[list[str]], Field(description="Keep only these page kinds: person, org, topic, decision, howto, me.")] = None,
        limit: Annotated[int, Field(ge=1, le=50, description="How many hits to answer with.")] = 10,
        since: Annotated[Optional[str], Field(description="Only facts dated on or after this ISO date.")] = None,
        include_superseded: Annotated[bool, Field(description="Also answer with the old wording of facts that were replaced (always shown as superseded and always ranked below).")] = False,
        brief: Annotated[bool, Field(description="Answer with one stitched text instead of a list of hits.")] = False,
        max_chars: Annotated[int, Field(ge=200, le=8000, description="Cap for the stitched text.")] = 1500,
        open_items: Annotated[bool, Field(description="Answer with the open items (the commitments) of the matching pages instead of facts.")] = False,
        owner: Annotated[Optional[str], Field(description="Open items only: 'me' for what the user owes, 'others' for what other people owe the user.")] = None,
        due_before: Annotated[Optional[str], Field(description="Open items only: keep the items due before this ISO date (that date itself is left out).")] = None,
        page: Annotated[Optional[str], Field(description="Keep to this one page (path, stem or wikilink).")] = None,
        include_done: Annotated[bool, Field(description="Open items only: also answer with the items already ticked.")] = False,
    ) -> str:
        """Ranked facts read from the wiki pages themselves: [{page, kind, title, fact_id, text, since, src, score, why[], superseded, streams, confirmed}], best first, at most three facts per page. streams is how many kinds of source back the fact (mail, meeting, chat, the user) and confirmed how many days ago it was last confirmed: streams 1 with confirmed over 180 means one source and nothing since, so say it with a hedge or ask. brief=true answers with {text, pages[], facts[], chars} — the top pages with their lead, facts, open items and the dated facts of the pages they link to, with such facts marked "(one source, unconfirmed since <date>)". open_items=true answers with the commitments [{page, stem, type, title, owner_name, id, text, owner, due, since, src, record, done}], oldest since first, at most 200 of them (limit is not used there). Notes are never read."""
        return _json(wiki_search.search_tool(query, kinds, limit, since, include_superseded, brief, max_chars, open_items, owner, due_before, page, include_done))

    @mcp.tool(
        name="vault_wiki_read",
        annotations={"title": "Read a wiki page", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_wiki_read(
        path: WikiPage,
        sections: Annotated[Optional[list[str]], Field(description="Which parts: lead, facts, people, topics, contacts, open, records, related, history, steps, notes. Default lead + facts.")] = None,
        max_chars: Annotated[int, Field(ge=0, le=20000, description="Trim the answer to about this many characters; 0 = no limit.")] = 2000,
    ) -> str:
        """Frontmatter plus the requested parts of one page; facts come as [{id, text, since, src}] so ops can name them by id."""
        return _json(wiki.read(path, sections, max_chars))

    @mcp.tool(
        name="vault_wiki_ingest",
        annotations={"title": "Apply ops from a record to wiki pages", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    @_guard
    def vault_wiki_ingest(
        record_path: Annotated[str, Field(description="Vault-relative path of the email, meeting or chat note the ops come from.")],
        pages: Annotated[list[dict[str, Any]], Field(description="Per page: {path, ops} for an existing page or {new: {type, title, aliases, lead, summary}, ops} for a new one. An empty ops list still adds the Records line.")],
        created_by: CreatedBy = wiki.CREATED_BY,
    ) -> str:
        """Apply op lists to wiki pages with the record as source (src and since default to the record's id and date). Per page: applied / refused ops with reasons, new ids, sizes; writes Records, History, the record's wiki: link, Log.md and Index.md; reports the topic candidate for the record's subject (candidate.suggest_due says a record named a day, so propose an owner and a due date). The answer carries confirmed_decisions: [page stems] when the user ticked an 'unconfirmed decision' line in Review.md. Every page is read back after the write: one that does not come back as it was written keeps its previous text and answers written: false with reason 'verify-failed'."""
        return _json(wiki.ingest(record_path, pages, created_by))

    @mcp.tool(
        name="vault_wiki_create",
        annotations={"title": "Create a wiki page", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    @_guard
    def vault_wiki_create(
        type: Annotated[str, Field(description="person, org, topic, decision, howto or me. A decision needs extra {decided, by}.")],
        title: Annotated[str, Field(description="Noun phrase, 6 words or fewer, no dates.")],
        aliases: Optional[list[str]] = None,
        lead: Annotated[str, Field(description="2-4 sentences, 80 words or fewer.")] = "",
        summary: Annotated[str, Field(description="One line, 160 characters or fewer; the Index.md line.")] = "",
        facts: Annotated[Optional[list[dict[str, Any]]], Field(description="[{text, since, src}] written as add ops.")] = None,
        src: WikiSrc = "user",
        created_by: CreatedBy = wiki.CREATED_BY,
        extra: Annotated[Optional[dict[str, Any]], Field(description="Type-specific keys: email (person), domains (org), owner / org / due (topic), decided (date, required) and by (person page links, required) for a decision. Code-owned keys are refused.")] = None,
    ) -> str:
        """Create a page under Wiki/<Type>/ (slug filename). Refused with the matching index line when a page with this title, alias or address exists: {created: false, reason: 'exists', path, match}. A new decision page is written with status current and flags [unconfirmed-decision] and gets one Review line ('unconfirmed decision: … — confirm or drop'); confirming it clears the flag, ticking that line in Obsidian does the same on the next lint or ingest."""
        return _json(wiki.create(type, title, aliases, lead, summary, facts, src, created_by, extra))

    @mcp.tool(
        name="vault_wiki_apply",
        annotations={"title": "Apply ops to a wiki page without a record", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    @_guard
    def vault_wiki_apply(path: WikiPage, ops: WikiOps, created_by: CreatedBy = wiki.CREATED_BY, src: WikiSrc = "user") -> str:
        """Apply ops the user asked for in chat (src defaults to 'user', since to today). Same answer shape as vault_wiki_ingest for one page."""
        return _json(wiki.apply(path, ops, created_by, src))

    @mcp.tool(
        name="vault_wiki_log",
        annotations={"title": "Read Wiki/Log.md", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_wiki_log(
        since: Annotated[Optional[str], Field(description="ISO date or datetime lower bound.")] = None,
        page: Annotated[Optional[str], Field(description="Only lines of this page (stem or link).")] = None,
        limit: Annotated[int, Field(ge=1, le=500)] = 50,
    ) -> str:
        """The newest matching lines of Wiki/Log.md: {path, total, lines}."""
        return _json(wiki.log(since, page, limit))

    @mcp.tool(
        name="vault_wiki_review",
        annotations={"title": "List or resolve Wiki/Review.md items", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    @_guard
    def vault_wiki_review(
        action: Annotated[str, Field(description="'list' or 'resolve'.")] = "list",
        item: Annotated[Optional[str], Field(description="resolve: the item's number in the Open list, or a part of its text.")] = None,
        resolution_ops: Annotated[Optional[list[dict[str, Any]]], Field(description="resolve: ops applied to the page the item names (src user), e.g. a supersede the user decided on.")] = None,
        created_by: CreatedBy = wiki.CREATED_BY,
    ) -> str:
        """list: {open: [{n, text}], done}. resolve: applies resolution_ops (if any) to the item's page, moves the item to Done with today's date, clears the page's contradiction and unconfirmed-decision flags when no other open item names it."""
        if action not in ("list", "resolve"):
            raise RuntimeError("action must be 'list' or 'resolve'.")
        return _json(wiki.review(action, item, resolution_ops, created_by))

    @mcp.tool(
        name="vault_wiki_lint",
        annotations={"title": "Run the wiki checks", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_wiki_lint(
        fix: Annotated[bool, Field(description="Apply the safe fixes: regenerate the index, recompute code-owned keys, fix section order, turn dangling links in code-owned sections into plain text, tick open items whose record action is done, set stale topics to dormant, rotate History / Log.")] = False,
        created_by: CreatedBy = wiki.CREATED_BY,
    ) -> str:
        """The wiki checks (index vs files, dangling links, orphans, frontmatter, sections, oversized, stale, due in the past, open items done, duplicate pages, records never ingested, topic candidates, History / Log rotation, pages to ask the model about, unconfirmed facts, 19 overdue: the user's own open items past their due date, 20 questions: how many of the questions in Wiki/Questions.md the wiki answers, and 21 unanswered: the questions the wiki could not answer, each asked more than once in the last 30 days). Flags (orphan, stale, oversized, possible-duplicate) and Review lines are written in both modes; fix=true also applies the safe fixes. Decision pages are left out of the stale check. Returns {date, fix, pages, counts, checks: {0..21}, flagged, review_added, written, cache}, plus confirmed_decisions: [page stems] when the user ticked an 'unconfirmed decision' line in Review.md (the one line a tick alone settles). checks['0'] is the pass that reads back what the user changed by hand in Obsidian; it runs at the start of every wiki tool, and when it took something over the answer carries adopted: [{page, changes}] — pass that on in one line. checks['14'].ask_model lists the pages touched since the last lint: read their facts and report pairs that cannot both be true with a contest op. checks['20'] is {name, asked, found, misses: [{question, expected, top}], unknown} and checks['21'] {name, count, days, items: [{query, times, last}]}; every run appends one Log.md line with all the counts ("questions 17/20, unanswered 3"), so vault_wiki_log shows whether the wiki is getting better."""
        return _json(wiki_lint.lint(fix, created_by))

    @mcp.tool(
        name="vault_wiki_merge",
        annotations={"title": "Merge one wiki page into another", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    )
    @_guard
    def vault_wiki_merge(
        keep: Annotated[str, Field(min_length=1, description="The page that stays (path, stem or wikilink).")],
        drop: Annotated[str, Field(min_length=1, description="The page folded into keep; its file becomes a redirect.")],
        created_by: CreatedBy = wiki.CREATED_BY,
    ) -> str:
        """Only after the user said the two pages are the same thing. Facts of drop are added to keep with their since / src (same text: confirm), aliases / records / links merged, drop becomes a 3-line redirect page (type redirect) so links keep resolving, other pages' links follow, keep's History records the merge. Returns {keep, drop, redirect, facts_added, facts_confirmed, facts_refused, relinked, review_closed, sizes}."""
        return _json(wiki_lint.merge(keep, drop, created_by))

    @mcp.tool(
        name="vault_wiki_migrate",
        annotations={"title": "Move a 0.1.0 People/ folder into the wiki", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    )
    @_guard
    def vault_wiki_migrate(
        dry_run: Annotated[bool, Field(description="true returns the plan and writes nothing; false does it with a backup.")] = True,
        created_by: CreatedBy = wiki.CREATED_BY,
    ) -> str:
        """Bring an older vault up to date in three parts. people: Administrator/People/*.md move to Wiki/People/ as person pages following the page contract (old Emails / Meetings lines become Records, a 'Voice with this person:' block and other user text go under Notes), [[People/...]] links are rewritten to [[Wiki/People/...]] everywhere including frontmatter, and the old folder goes when it is empty. followups: the Open rows of Follow-ups.md become open items on the person page the Who names (an unknown name lands on Wiki/Me.md with the name in the text) and the Done rows become History lines, after which the file is written from the pages. views: the .base views are brought up to date. A copy of what is replaced is kept under Administrator/_backup/<stamp>/. Returns the plan ({needed, parts: {people, followups, views}, people, links, views, followups: {open, done, count, backup}, left, backup}) plus, after a real run, {moved, skipped, links_rewritten, followups_moved: {open, done}, old_folder_removed, old_folder_left}."""
        return _json(wiki_migrate.migrate(dry_run, created_by))

    # ---------------------------------------------------------------- collect (0.3.0)

    @mcp.tool(
        name="vault_save_chat",
        annotations={"title": "Save a Teams chat as a day record", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_save_chat(
        chat: Annotated[dict[str, Any], Field(description="The chat as teams_list_chats returned it: id, title, type, members (names or {name, mri}), account.")],
        messages: Annotated[list[dict[str, Any]], Field(description="Messages of that chat, any order: [{id, time (local ISO), sender, is_self, text}].")],
        self_names: Annotated[Optional[list[str]], Field(description="The user's own display names, to tell 'from me' apart when is_self is missing.")] = None,
        created_by: CreatedBy = workflows.CREATED_BY,
    ) -> str:
        """Write or extend Teams/<date> <chat>.md, one record per chat per day (record_id = chat_id|date): '## Messages' with one line per message, oldest first, hidden message ids. A second call the same day appends only the messages whose ids are not in the file yet (under '## Update') and moves messages / last forward. Senders that match a person page by name or alias get a Records line and last_contact on it; senders without a page are listed in unknown_people (no page is made without an address). Returns {path, action (created / appended / unchanged), date, record_id, added, skipped_duplicates, messages, people: [{name, page}], unknown_people}; when the messages span several days, a list with one such result per day."""
        return _json(workflows.save_chat(chat, messages, self_names, created_by))

    @mcp.tool(
        name="vault_collect_sources",
        annotations={"title": "Read or advance the 'last collected' stamps", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_collect_sources(
        action: Annotated[str, Field(description="'read' returns the stamps; 'advance' moves them.")] = "read",
        source: Annotated[Optional[str], Field(description="advance: teams, outlook or notes; omit for all three.")] = None,
        at: Annotated[Optional[str], Field(description="advance: the new stamp (local ISO); defaults to now.")] = None,
        now: Annotated[Optional[str], Field(description="Only for tests: the time ages are measured against.")] = None,
    ) -> str:
        """The 'last collected' stamp per source in Wiki/_cache/collect.json. read: {stamps, age_hours, ask (a stamp is missing or older than 24 h: ask the user how far back to collect), default_since (the oldest stamp, else today 00:00), last_collected ('Thu 21 Aug 18:10', or 'never')}. advance: sets the stamp(s) to at; a stamp is never moved back (refused: [{source, reason: 'older-than-stamp', stamp, at}]). Returns {stamps, advanced, refused}."""
        return _json(workflows.collect_sources(action, source, at, now))

    @mcp.tool(
        name="vault_changed_notes",
        annotations={"title": "Notes modified since a time", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_changed_notes(
        since: Annotated[str, Field(min_length=1, description="Local ISO datetime; notes modified after it are returned.")],
        folders: Annotated[Optional[list[str]], Field(description="Vault-relative folders to read instead of the default set (Administrator/Meetings, Emails, Daily, Weekly plus the collect_folders of Preferences.md).")] = None,
        max_chars: Annotated[int, Field(ge=0, le=20000, description="Cut each excerpt at this many characters; 0 = no cut.")] = 1200,
        limit: Annotated[int, Field(ge=1, le=200, description="Max notes to return, oldest first.")] = 20,
    ) -> str:
        """Markdown notes modified after since, oldest first: {since, count, total, capped, folders, skipped, missing, notes: [{path, type, modified, ingested (a wiki key is present), excerpt (the last '## Update' section when there is one, else the body), from_update, truncated}]}. Wiki/, Attachments/, _views/, _backup/ and dot-folders are never read; folders outside Administrator/ are only read, never written; paths outside the vault are refused."""
        return _json(workflows.changed_notes(since, folders, max_chars, limit))

    @mcp.tool(
        name="vault_load_history",
        annotations={"title": "Read the past into the wiki", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    @_guard
    def vault_load_history(
        action: Annotated[str, Field(description="'status' reports where the pass stands, 'plan' starts one, 'next' hands out the window to list, 'done' reports a listed window.")] = "status",
        since: Annotated[Optional[str], Field(description="plan: the date to start from (ISO); defaults to 90 days before today, 00:00.")] = None,
        batch: Annotated[int, Field(ge=1, le=100, description="plan: how many records one batch works on.")] = 25,
        payload: Annotated[Optional[dict[str, Any]], Field(description="done: {saved: [{id, path, received}], skipped_ids: [ids left out], reached: the received time of the last record worked (ISO), exhausted: true when nothing in the window was left over, pages: [wiki pages touched], calls: how many tool calls the batch took, listed: how many records the window listed before the cut (drives the window size and the listed-vs-saved gap; defaults to saved + skipped)}.")] = None,
        reset: Annotated[bool, Field(description="plan: drop the running pass and start over.")] = False,
        now: Annotated[Optional[str], Field(description="Only for tests: the time the pass is measured against.")] = None,
    ) -> str:
        """Read the months before the 'last collected' stamps into the wiki, one window of days at a time, in the order Outlook inbox, Outlook sent items, Teams chats. status: the state ({started: false} before the first plan) with the collect stamps, the days left per source and how many records each source listed against how many were saved, so a gap shows. plan: fixes the start date, the batch size and, per source, the day the pass stops at (that source's collect stamp, else now) — refused while a pass is running unless reset=true; returns {planned, since, until_max, days, left_days, batches_estimate, note}. next: the window to list — {batch_no, source, since, until, expected, skip_ids (ids of that window already seen), list_with (the exact outlook_list_mails / teams_list_chats call), reissued}; turn the list oldest first, drop skip_ids and automated mail, work on the first 'expected' records; while a batch is open the same window is handed out again instead of a second one. done: takes payload and answers {batch, saved, skipped, listed, place, window_days, source_done, all_done, totals, next_hint, note} — the ids are recorded as seen, the place moves (to until when the window was exhausted, else to reached), the window is halved or doubled to fit the batch size (1 to 30 days), and when every source is finished the answer holds a summary that ends with 'Run /administrator:lint.'. The state is Wiki/_cache/history.json and is written after plan and after every done, so a crash costs at most one window. The collect stamps are only read, never moved."""
        return _json(history.load_history(action, since, batch, payload, reset, now))

    # ---------------------------------------------------------------- time blocks (0.3.0)

    @mcp.tool(
        name="vault_time_block_plan",
        annotations={"title": "Plan the week's focus and admin blocks", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_time_block_plan(
        week: Annotated[str, Field(min_length=1, description="ISO week, e.g. 2026-W35.")],
        events: Annotated[list[dict[str, Any]], Field(description="outlook_list_events items for the week: subject, start, end, all_day, attendee_count, is_meeting, occurrence_key, entry_id, busy_status.")],
        today: Annotated[Optional[str], Field(description="Local date YYYY-MM-DD; days before it are not planned. Defaults to today.")] = None,
        now: Annotated[Optional[str], Field(description="Local time HH:MM (from outlook_whoami.local_time). Only matters on today: nothing is placed before it. Omit and today is planned from work_start.")] = None,
        peak_hours: PeakHours = None,
    ) -> str:
        """Plan focus and admin blocks for the working days of week from today on, from Preferences.md (peak_hours, focus_block_minutes, focus_blocks_per_day, admin_blocks_per_day, admin_block_minutes, slack_share, work hours, buffer_minutes, no_meeting_blocks) and the priorities (the numbered lines of Priorities.md, then the user's own open items due by the end of the week, then active wiki topics due within 30 days or with open items). What has a due date is placed first, in the latest free new focus block before that day. peak_hours, when given, replaces the file's peak hours for this plan only (Preferences.md is not changed). Nothing is booked; the model creates the appointments after a yes. Bookable minutes per day = (1 - slack_share) * work minutes - meeting minutes; a day with none left is in skipped_days with the reason. Existing [Focus] / [Admin] appointments are kept (existing: true) and never duplicated. Returns {week, priorities: [{rank, name, page, due}], days: [{date, day, work_minutes, meeting_minutes, bookable_minutes, booked_minutes, slack_minutes, blocks: [{start, end, minutes, kind, subject, priority, page, existing}]}], totals: {focus_minutes, admin_minutes, new_blocks, existing_blocks, slack_share_kept}, deadlines: [{name, due, page, block_date}], unplaced, skipped_days: [{date, reason}], preferences_used, missing_keys}."""
        return _json(timeblock.time_block_plan(week, events, today, now, peak_hours))

    @mcp.tool(
        name="vault_time_block_write",
        annotations={"title": "Write the week's time-block note", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    )
    @_guard
    def vault_time_block_write(
        week: Annotated[str, Field(min_length=1, description="ISO week, e.g. 2026-W35.")],
        blocks: Annotated[list[dict[str, Any]], Field(description="The plan's blocks (start, end, kind, subject, priority) with the create results merged in: occurrence_key and entry_id from outlook_create_event. Existing blocks may be passed too.")],
        created_by: CreatedBy = workflows.CREATED_BY,
    ) -> str:
        """Write Time-blocks/<week>.md after the appointments exist: a '## Plan' table (Day | Start | End | Kind | Subject | Priority, hidden occurrence_key per row), an empty '## Held' table (Day | Block | Result | Note; /administrator:collect-information fills it with vault_append_row, dedupe_key = occurrence_key, key_label = occurrence_key) and '## Notes'. A re-plan of the same week appends the new table under '## Update'. Returns {path, action, week, blocks, planned}."""
        return _json(timeblock.write(week, blocks, created_by))

    @mcp.tool(
        name="vault_time_audit",
        annotations={"title": "Hours per kind for a week", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_time_audit(
        week: Annotated[str, Field(min_length=1, description="ISO week, e.g. 2026-W34.")],
        events: Annotated[list[dict[str, Any]], Field(description="outlook_list_events items for that week: subject, start, end, all_day, attendee_count, is_meeting, occurrence_key, busy_status.")],
    ) -> str:
        """How the week went: hours per kind (meeting = attendees or is_meeting, focus = '[Focus]', admin = '[Admin]', other, unplanned = work hours not booked; all-day events skipped) against the work hours of Preferences.md, the Held rows of Time-blocks/<week>.md applied (skipped blocks count as unplanned, moved ones keep their minutes, rows without an answer are unanswered), per-priority planned and held hours. Returns {week, hours, work_hours, shares, per_priority: [{name, planned_hours, held_hours}], blocks: {planned, held, moved, skipped, unanswered}, lines} — lines are ready for the weekly note's '## Time' section."""
        return _json(timeblock.time_audit(week, events))

    @mcp.tool(
        name="vault_priorities_write",
        annotations={"title": "Suggest or write the ranked priorities", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_priorities_write(
        action: Annotated[str, Field(description="'candidates' returns the material for a suggestion and writes nothing; 'write' replaces the numbered list in Priorities.md with lines.")] = "candidates",
        lines: Annotated[Optional[list[str]], Field(description="write: the confirmed priorities in rank order, 1 to 7 entries, each up to 120 characters, a topic page link ([[Wiki/Topics/acme-contract]]) or plain words; no headings or comments.")] = None,
        note: Annotated[Optional[str], Field(description="write: one optional line on how the list was chosen, kept as a comment under it.")] = None,
        created_by: CreatedBy = workflows.CREATED_BY,
    ) -> str:
        """candidates (read only): {topics: [{title, page, status, due, open_items, verified, summary}] (active wiki topics, soonest due first then most open items, at most 10), followups: [{since, who, what, age_days}] (open Follow-ups rows, oldest first, at most 5), weekly_open: [{subject, label, date}] (open act / reply rows of the latest weekly note's week, at most 5), current: [the numbered lines now in Priorities.md]}. write (only after the user confirmed the list): replaces the numbered list under '## Priorities' (the placeholder or the previous list) with lines plus a '<!-- suggested by administrator, confirmed <date> -->' comment and the note as a second comment; frontmatter, the text above the heading and every other section are kept byte for byte; a missing file is created first. Returns {path, action: 'written', lines, previous}."""
        return _json(priorities.priorities_write(action, lines, note, created_by))


__all__ = ["build_server", "register", "SCHEMAS"]
