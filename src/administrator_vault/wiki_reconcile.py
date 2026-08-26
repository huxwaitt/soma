"""Two-way editing: the wiki reads back what the user changed by hand.

Obsidian is a text editor over the same files the code writes, so a page can
change under it: a bullet typed into Facts, a fact reworded or deleted, an
open item ticked, a page renamed, moved between folders or made from
scratch. ``reconcile(root)`` runs at the start of every wiki tool call that
writes. It compares each file with what the code last wrote
(``Wiki/_cache/state.json``) and takes the change over: a new bullet becomes
a user fact dated the day the file changed, a changed fact keeps a History
line, a removed fact is retired, a renamed page takes its links with it.

The tools that only read call ``detect(root)`` instead. It compares the same
way and answers how many files differ, and writes nothing: a read tool says
``hand_edits: n`` and the next writing call is what adopts them.

Nothing is thrown away. Text under a heading the contract does not know moves
under ``## Notes`` with a dated marker, a History section that was shortened
comes back from the copy under ``_cache/prev/``, and a page deleted by hand is
only ever asked about — never restored or forgotten on its own.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from administrator_vault import frontmatter as fmt
from administrator_vault import store, wiki, wiki_lint, wiki_migrate, wiki_search
from administrator_vault.store import read_text, rel
from administrator_vault.wiki import CACHE_DIR, PREV_DIR, TYPE_FOLDER, TYPES, WIKI_DIR, _Ctx, _s, _stem

STATE_PATH = f"{CACHE_DIR}/state.json"
SCHEMA = 1
FOLDER_TYPE = {folder: t for t, folder in TYPE_FOLDER.items() if folder}
_COPY_RE = re.compile(r"\s\(\d+\)$|conflict", re.IGNORECASE)
_STATE: dict[str, tuple[int, dict[str, Any]]] = {}
_MEMO: dict[str, tuple] = {}
_KEEP = 4  # roots held in memory at once


# ------------------------------------------------------------------ small helpers


def _hash(text: str) -> str:
    return wiki._blake(text.encode("utf-8"))


def _day(mtime_ns: int) -> str:
    return datetime.fromtimestamp(mtime_ns / 1_000_000_000).date().isoformat()


def _folder_type(path: str) -> str:
    """The page type a file's folder asks for (``People/`` -> person)."""
    rest = path[len(WIKI_DIR) + 1 :] if path.startswith(WIKI_DIR + "/") else path
    if "/" not in rest:
        return "me" if rest == "Me.md" else ""
    return FOLDER_TYPE.get(rest.split("/", 1)[0], "")


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one}" if n == 1 else f"{n} {many}"


def _remember(key: str, sig: tuple) -> None:
    """Hold on to what the folders looked like, so a second call in the same
    process stats them once and stops there."""
    if key not in _MEMO and len(_MEMO) >= _KEEP:
        _MEMO.pop(next(iter(_MEMO)))
    _MEMO[key] = sig


def _with_id(text: str, page_id: str) -> Optional[str]:
    """The same text with an ``id`` line after ``type`` — every other byte kept."""
    lines = text.split("\n")
    if not lines or lines[0].rstrip("\r") != "---":
        return None
    close = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r") == "---"), None)
    if close is None:
        return None
    block = lines[1:close]
    at = next((i for i, l in enumerate(block) if l.partition(":")[0].strip() == "type"), -1)
    block.insert(at + 1, f"id: {fmt.format_scalar(page_id, 'id')}")
    return "\n".join(lines[:1] + block + lines[close:])


def _bare_facts(page: wiki.Page, text: str) -> list[wiki.Fact]:
    """The facts that were typed as plain bullets: their id is not in the file."""
    return [f for f in page.facts if f"f:{f.id}" not in text]


# ------------------------------------------------------------------ the state file


