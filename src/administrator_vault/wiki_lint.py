"""Wiki lint and merge: PLAN-wiki.md §8 / §8.1.

``lint(fix)`` runs the checks over ``Administrator/Wiki/`` — 0 to 21. Checks
1–13 and 15 to 21 are decided in code; check 14 (contradictions) only returns the
pages touched since the last lint so the model can read their Facts. Flags
(``orphan``, ``stale``, ``oversized``, ``possible-duplicate``) and Review
lines are written in both modes; the fixes marked "auto" in the plan run
with ``fix=True``. Every run writes ``Wiki/_cache/lint-<date>.json`` and one
Log.md line carrying every count, so the trend is readable in the log.

``merge(keep, drop)`` folds one page into another and leaves a redirect page
behind so no link breaks. It is only ever called after the user said yes.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from administrator_vault import frontmatter as fmt
from administrator_vault import store, wiki, wiki_search
from administrator_vault.notes import ADMIN_DIR
from administrator_vault.store import VaultError, read_text, rel
from administrator_vault.wiki import (
    CAP_HINT, HISTORY_MAX, ITEM_SECTIONS, LIVE_STATUSES, LOG_MAX, SECTIONS, TYPES, WIKI_DIR, Fact, Page, _Ctx, _LINK_RE, _LOG_RE,
    _add_alias, _aliases, _all_pages, _atomic_write, _candidates_over, _finalize, _history, _link_target, _load, _log, _norm, _norm_name,
    _put_link, _RECORD_RE, _review_add, _review_text, _s, _statuses, _stem, _today, _write_index, _write_page, _wiki_lock,
    format_page, measure, page_path,
)

CACHE_DIR = wiki.CACHE_DIR
STALE_DAYS = {"topic": 60, "howto": 60, "person": 120, "org": 120, "me": 120}
UNCONFIRMED_DAYS = 180
UNCONFIRMED_MAX = 20
UNINGESTED_MAX = 50
CLOSE_DAYS = 90  # a topic with a due date and nothing new for this long is asked about
THIN_DAYS = 60  # a topic, org or howto still standing on one record after this long
SETTLED = ("closed", "dormant")  # the two statuses that already answer "close it?"
QUESTIONS_TOP = 3  # a question counts as answered when its page is in the first three hits
UNANSWERED_DAYS = wiki_search.UNANSWERED_DAYS  # how far back the questions the wiki could not answer are read
LINT_FLAGS = ("orphan", "stale", "oversized", "possible-duplicate")
REQUIRED_KEYS = ("type", "id", "title", "aliases", "summary", "status", "created", "updated", "verified", "sources", "open_items", "flags", "created_by")
TYPE_KEYS = {
    "person": ("name", "email", "last_contact"),
    "decision": ("decided", "by"),
}
OPTIONAL_KEYS = {
    "owner", "org", "due", "domains", "last_done", "email", "name", "last_contact",
    "outcome", "decided", "by", "superseded_by", "reversal", "options_rejected", "links", "risks",
}
CODE_SECTIONS = ("Facts", "People", "Topics", "Contacts", "Open", "Records", "Related", "History")
_STOP_TITLE = {"the", "a", "of"}
_H2_RE = re.compile(r"^## (.+?)\s*$")
_CHECKED_LINE_RE = re.compile(r"^\s*- \[x\] (.*)$", re.IGNORECASE)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LINT_FILE_RE = re.compile(r"^lint-\d{4}-\d{2}-\d{2}\.json$")


# ------------------------------------------------------------------ helpers


def _digest(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _norm_title(text: str) -> str:
    return " ".join(w for w in _norm_name(text).split() if w not in _STOP_TITLE)


def _days_ago(day: str, today: date) -> Optional[int]:
    s = _s(day)[:10]
    if not _DATE_RE.match(s):
        return None
    try:
        return (today - date.fromisoformat(s)).days
    except ValueError:
        return None


def _record_files(root: Path) -> list[Path]:
    """Every note outside the wiki that may link to a page (records, daily, weekly, Follow-ups)."""
    admin = root / ADMIN_DIR
    out = []
    for p in admin.rglob("*.md"):
        r = rel(root, p)
        if r.startswith((WIKI_DIR + "/", f"{ADMIN_DIR}/_backup/", f"{ADMIN_DIR}/Attachments/")):
            continue
        out.append(p)
    return out


def _link_targets(text: str) -> list[str]:
    out = []
    for m in _LINK_RE.finditer(text):
        t = m.group(1).strip().split("#", 1)[0].split("^", 1)[0].strip()
        if t:
            out.append(t)
    return out


class _Resolver:
    """Does a wikilink target point at a file? Full paths under Administrator/,
    vault-root paths, and Obsidian's shortest-name form are all accepted."""

    def __init__(self, root: Path) -> None:
        self.root = root
        # _cache/ holds working files, not notes: the copy of a page under
        # _cache/prev/ must not keep the name of a deleted page alive.
        files = [p for p in (root / ADMIN_DIR).rglob("*") if p.is_file() and not rel(root, p).startswith(CACHE_DIR + "/")]
        self.names = {p.stem.lower() for p in files if p.suffix.lower() == ".md"}
        self.names |= {p.name.lower() for p in files}

    def ok(self, target: str) -> bool:
        t = target.replace("\\", "/").strip("/")
        if t.startswith(ADMIN_DIR + "/"):
            t = t[len(ADMIN_DIR) + 1 :]
        for cand in (self.root / ADMIN_DIR / (t + ".md"), self.root / ADMIN_DIR / t, self.root / (t + ".md"), self.root / t):
            if cand.is_file():
                return True
        base = t.rsplit("/", 1)[-1].lower()
        return base in self.names or (base + ".md") in self.names


