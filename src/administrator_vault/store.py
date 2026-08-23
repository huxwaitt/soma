"""The vault on disk: root lookup, path rules, and every read/write the tools do.

All paths that go in or come out are vault-relative with forward slashes,
for example ``Administrator/Emails/2026-08-21 Q3 budget.md``. Every write is
refused outside ``Administrator/``.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from administrator_vault import frontmatter as fmt
from administrator_vault import notes
from administrator_vault.notes import ADMIN_DIR, NoteError

VIEWS_DIR = Path(__file__).with_name("views")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_COMMENT_RE = re.compile(r"<!--\s*([A-Za-z_]+):\s*(.*?)\s*-->")


class VaultError(ValueError):
    """Vault not usable or a path rule was broken."""


# ------------------------------------------------------------------ root/paths


def vault_root() -> Path:
    raw = os.environ.get("ADMINISTRATOR_VAULT", "").strip()
    if not raw:
        raise VaultError(
            "ADMINISTRATOR_VAULT is not set. Set it to the absolute path of your "
            "Obsidian vault (for example C:\\Users\\you\\Documents\\Vault) and start a new session."
        )
    p = Path(raw)
    if not p.is_absolute():
        raise VaultError(f"ADMINISTRATOR_VAULT must be an absolute path, got {raw!r}.")
    if not p.is_dir():
        raise VaultError(f"ADMINISTRATOR_VAULT points to {raw!r}, which is not a directory.")
    return p


def vault_name(root: Path) -> str:
    return os.environ.get("ADMINISTRATOR_VAULT_NAME", "").strip() or root.name


def under_user_profile(root: Path) -> bool:
    profile = Path(os.environ.get("USERPROFILE") or Path.home())
    try:
        root.resolve().relative_to(profile.resolve())
        return True
    except ValueError:
        return False


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def resolve(root: Path, relative: str) -> Path:
    """Turn a vault-relative path into an absolute one, refusing anything
    outside ``Administrator/``."""
    raw = (relative or "").strip().replace("\\", "/")
    if not raw:
        raise VaultError("Path is empty.")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise VaultError(f"Path must be vault-relative, not absolute: {relative!r}.")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise VaultError(f"Path may not contain '..': {relative!r}.")
    if not parts or parts[0] != ADMIN_DIR:
        raise VaultError(f"Refused: {relative!r} is outside {ADMIN_DIR}/. The plugin only writes there.")
    p = root.joinpath(*parts)
    try:
        p.resolve().relative_to((root / ADMIN_DIR).resolve())
    except ValueError:
        raise VaultError(f"Refused: {relative!r} resolves outside {ADMIN_DIR}/.") from None
    return p


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def write_text(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if not text.endswith("\n"):
        text += "\n"
    p.write_text(text, encoding="utf-8", newline="\n")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- status/init


def status() -> dict[str, Any]:
    raw = os.environ.get("ADMINISTRATOR_VAULT", "").strip()
    p = Path(raw) if raw else None
    exists = bool(p and p.exists())
    is_dir = bool(p and p.is_dir())
    admin = p / ADMIN_DIR if p else None
    out: dict[str, Any] = {
        "vault": raw,
        "exists": exists,
        "is_dir": is_dir,
        "administrator_dir_exists": bool(admin and admin.is_dir()),
        "folders": {f: bool(admin and (admin / f).is_dir()) for f in notes.FOLDERS},
        "files": {f: bool(admin and (admin / f).is_file()) for f in notes.FILES},
        "under_user_profile": bool(p and is_dir and under_user_profile(p)),
        "vault_name": vault_name(p) if p else "",
    }
    return out


def followups_template(created_by: str) -> str:
    head = "| " + " | ".join(notes.FOLLOWUPS_OPEN_HEADER) + " |\n| --- | --- | --- | --- | --- |\n"
    done = "| " + " | ".join(notes.FOLLOWUPS_DONE_HEADER) + " |\n| --- | --- | --- | --- | --- |\n"
    fm = fmt.format_frontmatter({"type": "followups", "source": "outlook", "created_by": created_by})
    return (
        fm
        + "\n# Follow-ups\n\n"
        "Things I am waiting on. One row per thread. Move a row to Done when it is closed.\n\n"
        "## Open\n\n" + head + "\n## Done\n\n" + done
    )


def preferences_template(work_start: str, work_end: str, buffer_minutes: int, created_by: str) -> str:
    fm = fmt.format_frontmatter(
        {
            "type": "preferences",
            "source": "administrator",
            "work_start": work_start,
            "work_end": work_end,
            "timezone": "local — the timezone Outlook reports in outlook_whoami; all times in this file are in it",
            "buffer_minutes": buffer_minutes,
            "no_meeting_blocks": [f"Fri 13:00-{work_end}"],
            "max_meetings_per_day": 5,
            "default_duration": 30,
            "default_location": "Teams",
            "preferred_days": ["Tue", "Wed", "Thu"],
            "created_by": created_by,
        }
    )
    return fm + (
        "\n# Scheduling preferences\n\n"
        "Edit the frontmatter above. The plugin reads it before suggesting or booking any meeting. "
        "Plain words on what each key does:\n\n"
        "- `work_start` / `work_end` — the only hours a slot may be suggested in. 24-hour `\"HH:MM\"`, quoted.\n"
        "- `timezone` — a note to yourself; the plugin always works in the local time Outlook reports. "
        "Change your Windows timezone, not this line, if you travel.\n"
        "- `buffer_minutes` — free minutes the plugin keeps before and after every existing meeting. `0` switches it off.\n"
        "- `no_meeting_blocks` — weekday plus a time range, one per line, that are never offered: "
        "`\"Fri 13:00-17:30\"`, `\"Mon 09:00-10:00\"`. Weekday names: Mon Tue Wed Thu Fri Sat Sun. "
        "An empty list `[]` means none.\n"
        "- `max_meetings_per_day` — days that already have this many meetings are skipped. `0` means no limit.\n"
        "- `default_duration` — minutes, used when you do not say how long.\n"
        "- `default_location` — used when you do not say where. `\"Teams\"`, a room name, or `\"\"` for none.\n"
        "- `preferred_days` — days listed here are shown first when there is a choice. An empty list `[]` means no preference.\n\n"
        "## Notes\n\n"
        "Anything you write below this line is yours; the plugin never touches it.\n"
    )


def init(
    work_start: str = "09:00",
    work_end: str = "17:00",
    buffer_minutes: int = 15,
    overwrite: bool = False,
    created_by: str = "administrator-vault",
) -> dict[str, Any]:
    """Create the Administrator/ tree, Follow-ups.md, Preferences.md and the
    _views/*.base files. ``overwrite`` re-writes Preferences.md and the views;
    Follow-ups.md is never overwritten (it holds data)."""
    for t in (work_start, work_end):
        if not re.match(r"^\d{2}:\d{2}$", t):
            raise VaultError(f"Work hours must look like HH:MM, got {t!r}.")
    root = vault_root()
    created: list[str] = []
    skipped: list[str] = []
    admin = root / ADMIN_DIR
    for folder in ("",) + notes.FOLDERS:
        p = admin / folder if folder else admin
        if p.is_dir():
            skipped.append(rel(root, p) + "/")
        else:
            p.mkdir(parents=True, exist_ok=True)
            created.append(rel(root, p) + "/")

    fu = admin / "Follow-ups.md"
    if fu.exists():
        skipped.append(rel(root, fu))
    else:
        write_text(fu, followups_template(created_by))
        created.append(rel(root, fu))

    pref = admin / "Preferences.md"
    if pref.exists() and not overwrite:
        skipped.append(rel(root, pref))
    else:
        write_text(pref, preferences_template(work_start, work_end, buffer_minutes, created_by))
        created.append(rel(root, pref))

    from administrator_vault.workflows import rules_template  # local import: workflows imports store

    rules = admin / "Rules.md"
    if rules.exists():
        skipped.append(rel(root, rules))  # holds the user's rules; never overwritten
    else:
        write_text(rules, rules_template(created_by))
        created.append(rel(root, rules))

    if VIEWS_DIR.is_dir():
        for src in sorted(VIEWS_DIR.glob("*.base")):
            dst = admin / "_views" / src.name
            if dst.exists() and not overwrite:
                skipped.append(rel(root, dst))
            else:
                write_text(dst, src.read_text(encoding="utf-8"))
                created.append(rel(root, dst))
    return {"created": created, "skipped": skipped}


# ---------------------------------------------------------------- find/list


def _iter_notes(root: Path, note_type: str):
    folder = root / notes.folder_of(note_type)
    if not folder.is_dir():
        return
    for p in sorted(folder.glob("*.md")):
        try:
            fm, _block, _body = fmt.split_note(read_text(p))
        except (fmt.FrontmatterError, UnicodeDecodeError):
            continue
        if fm.get("type") != note_type:
            continue
        yield p, fm


def _pick(fm: dict[str, Any], fields: Optional[list[str]]) -> dict[str, Any]:
    """Only the named frontmatter keys (all of them when ``fields`` is empty)."""
    if not fields:
        return fm
    return {k: fm[k] for k in fields if k in fm}


def find(note_type: str, identity: Any, fields: Optional[list[str]] = None) -> dict[str, Any]:
    root = vault_root()
    ident = notes.normalize_identity(note_type, identity)
    hits = [(p, fm) for p, fm in _iter_notes(root, note_type) if notes.matches(note_type, fm, ident)]
    hits.sort(key=lambda h: notes.sort_value(note_type, h[1]), reverse=True)
    if not hits:
        return {"found": False, "path": None, "frontmatter": None, "matches": []}
    p, fm = hits[0]
    return {
        "found": True,
        "path": rel(root, p),
        "frontmatter": _pick(fm, fields),
        "matches": [rel(root, h[0]) for h in hits],
    }


def list_notes(
    note_type: str, since: Optional[str] = None, limit: int = 200, fields: Optional[list[str]] = None
) -> list[dict[str, Any]]:
    root = vault_root()
    items = [(p, fm) for p, fm in _iter_notes(root, note_type)]
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            raise VaultError(f"'since' must be an ISO date or datetime, got {since!r}.") from None
        since_key = notes.sort_value(note_type, {notes.schema(note_type)["date_key"]: since_dt.isoformat()})
        items = [(p, fm) for p, fm in items if notes.sort_value(note_type, fm) >= since_key]
    items.sort(key=lambda h: notes.sort_value(note_type, h[1]), reverse=True)
    return [{"path": rel(root, p), "frontmatter": _pick(fm, fields)} for p, fm in items[:limit]]


# ---------------------------------------------------------------- read/write


def read(path: str) -> dict[str, Any]:
    root = vault_root()
    p = resolve(root, path)
    if not p.is_file():
        raise VaultError(f"No such note: {path!r}.")
    fm, _block, body = fmt.split_note(read_text(p))
    sections = [m.group(2) for line in body.split("\n") if (m := _HEADING_RE.match(line))]
    return {"path": rel(root, p), "frontmatter": fm, "body": body, "sections": sections}


def _free_filename(folder: Path, base: str) -> Path:
    stem, ext = base[:-3], ".md"
    candidate = folder / base
    n = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({n}){ext}"
        n += 1
    return candidate


def write(note_type: str, frontmatter: dict[str, Any], body: str, mode: str = "create") -> dict[str, Any]:
    if mode not in ("create", "append", "upsert"):
        raise VaultError(f"mode must be create, append or upsert, got {mode!r}.")
    root = vault_root()
    fm = dict(frontmatter or {})
    fm.setdefault("type", note_type)
    notes.validate(note_type, fm)
    ident = notes.identity_of(note_type, fm)
    if not any(ident.values()):
        raise NoteError(f"{note_type} note has no identity ({', '.join(ident)} all empty).")

    hit = find(note_type, ident)
    if hit["found"]:
        if mode == "create":
            raise VaultError(f"A {note_type} note with this identity already exists: {hit['path']}.")
        return _append(root, hit["path"], fm, body, ident)
    if mode == "append":
        raise VaultError(f"No {note_type} note with identity {ident} to append to.")
    return _create(root, note_type, fm, body, ident)


def _create(root: Path, note_type: str, fm: dict[str, Any], body: str, ident: dict[str, Any]) -> dict[str, Any]:
    folder = root / notes.folder_of(note_type)
    folder.mkdir(parents=True, exist_ok=True)
    p = _free_filename(folder, notes.base_filename(note_type, fm))
    text = fmt.format_frontmatter(fm) + "\n" + (body or "").replace("\r\n", "\n").rstrip("\n") + "\n"
    write_text(p, text)
    return {"path": rel(root, p), "action": "created", "identity": ident}


def _append(root: Path, path: str, fm: dict[str, Any], body: str, ident: dict[str, Any]) -> dict[str, Any]:
    p = resolve(root, path)
    text = read_text(p)
    old_fm, block, old_body = fmt.split_note(text)
    updates = {k: fm[k] for k in notes.REPLACEABLE_KEYS if k in fm and fm[k] != old_fm.get(k)}
    changed_keys = list(updates)
    new_block = fmt.replace_keys(block, updates) if updates else block
    if "aliases" in fm and isinstance(fm["aliases"], list):
        old_aliases = old_fm.get("aliases") or []
        if isinstance(old_aliases, str):
            old_aliases = [old_aliases] if old_aliases else []
        merged = list(old_aliases)
        for a in fm["aliases"]:
            if a and a not in merged:
                merged.append(a)
        if merged != list(old_aliases):
            new_block = fmt.replace_list_key(new_block, "aliases", merged)
            changed_keys.append("aliases")
    stamp = now_iso()
    new_body = old_body.rstrip("\n") + "\n\n## Update " + stamp + "\n\n" + (body or "").rstrip("\n") + "\n"
    write_text(p, "---\n" + new_block + "\n---\n\n" + new_body.lstrip("\n"))
    return {
        "path": rel(root, p),
        "action": "appended",
        "identity": ident,
        "update_heading": "Update " + stamp,
        "frontmatter_changed": changed_keys,
    }


# ---------------------------------------------------------------- tables


def _section_range(lines: list[str], section: str) -> Optional[tuple[int, int]]:
    """(heading index, end index exclusive) of the ``## <section>`` block."""
    start = None
    level = 0
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if not m:
            continue
        if start is None:
            if m.group(2).strip() == section.strip():
                start, level = i, len(m.group(1))
        elif len(m.group(1)) <= level:
            return start, i
    return (start, len(lines)) if start is not None else None


def _table_rows(lines: list[str], lo: int, hi: int) -> list[int]:
    """Indexes of the lines of the first table inside lines[lo:hi]."""
    rows: list[int] = []
    for i in range(lo, hi):
        if lines[i].lstrip().startswith("|"):
            rows.append(i)
        elif rows:
            break
    return rows


def _unescape_cell(text: str) -> str:
    return text.replace("\\|", "|")


def _cells(line: str) -> list[str]:
    """Cells of a table line, with ``\\|`` turned back into ``|``.

    The inverse of ``_row_line``: a cell (or a hidden key comment inside it,
    such as an ``occurrence_key`` ``GID|start``) may hold a pipe, which is
    stored escaped so the table stays one row per line."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [_unescape_cell(c.strip()) for c in re.split(r"(?<!\\)\|", s)]


def _row_line(cells: list[str]) -> str:
    return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"


def _comment_key(line: str) -> Optional[str]:
    m = _COMMENT_RE.search(line)
    return _unescape_cell(m.group(2)) if m else None


def _header_for(p: Path, section: str, n: int) -> list[str]:
    if p.name == "Follow-ups.md":
        return notes.FOLLOWUPS_DONE_HEADER if section.strip().lower() == "done" else notes.FOLLOWUPS_OPEN_HEADER
    raise VaultError(
        f"Section '{section}' in {p.name} has no table yet; pass 'header' (a list of {n} column names)."
    )


def _ensure_table(lines: list[str], p: Path, section: str, n: int, header: Optional[list[str]]) -> list[int]:
    rng = _section_range(lines, section)
    if rng is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([f"## {section}", ""])
        rng = (len(lines) - 2, len(lines))
    lo, hi = rng
    rows = _table_rows(lines, lo + 1, hi)
    if rows:
        return rows
    cols = header or _header_for(p, section, n)
    table = [_row_line(cols), "| " + " | ".join("---" for _ in cols) + " |"]
    if lo + 1 < len(lines) and not lines[lo + 1].strip():
        at = lo + 2
        lines[at:at] = table + [""]
        first = at
    else:
        at = lo + 1
        lines[at:at] = [""] + table + [""]
        first = at + 1
    return [first, first + 1]


def append_row(
    path: str,
    section: str,
    row: list[str],
    dedupe_key: Optional[str] = None,
    header: Optional[list[str]] = None,
    key_label: str = "entry_id",
) -> dict[str, Any]:
    root = vault_root()
    p = resolve(root, path)
    if not p.is_file():
        raise VaultError(f"No such note: {path!r}.")
    if not row:
        raise VaultError("row is empty.")
    cells = [str(c) for c in row]
    text = read_text(p)
    lines = text.split("\n")
    if dedupe_key:
        for i, line in enumerate(lines):
            if line.lstrip().startswith("|") and _comment_key(line) == dedupe_key:
                return {"appended": False, "path": rel(root, p), "reason": "duplicate", "line": i + 1}
        cells[-1] = (cells[-1] + f" <!-- {key_label}: {dedupe_key} -->").strip()
    rows = _ensure_table(lines, p, section, len(cells), header)
    ncols = len(_cells(lines[rows[0]]))
    if len(cells) != ncols:
        raise VaultError(f"Row has {len(cells)} cells but the table under '{section}' has {ncols} columns.")
    line = _row_line(cells)
    lines.insert(rows[-1] + 1, line)
    write_text(p, "\n".join(lines))
    return {"appended": True, "path": rel(root, p), "section": section, "row": line}


def move_row(
    path: str,
    from_section: str,
    to_section: str,
    dedupe_key: str,
    set_last_cell: Optional[str] = None,
) -> dict[str, Any]:
    root = vault_root()
    p = resolve(root, path)
    if not p.is_file():
        raise VaultError(f"No such note: {path!r}.")
    if not dedupe_key:
        raise VaultError("dedupe_key is required to find the row.")
    lines = read_text(p).split("\n")
    rng = _section_range(lines, from_section)
    if rng is None:
        return {"moved": False, "path": rel(root, p), "reason": f"no section '{from_section}'"}
    rows = _table_rows(lines, rng[0] + 1, rng[1])
    idx = next((i for i in rows[2:] if _comment_key(lines[i]) == dedupe_key), None)
    if idx is None:
        return {"moved": False, "path": rel(root, p), "reason": "not found"}
    cells = _cells(lines[idx])
    if set_last_cell is not None:
        m = _COMMENT_RE.search(cells[-1])
        cells[-1] = (set_last_cell + " " + m.group(0)).strip() if m else set_last_cell
    del lines[idx]
    target = _ensure_table(lines, p, to_section, len(cells), None)
    line = _row_line(cells)
    lines.insert(target[-1] + 1, line)
    write_text(p, "\n".join(lines))
    return {"moved": True, "path": rel(root, p), "from": from_section, "to": to_section, "row": line}