def _load(root: Path) -> dict[str, Any]:
    """The state as it was last written. The same dict for the whole process, so
    a write during a pass and the pass itself never overwrite each other."""
    p = root / STATE_PATH
    key = str(root)
    try:
        sig = p.stat().st_mtime_ns
    except OSError:
        sig = -1
    hit = _STATE.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    data: dict[str, Any] = {"schema": SCHEMA, "written": "", "pages": {}}
    if sig != -1:
        try:
            raw = json.loads(read_text(p))
            if int(raw.get("schema") or 0) == SCHEMA and isinstance(raw.get("pages"), dict):
                data = raw
        except (OSError, UnicodeDecodeError, ValueError, TypeError):
            pass
    if len(_STATE) >= _KEEP:
        _STATE.pop(next(iter(_STATE)))
    _STATE[key] = (sig, data)
    return data


def _save(root: Path, state: dict[str, Any]) -> None:
    state["schema"] = SCHEMA
    state["written"] = store.now_iso()
    p = root / STATE_PATH
    wiki._atomic_write(p, json.dumps(state, ensure_ascii=False, indent=1))
    try:
        _STATE[str(root)] = (p.stat().st_mtime_ns, state)
    except OSError:
        _STATE.pop(str(root), None)


def _entry(page: wiki.Page, size: int, mtime_ns: int, digest: str) -> dict[str, Any]:
    """What one page looked like the last time code and file agreed."""
    return {
        "id": _s(page.fm.get("id")),
        "path": page.path,
        "kind": page.type,
        "title": page.title,
        "created": _s(page.fm.get("created")),
        "size": size,
        "mtime_ns": mtime_ns,
        "hash": digest,
        "fm_hash": _hash(json.dumps(wiki._fm_values(page.fm), ensure_ascii=False, sort_keys=True)),
        "lead_hash": _hash(page.lead.strip()),
        "facts": {f.id: [f.text, f.since, list(f.src)] for f in page.facts},
        "sections": {n: _hash("\n".join(lines)) for n, lines in page.sections.items() if n != "Facts"},
        "open": [o.line() for o in page.opens],
        "history_n": len(page.sections.get("History") or []),
        "history": list(page.sections.get("History") or []),
    }


def _skip_entry(path: str, size: int, mtime_ns: int, digest: str, why: str) -> dict[str, Any]:
    return {"path": path, "size": size, "mtime_ns": mtime_ns, "hash": digest, "skip": why}


def note_write(root: Path, page: wiki.Page, text: str) -> None:
    """Remember a page as the code just wrote it — called by ``wiki._commit``."""
    p = root / page.path
    try:
        st = p.stat()
        digest = _hash(read_text(p))
    except (OSError, UnicodeDecodeError):
        return
    state = _load(root)
    state.setdefault("pages", {})[page.stem] = _entry(page, st.st_size, st.st_mtime_ns, digest)
    _save(root, state)


def forget(root: Path, stem: str) -> None:
    """Drop what was remembered about one page: the file is not what the code
    meant to write, so the next pass reads it from scratch."""
    state = _load(root)
    if state.get("pages", {}).pop(stem, None) is not None:
        _save(root, state)


def load_state(root: Path) -> dict[str, Any]:
    """The state file as a dict (for lint and tests)."""
    return _load(root)


def detect(root: Path) -> int:
    """How many pages differ from what the code last wrote — a scan, no writes.

    The read tools call this instead of ``reconcile``: they say how many files
    the user changed by hand and leave taking them over to the next writing
    call, so no read ever rewrites a page. One stat per page, and only the few
    whose size or time moved are read."""
    if not (root / STATE_PATH).is_file():  # nothing written yet: the first writing call reads the wiki in
        return 0
    files = wiki_search._page_files(root)
    if _MEMO.get(str(root)) == tuple((path, size, mtime) for path, _p, size, mtime in files):
        return 0  # this process just read every page back
    pages = _load(root).get("pages") or {}
    seen: set[str] = set()
    n = 0
    for path, p, size, mtime in files:
        stem = _stem(path)
        seen.add(stem)
        old = pages.get(stem)
        if old is None:
            n += 1
            continue
        if old.get("size") == size and old.get("mtime_ns") == mtime:
            continue
        try:
            if old.get("hash") == _hash(read_text(p)):  # saved again with the same text
                continue
        except (OSError, UnicodeDecodeError):
            continue
        n += 1
    return n + sum(1 for stem, e in pages.items() if stem not in seen and not e.get("deleted"))