def _last_lint(root: Path) -> Optional[dict[str, Any]]:
    cache = root / CACHE_DIR
    if not cache.is_dir():
        return None
    files = sorted((p for p in cache.glob("lint-*.json") if _LINT_FILE_RE.match(p.name)), key=lambda p: p.stat().st_mtime)
    for p in reversed(files):
        try:
            return json.loads(read_text(p))
        except ValueError:
            continue
    return None


def _last_ingest(root: Path) -> str:
    p = root / wiki.LOG_PATH
    if not p.is_file():
        return ""
    last = ""
    for line in read_text(p).split("\n"):
        m = _LOG_RE.match(line)
        if m and m.group(2) == "ingest":
            last = max(last, m.group(1))
    return last


def _record_day(fm: dict[str, Any]) -> str:
    kind = fm.get("type")
    key = "received" if kind == "email" else "date" if kind == "chat" else "start"
    return _s(fm.get(key))[:10]


def uningested_records(root: Path) -> tuple[int, list[str]]:
    """Email / meeting / chat notes without a ``wiki:`` key that are newer than the last ingest (check 11)."""
    since = _last_ingest(root)[:10]
    out = []
    for kind in ("email", "meeting", "chat"):
        for p, fm in store._iter_notes(root, kind):
            if fm.get("wiki"):
                continue
            day = _record_day(fm)
            if since and day and day < since:
                continue
            out.append(rel(root, p))
    out.sort(reverse=True)
    return len(out), out


def _strip_links(text: str) -> str:
    return _LINK_RE.sub(lambda m: (m.group(0)[2:-2].split("|", 1)[-1]).strip(), text)


def _inbound(root: Path, pages: list[tuple[str, dict[str, Any]]]) -> dict[str, set[str]]:
    """stem -> set of files that link to it (wiki pages and records)."""
    stems = {_stem(p) for p, _fm in pages}
    by_base: dict[str, list[str]] = {}
    for s in stems:
        by_base.setdefault(s.rsplit("/", 1)[-1].lower(), []).append(s)
    hits: dict[str, set[str]] = {s: set() for s in stems}
    files = [root / p for p, _fm in pages] + _record_files(root)
    for p in files:
        try:
            text = read_text(p)
        except (OSError, UnicodeDecodeError):
            continue
        me = rel(root, p)
        my_stem = _stem(me)
        for t in _link_targets(text):
            t = t[len(ADMIN_DIR) + 1 :] if t.startswith(ADMIN_DIR + "/") else t
            targets = [t] if t in hits else by_base.get(t.rsplit("/", 1)[-1].lower(), []) if "/" not in t else []
            for s in targets:
                if s != my_stem:
                    hits[s].add(me)
    return hits


# --------------------------------------------------------------- questions

# "- <question> → [[Wiki/Topics/x]]" with an optional "f:<id>" naming the fact
_QUESTION_RE = re.compile(
    r"^\s*-\s*(?:\[[ xX]\]\s*)?(?P<q>.+?)\s*(?:→|->)\s*\[\[(?P<page>[^\]|#]+?)\s*(?:\|[^\]]*)?\]\]"
    r"(?:\s*f:(?P<fact>[A-Za-z0-9_-]+))?\s*$"
)


def read_questions(root: Path) -> list[dict[str, str]]:
    """The lines under ``## Questions`` in ``Wiki/Questions.md``, as
    ``[{question, page, fact}]``: what the user wants the wiki to answer and the
    page (or the one fact) that should answer it. The file is the user's; a line
    that does not follow the form is left alone."""
    p = root / store.QUESTIONS_PATH
    if not p.is_file():
        return []
    out: list[dict[str, str]] = []
    under = False
    for line in read_text(p).split("\n"):
        if line.startswith("## "):
            under = line[3:].strip().lower() == "questions"
            continue
        m = _QUESTION_RE.match(line) if under else None
        if not m:
            continue
        question = " ".join(m.group("q").split())
        try:
            stem = _stem(page_path(m.group("page").strip()))
        except VaultError:
            continue
        if question:
            out.append({"question": question, "page": stem, "fact": _s(m.group("fact"))})
    return out


