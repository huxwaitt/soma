"""``Soma/Follow-ups.md``, written from the wiki pages.

The file used to be kept row by row. From 0.4.0 it is a view: ``## Open`` holds
the open items the wiki pages say someone else owes the user, ``## Done`` the
newest lines their History says were done. The five columns are the ones the
Bases view has always had, so nothing that reads the file has to change.
``regenerate(root)`` runs wherever the wiki index is written; the file itself is
never edited — ``store.append_row`` and ``store.move_row`` refuse it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from soma_vault import frontmatter as fmt
from soma_vault import notes, store, wiki
from soma_vault.notes import ADMIN_DIR
from soma_vault.store import read_text
from soma_vault.wiki import _atomic_write, _s, _today

PATH = f"{ADMIN_DIR}/Follow-ups.md"
NOTE = (
    "Generated from the Open items of the wiki pages — edit or tick the item on its page, "
    "or say 'done' in chat; changes here are overwritten."
)
WHAT_CHARS = 80
DONE_MAX = 50

# - 2026-08-25 — done "Send the numbers" — owner: [[Wiki/People/Jane Doe]] · since 2026-08-20 ([[Emails/x]])
_DONE_RE = re.compile(
    r'^- (?P<closed>\d{4}-\d{2}-\d{2}) — done "(?P<text>.*?)"'
    r'(?: — owner: (?P<owner>.*?)(?: · since (?P<since>\d{4}-\d{2}-\d{2}))?)?'
    r'(?: \((?P<where>.*?)\))?\s*$'
)


def _short(text: Any, n: int = WHAT_CHARS) -> str:
    s = " ".join(_s(text).split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _link_cell(target: str) -> str:
    return f"[[{target}]]" if _s(target).strip() else ""


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    out = [store._row_line(header), "| " + " | ".join("---" for _ in header) + " |"]
    return out + [store._row_line(r) for r in rows]


def rows(root: Path) -> tuple[list[list[str]], list[list[str]]]:
    """The Open and Done rows, read from the pages. Open holds what other people
    owe the user, Done the newest ``done`` lines of every page's History."""
    day = _today()
    keyed: list[tuple[tuple[str, str, int], list[str]]] = []
    done: list[list[str]] = []
    for path, _fm in wiki._all_pages(root):  # one read per page: the open items and the History
        try:
            page = wiki.parse_page(read_text(root / path), path)
        except (fmt.FrontmatterError, UnicodeDecodeError, ValueError, OSError):
            continue
        stem = page.stem
        for n, o in enumerate(page.opens):
            owner = _s(o.owner).strip()
            if o.raw or o.done or not owner or owner.lower() == "me":
                continue
            keyed.append(((_s(o.since) or "9999", stem, n), [
                _s(o.since), owner, _short(o.text), _link_cell(o.record),
                f"{day} <!-- o: {_s(o.id)} @ {stem} -->",
            ]))
        for line in page.sections.get("History") or []:
            m = _DONE_RE.match(line)
            if not m:
                continue
            where = _s(m.group("where"))
            done.append([
                _s(m.group("since")), _s(m.group("owner")), _short(m.group("text")),
                where if where.startswith("[[") else "", _s(m.group("closed")),
            ])
    keyed.sort(key=lambda pair: pair[0])  # oldest first, then the page's own order
    done.sort(key=lambda r: (r[4], r[2]), reverse=True)
    return [row for _key, row in keyed][: wiki.COMMITMENTS_MAX], done[:DONE_MAX]


def text(root: Path, created_by: str = wiki.CREATED_BY, data: Any = None) -> str:
    open_rows, done_rows = data if data is not None else rows(root)
    fm = fmt.format_frontmatter({
        "type": "followups", "source": "wiki", "generated": True,
        "updated": store.now_iso(), "open": len(open_rows), "created_by": created_by,
    })
    body = ["# Follow-ups", "", NOTE, "", "## Open", ""]
    body += _table(notes.FOLLOWUPS_OPEN_HEADER, open_rows) + ["", "## Done", ""]
    body += _table(notes.FOLLOWUPS_DONE_HEADER, done_rows)
    return fm + "\n" + "\n".join(body) + "\n"


def regenerate(root: Path, created_by: str = wiki.CREATED_BY) -> dict[str, Any]:
    """Write Follow-ups.md from the pages. Returns {path, open, done, written}."""
    p = root / PATH
    if not (root / ADMIN_DIR).is_dir():
        return {"path": PATH, "open": 0, "done": 0, "written": False}
    if p.is_file():
        try:
            have = fmt.split_note(read_text(p))[0]
        except (fmt.FrontmatterError, UnicodeDecodeError, OSError):
            have = {}
        if have and have.get("generated") is not True:
            # a file the user still keeps by hand (before the migration): left alone
            return {"path": PATH, "open": 0, "done": 0, "written": False, "reason": "kept by hand"}
    open_rows, done_rows = rows(root)
    new = text(root, created_by, (open_rows, done_rows))
    same = False
    if p.is_file():
        try:  # only the timestamp differs when nothing moved: leave the file alone
            same = fmt.split_note(read_text(p))[2] == fmt.split_note(new)[2]
        except (fmt.FrontmatterError, UnicodeDecodeError, OSError):
            same = False
    if not same:
        _atomic_write(p, new)
    return {"path": PATH, "open": len(open_rows), "done": len(done_rows), "written": not same}


__all__ = ["PATH", "NOTE", "regenerate", "rows", "text"]