# ------------------------------------------------------------------ links


def _pattern(stem: str) -> re.Pattern:
    return re.compile(r"\[\[" + re.escape(stem) + r"(?=[\]|#])")


def _linking(root: Path, stem: str) -> list[tuple[Path, int]]:
    """The notes that link to a page, with how many links each holds. The page
    contract is left out: its links are examples, not links to this vault."""
    return [(p, n) for p, n in wiki_migrate._link_files(root, _pattern(stem)) if rel(root, p) != wiki.SCHEMA_PATH]


def _link_count(root: Path, stem: str) -> int:
    return sum(n for _p, n in _linking(root, stem))


def _rewrite_links(root: Path, old_stem: str, new_stem: str, self_path: str, pages: dict[str, Any], refresh: set[str]) -> int:
    """Point every link at the page's new place: wiki pages, records (the
    ``wiki:`` key included), Follow-ups, Review and the history files."""
    done = 0
    for p, count in _linking(root, old_stem):
        path = rel(root, p)
        if path == self_path:
            continue
        try:
            text = read_text(p)
        except (OSError, UnicodeDecodeError):
            continue
        wiki._atomic_write(p, wiki_lint._replace_links(text, old_stem, new_stem))
        done += count
        if _stem(path) in pages:
            refresh.add(path)
    return done


# ------------------------------------------------------------------ one changed page


def _to_notes(page: wiki.Page, day: str) -> list[str]:
    """Headings the contract does not know: their lines move under Notes."""
    known = wiki.SECTIONS.get(page.type, wiki.SECTIONS["topic"])
    moved = []
    for name in [n for n in list(page.sections) if n not in known and n != "Facts"]:
        lines = [l for l in page.sections.pop(name) if l.strip()]
        if not lines:  # an empty heading holds nothing to lose
            continue
        block = f"### {name} (moved {day})\n" + "\n".join(lines)
        page.notes = (page.notes.rstrip("\n") + "\n\n" + block) if page.notes.strip() else block
        moved.append(name)
    return moved


def _adopt(root: Path, page: wiki.Page, old: dict[str, Any], text: str, day: str, ctx: _Ctx) -> tuple[dict[str, Any], list[str]]:
    """Read one hand-edited page against what the code last wrote. The page is
    changed in place; the answer says what happened and what to ask about."""
    events: dict[str, Any] = {}
    review: list[str] = []
    old_facts: dict[str, Any] = dict(old.get("facts") or {})
    have = len(page.sections.get("History") or [])
    if int(old.get("history_n") or 0) > have:
        kept: list[str] = list(old.get("history") or [])  # the lines the code last wrote
        if len(kept) <= have:
            prev = root / PREV_DIR / (page.stem[len("Wiki/") :] + ".md.prev")
            if prev.is_file():
                try:
                    kept = wiki.parse_page(read_text(prev), page.path).sections.get("History") or []
                except (fmt.FrontmatterError, UnicodeDecodeError, ValueError):
                    kept = []
        now = page.sections.get("History") or []
        if len(kept) > have:
            page.sections["History"] = kept + [l for l in now if l not in kept]
            events["history"] = True
            review.append(
                f"- [ ] [[{page.stem}]] — the History section was shortened by hand; the lines came back. "
                'Say "drop it" to keep the short one.'
            )
        else:
            lost = int(old.get("history_n") or 0) - have
            events["history_lost"] = lost
            review.append(
                f"- [ ] [[{page.stem}]] — {lost} History line(s) were removed by hand and no copy holds them; "
                'say "fine" to keep it that way.'
            )
    bare = [f for f in _bare_facts(page, text) if f.id not in old_facts]
    for f in bare:
        f.src = ["user"]
        f.since = f.since or day
    if bare:
        events["facts_added"] = len(bare)
    changed = 0
    for f in page.facts:
        was = old_facts.get(f.id)
        if not was or f.text == was[0]:
            continue
        wiki._extend_src(f, "user")
        wiki._history(page, ctx, f'updated f:{f.id} "{was[0]}" → "{f.text}" — edited by hand')
        changed += 1
    if changed:
        events["facts_changed"] = changed
    removed = [fid for fid in old_facts if page.fact(fid) is None]
    for fid in removed:
        wiki._history(page, ctx, f'retired "{old_facts[fid][0]}" — removed by hand')
    if removed:
        events["facts_removed"] = len(removed)
    ticked = [o for o in page.opens if o.done and not o.raw]
    if ticked:
        events["done"] = len(ticked)  # _finalize moves them to History
    # a line typed under Open or Milestones by hand: _finalize gives it an id, the
    # file's date as since, src user and (under Open) owner me
    fresh = [o for name in wiki.ITEM_SECTIONS for o in page.items(name) if not o.id and not o.raw and not o.done]
    if fresh:
        events["items_added"] = len(fresh)
    moved = _to_notes(page, day)
    if moved:
        events["moved"] = moved
    was_title = _s(old.get("title"))
    if was_title and page.title.strip() and wiki._norm_name(page.title) != wiki._norm_name(was_title):
        wiki._add_alias(page, was_title)
        page.fm["title"] = page.title
        if page.type == "person":
            page.fm["name"] = page.title
        events["title"] = was_title
    if "lead_hash" in old and old["lead_hash"] != _hash(page.lead.strip()):
        events["lead"] = True
    if (old.get("id") and _s(page.fm.get("id")) != old["id"]) or (old.get("created") and _s(page.fm.get("created")) != old["created"]):
        events["keys"] = True
    return events, review


