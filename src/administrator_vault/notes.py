"""Note types: required frontmatter keys, identity rules, slug and filename rules.

This is the Python form of ``skills/administrator/references/vault.md`` and
``skills/meetings/references/meeting-note.md`` in the administrator plugin.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

ADMIN_DIR = "Administrator"

FOLDERS = (
    "Daily", "Emails", "Meetings", "Attachments", "Weekly", "Teams", "Time-blocks", "_views",
    "Wiki", "Wiki/People", "Wiki/Orgs", "Wiki/Topics", "Wiki/Decisions", "Wiki/Howto",
)
FILES = ("Follow-ups.md", "Preferences.md", "Rules.md", "Priorities.md")

# type -> (folder under Administrator/, required frontmatter keys, date key)
SCHEMAS: dict[str, dict[str, Any]] = {
    "email": {
        "folder": "Emails",
        "required": (
            "type", "source", "internet_message_id", "entry_id", "conversation_id",
            "subject", "from", "from_name", "from_link", "to", "cc", "received",
            "status", "created_by",
        ),
        "date_key": "received",
    },
    "meeting": {
        "folder": "Meetings",
        "required": (
            "type", "source", "global_id", "occurrence_key", "subject", "start", "end",
            "location", "organizer", "organizer_link", "attendees", "attendee_links",
            "is_recurring", "status", "created_by",
        ),
        "date_key": "start",
    },
    "person": {
        "folder": "Wiki/People",
        "required": ("type", "name", "email", "aliases", "last_contact", "created_by"),
        "date_key": "last_contact",
    },
    "daily": {
        "folder": "Daily",
        "required": (
            "type", "date", "folder", "since", "inbox_checked", "mails_seen",
            "status", "created_by",
        ),
        "date_key": "date",
    },
    "weekly": {
        "folder": "Weekly",
        "required": ("type", "week", "start", "end", "created_by"),
        "date_key": "start",
    },
    "chat": {  # one Teams chat on one day; record_id = "<chat_id>|<date>"
        "folder": "Teams",
        "required": (
            "type", "source", "chat_id", "chat_title", "date", "account", "members",
            "record_id", "messages", "first", "last", "created_by",
        ),
        "date_key": "date",
    },
    "time-block": {  # the plan note of one week (Time-blocks/<week>.md)
        "folder": "Time-blocks",
        "required": ("type", "source", "week", "start", "end", "planned", "created_by"),
        "date_key": "start",
    },
}

# Keys vault_write may replace on an existing note (everything else is frozen).
REPLACEABLE_KEYS = ("status", "last_contact", "inbox_checked", "mails_seen", "wiki", "messages", "last", "planned")

FOLLOWUPS_OPEN_HEADER = ["Since", "Who", "What", "Email", "Last checked"]
FOLLOWUPS_DONE_HEADER = ["Since", "Who", "What", "Email", "Closed"]


class NoteError(ValueError):
    """A note does not follow the rules (bad type, missing keys, bad identity)."""


def schema(note_type: str) -> dict[str, Any]:
    try:
        return SCHEMAS[note_type]
    except KeyError:
        raise NoteError(f"Unknown note type {note_type!r}. Known: {', '.join(SCHEMAS)}.") from None


def validate(note_type: str, fm: dict[str, Any]) -> None:
    sc = schema(note_type)
    missing = [k for k in sc["required"] if k not in fm]
    if missing:
        raise NoteError(f"{note_type} note is missing frontmatter keys: {', '.join(missing)}.")
    if fm.get("type") != note_type:
        raise NoteError(f"frontmatter 'type' is {fm.get('type')!r}, expected {note_type!r}.")


# ------------------------------------------------------------------- identity


def identity_of(note_type: str, fm: dict[str, Any]) -> dict[str, Any]:
    """The identity keys of a note, taken from its frontmatter."""
    if note_type == "email":
        return {
            "internet_message_id": str(fm.get("internet_message_id") or ""),
            "entry_id": str(fm.get("entry_id") or ""),
        }
    if note_type == "meeting":
        return {
            "occurrence_key": str(fm.get("occurrence_key") or ""),
            "global_id": str(fm.get("global_id") or ""),
        }
    if note_type == "person":
        return {"email": str(fm.get("email") or "")}
    if note_type == "daily":
        return {"date": str(fm.get("date") or "")}
    if note_type == "weekly":
        return {"week": str(fm.get("week") or "")}
    if note_type == "chat":
        return {"chat_id": str(fm.get("chat_id") or ""), "date": str(fm.get("date") or "")[:10]}
    if note_type == "time-block":
        return {"week": str(fm.get("week") or "")}
    schema(note_type)
    return {}


def normalize_identity(note_type: str, identity: Any) -> dict[str, Any]:
    """Accept a plain string or a dict and return the identity dict for the type."""
    if isinstance(identity, dict):
        ident = {k: ("" if v is None else str(v)) for k, v in identity.items()}
    elif isinstance(identity, str):
        s = identity.strip()
        if note_type == "email":
            ident = {"internet_message_id": s, "entry_id": s, "_any": True}
        elif note_type == "meeting":
            ident = {"occurrence_key": s, "global_id": s, "_any": True}
        elif note_type == "person":
            ident = {"email": s}
        elif note_type == "daily":
            ident = {"date": s}
        elif note_type == "weekly":
            ident = {"week": s}
        elif note_type == "chat":
            # the record_id form "<chat_id>|<date>"
            chat_id, _sep, day = s.rpartition("|")
            if not chat_id or not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
                raise NoteError(f"identity for a chat note must be 'chat_id|YYYY-MM-DD', got {s!r}.")
            ident = {"chat_id": chat_id, "date": day}
        elif note_type == "time-block":
            ident = {"week": s}
        else:
            schema(note_type)
            ident = {}
    else:
        raise NoteError("identity must be a string or an object.")
    if not any(v for k, v in ident.items() if k != "_any"):
        raise NoteError(f"identity for a {note_type} note is empty.")
    return ident


def matches(note_type: str, fm: dict[str, Any], identity: dict[str, Any]) -> bool:
    """Does the note with frontmatter ``fm`` have this identity?

    email: internet_message_id when the identity has one, else entry_id.
    meeting: occurrence_key when the identity has one, else global_id.
    person: email, case-insensitive, also against ``aliases``.
    daily: date. weekly: week. chat: chat_id and date. time-block: week.
    """
    if fm.get("type") not in (None, note_type):
        return False
    loose = bool(identity.get("_any"))  # a plain string: try every identity key
    if note_type == "email":
        imid = identity.get("internet_message_id") or ""
        if imid:
            if str(fm.get("internet_message_id") or "") == imid:
                return True
            if not loose:
                return False
        eid = identity.get("entry_id") or ""
        return bool(eid) and str(fm.get("entry_id") or "") == eid
    if note_type == "meeting":
        key = identity.get("occurrence_key") or ""
        if key:
            if str(fm.get("occurrence_key") or "") == key:
                return True
            if not loose:
                return False
        gid = identity.get("global_id") or ""
        return bool(gid) and str(fm.get("global_id") or "") == gid
    if note_type == "person":
        wanted = (identity.get("email") or "").strip().lower()
        if not wanted:
            return False
        if str(fm.get("email") or "").strip().lower() == wanted:
            return True
        aliases = fm.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        return any(str(a).strip().lower() == wanted for a in aliases)
    if note_type == "daily":
        return bool(identity.get("date")) and str(fm.get("date") or "") == identity["date"]
    if note_type == "weekly":
        return bool(identity.get("week")) and str(fm.get("week") or "") == identity["week"]
    if note_type == "chat":
        chat_id, day = identity.get("chat_id") or "", (identity.get("date") or "")[:10]
        return bool(chat_id and day) and str(fm.get("chat_id") or "") == chat_id and str(fm.get("date") or "")[:10] == day
    if note_type == "time-block":
        return bool(identity.get("week")) and str(fm.get("week") or "") == identity["week"]
    return False


# ----------------------------------------------------------------- slug / names

_PREFIX_RE = re.compile(r"^(?:re|fw|fwd|aw|wg|tr|sv)\s*:\s*", re.IGNORECASE)
_MEETING_PREFIX_RE = re.compile(
    r"^(?:re|fw|fwd|aw|wg|tr|sv|canceled|cancelled|abgesagt|updated|aktualisiert)\s*:\s*",
    re.IGNORECASE,
)
_ILLEGAL_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WS_RE = re.compile(r"\s+")


def strip_prefixes(subject: str, *, meeting: bool = False) -> str:
    rx = _MEETING_PREFIX_RE if meeting else _PREFIX_RE
    s = subject.strip()
    while True:
        new = rx.sub("", s, count=1).lstrip()
        if new == s:
            return s
        s = new


def sanitize(text: str, max_len: int = 60) -> str:
    s = _ILLEGAL_RE.sub("_", text or "")
    s = _WS_RE.sub(" ", s).strip().rstrip(".").strip()
    s = s[:max_len].strip().rstrip(".").strip()
    return s


def slug(subject: str, *, meeting: bool = False) -> str:
    s = sanitize(strip_prefixes(subject or "", meeting=meeting))
    return s or "(no subject)"


def person_filename(name: str, email: str = "") -> str:
    s = sanitize(name or "")
    if not s and email:
        s = sanitize(email.split("@", 1)[0])
    return s or "(unknown)"


def _date_part(value: Any, what: str) -> str:
    s = str(value or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}", s):
        raise NoteError(f"'{what}' must be an ISO date or datetime, got {s!r}.")
    return s[:10]


def _time_part(value: Any, what: str) -> str:
    s = str(value or "").strip()
    m = re.match(r"^\d{4}-\d{2}-\d{2}[T ](\d{2}):(\d{2})", s)
    if not m:
        raise NoteError(f"'{what}' must be an ISO datetime, got {s!r}.")
    return m.group(1) + m.group(2)


def base_filename(note_type: str, fm: dict[str, Any]) -> str:
    """Filename (without folder and without a collision suffix) for a note."""
    if note_type == "email":
        return f"{_date_part(fm.get('received'), 'received')} {slug(str(fm.get('subject') or ''))}.md"
    if note_type == "meeting":
        start = fm.get("start")
        return (
            f"{_date_part(start, 'start')} {_time_part(start, 'start')} "
            f"{slug(str(fm.get('subject') or ''), meeting=True)}.md"
        )
    if note_type == "person":
        return f"{person_filename(str(fm.get('name') or ''), str(fm.get('email') or ''))}.md"
    if note_type == "daily":
        return f"{_date_part(fm.get('date'), 'date')}.md"
    if note_type in ("weekly", "time-block"):
        week = str(fm.get("week") or "").strip()
        if not re.match(r"^\d{4}-W\d{2}$", week):
            raise NoteError(f"'week' must look like 2026-W34, got {week!r}.")
        return f"{week}.md"
    if note_type == "chat":
        title = str(fm.get("chat_title") or "").strip() or str(fm.get("chat_id") or "")
        return f"{_date_part(fm.get('date'), 'date')} {slug(title)}.md"
    schema(note_type)
    raise NoteError(f"No filename rule for {note_type}.")


def folder_of(note_type: str) -> str:
    return f"{ADMIN_DIR}/{schema(note_type)['folder']}"


def sort_value(note_type: str, fm: dict[str, Any]) -> str:
    """A string that sorts newest-first when sorted descending."""
    raw = str(fm.get(schema(note_type)["date_key"]) or "")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return raw
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")
