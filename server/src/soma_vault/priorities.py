"""Priorities.md: the material for a ranked suggestion, and the confirmed
list written under ``## Priorities``.

``candidates`` reads only: the active wiki topics, the open follow-ups, the
open act / reply rows of the latest weekly and the numbered lines already in
the file, so the model can propose a ranking. ``write`` replaces the numbered
list (and the plugin's own stamp comment) under the ``## Priorities``
heading and nothing else: frontmatter, the text above the heading and every
other section stay as they are.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

from soma_vault import frontmatter as fmt
from soma_vault import store, timeblock, wiki, workflows
from soma_vault.store import VaultError, read_text
from soma_vault.timeblock import PRIORITIES_PATH, _numbered_lines
from soma_vault.workflows import CREATED_BY, _s

SECTION = "Priorities"
MAX_LINES = 7
MAX_CHARS = 120
TOPIC_LIMIT = 10
FOLLOWUP_LIMIT = 5
WEEKLY_LIMIT = 5
STAMP = "suggested by soma, confirmed"

_STAMP_RE = re.compile(rf"^<!--\s*{re.escape(STAMP)} \d{{4}}-\d{{2}}-\d{{2}}\s*-->$")
_COMMENT_LINE_RE = re.compile(r"^<!--.*-->$")
_LEADING_NUMBER_RE = re.compile(r"^\d+[.)]\s+")


# ------------------------------------------------------------------ candidates


def _topic_rows(pages: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    out = []
    for t in timeblock._active_topics(pages)[:TOPIC_LIMIT]:
        fm = t["fm"]
        out.append(
            {
                "title": t["name"],
                "page": t["page"],
                "status": _s(fm.get("status")) or "active",
                "owner": _s(fm.get("owner")),
                "due": t["due"].isoformat() if t["due"] else None,
                "open_items": t["open_items"],
                "verified": _s(fm.get("verified") or fm.get("created"))[:10] or None,
                "summary": " ".join(_s(fm.get("summary")).split()),
            }
        )
    return out


def _followup_rows(root: Path, today: date) -> list[dict[str, Any]]:
    """What other people owe the user: the open items of the pages, oldest first."""
    out = []
    for c in wiki.commitments(root, owner="others"):
        since = workflows._date_of(c["since"])
        out.append(
            {
                "since": since,
                "who": c["owner_name"],
                "what": c["text"],
                "age_days": (today - date.fromisoformat(since)).days if since else None,
            }
        )
    out.sort(key=lambda r: r["since"] or "9999")
    return out[:FOLLOWUP_LIMIT]


def _weekly_open(today: date) -> list[dict[str, Any]]:
    latest = store.list_notes("weekly", limit=1, fields=["week"])
    week = _s(latest[0]["frontmatter"].get("week")) if latest else ""
    if not week:
        return []
    rows = workflows.weekly_facts(week, today.isoformat())["open_from_inbox"]
    return [{"subject": r["subject"], "label": r["label"], "date": r["date"]} for r in rows[:WEEKLY_LIMIT]]


def _current(root: Path) -> list[str]:
    p = root / PRIORITIES_PATH
    if not p.is_file():
        return []
    try:
        body = fmt.split_note(read_text(p))[2]
    except (fmt.FrontmatterError, UnicodeDecodeError):
        return []
    return _numbered_lines(body)


def candidates(today: Optional[str] = None) -> dict[str, Any]:
    """``vault_priorities_write(action="candidates")``: {topics, followups, weekly_open, current}."""
    root = store.vault_root()
    today_d = timeblock._parse_day(today, "today") if today else date.today()
    return {
        "path": PRIORITIES_PATH,
        "topics": _topic_rows(wiki._all_pages(root)),
        "followups": _followup_rows(root, today_d),
        "weekly_open": _weekly_open(today_d),
        "current": _current(root),
    }


# ------------------------------------------------------------------ write


def _clean_lines(lines: Optional[list[str]]) -> list[str]:
    if not isinstance(lines, list) or not lines:
        raise VaultError("lines must hold 1 to 7 priorities, one per entry.")
    if len(lines) > MAX_LINES:
        raise VaultError(f"lines holds {len(lines)} entries; at most {MAX_LINES} priorities are kept.")
    out = []
    for n, raw in enumerate(lines, 1):
        text = " ".join(_s(raw).split())
        text = _LEADING_NUMBER_RE.sub("", text)
        if not text:
            raise VaultError(f"Line {n} is empty.")
        if len(text) > MAX_CHARS:
            raise VaultError(f"Line {n} has {len(text)} characters; the limit is {MAX_CHARS}.")
        if text.startswith("#"):
            raise VaultError(f"Line {n} starts with '#'; a priority is a link or plain words, not a heading.")
        if "<!--" in text or "-->" in text:
            raise VaultError(f"Line {n} holds a comment; pass a note instead.")
        out.append(text)
    return out


def _clean_note(note: Optional[str]) -> Optional[str]:
    text = " ".join(_s(note).split())
    if not text:
        return None
    if "-->" in text:
        raise VaultError("note may not contain '-->'.")
    return text


def write(lines: Optional[list[str]], note: Optional[str] = None, created_by: str = CREATED_BY, today: Optional[str] = None) -> dict[str, Any]:
    """``vault_priorities_write(action="write")``: the numbered list under
    ``## Priorities`` replaced by ``lines`` plus the stamp comment (and the
    note as a second comment). Everything else in the file is kept."""
    lines = _clean_lines(lines)
    note = _clean_note(note)
    today_d = timeblock._parse_day(today, "today") if today else date.today()
    root = store.vault_root()
    p = root / PRIORITIES_PATH
    if not p.is_file():
        store.write_text(p, store.priorities_template(created_by))
    text = read_text(p)
    rows = text.split("\n")
    found = next(((lo, hi) for level, heading, lo, hi in workflows._sections(text) if level == 2 and heading.strip().lower() == SECTION.lower()), None)
    if found is None:
        if rows and rows[-1] == "":
            rows.pop()
        rows.extend(["", f"## {SECTION}", ""])
        found = (len(rows), len(rows))
    lo, hi = found
    remove: set[int] = set()
    i = lo
    while i < hi:
        s = rows[i].strip()
        if timeblock._NUMBERED_RE.match(rows[i]):
            remove.add(i)
        elif _STAMP_RE.match(s):
            remove.add(i)
            if i + 1 < hi and _COMMENT_LINE_RE.match(rows[i + 1].strip()):
                remove.add(i + 1)
                i += 1
        i += 1
    previous = _numbered_lines("\n".join(rows[i] for i in sorted(remove)))
    # the user's other lines in the section stay; the new list goes where the old one was
    kept: list[str] = []
    at: Optional[int] = None
    for i in range(lo, hi):
        if i in remove:
            at = len(kept) if at is None else at
        else:
            kept.append(rows[i])
    if at is None:
        at = 1 if kept and not kept[0].strip() else 0
    block = [f"{n}. {t}" for n, t in enumerate(lines, 1)] + [f"<!-- {STAMP} {today_d.isoformat()} -->"]
    if note:
        block.append(f"<!-- {note} -->")
    before = kept[at - 1] if at > 0 else rows[lo - 1]  # rows[lo - 1] is the heading
    if before.strip():
        block.insert(0, "")
    if at < len(kept) and kept[at].strip():
        block.append("")
    wiki._atomic_write(p, "\n".join(rows[:lo] + kept[:at] + block + kept[at:] + rows[hi:]))
    return {"path": PRIORITIES_PATH, "action": "written", "lines": lines, "previous": previous}


def priorities_write(action: str = "candidates", lines: Optional[list[str]] = None, note: Optional[str] = None, created_by: str = CREATED_BY) -> dict[str, Any]:
    if action == "candidates":
        return candidates()
    if action == "write":
        return write(lines, note, created_by)
    raise VaultError("action must be 'candidates' or 'write'.")