def _detail(events: dict[str, Any]) -> str:
    """One plain line for the log and for the model to pass on."""
    bits: list[str] = []
    if events.get("created"):
        bits.append("new page written by hand")
    if events.get("renamed"):
        bits.append(f"moved from {events['renamed']}" + (f", {_plural(events['links'], 'link', 'links')} rewritten" if events.get("links") else ""))
    if events.get("kind"):
        bits.append(("now an " if events["kind"][0] in "aeiou" else "now a ") + f"{events['kind']} page")
    for key, one, many in (("facts_added", "new fact", "new facts"), ("facts_changed", "fact changed", "facts changed"),
                           ("facts_removed", "fact removed", "facts removed"), ("done", "open item ticked", "open items ticked"),
                           ("items_added", "new open item", "new open items")):
        if events.get(key):
            bits.append(_plural(events[key], one, many))
    if events.get("moved"):
        bits.append("moved " + ", ".join(events["moved"]) + " under Notes")
    if events.get("history"):
        bits.append("History put back")
    if events.get("history_lost"):
        bits.append(_plural(events["history_lost"], "History line lost", "History lines lost"))
    if events.get("title"):
        bits.append(f'title changed from "{events["title"]}"')
    if events.get("lead"):
        bits.append("new lead")
    if events.get("keys"):
        bits.append("id and created put back")
    return ", ".join(bits) or "read again"


# ------------------------------------------------------------------ the pass


def reconcile(root: Path, lock_held: bool = False) -> dict[str, Any]:
    """Read every page the user touched since the last write and take it over.

    ``lock_held`` says the caller already holds the write lock. Nothing changed
    is the common case and costs one stat per page."""
    files = wiki_search._page_files(root)
    sig = tuple((path, size, mtime) for path, _p, size, mtime in files)
    key = str(root)
    quiet = {"adopted": [], "review": [], "busy": [], "first_run": False, "scanned": len(files)}
    if _MEMO.get(key) == sig:
        return quiet
    first_run = not (root / STATE_PATH).is_file()
    state = _load(root)
    pages = state.setdefault("pages", {})
    work: list[tuple] = []
    seen: set[str] = set()
    restated = False
    for path, p, size, mtime in files:
        stem = _stem(path)
        seen.add(stem)
        old = pages.get(stem)
        if old and old.get("size") == size and old.get("mtime_ns") == mtime:
            continue
        try:
            text = read_text(p)
        except (OSError, UnicodeDecodeError):
            continue
        digest = _hash(text)
        if old and old.get("hash") == digest:  # saved again with the same text
            old["size"], old["mtime_ns"] = size, mtime
            restated = True
            continue
        work.append((stem, path, p, size, mtime, text, digest))
    gone = [s for s, e in pages.items() if s not in seen and not e.get("deleted")]
    if not work and not gone:
        if restated or first_run:  # an empty wiki still gets its state file, so the next pass is not a first one
            _save(root, state)
        _remember(key, sig)
        quiet["first_run"] = first_run
        return quiet
    if lock_held:
        out = _pass(root, state, work, gone, first_run, len(files))
    else:
        lock = wiki._wiki_lock(root)
        try:
            lock.__enter__()
        except store.VaultError:
            return quiet  # another process is writing: reading the page back can wait for the next call
        try:
            out = _pass(root, state, work, gone, first_run, len(files))
        finally:
            lock.__exit__()
    if out["busy"]:  # a file was being written: look at it again on the next call
        _MEMO.pop(key, None)
    else:
        _remember(key, tuple((path, size, mtime) for path, _p, size, mtime in wiki_search._page_files(root)))
    return out


