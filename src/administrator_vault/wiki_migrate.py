"""Move a 0.1.0 vault's ``Administrator/People/`` into the wiki (PLAN-wiki.md §10).

``migrate(dry_run=True)`` returns the plan and writes nothing. ``dry_run=False``
does it under the wiki lock: backup copy of ``People/`` to
``Administrator/_backup/<stamp>/People/``, every person note rewritten to the
page contract under ``Wiki/People/``, ``[[People/…]]`` links rewritten to
``[[Wiki/People/…]]`` in every other note (frontmatter included), the ``.base``
views updated, the index generated, one Log.md line, and the old folder
removed when it is empty.
"""

from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from administrator_vault import frontmatter as fmt
from administrator_vault import store, wiki
from administrator_vault.notes import ADMIN_DIR
from administrator_vault.store import read_text, rel
from administrator_vault.wiki import Page, _Ctx, _atomic_write, _finalize, _log, _s, _wiki_lock, _write_index, format_page, measure

OLD_DIR = f"{ADMIN_DIR}/People"
NEW_DIR = f"{wiki.WIKI_DIR}/People"
BACKUP_DIR = f"{ADMIN_DIR}/_backup"

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


def migrate(dry_run: bool = True, created_by: str = wiki.CREATED_BY) -> dict[str, Any]:
    root = store.vault_root()
    old = root / OLD_DIR
    if not old.is_dir():
        return {"needed": False, "dry_run": dry_run, "detail": f"No {OLD_DIR}/ folder; nothing to move."}
    people, left = _plan_people(root, created_by)
    links = _link_files(root)
    views = _views_plan(root)
    plan = {
        "needed": True,
        "dry_run": dry_run,
        "people": [{k: v for k, v in p.items() if k != "page"} for p in people],
        "links": {"files": len(links), "count": sum(n for _p, n in links), "per_file": [{"path": rel(root, p), "links": n} for p, n in links[:50]]},
        "views": views,
        "left": left,
        "backup": f"{BACKUP_DIR}/<stamp>/People/",
    }
    if dry_run:
        return plan
    with _wiki_lock(root):
        wiki.init_files(root, created_by)
        (root / NEW_DIR).mkdir(parents=True, exist_ok=True)
        stamp = _stamp()
        backup = root / BACKUP_DIR / stamp / "People"
        n = 2
        while backup.exists():  # a second run within the same second
            backup = root / BACKUP_DIR / f"{stamp}-{n}" / "People"
            n += 1
        shutil.copytree(old, backup)
        plan["backup"] = rel(root, backup)
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
        _log(root, "migrate", "Wiki/People", "-", f"{len(moved)} people, {rewritten} links")
        _write_index(root, [wiki._stem(p) for p in moved])
        remaining = [rel(root, p) for p in old.iterdir()]
        removed = False
        if not remaining:
            old.rmdir()
            removed = True
    plan.update({"moved": moved, "skipped": skipped, "links_rewritten": rewritten, "old_folder_removed": removed, "old_folder_left": remaining})
    return plan


__all__ = ["migrate", "OLD_DIR", "NEW_DIR", "BACKUP_DIR"]
