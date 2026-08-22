"""FastMCP server ``vault``: the administrator plugin's note writer."""

from __future__ import annotations

import functools
import json
from typing import Annotated, Any, Callable, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from administrator_vault import store
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
    def vault_find(type: NoteType, identity: Identity) -> str:
        """Find the note of a type with this identity by reading frontmatter, not filenames. Returns {found, path, frontmatter, matches}; a global_id-only meeting identity returns the newest occurrence first."""
        return _json(store.find(type, identity))

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
    def vault_list(type: NoteType, since: Since = None, limit: Limit = 200) -> str:
        """List notes of a type, newest first by its date key (email: received, meeting: start, person: last_contact, daily: date, weekly: start): [{path, frontmatter}]."""
        return _json(store.list_notes(type, since, limit))


__all__ = ["build_server", "register", "SCHEMAS"]