def questions_score(root: Path, stems: Optional[set[str]] = None, top: int = QUESTIONS_TOP) -> dict[str, Any]:
    """Ask the wiki every question in Questions.md and count the answers: a
    question is answered when its page (or the fact it names) comes back in the
    first ``top`` hits. Lines naming a page that does not exist yet are listed
    under ``unknown`` and not counted. They are not written to ``queries.log``:
    they are the measure, not questions somebody asked."""
    rows = read_questions(root)
    if stems is None:
        stems = {_stem(p) for p, _fm in _all_pages(root)}
    found = 0
    asked = 0
    misses: list[dict[str, Any]] = []
    unknown: list[dict[str, str]] = []
    for row in rows:
        if row["page"] not in stems:
            unknown.append({"question": row["question"], "expected": row["page"]})
            continue
        asked += 1
        hits = wiki_search.search(row["question"], limit=top, root=root, log=False)
        expected = row["page"] + (f" f:{row['fact']}" if row["fact"] else "")
        if row["fact"]:
            hit = any(h["fact_id"] == row["fact"] for h in hits)
        else:
            hit = any(h["page"] == row["page"] for h in hits)
        if hit:
            found += 1
        else:
            misses.append({
                "question": row["question"], "expected": expected,
                "top": [h["page"] + (f" f:{h['fact_id']}" if h["fact_id"] else "") for h in hits],
            })
    return {"name": "questions", "asked": asked, "found": found, "misses": misses, "unknown": unknown}


# ------------------------------------------------------------------ lint


