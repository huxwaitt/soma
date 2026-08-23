"""FastMCP server ``vault``: the administrator plugin's note writer."""

from __future__ import annotations

import functools
import json
from typing import Annotated, Any, Callable, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from administrator_vault import store, workflows
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
daily (date), weekly (week). Every tool returns a JSON string.
"""

# Module-level aliases: with ``from __future__ import annotations`` every hint
# is a string resolved against module globals when FastMCP builds the schema.
NoteType = Annotated[
    str,
    Field(description="Note type: email, meeting, person, daily or weekly."),
]
Identity = Annotated[
    Any,
    Field(
        description=(
            "Identity of the note: a string, or an object with the identity keys "
            "(email: internet_message_id / entry_id; meeting: occurrence_key / global_id; "
            "person: email; daily: date; weekly: week)."
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
    ) -> str:
        """Create Administrator/ with its folders, Follow-ups.md, Preferences.md (from the given work hours) and the _views/*.base files. Existing files are kept unless overwrite=true (Follow-ups.md is always kept)."""
        return _json(store.init(work_start, work_end, buffer_minutes, overwrite, created_by))

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
        """Render Daily/YYYY-MM-DD.md from labels + items (items default to the vault_inbox_prepare cache): inbox table sorted act/reply/waiting/fyi/noise with hidden entry_id comments, To do, Waiting on (rows also go to Follow-ups.md), Calendar from events with occurrence_key comments, Watch out (given bullets + clashes + missing prep notes). A second run on the same day appends only the new rows under '## Update'. Returns {path, action (created/appended/unchanged), rows_written, duplicates_skipped, followups_added, calendar_rows, unlabelled}."""
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
        """Build the email note from outlook_get_mail JSON (body_trimmed when present), write it (upsert: an existing note gets an Update with the new summary), create or update the sender's person note (last_contact, aliases, '## Emails' line), and add a Follow-ups row when status is waiting. Returns {path, action, status, person_path, person_action, followup_added}."""
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
    ) -> str:
        """Everything the vault knows for a prep in one call: {existing_note, existing_status, previous_occurrence: {path, date, open_actions} or null, people: [{email, name, path, last_contact, company, last_emails (up to 3 '## Emails' lines)}], followups_open: [rows mentioning any attendee]}."""
        return _json(workflows.prep_context(occurrence_key, global_id, attendees))

    @mcp.tool(
        name="vault_weekly_facts",
        annotations={"title": "Facts for the weekly review", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    )
    @_guard
    def vault_weekly_facts(
        week: Annotated[str, Field(description="ISO week, e.g. 2026-W34.")],
        today: Annotated[Optional[str], Field(description="Local date YYYY-MM-DD; defaults to the machine date.")] = None,
    ) -> str:
        """Computed from the vault only: {week, start, end, open_from_inbox: [{date, label, subject, from, entry_id, note, daily}] (act/reply rows of the week's daily notes not ticked and with no email note of status done), waiting: [Follow-ups Open rows with age_days], meetings_held: [{path, subject, date, unchecked_actions}], no_notes: [past meetings still 'upcoming'], quiet_people: [{name, email, path, last_contact, days}] over 30 days}."""
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


__all__ = ["build_server", "register", "SCHEMAS"]
