"""Bring an older vault up to date (PLAN-wiki.md §10) in three parts.

``migrate(dry_run=True)`` returns the plan and writes nothing. ``dry_run=False``
does it under the wiki lock, keeping a copy of everything it replaces under
``Administrator/_backup/<stamp>/``:

* **people** — every note of a 0.1.0 ``Administrator/People/`` rewritten to the
  page contract under ``Wiki/People/``, ``[[People/…]]`` links rewritten to
  ``[[Wiki/People/…]]`` in every other note (frontmatter included), and the old
  folder removed when it is empty;
* **followups** — the rows of a hand-kept ``Follow-ups.md`` become open items on
  the person pages they name (an unknown name goes to ``Wiki/Me.md``) and
  History lines for what was done, after which the file is written from the
  pages;
* **views** — the ``.base`` views brought up to date.

Each part writes one Log.md line and the index is generated at the end.
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from administrator_vault import frontmatter as fmt
from administrator_vault import store, wiki
from administrator_vault.notes import ADMIN_DIR
from administrator_vault.store import read_text, rel
from administrator_vault.wiki import Page, _Ctx, _atomic_write, _finalize, _log, _s, _wiki_lock, _write_index, format_page, measure

OLD_DIR = f"{ADMIN_DIR}/People"
NEW_DIR = f"{wiki.WIKI_DIR}/People"
BACKUP_DIR = f"{ADMIN_DIR}/_backup"
FOLLOWUPS_PATH = f"{ADMIN_DIR}/Follow-ups.md"
ME_STEM = "Wiki/Me"

_OLD_LINK_RE = re.compile(r"\[\[People/")
_RECORD_LINE_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) — (\[\[[^\]]+\]\])\s*(.*?)\s*$")
_GENERATED_H2_RE = re.compile(r"^## (Emails|Meetings|Update\b.*)\s*$")
_STATUS_TAIL_RE = re.compile(r"^\((?:todo|waiting|done|fyi|held|upcoming|cancelled|canceled|prep)\)$", re.IGNORECASE)


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


def _rewrite(text: str) -> tuple[str, int]:
    new, n = _OLD_LINK_RE.subn("[[Wiki/People/", text)
    return new, n


def _convert(text: str, created_by: str) -> tuple[Page, dict[str, Any]]:
    """An old person note -> a Page following the contract, plus what was found."""
    fm, _block, body = fmt.split_note(text)
    name = _s(fm.get("name")).strip()
    email = _s(fm.get("email")).strip()
    company = _s(fm.get("org") or fm.get("company")).strip()
    aliases = fm.get("aliases") or []
    aliases = [_s(a) for a in ([aliases] if isinstance(aliases, str) else aliases) if _s(a).strip() and _s(a).strip().lower() != email.lower()]
    records: list[str] = []
    user_lines: list[str] = []
    voice = False
    identity_line = f"{email} · {company}".strip(" ·") if email or company else ""
    for raw_line in body.split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            user_lines.append("")
            continue
        if line.startswith("# ") or _GENERATED_H2_RE.match(line):
            continue
        if identity_line and line.strip() == identity_line:
            continue
        if line.strip() == email or line.strip() == f"{email} ·":
            continue
        m = _RECORD_LINE_RE.match(line)
        if m:
            link, _n = _rewrite(m.group(2))
            tail = m.group(3).strip()
            tail = "" if _STATUS_TAIL_RE.match(tail) else tail.lstrip("—- ").strip()
            records.append(f"- {m.group(1)} — {link}" + (f" — {tail}" if tail else ""))
            continue
        if line.lstrip().lower().startswith("voice with this person:"):
            voice = True
        user_lines.append(_rewrite(line)[0])
    notes = re.sub(r"\n{3,}", "\n\n", "\n".join(user_lines)).strip("\n")
    last_contact = _s(fm.get("last_contact"))
    dates = sorted({l[2:12] for l in records}, reverse=True)
    new_fm: dict[str, Any] = {
        "type": "person", "title": name, "name": name, "email": email, "aliases": aliases, "summary": "", "status": "draft",
        "org": company, "last_contact": last_contact, "created": (dates[-1] if dates else last_contact[:10]) or wiki._today(), "created_by": created_by,
    }
    if not company:
        new_fm.pop("org")
    lead = f"{name} ({email})" + (f" — {company}." if company else ".") if name else ""
    page = Page(path="", fm=new_fm, title=name or email, lead=lead, notes=notes)
    page.sections["Records"] = records
    page.sections["History"] = [f"- {wiki._today()} — migrated from People/{name} (user)"]
    return page, {"records": len(records), "notes_lines": len([l for l in user_lines if l.strip()]), "voice": voice, "newest_record": dates[0] if dates else None}


def _plan_people(root: Path, created_by: str) -> tuple[list[dict[str, Any]], list[str]]:
    old = root / OLD_DIR
    people, left = [], []
    for p in sorted(old.iterdir()):
        r = rel(root, p)
        if p.is_dir() or p.suffix.lower() != ".md":
            left.append(r)
            continue
        try:
            text = read_text(p)
            fm = fmt.split_note(text)[0]
        except (fmt.FrontmatterError, UnicodeDecodeError):
            left.append(r)
            continue
        if fm.get("type") not in (None, "", "person") or not (fm.get("name") or fm.get("email")):
            left.append(r)
            continue
        page, found = _convert(text, created_by)
        target = root / NEW_DIR / p.name
        page.path = rel(root, target)
        people.append({"from": r, "to": page.path, "exists": target.is_file(), "page": page, **found})
    return people, left


def _link_files(root: Path, pattern: "re.Pattern[str]" = _OLD_LINK_RE) -> list[tuple[Path, int]]:
    """Every note holding a link that matches ``pattern``, with how many it holds:
    the old ``People/`` links here, a renamed page in wiki_reconcile. The backup
    folder and the copies under ``_cache/`` are left out."""
    admin = root / ADMIN_DIR
    out = []
    for p in sorted(admin.rglob("*.md")):
        r = rel(root, p)
        if r.startswith((OLD_DIR + "/", BACKUP_DIR + "/", wiki.CACHE_DIR + "/")):
            continue
        try:
            text = read_text(p)
        except (OSError, UnicodeDecodeError):
            continue
        n = len(pattern.findall(text))
        if n:
            out.append((p, n))
    return out


def _views_plan(root: Path) -> list[dict[str, Any]]:
    out = []
    views = root / ADMIN_DIR / "_views"
    shipped = {p.name: p for p in store.VIEWS_DIR.glob("*.base")} if store.VIEWS_DIR.is_dir() else {}
    if views.is_dir():
        for p in sorted(views.glob("*.base")):
            text = read_text(p)
            if p.name in ("People.base", "Wiki.base") and p.name in shipped:
                if text != shipped[p.name].read_text(encoding="utf-8"):
                    out.append({"path": rel(root, p), "action": "replace with the shipped view"})
            elif 'Administrator/People"' in text or "note.company" in text:
                out.append({"path": rel(root, p), "action": "rewrite folder filter and company column"})
    if "Wiki.base" in shipped and not (views / "Wiki.base").is_file():
        out.append({"path": rel(root, views / "Wiki.base"), "action": "install"})
    return out


def _apply_views(root: Path, plan: list[dict[str, Any]]) -> None:
    shipped = {p.name: p for p in store.VIEWS_DIR.glob("*.base")} if store.VIEWS_DIR.is_dir() else {}
    for item in plan:
        p = root / item["path"]
        if p.name in shipped and item["action"] != "rewrite folder filter and company column":
            _atomic_write(p, shipped[p.name].read_text(encoding="utf-8"))
        else:
            text = read_text(p).replace('Administrator/People"', 'Administrator/Wiki/People"').replace("note.company", "note.org")
            _atomic_write(p, text)


def _followups_tables(root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """The Open and Done rows of a Follow-ups.md the user still keeps by hand.
    A file the code already writes gives nothing back."""
    from administrator_vault import workflows  # imported here: it reads wiki, this module is a tool

    p = root / FOLLOWUPS_PATH
    if not p.is_file():
        return [], []
    try:
        fm, _block, body = fmt.split_note(read_text(p))
    except (fmt.FrontmatterError, UnicodeDecodeError):
        return [], []
    if fm.get("generated") is True:
        return [], []
    lines = body.split("\n")
    found: dict[str, list[dict[str, str]]] = {"open": [], "done": []}
    for _level, heading, lo, hi in workflows._sections(body):
        name = heading.strip().lower()
        if name in found and not found[name]:
            tables = workflows._tables(lines, lo, hi)
            found[name] = tables[0] if tables else []
    return found["open"], found["done"]


def _followups_target(root: Path, pages: list[tuple[str, dict[str, Any]]], who: str, moving: dict[str, str]) -> tuple[str, str]:
    """(page stem, the name to keep in the text). A link or a name that matches a
    page that can hold an open item wins (``moving`` holds the person pages this
    run is about to write); anything else lands on Wiki/Me.md with the name in
    the item."""
    plain = store._unescape_cell(re.sub(r"<!--.*?-->", "", _s(who))).strip()
    can_hold = {wiki._stem(p) for p, _fm in pages} | set(moving.values())
    m = wiki._LINK_RE.search(_s(who))
    if m:
        stem = moving.get(wiki._link_target(m.group(1)), wiki._link_target(m.group(1)))
        if stem in can_hold:
            return stem, ""
        named = next((fm for p, fm in wiki._all_pages(root) if wiki._stem(p) == stem), None)
        plain = _s(named.get("title") or named.get("name")) if named else stem.rsplit("/", 1)[-1]
    if plain:
        hit = wiki._find_by_name(pages, plain, [])
        if hit:
            return wiki._stem(hit[0]), ""
        for stem in moving.values():
            if wiki._norm_name(stem.rsplit("/", 1)[-1]) == wiki._norm_name(plain):
                return stem, ""
    return "", plain


def _followups_plan(root: Path, moving: Optional[dict[str, str]] = None) -> dict[str, Any]:
    moving = moving or {}
    opens, dones = _followups_tables(root)
    # only a page whose contract has an Open section can hold the row; the rest go to Wiki/Me.md
    pages = [pg for pg in wiki._all_pages(root) if "Open" in wiki.SECTIONS.get(_s(pg[1].get("type")), ())]
    items: dict[str, list[dict[str, Any]]] = {"open": [], "done": []}
    for kind, rows in (("open", opens), ("done", dones)):
        for row in rows:
            stem, name = _followups_target(root, pages, row.get("Who", ""), moving)
            what = _s(row.get("What", "")).strip()
            record = ""
            m = wiki._LINK_RE.search(_s(row.get("Email", "")))
            if m:
                record = wiki._link_target(m.group(1))
            items[kind].append({
                "who": name or (f"[[{stem}]]" if stem else ""),
                "text": f"{name}: {what}" if name and not stem else what,
                "since": _s(row.get("Since", ""))[:10],
                "closed": _s(row.get("Closed", ""))[:10],
                "page": stem or ME_STEM,
                "record": record,
                "src": store._comment_key(_s(row.get("_line", ""))) or "user",
            })
    return {
        "open": items["open"], "done": items["done"],
        "count": len(items["open"]) + len(items["done"]),
        "backup": f"{BACKUP_DIR}/<stamp>/Follow-ups.md",
    }


def _me_page(root: Path, created_by: str) -> str:
    """Wiki/Me.md, created as a draft when it is missing."""
    p = root / wiki.WIKI_DIR / "Me.md"
    if not p.is_file():
        ctx = _Ctx(root=root, src="user", since=wiki._today(), record=None)
        wiki._create_page(root, "me", "Me", None, "", "", None, ctx, created_by)
    return rel(root, p)


def _apply_followups(root: Path, plan: dict[str, Any], created_by: str) -> dict[str, int]:
    """The rows as open items and History lines on the pages they belong to."""
    done_n = 0
    for item in plan["open"] + plan["done"]:
        if item["page"] == ME_STEM:
            _me_page(root, created_by)
    for item in plan["open"]:
        rec = None
        if item["record"]:
            try:
                rec = wiki._record_info(root, f"{ADMIN_DIR}/{item['record']}.md")
            except (store.VaultError, fmt.FrontmatterError):
                rec = None
        since = item["since"] or wiki._today()
        ctx = _Ctx(root=root, src=item["src"], since=since, record=rec)
        op = {"op": "open", "text": item["text"], "owner": item["who"] or "me", "since": since, "src": item["src"]}
        wiki._write_ops(root, wiki.page_path(item["page"]), [op], ctx, "migrate")
    for item in plan["done"]:
        path = wiki.page_path(item["page"])
        if not (root / path).is_file():
            continue
        page = wiki._load(root, path)
        where = f"[[{item['record']}]]" if item["record"] else "user"
        closed = item["closed"] or item["since"] or wiki._today()
        line = f'- {closed} — done "{item["text"]}" — owner: {item["who"] or "me"} · since {item["since"]} ({where})'
        if line not in page.lines("History"):
            page.lines("History").append(line)
            ctx = _Ctx(root=root, src="user", since=wiki._today(), record=None)
            _finalize(page, ctx)
            wiki._write_page(page, ctx)
            done_n += 1
    from administrator_vault import followups  # the file becomes the view of the pages

    _atomic_write(root / FOLLOWUPS_PATH, followups.text(root, created_by))
    return {"open": len(plan["open"]), "done": done_n}


def migrate(dry_run: bool = True, created_by: str = wiki.CREATED_BY) -> dict[str, Any]:
    root = store.vault_root()
    old = root / OLD_DIR
    people, left = ([], []) if not old.is_dir() else _plan_people(root, created_by)
    moving = {wiki._stem(p["from"]): wiki._stem(p["to"]) for p in people if not p["exists"]}
    followups = _followups_plan(root, moving)
    links = _link_files(root) if old.is_dir() else []
    views = _views_plan(root)
    parts = {"people": old.is_dir(), "followups": followups["count"] > 0, "views": bool(views)}
    plan = {
        "needed": any(parts.values()),
        "dry_run": dry_run,
        "parts": parts,
        "people": [{k: v for k, v in p.items() if k != "page"} for p in people],
        "links": {"files": len(links), "count": sum(n for _p, n in links), "per_file": [{"path": rel(root, p), "links": n} for p, n in links[:50]]},
        "views": views,
        "followups": followups,
        "left": left,
        "backup": f"{BACKUP_DIR}/<stamp>/People/",
    }
    if not plan["needed"]:
        plan["detail"] = f"No {OLD_DIR}/ folder and no Follow-ups rows to move; nothing to do."
        return plan
    if dry_run:
        return plan
    with _wiki_lock(root):
        wiki.init_files(root, created_by)
        (root / NEW_DIR).mkdir(parents=True, exist_ok=True)
        stamp = _stamp()
        keep = root / BACKUP_DIR / stamp
        n = 2
        while keep.exists():  # a second run within the same second
            keep = root / BACKUP_DIR / f"{stamp}-{n}"
            n += 1
        keep.mkdir(parents=True, exist_ok=True)
        if old.is_dir():
            shutil.copytree(old, keep / "People")
            plan["backup"] = rel(root, keep / "People")
        if followups["count"]:
            shutil.copy2(root / FOLLOWUPS_PATH, keep / "Follow-ups.md")
            plan["followups"] = dict(followups, backup=rel(root, keep / "Follow-ups.md"))
        moved, skipped = [], []
        for item in people:
            page: Page = item["page"]
            if item["exists"]:
                skipped.append({"from": item["from"], "to": item["to"], "reason": "a page with this filename already exists in Wiki/People; left in place"})
                continue
            ctx = _Ctx(root=root, src="user", since=wiki._today(), record=None)
            if item["newest_record"]:
                ctx.verified.append(item["newest_record"])
            _finalize(page, ctx)
            text = format_page(page)
            sizes = measure("person", text)
            if sizes["over"]:
                # keep the newest records and trim the notes rather than refuse a migration
                page.sections["Records"] = page.sections["Records"][: wiki.RECORDS_MAX]
                text = format_page(page)
            _atomic_write(root / page.path, text)
            (root / item["from"]).unlink()
            moved.append(page.path)
        rewritten = 0
        for p, _n in links:
            text, n = _rewrite(read_text(p))
            _atomic_write(p, text)
            rewritten += n
        _apply_views(root, views)
        if old.is_dir():
            _log(root, "migrate", "Wiki/People", "-", f"{len(moved)} people, {rewritten} links")
        _write_index(root, [wiki._stem(p) for p in moved])
        rows = {"open": 0, "done": 0}
        if followups["count"]:
            rows = _apply_followups(root, followups, created_by)
            _log(root, "migrate", "Follow-ups", "-", f"{rows['open']} open, {rows['done']} done")
            _write_index(root)  # Follow-ups.md is written from the pages again
        remaining = [rel(root, p) for p in old.iterdir()] if old.is_dir() else []
        removed = False
        if old.is_dir() and not remaining:
            old.rmdir()
            removed = True
    plan.update({"moved": moved, "skipped": skipped, "links_rewritten": rewritten,
                 "followups_moved": rows, "old_folder_removed": removed, "old_folder_left": remaining})
    return plan


__all__ = ["migrate", "OLD_DIR", "NEW_DIR", "BACKUP_DIR"]