def lint(fix: bool = False, created_by: str = wiki.CREATED_BY) -> dict[str, Any]:
    root = store.vault_root()
    today = date.today()
    today_s = today.isoformat()
    from administrator_vault import wiki_reconcile  # imported here: that module reads this one

    with _wiki_lock(root):
        started = store.now_iso()
        edits = wiki_reconcile.reconcile(root, lock_held=True)  # 0 what the user changed by hand
        confirmed = wiki._settle_ticked_decisions(root)  # a decision the user ticked in Review.md
        previous = _last_lint(root)
        last_done = _s((previous or {}).get("finished"))
        listing = _all_pages(root)
        pages: dict[str, Page] = {}
        raw: dict[str, str] = {}
        for path, _fm in listing:
            raw[path] = read_text(root / path)
            pages[path] = wiki.parse_page(raw[path], path)
        resolver = _Resolver(root)
        checks: dict[str, Any] = {"0": {
            "name": "hand-edits", "adopted": edits["adopted"], "review": edits["review"],
            "first_run": edits["first_run"], "scanned": edits["scanned"],
        }}
        flags: dict[str, list[str]] = {p: [] for p in pages}
        id_cache: dict[str, str] = {}
        to_write: set[str] = set()
        review_lines: list[str] = []
        log_lines: list[tuple[str, str]] = []

        # 1 index <-> files
        idx = root / wiki.INDEX_PATH
        in_index: set[str] = set()
        if idx.is_file():
            for t in _link_targets(read_text(idx)):
                if t.endswith("/Index"):
                    sub = root / ADMIN_DIR / (t + ".md")
                    if sub.is_file():
                        in_index |= set(_link_targets(read_text(sub)))
                else:
                    in_index.add(t)
        stems = {_stem(p) for p in pages}
        checks["1"] = {"name": "index", "missing_lines": sorted(stems - in_index), "extra_lines": sorted(t for t in in_index - stems if t.startswith("Wiki/") and not t.endswith("/Index")), "fixed": True}

        # 2 dangling links
        dangling: list[dict[str, Any]] = []
        for path, page in pages.items():
            fm_text = fmt.split_note(raw[path])[1]
            for t in set(_link_targets(raw[path])):
                if resolver.ok(t):
                    continue
                where = "frontmatter" if f"[[{t}" in fm_text else "body"
                dangling.append({"page": page.stem, "target": t, "where": where})
            if fix:
                changed = False
                for f in page.facts:
                    if any(not resolver.ok(t) for t in _link_targets(f.text)):
                        f.text = _strip_links(f.text)
                        changed = True
                for name in CODE_SECTIONS:
                    lines = page.sections.get(name) or []
                    for i, line in enumerate(lines):
                        if any(not resolver.ok(t) for t in _link_targets(line)):
                            lines[i] = _strip_links(line)
                            changed = True
                for name in ITEM_SECTIONS:  # the open items and milestones keep their own lines
                    for o in page.items(name):
                        if o.record and not resolver.ok(o.record):
                            o.record = ""
                            changed = True
                        for key in ("text", "raw"):
                            was = getattr(o, key)
                            if was and any(not resolver.ok(t) for t in _link_targets(was)):
                                setattr(o, key, _strip_links(was))
                                changed = True
                if changed:
                    to_write.add(path)
        checks["2"] = {"name": "dangling-links", "count": len(dangling), "items": dangling[:50], "fixed": fix}

        # 3 orphans
        inbound = _inbound(root, listing)
        orphans = sorted(s for s, who in inbound.items() if not who)
        for path, page in pages.items():
            if page.stem in orphans:
                flags[path].append("orphan")
        checks["3"] = {"name": "orphans", "count": len(orphans), "pages": orphans}

        # 4 frontmatter schema
        schema: list[dict[str, Any]] = []
        for path, page in pages.items():
            fm = page.fm
            need = REQUIRED_KEYS + TYPE_KEYS.get(page.type, ())
            missing = [k for k in need if k not in fm]
            extra = [k for k in fm if k not in need and k not in OPTIONAL_KEYS]
            bad = []
            if _s(fm.get("status")) not in _statuses(page.type):
                bad.append("status")
            for k in ("aliases", "flags"):
                if k in fm and not isinstance(fm[k], list):
                    bad.append(k)
            for k in ("created", "verified"):
                if k in fm and not _DATE_RE.match(_s(fm[k])[:10]):
                    bad.append(k)
            for k in ("sources", "open_items"):
                if k in fm and not isinstance(fm[k], int):
                    bad.append(k)
            expect_sources = wiki.count_sources(root, page, id_cache)
            expect_open = sum(1 for o in page.opens if not o.raw and not o.done)
            hand = []
            if "sources" in fm and fm.get("sources") != expect_sources:
                hand.append("sources")
            if "open_items" in fm and fm.get("open_items") != expect_open:
                hand.append("open_items")
            if missing or extra or bad or hand:
                schema.append({"page": page.stem, "missing": missing, "extra": extra, "mistyped": bad, "code_owned_edited": hand})
                if fix and (missing or bad or hand):
                    if "status" in bad:
                        fm["status"] = _statuses(page.type)[0] if page.lead or page.type == "decision" else "draft"
                    for k in bad:
                        if k in ("aliases", "flags"):
                            fm[k] = [_s(fm[k])] if _s(fm[k]) else []
                        elif k in ("created", "verified", "sources", "open_items"):
                            fm.pop(k, None)
                    to_write.add(path)
        checks["4"] = {"name": "frontmatter", "count": len(schema), "items": schema, "fixed": fix}

        # 5 sections
        sections: list[dict[str, Any]] = []
        for path, page in pages.items():
            body = fmt.split_note(raw[path])[2]
            heads = []
            for line in body.split("\n"):
                m = _H2_RE.match(line)
                if m:
                    if m.group(1).strip() == "Notes":
                        break
                    heads.append(m.group(1).strip())
            contract = [n for n in SECTIONS.get(page.type, SECTIONS["topic"]) if n != "Notes"]
            unknown = [h for h in heads if h not in contract]
            dup = [h for h, n in Counter(heads).items() if n > 1]
            known = [h for h in heads if h in contract]
            ordered = sorted(set(known), key=contract.index)
            out_of_order = [h for h in dict.fromkeys(known)] != ordered
            if unknown or dup or out_of_order:
                sections.append({"page": page.stem, "unknown": unknown, "duplicate": dup, "out_of_order": out_of_order})
                if fix and (dup or out_of_order):
                    to_write.add(path)
        checks["5"] = {"name": "sections", "count": len(sections), "items": sections, "fixed": fix}

        # 6 oversized
        oversized = []
        for path, page in pages.items():
            m = measure(page.type, raw[path])
            if m["over"]:
                flags[path].append("oversized")
                oversized.append({"page": page.stem, **{k: v for k, v in m.items() if k != "over"}})
        checks["6"] = {"name": "oversized", "count": len(oversized), "items": oversized, "remedies": CAP_HINT}

        # 7 stale
        stale = []
        for path, page in pages.items():
            fm = page.fm
            if _s(fm.get("status")) not in LIVE_STATUSES or page.type not in STALE_DAYS:
                continue  # a decision never goes stale: it is what was decided, not what is new
            age = _days_ago(_s(fm.get("verified") or fm.get("created")), today)
            limit = STALE_DAYS[page.type]
            if age is not None and age > limit:
                flags[path].append("stale")
                item = {"page": page.stem, "verified": _s(fm.get("verified"))[:10], "days": age, "set_dormant": False}
                if fix and page.type == "topic" and not _s(fm.get("due")).strip():  # a topic with a due date is asked about by check 17 instead
                    fm["status"] = "dormant"
                    item["set_dormant"] = True
                    to_write.add(path)
                    log_lines.append((page.stem, f"stale {age} days → dormant"))
                stale.append(item)
        checks["7"] = {"name": "stale", "count": len(stale), "items": stale}

        # 8 due in the past
        due = []
        for path, page in pages.items():
            d = _s(page.fm.get("due"))[:10]
            if page.type == "topic" and _s(page.fm.get("status")) in LIVE_STATUSES and _DATE_RE.match(d) and d < today_s:
                due.append({"page": page.stem, "due": d})
        checks["8"] = {"name": "due-past", "count": len(due), "items": due}

        # 9 open items done in the record
        done_open = []
        for path, page in pages.items():
            for o in page.opens:
                if o.raw or o.done or not o.record:
                    continue
                rp = root / ADMIN_DIR / (o.record.strip() + ".md")
                if not rp.is_file():
                    continue
                checked = [_norm(c.group(1)) for c in (_CHECKED_LINE_RE.match(l) for l in read_text(rp).split("\n")) if c]
                want = _norm(o.text)
                if any(want and (want in c or c in want) for c in checked):
                    done_open.append({"page": page.stem, "id": o.id, "text": o.text, "record": o.record})
                    if fix:
                        o.done = True
                        to_write.add(path)
        checks["9"] = {"name": "open-done", "count": len(done_open), "items": done_open, "fixed": fix}

        # 10 duplicates
        keys: dict[tuple[str, str], list[str]] = {}
        for path, page in pages.items():
            fm = page.fm
            names = {_norm_title(n) for n in [page.title] + _aliases(fm)}
            for n in names:
                if n:
                    keys.setdefault(("name", n), []).append(path)
            if _s(fm.get("email")).strip():
                keys.setdefault(("email", _s(fm.get("email")).strip().lower()), []).append(path)
            for d in fm.get("domains") or []:
                if _s(d).strip():
                    keys.setdefault(("domain", _s(d).strip().lower().lstrip("@")), []).append(path)
        pairs: dict[tuple[str, str], list[str]] = {}
        for (kind, value), paths in keys.items():
            uniq = sorted(set(paths))
            for a in range(len(uniq)):
                for b in range(a + 1, len(uniq)):
                    pairs.setdefault((uniq[a], uniq[b]), []).append(f'{kind} "{value}"')
        dups = []
        for (a, b), why in sorted(pairs.items()):
            for p in (a, b):
                if "possible-duplicate" not in flags[p]:
                    flags[p].append("possible-duplicate")
            line = f"- [ ] merge [[{_stem(b)}]] into [[{_stem(a)}]]? (shared {', '.join(why)})"
            review_lines.append(line)
            dups.append({"a": _stem(a), "b": _stem(b), "shared": why})
        checks["10"] = {"name": "duplicates", "count": len(dups), "items": dups}

        # 11 records never ingested
        n_un, un = uningested_records(root)
        checks["11"] = {"name": "uningested", "count": n_un, "records": un[:UNINGESTED_MAX]}

        # 12 candidates
        cands = _candidates_over(root, listing)
        checks["12"] = {"name": "candidates", "count": len(cands), "items": cands}

        # 13 rotation
        long_hist = [page.stem for path, page in pages.items() if len(page.sections.get("History") or []) > HISTORY_MAX]
        if fix:
            to_write |= {path for path, page in pages.items() if page.stem in long_hist}
        lp = root / wiki.LOG_PATH
        n_log = sum(1 for l in read_text(lp).split("\n") if l.startswith("- [")) if lp.is_file() else 0
        checks["13"] = {"name": "rotation", "history_over": long_hist, "log_lines": n_log, "log_over": n_log >= LOG_MAX, "fixed": fix}

        # 14 pages touched since the last lint: the model reads their Facts.
        # The previous report holds a digest of each page's text as the lint left it;
        # a page whose digest differs (or is new) was written since.
        snapshot = (previous or {}).get("digests")

        def _touched(path: str, page: Page) -> bool:
            if not isinstance(snapshot, dict):
                return True
            return _digest(raw[path]) != _s(snapshot.get(page.stem))

        touched = sorted(page.stem for path, page in pages.items() if _touched(path, page))
        checks["14"] = {"name": "contradictions", "ask_model": touched, "since": last_done or None, "detail": "Read the Facts of these pages and report pairs that cannot both be true with a contest op."}

        # 15 unconfirmed facts
        unconfirmed: dict[str, list[dict[str, str]]] = {}
        n_unc = 0
        for path, page in pages.items():
            if _s(page.fm.get("status")) not in LIVE_STATUSES:
                continue
            for f in page.facts:
                age = _days_ago(f.since, today)
                if age is not None and age > UNCONFIRMED_DAYS and len(f.src) == 1:
                    n_unc += 1
                    if n_unc <= UNCONFIRMED_MAX:
                        unconfirmed.setdefault(page.stem, []).append({"id": f.id, "text": f.text, "since": f.since})
        checks["15"] = {"name": "unconfirmed", "count": n_unc, "shown": min(n_unc, UNCONFIRMED_MAX), "pages": unconfirmed}

        # 16 consistency: what two pages say about each other, and what one page says twice
        by_stem = {page.stem: path for path, page in pages.items()}
        consistency: list[dict[str, Any]] = []
        # the pages each page links to; a person's org key counts as a link
        out: dict[str, set[str]] = {}
        org_of: dict[str, str] = {}
        for path, page in pages.items():
            out[page.stem] = {t for t in wiki._link_sections(page) if t in by_stem and t != page.stem}
            if page.type == "person" and _s(page.fm.get("org")).strip():
                raw_org = _s(page.fm.get("org")).strip()
                org = _link_target(raw_org)
                if not (org in by_stem and pages[by_stem[org]].type == "org"):
                    orgs = [(p, pg.fm) for p, pg in pages.items() if pg.type == "org"]
                    hit = wiki._find_by_name(orgs, raw_org, [])
                    org = _stem(hit[0]) if hit else ""
                if org in by_stem and pages[by_stem[org]].type == "org":
                    org_of[page.stem] = org
                    out[page.stem].add(org)
        for a in sorted(out):
            for b in sorted(out[a]):
                if a in out[b]:
                    continue
                other = pages[by_stem[b]]
                section = wiki._section_for(other.type, pages[by_stem[a]].type)
                consistency.append({
                    "page": a, "kind": "org-contacts" if org_of.get(a) == b else "link",
                    "other": b, "section": section, "fixed": fix,
                })
                if fix:
                    _put_link(other.lines(section), a, "", section != "Related")
                    out[b].add(a)
                    to_write.add(by_stem[b])
        # an owner is a person page
        people = [(p, pg.fm) for p, pg in pages.items() if pg.type == "person"]
        for path, page in pages.items():
            owner = _s(page.fm.get("owner")).strip()
            if page.type not in ("topic", "howto") or not owner:
                continue
            target = _link_target(owner)
            if target in by_stem and pages[by_stem[target]].type == "person":
                continue
            hit = wiki._find_by_name(people, owner, [])
            item = {"page": page.stem, "kind": "owner", "owner": owner, "other": _stem(hit[0]) if hit else None, "fixed": False}
            if hit and fix:
                page.fm["owner"] = f"[[{_stem(hit[0])}]]"
                to_write.add(path)
                item["fixed"] = True
            elif not hit:
                review_lines.append(f'- [ ] [[{page.stem}]] — owner: "{owner}" but no person page carries that name; link the person page or drop the key')
            consistency.append(item)
        # the due date against a fact on the same page naming another day for the same thing
        for path, page in pages.items():
            d = _s(page.fm.get("due"))[:10]
            if page.type != "topic" or not _DATE_RE.match(d):
                continue
            about = wiki._content_tokens(page.title)
            for f in page.facts:
                days = {v for v in wiki._values(f.text) if _DATE_RE.match(v)}
                if not days or d in days:
                    continue
                words = wiki._content_tokens(f.text)
                if len(words & about) < 2 and not (words & {"due", "deadline"}):
                    continue
                consistency.append({"page": page.stem, "kind": "due", "due": d, "id": f.id, "text": f.text})
                review_lines.append(f'- [ ] [[{page.stem}]] — due: {d} but f:{f.id} says "{f.text}"; which day holds?')
        checks["16"] = {"name": "consistency", "count": len(consistency), "items": consistency, "fixed": fix}

        # 17 a project nothing has moved for three months
        # (a page already closed or parked as dormant is not asked about again:
        # that question was put by check 7 and the status is the answer)
        close = []
        for path, page in pages.items():
            d = _s(page.fm.get("due"))[:10]
            if page.type != "topic" or not _DATE_RE.match(d) or _s(page.fm.get("status")) in SETTLED:
                continue
            age = _days_ago(_s(page.fm.get("verified") or page.fm.get("created")), today)
            if age is not None and age > CLOSE_DAYS:
                close.append({"page": page.stem, "due": d, "verified": _s(page.fm.get("verified"))[:10], "days": age})
                review_lines.append(f"- [ ] [[{page.stem}]] — no update in {CLOSE_DAYS} days: close it?")
        checks["17"] = {"name": "close", "count": len(close), "items": close}

        # 18 a page that never grew past the record it was born from
        # (a person page is left out: one mail is reason enough to keep it;
        # so is a page already closed or dormant — retiring it adds nothing)
        thin = []
        for path, page in pages.items():
            if page.type not in ("topic", "org", "howto") or _s(page.fm.get("status")) in SETTLED:
                continue
            age = _days_ago(_s(page.fm.get("created")), today)
            if age is None or age <= THIN_DAYS:
                continue
            n = wiki.count_sources(root, page, id_cache)
            if n <= 1:
                thin.append({"page": page.stem, "sources": n, "days": age})
                review_lines.append(f"- [ ] [[{page.stem}]] — one record after {THIN_DAYS} days: merge or retire?")
        checks["18"] = {"name": "thin", "count": len(thin), "items": thin}

        # 19 overdue: the user's own items past their due date
        overdue = []
        for path, page in pages.items():
            for o in page.opens:
                if o.raw or o.done or _s(o.owner).lower() != "me":
                    continue
                if not _DATE_RE.match(_s(o.due)[:10]) or _s(o.due)[:10] >= today_s:
                    continue
                overdue.append({"page": page.stem, "id": o.id, "text": o.text, "due": _s(o.due)[:10]})
                review_lines.append(f'- [ ] [[{page.stem}]] — overdue: "{o.text}" due {_s(o.due)[:10]} — done, reschedule, or drop')
        checks["19"] = {"name": "overdue", "count": len(overdue), "items": overdue}

        # 20 questions: the user's own list in Questions.md, asked of the wiki
        checks["20"] = questions_score(root, stems)

        # 21 the questions the wiki could not answer, asked more than once
        gaps = wiki_search.unanswered(root, UNANSWERED_DAYS, today_s)
        checks["21"] = {"name": "unanswered", "count": len(gaps), "days": UNANSWERED_DAYS, "items": gaps}
        for gap in gaps:
            review_lines.append(f'- [ ] no page answers "{gap["query"]}" — create one?')

        # stale / orphan / oversized / duplicate pages with no other open Review line get one
        for path, page in pages.items():
            if "stale" in flags[path]:
                review_lines.append(f"- [ ] [[{page.stem}]] — stale: verified {_s(page.fm.get('verified'))[:10]}; close it, confirm a fact, or leave it dormant")

        # write flags and fixes
        written = []
        flagged: dict[str, list[str]] = {}
        for path, page in pages.items():
            old = [str(f) for f in (page.fm.get("flags") or [])]
            new = [f for f in old if f not in LINT_FLAGS] + flags[path]
            if new:
                flagged[page.stem] = new
            if new != old or path in to_write:
                page.fm["flags"] = new
                ctx = _Ctx(root=root, src="user", since=today_s, record=None)
                _finalize(page, ctx)
                _write_page(page, ctx)
                raw[path] = format_page(page)
                written.append(page.stem)
        open_before = set(_review_text(root)[0])
        added = []
        for line in review_lines:
            if line not in open_before:
                _review_add(root, line)
                added.append(line)
        for stem, detail in log_lines:
            _log(root, "lint", stem, "-", detail)
        _write_index(root)
        summary = {
            "dangling": checks["2"]["count"], "orphans": checks["3"]["count"], "frontmatter": checks["4"]["count"], "sections": checks["5"]["count"],
            "oversized": checks["6"]["count"], "stale": checks["7"]["count"], "due_past": checks["8"]["count"], "open_done": checks["9"]["count"],
            "duplicates": checks["10"]["count"], "uningested": checks["11"]["count"], "candidates": checks["12"]["count"],
            "history_over": len(long_hist), "ask_model": len(touched), "unconfirmed": n_unc,
            "consistency": checks["16"]["count"], "close": checks["17"]["count"], "thin": checks["18"]["count"],
            "overdue": checks["19"]["count"], "hand_edits": len(edits["adopted"]),
            "questions": f"{checks['20']['found']}/{checks['20']['asked']}", "unanswered": checks["21"]["count"],
        }
        # one line per run with every count on it, so vault_wiki_log shows the trend
        _log(root, "lint", "Wiki", "-", ("fix, " if fix else "")
             + f"{len(pages)} pages, {len(flagged)} flagged, {len(added)} review lines, {len(written)} written, "
             + ", ".join(f"{name.replace('_', ' ')} {value}" for name, value in summary.items()))
        finished = store.now_iso()
        report = {
            "date": today_s, "started": started, "finished": finished, "fix": fix, "pages": len(pages),
            "counts": summary, "checks": checks, "flagged": flagged, "review_added": added, "written": written,
            "digests": {page.stem: _digest(raw[path]) for path, page in pages.items()},
        }
        if edits["adopted"]:
            report["adopted"] = edits["adopted"]
        if confirmed:
            report["confirmed_decisions"] = confirmed
        cache = root / CACHE_DIR / f"lint-{today_s}.json"  # one file per day; a later run the same day replaces it
        _atomic_write(cache, json.dumps(report, ensure_ascii=False, indent=1))
        report["cache"] = rel(root, cache)
    return report