def _pass(root: Path, state: dict[str, Any], work: list[tuple], gone: list[str], first_run: bool, scanned: int) -> dict[str, Any]:
    pages: dict[str, Any] = state["pages"]
    by_id = {_s(e.get("id")): s for s, e in pages.items() if e.get("id")}
    missing = set(gone)
    adopted: list[dict[str, str]] = []
    review: list[str] = []
    busy: list[str] = []
    touched: set[str] = set()
    refresh: set[str] = set()
    claimed: set[str] = set()
    ids_added = 0
    bullets = 0

    for stem, path, p, size, mtime, text, digest in work:
        try:
            st = p.stat()
        except OSError:
            continue
        if (st.st_size, st.st_mtime_ns) != (size, mtime):  # being written right now
            busy.append(stem)
            continue
        day = _day(mtime)
        try:
            page = wiki.parse_page(text, path, today=day)
        except (fmt.FrontmatterError, ValueError):
            pages[stem] = _skip_entry(path, size, mtime, digest, "unreadable")
            continue
        kind = _s(page.fm.get("type"))
        page_id = _s(page.fm.get("id"))
        old = pages.get(stem)
        if kind and kind not in TYPES:  # a redirect or another file the code owns
            pages[stem] = _skip_entry(path, size, mtime, digest, kind)
            continue
        if old is None and page_id and _COPY_RE.search(Path(path).stem) and by_id.get(page_id, stem) != stem:
            review.append(f"- [ ] [[{stem}]] — this file looks like a copy of [[{by_id[page_id]}]] left by a sync; it was not read.")
            pages[stem] = _skip_entry(path, size, mtime, digest, "copy")
            continue
        was_stem = ""
        if old is None and page_id and by_id.get(page_id, stem) != stem and by_id[page_id] in missing:
            was_stem = by_id[page_id]
            old = pages.get(was_stem)
        ctx = _Ctx(root=root, src="user", since=day, record=None, today=day, touched=touched)

        if old is not None:  # a page the code knows: hand edits, a new name, a new folder
            moved_kind = ""
            if was_stem:  # the folder decides the kind, before the sections are read
                folder = _folder_type(path)
                if folder and folder != page.type:
                    page.fm["type"] = moved_kind = folder
            events, lines = _adopt(root, page, old, text, day, ctx)
            review += lines
            if was_stem:
                events["renamed"] = was_stem
                events["links"] = _rewrite_links(root, was_stem, stem, path, pages, refresh)
                if moved_kind:
                    events["kind"] = moved_kind
                pages.pop(was_stem, None)
                claimed.add(was_stem)
            if not events:
                pages[stem] = _entry(page, size, mtime, digest)
                continue
            if old.get("id"):
                page.fm["id"] = old["id"]
            if old.get("created"):
                page.fm["created"] = old["created"]
            bullets += int(events.get("facts_added") or 0)
        elif kind in TYPES:
            bare = _bare_facts(page, text)
            if not bare and page_id:  # written by another part of the code
                pages[stem] = _entry(page, size, mtime, digest)
                continue
            if not bare:  # a page from before ids: give it one, leave every other byte
                with_id = _with_id(text, wiki.new_page_id())
                if with_id is None:
                    pages[stem] = _entry(page, size, mtime, digest)
                    continue
                wiki._atomic_write(p, with_id)
                ids_added += 1
                refresh.add(path)
                continue
            for f in bare:
                f.src = ["user"]
                f.since = f.since or day
            events = {"facts_added": len(bare)}
            bullets += len(bare)
            ids_added += 0 if page_id else 1
        else:  # a page someone wrote from scratch in the folder
            folder = _folder_type(path)
            if not folder:
                pages[stem] = _skip_entry(path, size, mtime, digest, "unknown folder")
                continue
            title = page.title.strip() or Path(path).stem
            hit = wiki._find_by_name(wiki._all_pages(root), title, [])
            if hit and hit[0] != path:
                review.append(f"- [ ] [[{stem}]] — a page written by hand has the same name as [[{_stem(hit[0])}]]; merge them or rename one?")
                pages[stem] = _skip_entry(path, size, mtime, digest, "same name")
                continue
            page.title = title
            page.fm = {
                "type": folder, "title": title, "aliases": [], "summary": "",
                "status": "active" if page.lead.strip() else "draft", "created": day, "created_by": "user",
            }
            if folder == "person":  # the keys a person page always has; the model fills them on the first record
                page.fm.update({"name": title, "email": "", "last_contact": ""})
            if not page.facts and page.lead.strip():  # bullets typed under the title with no "## Facts" heading
                lead_lines = page.lead.split(chr(10))
                taken: set[str] = set()
                found = [f for l in lead_lines if l.lstrip().startswith("- ") and (f := wiki._parse_fact(l.strip(), taken, day))]
                if found:
                    page.facts = found
                    page.lead = chr(10).join(l for l in lead_lines if not l.lstrip().startswith("- ")).strip()
                    page.fm["status"] = "active" if page.lead else "draft"
            for f in page.facts:
                f.src = ["user"]
                f.since = f.since or day
            events = {"created": True, "facts_added": len(page.facts)}
            moved = _to_notes(page, day)
            if moved:
                events["moved"] = moved
            bullets += len(page.facts)
            ids_added += 1

        wiki._finalize(page, ctx)
        check = wiki._commit(root, page, wiki.format_page(page), ctx, "adopt")
        refresh.add(path)
        if not check["verified"]:
            continue
        touched.add(stem)
        detail = _detail(events)
        if not first_run:
            wiki._log(root, "adopt", stem, "user", detail)
            adopted.append({"page": stem, "changes": detail})

    for stem in gone:
        if stem in claimed:
            continue
        entry = pages.get(stem)
        if not entry:
            continue
        if entry.get("skip") or not entry.get("id"):
            pages.pop(stem, None)
            continue
        links = _link_count(root, stem)
        tail = f"drop the {_plural(links, 'link', 'links')} that still point at it?" if links else "is that what you wanted?"
        review.append(f"- [ ] [[{stem}]] — the page was deleted by hand; put it back from the copy under {PREV_DIR}/, or {tail}")
        entry["deleted"] = store.now_iso()

    for path in sorted(refresh):
        p = root / path
        try:
            text = read_text(p)
            st = p.stat()
            page = wiki.parse_page(text, path)
        except (OSError, UnicodeDecodeError, fmt.FrontmatterError, ValueError):
            continue
        pages[_stem(path)] = _entry(page, st.st_size, st.st_mtime_ns, _hash(text))
    for line in review:
        wiki._review_add(root, line)
    if first_run and (bullets or touched):  # ids alone are bookkeeping and say nothing worth a line
        wiki._log(root, "migrate", "Wiki", "-", f"reconcile first run: {scanned} pages, {ids_added} ids added, {_plural(bullets, 'bullet', 'bullets')} adopted")
    elif ids_added and not first_run:
        wiki._log(root, "adopt", "Wiki", "user", f"{_plural(ids_added, 'page', 'pages')} given an id")
    _save(root, state)
    if touched:
        wiki._write_index(root, sorted(touched))
    return {"adopted": adopted, "review": review, "busy": busy, "first_run": first_run, "scanned": scanned}


__all__ = ["reconcile", "detect", "note_write", "forget", "load_state", "STATE_PATH", "SCHEMA"]