def summary(root: Path) -> dict[str, Any]:
    """The counts the weekly note shows: open review items, stale pages,
    un-ingested records, topic candidates over the threshold, how many of the
    questions in Questions.md the wiki answers, and how many questions it could
    not answer at all."""
    listing = _all_pages(root)
    stale = sum(1 for _p, fm in listing if "stale" in (fm.get("flags") or []))
    score = questions_score(root, {_stem(p) for p, _fm in listing})
    return {
        "review_open": len(_review_text(root)[0]),
        "stale": stale,
        "uningested": uningested_records(root)[0],
        "candidates": len(_candidates_over(root, listing)),
        "questions": f"{score['found']}/{score['asked']}",
        "unanswered": len(wiki_search.unanswered(root, UNANSWERED_DAYS)),
    }


# ------------------------------------------------------------------ merge


def _replace_links(text: str, old_stem: str, new_stem: str) -> str:
    return re.sub(r"\[\[" + re.escape(old_stem) + r"(?=[\]|#])", "[[" + new_stem, text)


def _dedupe_links(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for l in lines:
        m = _LINK_RE.search(l)
        key = _link_target(m.group(1)) if m and l.startswith("- [[") else l
        if key in seen:
            continue
        seen.add(key)
        out.append(l)
    return out


def merge(keep: str, drop: str, created_by: str = wiki.CREATED_BY) -> dict[str, Any]:
    root = store.vault_root()
    keep_path, drop_path = page_path(keep), page_path(drop)
    if keep_path == drop_path:
        raise VaultError("keep and drop are the same page.")
    from administrator_vault import wiki_reconcile  # imported here: that module reads this one

    with _wiki_lock(root):
        adopted = wiki_reconcile.reconcile(root, lock_held=True)["adopted"]
        kp, dp = _load(root, keep_path), _load(root, drop_path)
        for pg in (kp, dp):
            if pg.type not in TYPES:
                raise VaultError(f"{pg.stem} is a {pg.type or 'typeless'} page; only {', '.join(TYPES)} pages can be merged.")
            if pg.type == "decision":
                raise VaultError(f"{pg.stem} is a decision; decisions are never merged. Link them with superseded_by instead.")
        ctx = _Ctx(root=root, src="user", since=_today(), record=None)
        ctx.record = {"link": f"[[{dp.stem}]]", "path": dp.path, "date": _today(), "src": "user", "summary": ""}  # History lines name the dropped page
        added, confirmed, refused = [], [], []
        for f in dp.facts:
            dup = next((k for k in kp.facts if _norm(k.text) == _norm(f.text)), None)
            if dup:
                for s in reversed(f.src):
                    wiki._extend_src(dup, s)
                confirmed.append(dup.id)
                continue
            if len(kp.facts) >= wiki.FACTS_MAX:
                refused.append({"id": f.id, "text": f.text, "reason": "facts-cap"})
                continue
            nf = Fact(wiki._new_id(kp.ids()), f.text, f.since, list(f.src)[: wiki.SRC_MAX])
            kp.facts.append(nf)
            ctx.verified.append(f.since)
            added.append(nf.id)
        # names and identity
        for a in [dp.title] + _aliases(dp.fm) + [dp.stem.rsplit("/", 1)[-1]]:
            _add_alias(kp, a)
        if kp.type == "person":
            if not _s(kp.fm.get("email")) and _s(dp.fm.get("email")):
                kp.fm["email"] = dp.fm["email"]
            elif _s(dp.fm.get("email")) and _s(dp.fm.get("email")).lower() != _s(kp.fm.get("email")).lower():
                _add_alias(kp, _s(dp.fm["email"]))
            old_lc, new_lc = _s(kp.fm.get("last_contact")), _s(dp.fm.get("last_contact"))
            if new_lc > old_lc:
                kp.fm["last_contact"] = new_lc
        if kp.type == "org":
            have = [_s(d) for d in (kp.fm.get("domains") or [])]
            kp.fm["domains"] = have + [_s(d) for d in (dp.fm.get("domains") or []) if _s(d) and _s(d).lower() not in {h.lower() for h in have}]
        for k in ("org", "owner", "due", "summary"):
            if not _s(kp.fm.get(k)) and _s(dp.fm.get(k)):
                kp.fm[k] = dp.fm[k]
        # sections
        kp.lines("Records").extend(l for l in dp.sections.get("Records") or [] if l not in kp.lines("Records"))
        have = {_norm(o.text) for o in kp.opens}
        kp.opens.extend(o for o in dp.opens if not o.raw and _norm(o.text) not in have)
        for name in ("People", "Topics", "Contacts", "Related"):
            for l in dp.sections.get(name) or []:
                m = wiki._LINK_LINE_RE.match(l)
                if m:
                    t = _link_target(m.group(1))
                    if t != kp.stem and t != dp.stem:
                        _put_link(kp.lines(name), t, m.group(2) or "", name != "Related")
        for name in list(kp.sections):
            if name == "Records":
                kp.sections[name] = _dedupe_links([l for l in kp.sections[name] if dp.stem not in l])
        for o in kp.opens:  # an item that named the dropped page now names the kept one
            if o.record == dp.stem:
                o.record = ""
            if _link_target(_s(o.owner)) == dp.stem:
                o.owner = f"[[{kp.stem}]]"
        _history(kp, ctx, f'merged [[{dp.stem}]] into this page: facts added {len(added)}, confirmed {len(confirmed)}')
        # the merge answers the duplicate question; the flag goes with it
        kp.fm["flags"] = [f for f in (kp.fm.get("flags") or []) if f != "possible-duplicate"]
        _finalize(kp, ctx)
        text = format_page(kp)
        sizes = measure(kp.type, text)
        if sizes["over"]:
            raise VaultError(f"Refused: the merged page would be {sizes['lines']} lines / {sizes['chars']} chars (cap {sizes['max_lines']} / {sizes['max_chars']}). {CAP_HINT}")
        # keep a full copy of the dropped page, then turn it into a redirect
        hp = root / wiki.HISTORY_DIR / (dp.stem[len("Wiki/"):] + ".md")
        old = read_text(hp) if hp.is_file() else f"# History of [[{dp.stem}]]\n\n"
        _atomic_write(hp, old.rstrip("\n") + f"\n\n## Page text before the merge into [[{kp.stem}]] on {_today()}\n\n" + read_text(root / dp.path).rstrip("\n") + "\n")
        _atomic_write(root / kp.path, text)
        redirect_fm = {"type": "redirect", "title": dp.title, "aliases": _aliases(dp.fm), "redirect": f"[[{kp.stem}]]", "created_by": created_by}
        _atomic_write(root / dp.path, fmt.format_frontmatter(redirect_fm) + f"\n# {dp.title}\n\nMerged into [[{kp.stem}]] on {_today()}.\n")
        # links on other wiki pages follow the page
        relinked = []
        for path, _fm in _all_pages(root):
            if path in (kp.path, dp.path):
                continue
            t = read_text(root / path)
            if f"[[{dp.stem}" not in t:
                continue
            pg = wiki.parse_page(_replace_links(t, dp.stem, kp.stem), path)
            for name in ("People", "Topics", "Contacts", "Related", "Records", "Open"):
                if name in pg.sections:
                    pg.sections[name] = _dedupe_links(pg.sections[name])
            c2 = _Ctx(root=root, src="user", since=_today(), record=None)
            _finalize(pg, c2)
            _write_page(pg, c2)
            relinked.append(pg.stem)
        # Review lines that named the dropped page are done
        open_lines, done_lines = _review_text(root)
        moved = [l for l in open_lines if f"[[{dp.stem}]]" in l]
        if moved:
            open_lines = [l for l in open_lines if l not in moved]
            done_lines += [l.replace("- [ ] ", "- [x] ", 1) + f" — merged {_today()}" for l in moved]
            wiki._write_review(root, open_lines, done_lines)
        _log(root, "merge", kp.stem, f"[[{dp.stem}]]", f"facts added {len(added)}, confirmed {len(confirmed)}, refused {len(refused)}, relinked {len(relinked)}")
        _write_index(root, [kp.stem, dp.stem] + relinked)
    out = {
        "keep": kp.path, "drop": dp.path, "redirect": f"[[{kp.stem}]]", "facts_added": added, "facts_confirmed": confirmed, "facts_refused": refused,
        "relinked": relinked, "review_closed": len(moved), "sizes": {k: v for k, v in sizes.items() if k != "over"},
    }
    if adopted:
        out["adopted"] = adopted
    return out


__all__ = ["lint", "merge", "summary", "uningested_records", "STALE_DAYS"]
