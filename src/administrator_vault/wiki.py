"""The wiki: pages the model keeps next to the records (``Administrator/Wiki/``).

Python form of PLAN-wiki.md §2–§7 and ``skills/wiki/references/wiki.md`` in the
administrator plugin. Six page types (person, org, topic, decision, howto, me), one
fixed section contract, facts as keyed bullets with a hidden comment, four
fact operations plus page operations, size caps that refuse writes, a
generated Index.md / Log.md / Review.md, one write lock, atomic writes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Optional

from administrator_vault import frontmatter as fmt
from administrator_vault import notes, store
from administrator_vault.notes import ADMIN_DIR
from administrator_vault.store import VaultError, read_text, rel, resolve

CREATED_BY = "administrator/0.4.1"
WIKI_DIR = f"{ADMIN_DIR}/Wiki"
INDEX_PATH = f"{WIKI_DIR}/Index.md"
LOG_PATH = f"{WIKI_DIR}/Log.md"
REVIEW_PATH = f"{WIKI_DIR}/Review.md"
SCHEMA_PATH = f"{WIKI_DIR}/Wiki.md"
LOCK_PATH = f"{WIKI_DIR}/.lock"
HISTORY_DIR = f"{WIKI_DIR}/_history"
CACHE_DIR = f"{WIKI_DIR}/_cache"
CANDIDATES_PATH = f"{CACHE_DIR}/candidates.json"
PREV_DIR = f"{CACHE_DIR}/prev"  # the text of each page as it was before the last write

TYPES = ("person", "org", "topic", "decision", "howto", "me")
TYPE_FOLDER = {"person": "People", "org": "Orgs", "topic": "Topics", "decision": "Decisions", "howto": "Howto", "me": ""}
TYPE_HEADING = {"topic": "Topics", "decision": "Decisions", "person": "People", "org": "Orgs", "howto": "Howto", "me": "Me"}
INDEX_ORDER = ("topic", "decision", "person", "org", "howto", "me")
# the index groups in the order they are written: a topic with a due date is a
# project, and the decisions come between the projects and the other topics
INDEX_BODY_ORDER = (
    "topic/Projects", "decision", "decision/Decisions", "topic", "topic/Topics",
    "person", "person/People", "org", "org/Orgs", "howto", "howto/Howto", "me", "me/Me",
)
SECTIONS = {
    "topic": ("Facts", "Milestones", "People", "Open", "Records", "Related", "History", "Notes"),
    "person": ("Facts", "Topics", "Open", "Records", "Related", "History", "Notes"),
    "org": ("Facts", "Contacts", "Topics", "Records", "Related", "History", "Notes"),
    "decision": ("Facts", "People", "Open", "Records", "Related", "History", "Notes"),
    "howto": ("Steps", "Facts", "Records", "Related", "History", "Notes"),
    "me": ("Facts", "Open", "Related", "History", "Notes"),
}
# the sections whose lines are items with a checkbox and a hidden comment, and the letter their id carries
ITEM_SECTIONS = {"Open": "o", "Milestones": "m"}
# (page type, linked page type) -> section that lists the link with a role
LINK_SECTION = {
    ("topic", "person"): "People",
    ("person", "topic"): "Topics",
    ("org", "person"): "Contacts",
    ("org", "topic"): "Topics",
    ("decision", "person"): "People",
    ("person", "decision"): "Topics",  # a person page lists topics and decisions in one section
    ("org", "decision"): "Topics",
}
CODE_OWNED = ("created", "updated", "verified", "sources", "open_items", "flags", "id")
KEY_ORDER = (
    "type", "id", "title", "name", "email", "aliases", "domains", "summary", "status", "owner", "org", "due",
    "outcome", "decided", "by", "superseded_by", "reversal", "options_rejected", "links", "risks",
    "last_contact", "last_done", "created", "updated", "verified", "sources", "open_items", "flags", "created_by",
)
STATUSES = ("active", "dormant", "closed", "draft")
# the statuses a page type allows; the first one is what a page with a lead gets
STATUSES_BY_TYPE = {
    "topic": ("active", "at-risk", "blocked", "closed", "dormant", "draft"),
    "decision": ("current", "superseded", "dropped", "draft"),
}
LIVE_STATUSES = ("active", "at-risk", "blocked")  # a topic still being worked on
FACT_OPS = ("add", "update", "supersede", "confirm", "retire", "contest")
PAGE_OPS = (
    "lead", "summary", "status", "title", "alias", "related", "role", "open", "done", "reschedule", "steps",
    "due", "owner", "org", "outcome", "milestone", "risk", "link", "superseded_by", "reversal",
)
NO_SRC_OPS = ("lead", "summary", "title", "related", "role")
# what a decision page refuses after it was created: it is added to, never rewritten
APPEND_ONLY_OPS = ("add", "update", "supersede", "retire", "contest", "due", "steps", "outcome", "milestone", "risk", "link")
APPEND_ONLY_HINT = (
    "A decision page is never rewritten. Write a new decision and link it with superseded_by, "
    "or put what changed on the topic page."
)

CAPS = {"person": (80, 4000), "org": (80, 4000), "howto": (80, 4000), "topic": (120, 6000), "decision": (60, 3000), "me": (80, 4000)}
FACTS_MAX = 25
FACTS_MAX_BY_TYPE = {"decision": 8}
OUTCOME_CHARS = 160
REVERSAL_CHARS = 160
RISK_CHARS = 80
RISKS_MAX = 8
LINKS_MAX = 10
FACT_WORDS = 25
LEAD_WORDS = 80
SUMMARY_CHARS = 160
TITLE_WORDS = 6
ROLE_WORDS = 4
SRC_MAX = 3
RECORDS_MAX = 15
HISTORY_MAX = 40
INDEX_MAX_LINES = 200
INDEX_MAX_CHARS = 25000
CLOSED_SHOWN = 20
LOG_MAX = 500
LOCK_TAKEOVER_S = 60
CANDIDATE_RECORDS = 2
CANDIDATE_DAYS = 2

CAP_HINT = "Send a smaller op set: supersede or merge facts, move detail to a new page and leave a one-line pointer fact, or close the page."

_H2_RE = re.compile(r"^## (.+?)\s*$")
_FACT_RE = re.compile(r"^- (?P<text>.*?)\s*<!--\s*f:(?P<id>[a-z2-7]{4})\s+since:(?P<since>\S+)\s+src:(?P<src>.*?)\s*-->\s*$")
_QUOTED_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_RECORD_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) — \[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
_LINK_LINE_RE = re.compile(r"^- \[\[([^\]|]+)(?:\|[^\]]*)?\]\](?: — (.*))?$")
# - [ ] <text> — owner: me | [[page]] | <name> · due: YYYY-MM-DD — [[record]] <!-- o:<id> since:<date> src:"…" -->
_ITEM_RE = re.compile(
    r"^\s*- \[(?P<tick>[ xX])\] (?P<body>.*?)"
    r"(?:\s*<!--\s*[om]:(?P<id>[a-z2-7]{4})\s+since:(?P<since>\S+)\s+src:(?P<src>.*?)\s*-->)?\s*$"
)
_ITEM_REC_RE = re.compile(r" — \[\[(?P<rec>[^\]|]+)(?:\|[^\]]*)?\]\]$")
_ITEM_META_RE = re.compile(
    r" — (?:owner: (?P<owner>\[\[[^\]]+\]\]|[^·—<\[]+?)(?: · due: (?P<owner_due>\d{4}-\d{2}-\d{2}))?"
    r"|due: (?P<due>\d{4}-\d{2}-\d{2}))$"
)
_OWNER_BAD = ("·", "—", "<", "[", "]")
_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
# a day named in a record summary: an ISO date, a written date, or a weekday
_DATE_TOKEN_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\.\d{1,2}\.(?:\d{2,4})?|"
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? ?\d{1,2}\b|"
    r"\b\d{1,2}\.? ?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|"
    r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tomorrow)\b",
    re.IGNORECASE,
)
_LOG_RE = re.compile(r"^- \[([^\]]+)\] (\S+) \| (\S+) \| (.*)$")
_CHAT_LINE_RE = re.compile(r"^- \d{2}:\d{2} \*\*(.+?)\*\*: (.*?)\s*(?:<!--.*?-->)?\s*$")
# a date or an amount inside a fact: an ISO date, a number with a currency on
# either side of it, a number with a unit, or a bare number of four digits or more
_VALUE_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|[€$£] ?\d+(?:[.,]\d+)*"
    r"|\d+(?:[.,]\d+)* ?[%€$£]"
    r"|\d+(?:[.,]\d+)* ?(?:eur|usd|gbp|k|m|days?|weeks?|months?|h|hours?)\b"
    r"|\b\d{4,}\b",
    re.IGNORECASE,
)
# the same amount written with the sign or with the name is one value
_CURRENCY = (("€", "eur"), ("$", "usd"), ("£", "gbp"))
# words that say nothing about what a fact is about
_CONTENT_STOP = {"we", "us", "me", "my", "it", "its", "they", "them", "be", "by", "at", "as", "has", "have", "had", "not", "per", "than", "will", "would"}
_STOP = {"re", "fw", "aw", "wg", "of", "a", "an", "in", "on", "to", "the", "and", "for", "with", "from", "about", "into", "your", "our", "this", "that", "are", "was", "is"}
_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"
_PAGE_ID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O, U
PAGE_ID_LEN = 26
PAGE_ID_CLOCK = 10  # of those 26, the first ten hold the millisecond the id was made

_LOCK = threading.Lock()


class WikiRefusal(Exception):
    """One op was refused; the page write goes on without it."""

    def __init__(self, reason: str, **info: Any) -> None:
        super().__init__(reason)
        self.reason = reason
        self.info = info


# ------------------------------------------------------------------ small helpers


def _s(v: Any) -> str:
    return "" if v is None else str(v)


def _today() -> str:
    return date.today().isoformat()


def _words(text: str) -> int:
    return len(_s(text).split())


def _norm(text: str) -> str:
    s = " ".join(_s(text).lower().split())
    return s.rstrip(". ").strip()


def _norm_name(text: str) -> str:
    s = re.sub(r"[^\w\s]", " ", _s(text).lower())
    return " ".join(s.split())


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9äöüß]{2,}", _s(text).lower()) if w not in _STOP}


def _values(text: str) -> set[str]:
    """The dates and amounts a fact states — what two facts can disagree about.

    A small bare number ("net 45", "Fact 10") is not one: there are too many of
    them and they mean too little.
    """
    out = set()
    for m in _VALUE_RE.finditer(_s(text)):
        v = re.sub(r"\s+", "", m.group(0).lower())
        for sign, name in _CURRENCY:  # "€500", "500€" and "500 EUR" are one amount
            if sign in v:
                v = v.replace(sign, "") + name
                break
        out.add(v[:-1] if v.endswith("s") else v)
    return out


def _content_tokens(text: str) -> set[str]:
    """The words a fact is about: its words without the values and the small words."""
    return _tokens(_VALUE_RE.sub(" ", _s(text))) - _CONTENT_STOP


def _stem(path: str) -> str:
    """``Administrator/Wiki/Topics/x.md`` -> ``Wiki/Topics/x`` (the wikilink target)."""
    p = path[len(ADMIN_DIR) + 1 :] if path.startswith(ADMIN_DIR + "/") else path
    return p[:-3] if p.endswith(".md") else p


def _link(path: str) -> str:
    return f"[[{_stem(path)}]]"


def _link_target(ref: str) -> str:
    """The stem inside ``[[...]]`` (or a bare stem / path), without alias or extension."""
    s = _s(ref).strip().replace("\\", "/")
    m = _LINK_RE.search(s)
    if m:
        s = m.group(1).strip()
    if s.startswith(ADMIN_DIR + "/"):
        s = s[len(ADMIN_DIR) + 1 :]
    return s[:-3] if s.endswith(".md") else s


def page_path(ref: str) -> str:
    """Vault-relative path of a wiki page from a path, stem or wikilink."""
    stem = _link_target(ref)
    if not stem:
        raise VaultError("Page path is empty.")
    path = f"{ADMIN_DIR}/{stem}.md"
    if not path.startswith(WIKI_DIR + "/"):
        raise VaultError(f"{ref!r} is not a wiki page (expected something under {WIKI_DIR}/).")
    return path


def slugify(title: str) -> str:
    s = unicodedata.normalize("NFKD", _s(title)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:40].rstrip("-") or "page"


def new_page_id() -> str:
    """A page id: 26 Crockford base32 chars, 10 of the clock (ms) then 16 random.

    Ids sort by the time they were made, never change, and are what tells the
    code a renamed or moved file is still the same page."""
    ms = int(time.time() * 1000)
    head = "".join(_PAGE_ID_ALPHABET[(ms >> (5 * i)) & 31] for i in range(PAGE_ID_CLOCK - 1, -1, -1))
    return head + "".join(secrets.choice(_PAGE_ID_ALPHABET) for _ in range(PAGE_ID_LEN - PAGE_ID_CLOCK))


def _reconcile() -> Any:
    """The two-way editing module, imported late: it reads this one."""
    from administrator_vault import wiki_reconcile

    return wiki_reconcile


def _hand_edits(root: Path, lock_held: bool = False) -> list[dict[str, str]]:
    """Take over what the user changed by hand before the tool writes. The
    answer is the pages that changed, for the tool to pass on. Only the tools
    that write call this."""
    return _reconcile().reconcile(root, lock_held)["adopted"]


def _hand_edit_count(root: Path) -> int:
    """How many pages the user changed by hand, without taking any of them over:
    what a read tool answers as ``hand_edits``. The next writing call adopts
    them."""
    return _reconcile().detect(root)


def _file_sig(p: Path) -> tuple[int, int]:
    """(size, mtime_ns) of a file — the cheap check for "did this change?"."""
    st = p.stat()
    return st.st_size, st.st_mtime_ns


def _blake(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=16).hexdigest()


def _new_id(taken: set[str]) -> str:
    while True:
        fid = "".join(secrets.choice(_ID_ALPHABET) for _ in range(4))
        if fid not in taken:
            return fid


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _unquote(s: str) -> str:
    return s.replace('\\"', '"').replace("\\\\", "\\")


def _parse_src(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw:
        return ["user"]
    quoted = _QUOTED_RE.findall(raw)
    if quoted:
        return [_unquote(q) for q in quoted]
    return [p.strip() for p in raw.split(",") if p.strip()]


def _format_src(srcs: list[str]) -> str:
    return ",".join(_quote(s) for s in srcs)


def src_record(src: Any) -> str:
    """The record a source names, without its locator: '<id>#p3' -> '<id>'.

    A src is written whole ('<id>#s4') and kept whole; everything that
    compares or counts sources uses this, so one document cited from three
    pages, and from three places on one page, is one source. A record id
    itself never holds a '#'."""
    s = _s(src)
    return s.split("#", 1)[0] or s


def _atomic_write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if not text.endswith("\n"):
        text += "\n"
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, p)


def _check_date(value: Any, what: str) -> str:
    s = _s(value).strip()
    if not _DATE_RE.match(s):
        raise WikiRefusal("bad-date", detail=f"{what} must be an ISO date, got {s!r}.")
    return s[:10]


def _statuses(page_type: str) -> tuple[str, ...]:
    """The statuses one page type allows (topics and decisions have their own)."""
    return STATUSES_BY_TYPE.get(_s(page_type), STATUSES)


def _refuse_code_owned(data: dict[str, Any]) -> None:
    bad = [k for k in CODE_OWNED if k in (data or {})]
    if bad:
        raise VaultError(f"Refused: {', '.join(bad)} are code-owned frontmatter keys; the wiki sets them itself.")


# ------------------------------------------------------------------ lock


class _wiki_lock:
    """One writer at a time: a process lock plus ``Wiki/.lock`` (pid, epoch, time).
    A lock file older than 60 s is taken over."""

    def __init__(self, root: Path) -> None:
        self.path = root / LOCK_PATH

    def __enter__(self) -> "_wiki_lock":
        _LOCK.acquire()
        try:
            if self.path.is_file():
                parts = self.path.read_text(encoding="utf-8").split()
                pid = int(parts[0]) if parts and parts[0].isdigit() else -1
                try:
                    age = time.time() - float(parts[1])
                except (IndexError, ValueError):
                    age = LOCK_TAKEOVER_S + 1
                if pid != os.getpid() and age < LOCK_TAKEOVER_S:
                    raise VaultError(
                        f"The wiki is being written by another process (pid {pid}, {age:.0f} s ago). Try again in a minute."
                    )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(f"{os.getpid()} {time.time():.0f} {store.now_iso()}\n", encoding="utf-8")
        except BaseException:
            _LOCK.release()
            raise
        return self

    def __exit__(self, *exc: Any) -> None:
        try:
            self.path.unlink(missing_ok=True)
        finally:
            _LOCK.release()


# ------------------------------------------------------------------ page model


@dataclass
class Fact:
    id: str
    text: str
    since: str
    src: list[str]

    def line(self) -> str:
        return f"- {self.text} <!-- f:{self.id} since:{self.since} src:{_format_src(self.src)} -->"

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "text": self.text, "since": self.since, "src": list(self.src)}


@dataclass
class OpenItem:
    """One line of ``## Open`` (a commitment) or of ``## Milestones``.

    ``owner`` says who does it: ``me``, a ``[[Wiki/People/…]]`` link or a plain
    name; milestones have none. ``raw`` holds a line under the heading that is
    not a checkbox, so nothing a person wrote there is lost."""

    id: Optional[str]
    text: str
    owner: Optional[str] = None
    due: str = ""
    since: str = ""
    src: list[str] = field(default_factory=list)
    record: str = ""
    done: bool = False
    prefix: str = "o"  # the letter the hidden comment carries: o for Open, m for Milestones
    raw: str = ""

    def line(self) -> str:
        if self.raw:
            return self.raw
        out = f"- [{'x' if self.done else ' '}] {self.text}"
        meta = ([f"owner: {self.owner}"] if self.owner else []) + ([f"due: {self.due}"] if self.due else [])
        if meta:
            out += " — " + " · ".join(meta)
        if self.record:
            out += f" — [[{self.record}]]"
        if self.id:
            out += f" <!-- {self.prefix}:{self.id} since:{self.since} src:{_format_src(self.src)} -->"
        return out

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "text": self.text, "owner": self.owner, "due": self.due, "since": self.since,
                "src": list(self.src), "record": self.record, "done": self.done}


@dataclass
class Page:
    path: str
    fm: dict[str, Any]
    title: str
    lead: str = ""
    facts: list[Fact] = field(default_factory=list)
    opens: list[OpenItem] = field(default_factory=list)
    milestones: list[OpenItem] = field(default_factory=list)
    sections: dict[str, list[str]] = field(default_factory=dict)
    notes: str = ""

    @property
    def type(self) -> str:
        return _s(self.fm.get("type"))

    @property
    def stem(self) -> str:
        return _stem(self.path)

    def ids(self) -> set[str]:
        """Every id in use on the page: facts, open items and milestones share one set."""
        return {f.id for f in self.facts} | {o.id for o in self.opens + self.milestones if o.id}

    def fact(self, fid: str) -> Optional[Fact]:
        return next((f for f in self.facts if f.id == _s(fid).strip()), None)

    def item(self, oid: str, name: str = "Open") -> Optional[OpenItem]:
        items = self.milestones if name == "Milestones" else self.opens
        return next((o for o in items if o.id and o.id == _s(oid).strip()), None)

    def items(self, name: str) -> list[OpenItem]:
        return self.milestones if name == "Milestones" else self.opens

    def lines(self, name: str) -> list[str]:
        return self.sections.setdefault(name, [])


def _trim(lines: list[str]) -> list[str]:
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    return lines


def _parse_fact(line: str, taken: set[str], today: str) -> Optional[Fact]:
    m = _FACT_RE.match(line)
    if m:
        fid = m.group("id")
        if fid in taken:
            fid = _new_id(taken)
        taken.add(fid)
        return Fact(fid, m.group("text").strip(), m.group("since")[:10], _parse_src(m.group("src")))
    text = line[2:].strip() if line.startswith("- ") else line.strip()
    if not text:
        return None
    fid = _new_id(taken)
    taken.add(fid)
    return Fact(fid, text, today, ["user"])  # a hand-written bullet is a user fact


def _parse_item(line: str, taken: set[str], prefix: str = "o") -> Optional[OpenItem]:
    """One ``## Open`` / ``## Milestones`` line. A 0.3.0 line (no hidden comment)
    comes back with no id and no owner; ``_finalize`` gives it both."""
    if not _s(line).strip():
        return None
    m = _ITEM_RE.match(line)
    if not m:
        return OpenItem(id=None, text="", prefix=prefix, raw=line.rstrip())
    body = m.group("body").strip()
    record = ""
    rec = _ITEM_REC_RE.search(body)
    if rec:
        record = _link_target(rec.group("rec"))
        body = body[: rec.start()].rstrip()
    owner, due = None, ""
    meta = _ITEM_META_RE.search(body)
    if meta:
        owner = _s(meta.group("owner")).strip() or None
        due = meta.group("owner_due") or meta.group("due") or ""
        body = body[: meta.start()].rstrip()
    oid = m.group("id")
    if oid and oid in taken:
        oid = _new_id(taken)
    if oid:
        taken.add(oid)
    return OpenItem(
        id=oid, text=body, owner=owner, due=due, since=_s(m.group("since"))[:10],
        src=_parse_src(m.group("src")) if oid else [], record=record,
        done=m.group("tick").lower() == "x", prefix=prefix,
    )


def parse_page(text: str, path: str = "", today: Optional[str] = None) -> Page:
    """Read a page. ``today`` dates the bullets someone wrote by hand (the
    file's own date when the caller knows it); it defaults to the wall clock."""
    fm, _block, body = fmt.split_note(text)
    lines = body.split("\n")
    first_h2 = next((k for k, l in enumerate(lines) if _H2_RE.match(l)), len(lines))
    h1 = next((k for k, l in enumerate(lines[:first_h2]) if l.startswith("# ")), None)
    if h1 is not None:
        title = lines[h1][2:].strip()
        lead_lines = lines[h1 + 1 : first_h2]
    else:
        title = _s(fm.get("title") or fm.get("name"))
        lead_lines = lines[:first_h2]
    page = Page(path=path, fm=dict(fm), title=title, lead="\n".join(_trim(lead_lines)).strip())
    k = first_h2
    while k < len(lines):
        name = _H2_RE.match(lines[k]).group(1).strip()
        if name == "Notes":
            page.notes = "\n".join(_trim(lines[k + 1 :]))
            break
        end = next((j for j in range(k + 1, len(lines)) if _H2_RE.match(lines[j])), len(lines))
        content = _trim(lines[k + 1 : end])
        page.sections.setdefault(name, []).extend(content)
        k = end
    taken: set[str] = set()
    day = _s(today)[:10] or _today()
    for line in page.sections.pop("Facts", []):
        f = _parse_fact(line, taken, day)
        if f:
            page.facts.append(f)
    for name, prefix in ITEM_SECTIONS.items():
        for line in page.sections.pop(name, []):
            item = _parse_item(line, taken, prefix)
            if item is not None:
                page.items(name).append(item)
    return page


def _ordered_fm(fm: dict[str, Any]) -> dict[str, Any]:
    out = {k: fm[k] for k in KEY_ORDER if k in fm}
    out.update({k: v for k, v in fm.items() if k not in out})
    return out


def format_page(page: Page) -> str:
    names = SECTIONS.get(page.type, SECTIONS["topic"])
    known = [n for n in names if n != "Notes"]
    extra = [n for n in page.sections if n not in known and n != "Facts" and n != "Notes"]
    for name in ITEM_SECTIONS:  # items on a page type whose contract has no such section are still written
        if page.items(name) and name not in known and name not in extra:
            extra.append(name)
    out = [fmt.format_frontmatter(_ordered_fm(page.fm)).rstrip("\n"), "", f"# {page.title}", ""]
    if page.lead:
        out += [page.lead, ""]
    for name in known + extra:
        out += [f"## {name}", ""]
        if name == "Facts":
            content = [f.line() for f in page.facts]
        elif name in ITEM_SECTIONS:
            # a page built in code (a merge, the migration) may still carry plain lines
            content = [o.line() for o in page.items(name)] or page.sections.get(name, [])
        else:
            content = page.sections.get(name, [])
        if content:
            out += list(content) + [""]
    out += ["## Notes", ""]
    if page.notes:
        out += [page.notes, ""]
    return "\n".join(out).rstrip("\n") + "\n"


def measure(page_type: str, text: str) -> dict[str, Any]:
    max_lines, max_chars = CAPS.get(page_type, CAPS["topic"])
    n_lines = text.count("\n")
    return {
        "lines": n_lines,
        "max_lines": max_lines,
        "chars": len(text),
        "max_chars": max_chars,
        "over": n_lines > max_lines or len(text) > max_chars,
    }


# ------------------------------------------------------------------ load / scan


def _load(root: Path, path: str) -> Page:
    p = resolve(root, path)
    if not p.is_file():
        raise VaultError(f"No such wiki page: {path!r}.")
    return parse_page(read_text(p), rel(root, p))


def _all_pages(root: Path) -> list[tuple[str, dict[str, Any]]]:
    """(path, frontmatter) of every wiki page, Index files and redirects left out."""
    out = []
    wiki = root / WIKI_DIR
    if not wiki.is_dir():
        return out
    files = [wiki / "Me.md"] + [p for f in ("People", "Orgs", "Topics", "Decisions", "Howto") for p in sorted((wiki / f).glob("*.md"))]
    for p in files:
        if not p.is_file() or p.name == "Index.md":
            continue
        try:
            fm = fmt.split_note(read_text(p))[0]
        except (fmt.FrontmatterError, UnicodeDecodeError):
            continue
        if fm.get("type") in TYPES:
            out.append((rel(root, p), fm))
    return out


def _aliases(fm: dict[str, Any]) -> list[str]:
    a = fm.get("aliases") or []
    return [str(x) for x in ([a] if isinstance(a, str) else a) if _s(x).strip()]


def _names(fm: dict[str, Any]) -> list[str]:
    return [n for n in [_s(fm.get("title") or fm.get("name"))] + _aliases(fm) if n]


def _find_by_name(pages: list[tuple[str, dict[str, Any]]], title: str, aliases: list[str], email: str = "") -> Optional[tuple[str, dict[str, Any]]]:
    wanted = {_norm_name(n) for n in [title] + list(aliases or []) if _norm_name(n)}
    mail = _s(email).strip().lower()
    for path, fm in pages:
        if wanted & {_norm_name(n) for n in _names(fm)}:
            return path, fm
        if mail and fm.get("type") == "person":
            addrs = {_s(fm.get("email")).lower()} | {a.lower() for a in _aliases(fm)}
            if mail in addrs:
                return path, fm
    return None


# ------------------------------------------------------------------ index / log / review


def _index_line(path: str, fm: dict[str, Any]) -> str:
    stem = _stem(path)
    title = _s(fm.get("title") or fm.get("name")) or stem.rsplit("/", 1)[-1]
    verified = _s(fm.get("verified") or fm.get("created"))[:10]
    summary = " ".join(_s(fm.get("summary")).split())
    if fm.get("type") == "person":
        org = _link_target(_s(fm.get("org"))).rsplit("/", 1)[-1] or "—"
        head = f"- [[{stem}]] · {org} · {verified}"
    elif _is_project(fm):
        owner = _link_target(_s(fm.get("owner"))).rsplit("/", 1)[-1] or "—"
        head = f"- [[{stem}|{title}]] · {owner} · {_s(fm.get('due'))[:10]} · {_s(fm.get('status')) or 'draft'}"
    else:
        head = f"- [[{stem}|{title}]] · {_s(fm.get('status')) or 'draft'} · {verified}"
    return head + (f" — {summary}" if summary else "")


def _is_project(fm: dict[str, Any]) -> bool:
    """A topic with a due date is a project; the index lists those first."""
    return _s(fm.get("type")) == "topic" and bool(_s(fm.get("due")).strip())


def _status_rank(fm: dict[str, Any]) -> int:
    return {
        "active": 0, "at-risk": 0, "blocked": 0, "current": 0,
        "draft": 1, "dormant": 2, "closed": 3, "superseded": 3, "dropped": 3,
    }.get(_s(fm.get("status")), 1)


def _index_lines_by_type(pages: list[tuple[str, dict[str, Any]]]) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    by: dict[str, list[tuple[str, dict[str, Any]]]] = {t: [] for t in INDEX_ORDER}
    for path, fm in pages:
        by[_s(fm.get("type"))].append((path, fm))
    for items in by.values():
        items.sort(key=lambda t: _s(t[1].get("verified") or t[1].get("created")), reverse=True)
        items.sort(key=lambda t: _status_rank(t[1]))
    return by


def _index_text(body_lines: list[str], n_pages: int) -> str:
    fm = fmt.format_frontmatter({"type": "wiki-index", "updated": store.now_iso(), "pages": n_pages})
    return fm + "\n# Wiki index\n\n" + "\n".join(body_lines).rstrip("\n") + "\n"


def _index_groups(page_type: str, items: list[tuple[str, dict[str, Any]]], lines: list[str]) -> list[tuple[str, list[tuple[tuple[str, dict[str, Any]], str]]]]:
    """The groups one page type shows in the index: topics with a due date are
    listed as Projects, soonest first, above the other topics."""
    pairs = list(zip(items, lines))
    if page_type == "topic":
        projects = [x for x in pairs if _is_project(x[0][1])]
        rest = [x for x in pairs if not _is_project(x[0][1])]
        if projects:
            projects.sort(key=lambda x: (_s(x[0][1].get("due"))[:10], _stem(x[0][0])))
            return [g for g in (("Projects", projects), (TYPE_HEADING[page_type], rest)) if g[1]]
    return [(TYPE_HEADING[page_type], pairs)]


def _index_map(root: Path) -> dict[str, str]:
    """{page stem: the line the index has for it} as the files read right now."""
    out: dict[str, str] = {}
    files = [root / INDEX_PATH] + [root / WIKI_DIR / f / "Index.md" for f in TYPE_FOLDER.values() if f]
    for p in files:
        if not p.is_file():
            continue
        for line in read_text(p).split("\n"):
            if not line.startswith("- [["):
                continue
            m = _LINK_RE.search(line)
            target = _link_target(m.group(1)) if m else ""
            if target.startswith("Wiki/") and not target.endswith("/Index"):
                out[target] = line
    return out


def _write_index(root: Path, touched: Any = ()) -> dict[str, Any]:
    """Regenerate Index.md (and the per-type indexes when the list is long).

    ``touched`` are the stems the caller just wrote. A line that differs for any
    other page means the index was changed by hand: it is put right and one
    ``index-repaired`` line goes to the log."""
    pages = _all_pages(root)
    by = _index_lines_by_type(pages)
    full: dict[str, list[str]] = {t: [_index_line(p, fm) for p, fm in items] for t, items in by.items()}
    total = sum(len(v) for v in full.values())
    split = total + 2 * len([t for t in INDEX_ORDER if full[t]]) > INDEX_MAX_LINES or sum(len(l) + 1 for v in full.values() for l in v) > INDEX_MAX_CHARS
    before = _index_map(root)
    had_index = (root / INDEX_PATH).is_file()
    now: dict[str, str] = {}
    hidden_stems: set[str] = set()
    blocks: dict[str, list[str]] = {}  # "<type>/<group>", or "<type>" for a split-off index
    written = []
    for t in INDEX_ORDER:
        items = by[t]
        if not items:
            continue
        folder = TYPE_FOLDER[t]
        groups: list[tuple[str, list[str]]] = []
        for name, pairs in _index_groups(t, items, full[t]):
            lines = []
            closed_seen = 0
            for (p, fm), line in pairs:
                if _s(fm.get("status")) in ("closed", "superseded", "dropped"):
                    closed_seen += 1
                    if closed_seen > CLOSED_SHOWN:
                        hidden_stems.add(_stem(p))
                        continue
                now[_stem(p)] = line
                lines.append(line)
            hidden = max(0, closed_seen - CLOSED_SHOWN)
            if hidden:
                lines.append(f"- … {hidden} more closed pages (vault_find)")
            groups.append((name, [f"## {name} ({len(pairs)})", ""] + lines + [""]))
        if split and folder:
            sub = root / WIKI_DIR / folder / "Index.md"
            _atomic_write(sub, _index_text([l for _n, g in groups for l in g], len(items)))
            written.append(rel(root, sub))
            blocks[t] = [f"- [[Wiki/{folder}/Index|{TYPE_HEADING[t]}]] — {len(items)} pages"]
            continue
        for name, group in groups:
            blocks[f"{t}/{name}"] = group
    body: list[str] = [l for key in INDEX_BODY_ORDER for l in blocks.pop(key, [])]
    body += [l for group in blocks.values() for l in group]
    if not split:
        for t, folder in TYPE_FOLDER.items():
            sub = root / WIKI_DIR / folder / "Index.md" if folder else None
            if sub and sub.is_file():
                sub.unlink()
    idx = root / INDEX_PATH
    _atomic_write(idx, _index_text(body or ["(no pages yet)"], total))
    fresh = {_s(s) for s in (touched or ())} | hidden_stems
    drift = sorted(s for s in set(before) | set(now) if s not in fresh and before.get(s) != now.get(s))
    if had_index and drift:
        _log(root, "index-repaired", "Wiki/Index", "-", f"{len(drift)} lines: " + ", ".join(drift[:3]))
    view = _followups().regenerate(root)  # Follow-ups.md is a view of the pages' open items
    return {"path": rel(root, idx), "pages": total, "split": split, "per_type": written, "repaired": drift, "followups": view}


def _followups() -> Any:
    """The Follow-ups view, imported late: it reads this module."""
    from administrator_vault import followups

    return followups


def _log(root: Path, op: str, page: str, source: str, detail: str) -> None:
    p = root / LOG_PATH
    head = "# Wiki log\n\n"
    text = read_text(p) if p.is_file() else head
    lines = [l for l in text.split("\n") if l.startswith("- [")]
    if len(lines) >= LOG_MAX:
        year = lines[0][3:7] if len(lines[0]) > 7 else _today()[:4]
        hist = root / HISTORY_DIR / f"Log-{year}.md"
        old = read_text(hist) if hist.is_file() else "# Wiki log (rotated)\n\n"
        _atomic_write(hist, old.rstrip("\n") + "\n" + "\n".join(lines) + "\n")
        lines = [f"- [{store.now_iso()}] rotate | Wiki/Log | [[{_stem(rel(root, hist))}]] | {len(lines)} lines moved"]
    lines.append(f"- [{store.now_iso()}] {op} | {page} | {source or '-'} | {detail}")
    _atomic_write(p, head + "\n".join(lines) + "\n")


def _review_text(root: Path) -> tuple[list[str], list[str]]:
    p = root / REVIEW_PATH
    open_lines: list[str] = []
    done_lines: list[str] = []
    if p.is_file():
        cur = None
        for line in read_text(p).split("\n"):
            if line.startswith("## "):
                cur = line[3:].strip().lower()
                continue
            if line.startswith("- ") and cur == "open":
                open_lines.append(line)
            elif line.startswith("- ") and cur == "done":
                done_lines.append(line)
    return open_lines, done_lines


def _write_review(root: Path, open_lines: list[str], done_lines: list[str]) -> None:
    fm = fmt.format_frontmatter({"type": "wiki-review", "updated": store.now_iso(), "open": len(open_lines)})
    text = fm + "\n# Wiki review\n\nThings the code could not decide. Answer in chat (\"resolve review\") or tick and tell.\n\n## Open\n\n"
    text += "\n".join(open_lines) + ("\n" if open_lines else "") + "\n## Done\n\n" + "\n".join(done_lines) + ("\n" if done_lines else "")
    _atomic_write(root / REVIEW_PATH, text)


def _review_add(root: Path, line: str) -> None:
    open_lines, done_lines = _review_text(root)
    if line not in open_lines:
        open_lines.append(line)
        _write_review(root, open_lines, done_lines)


UNCONFIRMED_FLAG = "unconfirmed-decision"
_UNCONFIRMED_RE = re.compile(r"^- \[[xX]\] .*— unconfirmed decision: ")


def _name_the_decision(root: Path, path: str) -> None:
    """The Review line of a new decision quotes its first fact. At ingest the
    facts arrive with the ops, a moment after the page: the line is written
    again once they are there."""
    page = _load(root, path)
    if not page.facts:
        return
    head = f"- [ ] [[{page.stem}]] — unconfirmed decision: "
    open_lines, done_lines = _review_text(root)
    for i, line in enumerate(open_lines):
        if line.startswith(head):
            tail = line[len(head):].split('" — confirm or drop ', 1)
            if len(tail) == 2:
                open_lines[i] = f'{head}"{page.facts[0].text}" — confirm or drop {tail[1]}'
                _write_review(root, open_lines, done_lines)
            return


def _settle_ticked_decisions(root: Path) -> list[str]:
    """A ticked "unconfirmed decision" line in Review.md counts as a confirm:
    the flag goes and the line moves to Done. It is the one line where ticking
    the box on its own does something. Runs at the start of lint and ingest."""
    open_lines, done_lines = _review_text(root)
    ticked = [l for l in open_lines if _UNCONFIRMED_RE.match(l)]
    settled: list[str] = []
    for line in ticked:
        target = next((_link_target(m.group(1)) for m in _LINK_RE.finditer(line) if m.group(1).startswith("Wiki/")), "")
        try:
            p = root / page_path(target) if target else None
        except VaultError:
            p = None
        if p is not None and p.is_file():
            page = _load(root, rel(root, p))
            flags = [f for f in (page.fm.get("flags") or []) if f != UNCONFIRMED_FLAG]
            if flags != [str(f) for f in (page.fm.get("flags") or [])]:
                page.fm["flags"] = flags
                ctx = _Ctx(root=root, src="user", since=_today(), record=None)
                _history(page, ctx, "decision confirmed")
                _finalize(page, ctx)
                _write_page(page, ctx)
            settled.append(page.stem)
        open_lines.remove(line)
        done_lines.append(line + f" — confirmed {_today()}")
        _log(root, "review", target or "-", "user", "confirmed by tick: " + line[6:80])
    if ticked:
        _write_review(root, open_lines, done_lines)
    return settled


def init_files(root: Path, created_by: str = CREATED_BY) -> list[str]:
    """Create Index.md, Log.md, Review.md and a placeholder Wiki.md when missing."""
    created = []
    if not (root / INDEX_PATH).is_file():
        _write_index(root)
        created.append(INDEX_PATH)
    if not (root / LOG_PATH).is_file():
        _atomic_write(root / LOG_PATH, "# Wiki log\n\n")
        created.append(LOG_PATH)
    if not (root / REVIEW_PATH).is_file():
        _write_review(root, [], [])
        created.append(REVIEW_PATH)
    if not (root / SCHEMA_PATH).is_file():
        # the page contract shipped with the package (a copy of the plugin's skills/wiki/references/wiki.md)
        shipped = Path(__file__).with_name("wiki_schema.md")
        body = shipped.read_text(encoding="utf-8") if shipped.is_file() else (
            "# The wiki — how pages work\n\nThe page contract lives in the administrator plugin "
            "(skills/wiki/references/wiki.md); this copy was not shipped with the server.\n"
        )
        _atomic_write(root / SCHEMA_PATH, fmt.format_frontmatter({"type": "wiki-schema", "created_by": created_by}) + "\n" + body)
        created.append(SCHEMA_PATH)
    return created


# ------------------------------------------------------------------ candidates


def _norm_subject(subject: str) -> str:
    return _norm_name(notes.strip_prefixes(_s(subject), meeting=True))


def _load_candidates(root: Path) -> dict[str, Any]:
    p = root / CANDIDATES_PATH
    if not p.is_file():
        return {}
    try:
        return json.loads(read_text(p))
    except ValueError:
        return {}


def _candidate_note(root: Path, record_path: str, subject: str, day: str, summary: str = "") -> Optional[dict[str, Any]]:
    key = _norm_subject(subject)
    if not key:
        return None
    data = _load_candidates(root)
    entry = data.setdefault(key, {"subject": notes.strip_prefixes(_s(subject), meeting=True), "records": {}})
    entry["records"][_stem(record_path)] = day
    # a record whose summary names a day is what makes the subject look like a project
    entry.setdefault("dated", {})[_stem(record_path)] = bool(_DATE_TOKEN_RE.search(_s(summary)))
    _atomic_write(root / CANDIDATES_PATH, json.dumps(data, ensure_ascii=False, indent=1))
    return _candidate_status(key, entry, _all_pages(root))


def _candidate_status(key: str, entry: dict[str, Any], pages: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    days = {d for d in entry["records"].values() if d}
    hit = _find_by_name(pages, entry["subject"], [])
    return {
        "subject": entry["subject"],
        "records": sorted(entry["records"], key=lambda k: entry["records"][k], reverse=True),
        "days": len(days),
        "over_threshold": len(entry["records"]) >= CANDIDATE_RECORDS and len(days) >= CANDIDATE_DAYS,
        "page": _stem(hit[0]) if hit else None,
        "suggest_due": any((entry.get("dated") or {}).values()),
    }


def _candidates_over(root: Path, pages: Optional[list[tuple[str, dict[str, Any]]]] = None) -> list[dict[str, Any]]:
    pages = _all_pages(root) if pages is None else pages
    out = []
    for key, entry in _load_candidates(root).items():
        st = _candidate_status(key, entry, pages)
        if st["over_threshold"] and not st["page"]:
            out.append(st)
    out.sort(key=lambda c: (-len(c["records"]), c["subject"]))
    return out


# ------------------------------------------------------------------ records


def _record_info(root: Path, record_path: str) -> dict[str, Any]:
    p = resolve(root, record_path)
    if not p.is_file():
        raise VaultError(f"No such record: {record_path!r}.")
    fm, _block, body = fmt.split_note(read_text(p))
    kind = _s(fm.get("type"))
    # record_id is what every record carries; the older per-kind keys are the fallback
    src = _s(fm.get("record_id")).strip()
    if kind == "email":
        day = _s(fm.get("date") or fm.get("received"))[:10]
        src = src or _s(fm.get("internet_message_id")) or _s(fm.get("entry_id"))
    elif kind == "meeting":
        day = _s(fm.get("date") or fm.get("start"))[:10]
        src = src or _s(fm.get("occurrence_key")) or _s(fm.get("global_id"))
    elif kind == "chat":
        day = _s(fm.get("date"))[:10]
        src = src or f"{_s(fm.get('chat_id'))}|{day}"
    elif kind == "document":
        day = _s(fm.get("date"))[:10]
        src = src or _s(fm.get("hash"))
    else:
        raise VaultError(f"{record_path!r} is not an email, meeting, chat or document note (type {kind!r}).")
    if not _DATE_RE.match(day):
        raise VaultError(f"{record_path!r} has no usable date in its frontmatter.")
    summary = ""
    lines = body.split("\n")
    if kind == "chat":
        # the first message line: "- HH:MM **Sender**: text <!-- id: … -->" -> "Sender: text"
        for line in lines:
            m = _CHAT_LINE_RE.match(line)
            if m:
                summary = f"{m.group(1)}: {m.group(2)}"
                break
    else:
        for i, line in enumerate(lines):
            if re.match(r"^#{2,3} Summary\s*$", line):
                summary = next((l.strip() for l in lines[i + 1 :] if l.strip() and not l.startswith("#")), "")
                break
    subject = _s(fm.get("subject") or fm.get("chat_title") or fm.get("title"))
    path = rel(root, p)
    return {
        "path": path,
        "link": _link(path),
        "date": day,
        "src": src or "user",
        "subject": subject,
        "summary": " ".join(summary.split()) or subject,
        "type": kind,
    }


def _link_record(root: Path, record_path: str, page_stem: str) -> bool:
    """Append ``[[page]]`` to the record's ``wiki`` frontmatter list (two-way link)."""
    p = resolve(root, record_path)
    text = read_text(p)
    fm, block, _body = fmt.split_note(text)
    if not block:
        return False
    have = fm.get("wiki") or []
    have = [have] if isinstance(have, str) else [str(x) for x in have]
    link = f"[[{page_stem}]]"
    if link in have:
        return False
    new_block = fmt.replace_list_key(block, "wiki", have + [link])
    lines = text.split("\n")
    close = next(i for i in range(1, len(lines)) if lines[i].rstrip("\r") == "---")
    _atomic_write(p, "\n".join(["---", new_block, "---"] + lines[close + 1 :]))
    return True


def _mark_ingested(root: Path, record_path: str, day: str) -> bool:
    """Write today's date on the record's ``ingested`` key."""
    p = resolve(root, record_path)
    text = read_text(p)
    fm, block, _body = fmt.split_note(text)
    if not block or _s(fm.get("ingested")) == day:
        return False
    lines = text.split("\n")
    close = next(i for i in range(1, len(lines)) if lines[i].rstrip("\r") == "---")
    _atomic_write(p, "\n".join(["---", fmt.replace_keys(block, {"ingested": day}), "---"] + lines[close + 1 :]))
    return True


def _add_record_line(page: Page, link: str, day: str, summary: str) -> bool:
    target = _link_target(link)
    recs = page.lines("Records")
    if any(_link_target(m.group(2)) == target for l in recs if (m := _RECORD_RE.match(l))):
        return False
    recs.append(f"- {day} — {link} — {summary}" if summary else f"- {day} — {link}")
    return True


# ------------------------------------------------------------------ ops


@dataclass
class _Ctx:
    root: Path
    src: str
    since: str
    record: Optional[dict[str, Any]]
    today: str = field(default_factory=_today)
    verified: list[str] = field(default_factory=list)
    deferred: list[tuple[str, str, str, str]] = field(default_factory=list)  # (target path, section, stem, role)
    review: list[str] = field(default_factory=list)
    ids: dict[str, str] = field(default_factory=dict)  # record stem -> source id, per write
    touched: set[str] = field(default_factory=set)  # stems written through _commit, for the index check
    strict: bool = False  # a page over its cap is a write check problem (ingest, apply, create)
    creating: bool = False  # the page is being created: a decision takes its facts here and nowhere else

    @property
    def where(self) -> str:
        return self.record["link"] if self.record else "user"


def _history(page: Page, ctx: _Ctx, text: str) -> None:
    page.lines("History").append(f"- {ctx.today} — {text} ({ctx.where})")


def _clean_text(raw: Any, what: str = "text") -> str:
    text = " ".join(_s(raw).split())
    if not text:
        raise WikiRefusal("missing-text", detail=f"{what} is empty.")
    if "<!--" in text or "-->" in text:
        raise WikiRefusal("bad-text", detail=f"{what} may not contain an HTML comment.")
    return text


def _fact_text(raw: Any) -> str:
    text = _clean_text(raw)
    if _words(text) > FACT_WORDS:
        raise WikiRefusal("fact-too-long", words=_words(text), max_words=FACT_WORDS)
    return text


def _need_fact(page: Page, raw: dict[str, Any]) -> Fact:
    f = page.fact(_s(raw.get("id")))
    if f is None:
        raise WikiRefusal("unknown-id", id=_s(raw.get("id")), known=sorted(page.ids()))
    return f


def _need_topic(page: Page, op: str) -> None:
    if page.type != "topic":
        raise WikiRefusal("wrong-type", detail=f"{op} is only for topic pages.")


def _link_entry(root: Path, raw: dict[str, Any]) -> str:
    """One ``links`` entry: ``[label](url)`` for a web address, ``[[path|label]]``
    for a note that is in the vault."""
    url = _s(raw.get("url") or raw.get("value") or raw.get("page")).strip()
    label = " ".join(_s(raw.get("label") or raw.get("text")).split())
    if not url:
        raise WikiRefusal("missing-text", detail="link needs a url or a path in the vault.")
    if "<!--" in url or "-->" in url:
        raise WikiRefusal("bad-text", detail="A link may not contain an HTML comment.")
    if _URL_RE.match(url):
        return f"[{label or url}]({url})"
    target = _link_target(url)
    if not (root / ADMIN_DIR / (target + ".md")).is_file():
        raise WikiRefusal("no-such-page", page=target, detail="link takes a web address (http…) or a note that is in the vault.")
    return f"[[{target}|{label}]]" if label else f"[[{target}]]"


def _need_open(page: Page, raw: dict[str, Any], name: str = "Open") -> OpenItem:
    o = page.item(_s(raw.get("id")), name)
    if o is None:
        raise WikiRefusal("unknown-id", id=_s(raw.get("id")), known=sorted(x.id for x in page.items(name) if x.id))
    return o


def _owner_value(root: Path, raw_owner: Any) -> str:
    """The owner of an open item: ``me`` (the default), a link to a page that
    exists (the page it sits on included), or a plain name."""
    value = _s(raw_owner).strip() or "me"
    if value.lower() == "me":
        return "me"
    if value.startswith("[[") or value.startswith("Wiki/") or value.startswith(ADMIN_DIR + "/Wiki/"):
        try:
            path = page_path(value)
        except VaultError as exc:
            raise WikiRefusal("no-such-page", detail=str(exc)) from None
        if not (root / path).is_file():
            raise WikiRefusal("no-such-page", page=_stem(path))
        return f"[[{_stem(path)}]]"
    if any(bad in value for bad in _OWNER_BAD):
        raise WikiRefusal("bad-owner", detail="An owner is 'me', a [[page]] link or a plain name without · — < [ ].")
    return value


def _pin_check(page: Page, f: Fact, src: str, new_text: str, ctx: _Ctx) -> None:
    if "user" in f.src and src != "user":
        ctx.review.append(f'- [ ] [[{page.stem}]] — f:{f.id} user fact "{f.text}" vs "{new_text}" ({ctx.where})')
        raise WikiRefusal("user-pin", id=f.id, detail="This fact was written by the user; only src user may change it. Sent to Review.md.")


def _extend_src(f: Any, src: str) -> None:  # a Fact or an OpenItem: both keep a src list
    # the same record again, whatever part of it, replaces the src it already has:
    # a second page of one document is the same source, not a second one
    record = src_record(src)
    f.src[:] = [s for s in f.src if src_record(s) != record]
    f.src.insert(0, src)
    del f.src[SRC_MAX:]


def _src_of(raw: dict[str, Any], ctx: _Ctx, op: str) -> str:
    src = _s(raw.get("src")).strip() or ctx.src
    if not src and op not in NO_SRC_OPS:
        raise WikiRefusal("missing-src")
    if "-->" in src:
        raise WikiRefusal("bad-src", detail="src may not contain '-->'.")
    return src


def _since_of(raw: dict[str, Any], ctx: _Ctx) -> str:
    return _check_date(raw.get("since") or ctx.since, "since")


def _section_for(page_type: str, other_type: str) -> str:
    return LINK_SECTION.get((page_type, other_type), "Related")


def _link_line(stem: str, role: str) -> str:
    return f"- [[{stem}]]" + (f" — {role}" if role else "")


def _put_link(lines: list[str], stem: str, role: str, sort: bool) -> bool:
    """Add or re-role the line linking ``stem``. Returns True when the section changed."""
    for i, line in enumerate(lines):
        m = _LINK_LINE_RE.match(line)
        if m and _link_target(m.group(1)) == stem:
            if role and (m.group(2) or "") != role:
                lines[i] = _link_line(stem, role)
                return True
            return False
    lines.append(_link_line(stem, role))
    if sort:
        lines.sort(key=lambda l: ((m.group(2) or "~").lower(), m.group(1).lower()) if (m := _LINK_LINE_RE.match(l)) else ("~", l))
    return True


def _apply_one(page: Page, op: str, raw: dict[str, Any], ctx: _Ctx) -> dict[str, Any]:
    src = _src_of(raw, ctx, op)
    out: dict[str, Any] = {"op": op}
    if page.type == "decision" and not ctx.creating:
        if op in APPEND_ONLY_OPS:
            raise WikiRefusal("append-only", detail=APPEND_ONLY_HINT)
        if op == "status" and (_s(raw.get("value") or raw.get("text")).strip().lower() != "dropped" or src != "user"):
            raise WikiRefusal("append-only", detail="A decision's status follows from superseded_by; only 'dropped', and only when the user says so (src user), is set by hand.")
    if op == "add":
        text = _fact_text(raw.get("text"))
        since = _since_of(raw, ctx)
        dup = next((f for f in page.facts if _norm(f.text) == _norm(text)), None)
        if dup:
            _extend_src(dup, src)
            ctx.verified.append(since)
            return {"op": "add", "result": "confirm", "id": dup.id, "detail": "same text already on the page; treated as confirm."}
        # a new fact that names a date or an amount, next to a fact about the
        # same thing naming a different one: the page would hold both as true.
        # A decision page is never checked; it is added to, never corrected.
        new_values = _values(text) if page.type != "decision" else set()
        if new_values:
            new_content = _content_tokens(text)
            for f in page.facts:
                old_values = _values(f.text)
                if not old_values or (old_values & new_values):
                    continue
                old_content = _content_tokens(f.text)
                alike = bool(new_content) and bool(old_content) and (new_content <= old_content or old_content <= new_content)
                if alike or len(new_content & old_content) >= 2:
                    raise WikiRefusal(
                        "conflicts-with", id=f.id, current=f.text, since=f.since,
                        detail="A fact on this page states another date or amount for the same thing. Use supersede (newer) or contest (older or unsure).",
                    )
        facts_max = FACTS_MAX_BY_TYPE.get(page.type, FACTS_MAX)
        if len(page.facts) >= facts_max:
            raise WikiRefusal("facts-cap", facts=len(page.facts), max_facts=facts_max, detail=CAP_HINT)
        f = Fact(_new_id(page.ids()), text, since, [src])
        page.facts.append(f)
        ctx.verified.append(since)
        out.update(id=f.id, text=f.text)
    elif op == "update":
        f = _need_fact(page, raw)
        text = _fact_text(raw.get("text"))
        _pin_check(page, f, src, text, ctx)
        old = f.text
        f.text = text
        _extend_src(f, src)
        ctx.verified.append(ctx.since)
        _history(page, ctx, f'updated f:{f.id} "{old}" → "{text}"')
        out.update(id=f.id)
    elif op == "supersede":
        f = _need_fact(page, raw)
        text = _fact_text(raw.get("text"))
        since = _since_of(raw, ctx)
        _pin_check(page, f, src, text, ctx)
        if since < f.since:
            ctx.review.append(f'- [ ] [[{page.stem}]] — f:{f.id} "{f.text}" (since {f.since}) vs older "{text}" (since {since}) ({ctx.where})')
            raise WikiRefusal("older-than-current", id=f.id, current_since=f.since, since=since, detail="The new fact is older than the current one. Sent to Review.md.")
        new = Fact(_new_id(page.ids()), text, since, [src])
        page.facts[page.facts.index(f)] = new
        ctx.verified.append(since)
        _history(page, ctx, f'superseded "{f.text}" → "{text}"')
        out.update(id=new.id, replaced=f.id)
    elif op == "confirm":
        f = _need_fact(page, raw)
        _extend_src(f, src)
        ctx.verified.append(_since_of(raw, ctx))
        out.update(id=f.id)
    elif op == "retire":
        f = _need_fact(page, raw)
        reason = _clean_text(raw.get("reason"), "reason")
        _pin_check(page, f, src, f"retire: {reason}", ctx)
        page.facts.remove(f)
        _history(page, ctx, f'retired "{f.text}" — {reason}')
        out.update(id=f.id)
    elif op == "contest":
        f = _need_fact(page, raw)
        text = _fact_text(raw.get("text"))
        flags = page.fm.get("flags") or []
        if "contradiction" not in flags:
            page.fm["flags"] = list(flags) + ["contradiction"]
        ctx.review.append(f'- [ ] [[{page.stem}]] — f:{f.id} "{f.text}" vs "{text}" ({_format_src(f.src)} / {ctx.where})')
        out.update(id=f.id, result="review")
    elif op == "lead":
        text = _s(raw.get("text")).strip()
        if not text:
            raise WikiRefusal("missing-text")
        if _words(text) > LEAD_WORDS:
            raise WikiRefusal("lead-too-long", words=_words(text), max_words=LEAD_WORDS)
        if any(l.startswith("#") for l in text.split("\n")):
            raise WikiRefusal("bad-text", detail="The lead may not contain headings.")
        page.lead = text
        if _s(page.fm.get("status")) in ("", "draft"):
            page.fm["status"] = _statuses(page.type)[0]
    elif op == "summary":
        text = _clean_text(raw.get("text"), "summary")
        if len(text) > SUMMARY_CHARS:
            raise WikiRefusal("summary-too-long", chars=len(text), max_chars=SUMMARY_CHARS)
        page.fm["summary"] = text
    elif op == "status":
        value = _s(raw.get("value") or raw.get("text")).strip().lower()
        allowed = _statuses(page.type)
        if value not in allowed:
            raise WikiRefusal("bad-status", value=value, allowed=list(allowed))
        page.fm["status"] = value
    elif op == "title":
        text = _check_title(raw.get("text"))
        if _norm_name(text) != _norm_name(page.title):
            old = page.title
            page.title = text
            page.fm["title"] = text
            _add_alias(page, old)
    elif op == "alias":
        _add_alias(page, _clean_text(raw.get("text"), "alias"))
    elif op == "related":
        stem = _existing_page(ctx.root, raw.get("page"), page)
        _put_link(page.lines("Related"), stem, "", False)
        ctx.deferred.append((page_path(stem), "Related", page.stem, ""))
        out.update(page=stem)
    elif op == "role":
        stem = _existing_page(ctx.root, raw.get("page"), page)
        role = _clean_text(raw.get("role"), "role")
        if _words(role) > ROLE_WORDS:
            raise WikiRefusal("role-too-long", words=_words(role), max_words=ROLE_WORDS)
        other_type = _s(_load(ctx.root, page_path(stem)).fm.get("type"))
        sec = _section_for(page.type, other_type)
        _put_link(page.lines(sec), stem, role if sec != "Related" else "", sec != "Related")
        back = _section_for(other_type, page.type)
        ctx.deferred.append((page_path(stem), back, page.stem, role if back != "Related" else ""))
        out.update(page=stem, section=sec)
    elif op == "open":
        if "Open" not in SECTIONS.get(page.type, ()):
            raise WikiRefusal("wrong-type", detail=f"{page.type} pages have no Open section; put the item on the person, topic, decision or me page it is about.")
        text = _clean_text(raw.get("text"))
        owner = _owner_value(ctx.root, raw.get("owner"))
        due = _check_date(raw.get("due"), "due") if _s(raw.get("due")).strip() else ""
        since = _since_of(raw, ctx)
        # the same wording, or the same record twice ("user" is not a record: it may say many things)
        same_src = src_record(src) if src and src != "user" else ""
        if any(_norm(o.text) == _norm(text) or (same_src and any(src_record(s) == same_src for s in o.src))
               for o in page.opens if not o.raw):
            raise WikiRefusal("duplicate", detail="This open item is already on the page.")
        item = OpenItem(
            id=_new_id(page.ids()), text=text, owner=owner, due=due, since=since, src=[src],
            record=_link_target(ctx.record["link"]) if ctx.record else "",
        )
        page.opens.append(item)
        out.update(id=item.id, owner=item.owner)
    elif op == "done":
        item = _need_open(page, raw)
        item.done = True
        _extend_src(item, src)
        out.update(id=item.id, text=item.text)
    elif op == "reschedule":
        item = _need_open(page, raw)
        due = _check_date(raw.get("due") or raw.get("value"), "due")
        old = item.due or "—"
        item.due = due
        _extend_src(item, src)
        _history(page, ctx, f'rescheduled "{item.text}" {old} → {due}')
        out.update(id=item.id, due=due)
    elif op == "steps":
        if page.type != "howto":
            raise WikiRefusal("wrong-type", detail="steps is only for howto pages.")
        text = _s(raw.get("text")).strip()
        if not text:
            raise WikiRefusal("missing-text")
        if any(_H2_RE.match(l) for l in text.split("\n")):
            raise WikiRefusal("bad-text", detail="Steps may not contain '## ' headings.")
        page.sections["Steps"] = _trim(text.split("\n"))
    elif op == "due":
        if page.type != "topic":
            raise WikiRefusal("wrong-type", detail="due is only for topic pages.")
        page.fm["due"] = _check_date(raw.get("value") or raw.get("text"), "due")
    elif op == "outcome":
        _need_topic(page, "outcome")
        text = _clean_text(raw.get("text") or raw.get("value"), "outcome")
        if len(text) > OUTCOME_CHARS:
            raise WikiRefusal("outcome-too-long", chars=len(text), max_chars=OUTCOME_CHARS)
        page.fm["outcome"] = text
    elif op == "milestone":
        _need_topic(page, "milestone")
        text = _clean_text(raw.get("text"))
        due = _check_date(raw.get("due"), "due") if _s(raw.get("due")).strip() else ""
        if any(_norm(m.text) == _norm(text) for m in page.milestones if not m.raw):
            raise WikiRefusal("duplicate", detail="This milestone is already on the page.")
        item = OpenItem(id=_new_id(page.ids()), text=text, due=due, since=_since_of(raw, ctx), src=[src], prefix="m")
        page.milestones.append(item)
        out.update(id=item.id, due=item.due)
    elif op == "risk":
        _need_topic(page, "risk")
        text = _clean_text(raw.get("text"), "risk")
        if len(text) > RISK_CHARS:
            raise WikiRefusal("risk-too-long", chars=len(text), max_chars=RISK_CHARS)
        have = [_s(r) for r in (page.fm.get("risks") or [])]
        if any(_norm(r) == _norm(text) for r in have):
            raise WikiRefusal("duplicate", detail="This risk is already on the page.")
        if len(have) >= RISKS_MAX:
            raise WikiRefusal("risks-cap", risks=len(have), max_risks=RISKS_MAX, detail="Drop or reword a risk first; a page keeps at most 8.")
        page.fm["risks"] = have + [text]
        _history(page, ctx, f'risk added "{text}"')
    elif op == "link":
        _need_topic(page, "link")
        entry = _link_entry(ctx.root, raw)
        have = [_s(l) for l in (page.fm.get("links") or [])]
        if entry in have:
            raise WikiRefusal("duplicate", detail="This link is already on the page.")
        if len(have) >= LINKS_MAX:
            raise WikiRefusal("links-cap", links=len(have), max_links=LINKS_MAX, detail="Drop a link first; a page keeps at most 10.")
        page.fm["links"] = have + [entry]
        out.update(link=entry)
    elif op == "superseded_by":
        if page.type != "decision":
            raise WikiRefusal("wrong-type", detail="superseded_by is only for decision pages.")
        stem = _existing_page(ctx.root, raw.get("page") or raw.get("value") or raw.get("text"), page)
        other_type = _s(_load(ctx.root, page_path(stem)).fm.get("type"))
        if other_type != "decision":
            raise WikiRefusal("wrong-type", detail=f"{stem} is a {other_type or 'typeless'} page; a decision is superseded by a decision.")
        page.fm["superseded_by"] = f"[[{stem}]]"
        page.fm["status"] = "superseded"
        _put_link(page.lines("Related"), stem, "", False)
        ctx.deferred.append((page_path(stem), "Related", page.stem, ""))
        _history(page, ctx, f"superseded by [[{stem}]]")
        out.update(page=stem)
    elif op == "reversal":
        if page.type != "decision":
            raise WikiRefusal("wrong-type", detail="reversal is only for decision pages.")
        text = _clean_text(raw.get("text") or raw.get("value"), "reversal")
        if len(text) > REVERSAL_CHARS:
            raise WikiRefusal("reversal-too-long", chars=len(text), max_chars=REVERSAL_CHARS)
        page.fm["reversal"] = text
    elif op in ("owner", "org"):
        value = _s(raw.get("value") or raw.get("text") or raw.get("page")).strip()
        if not value:
            raise WikiRefusal("missing-text")
        if value.startswith("[[") or value.startswith("Wiki/"):
            value = f"[[{_existing_page(ctx.root, value, page)}]]"
        page.fm[op] = value
    else:
        raise WikiRefusal("unknown-op", known=list(FACT_OPS + PAGE_OPS))
    return out


def _check_title(raw: Any) -> str:
    text = _clean_text(raw, "title")
    if _words(text) > TITLE_WORDS:
        raise WikiRefusal("title-too-long", words=_words(text), max_words=TITLE_WORDS)
    if re.search(r"\d{4}-\d{2}", text):
        raise WikiRefusal("bad-title", detail="Titles carry no dates.")
    return text


def _add_alias(page: Page, alias: str) -> bool:
    alias = _s(alias).strip()
    have = _aliases(page.fm)
    if not alias or alias.lower() in {a.lower() for a in have} or alias.lower() == page.title.lower():
        page.fm["aliases"] = have
        return False
    page.fm["aliases"] = have + [alias]
    return True


def _existing_page(root: Path, ref: Any, page: Page) -> str:
    try:
        path = page_path(_s(ref))
    except VaultError as exc:
        raise WikiRefusal("no-such-page", detail=str(exc)) from None
    if not (root / path).is_file():
        raise WikiRefusal("no-such-page", page=_stem(path))
    if path == page.path:
        raise WikiRefusal("self-link")
    return _stem(path)


def _apply_ops(page: Page, ops: list[Any], ctx: _Ctx) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    applied, refused = [], []
    for raw in ops or []:
        if not isinstance(raw, dict):
            refused.append({"op": _s(raw), "reason": "not-an-object"})
            continue
        op = _s(raw.get("op")).strip().lower()
        try:
            applied.append(_apply_one(page, op, raw, ctx))
        except WikiRefusal as r:
            refused.append({"op": op, "reason": r.reason, **r.info})
    return applied, refused


# ------------------------------------------------------------------ finalize / write


def _rotate_history(page: Page, root: Path) -> None:
    hist = page.lines("History")
    pointer = f"- older history: [[{_stem(HISTORY_DIR)}/{page.stem[len('Wiki/'):]}]]"
    body = [l for l in hist if not l.startswith("- older history: ")]
    if len(body) + 1 <= HISTORY_MAX and not any(l.startswith("- older history: ") for l in hist):
        page.sections["History"] = body
        return
    keep = HISTORY_MAX - 1
    overflow = body[:-keep] if len(body) > keep else []
    if overflow:
        hp = root / HISTORY_DIR / (page.stem[len("Wiki/"):] + ".md")
        old = read_text(hp) if hp.is_file() else f"# History of [[{page.stem}]]\n\n"
        _atomic_write(hp, old.rstrip("\n") + "\n" + "\n".join(overflow) + "\n")
    page.sections["History"] = [pointer] + body[-keep:]


def _record_src_id(root: Path, stem: str, cache: dict[str, str]) -> str:
    """The source id (record_id / internet_message_id / occurrence_key / ...) of the record at ``stem``.

    Falls back to the stem itself when the record cannot be read, so a Records
    line and a fact src for the same record count as one source."""
    if stem not in cache:
        ident = stem
        p = root / ADMIN_DIR / (stem + ".md")
        if p.is_file():
            try:
                rfm, _block, _body = fmt.split_note(read_text(p))
                ident = (
                    _s(rfm.get("record_id")) or _s(rfm.get("internet_message_id")) or _s(rfm.get("occurrence_key"))
                    or _s(rfm.get("entry_id")) or _s(rfm.get("global_id")) or _s(rfm.get("hash")) or stem
                )
            except Exception:  # noqa: BLE001 - an unreadable record still counts once
                ident = stem
        cache[stem] = src_record(ident)
    return cache[stem]


def count_sources(root: Path, page: Page, cache: Optional[dict[str, str]] = None) -> int:
    """Distinct records behind a page: fact sources plus the Records list, deduped
    by record id. A locator ('#p3') does not make a second source."""
    cache = cache if cache is not None else {}
    ids = {src_record(s) for f in page.facts for s in f.src if s != "user"}
    for line in page.lines("Records"):
        m = _RECORD_RE.match(line)
        if m:
            ids.add(_record_src_id(root, _link_target(m.group(2)), cache))
    return len(ids)


def _finalize(page: Page, ctx: _Ctx) -> None:
    fm = page.fm
    fm["type"] = page.type or "topic"
    if page.type == "person":
        fm.setdefault("name", page.title)
        fm.setdefault("title", page.title)
    else:
        fm["title"] = page.title
    fm["aliases"] = _aliases(fm)
    fm["flags"] = [str(f) for f in (fm.get("flags") or [])]
    fm["summary"] = fm.get("summary") or ""
    fm.setdefault("created", ctx.today)
    fm.setdefault("id", new_page_id())
    if not fm.get("status"):
        # a decision is current from the moment it is written; the others need a lead first
        fm["status"] = _statuses(page.type)[0] if (page.lead or page.type == "decision") else "draft"
    # verified = newest source date, never the write date; a page created from a
    # record with no facts yet takes the record's date.
    prior = _s(fm.get("verified"))[:10]
    cands = [v[:10] for v in ctx.verified if v]
    if not prior and not cands and ctx.record:
        cands = [_s(ctx.record.get("date"))[:10]]
    verified = max([prior] + cands)
    fm["verified"] = verified or _s(fm.get("created"))[:10]
    # Open / Milestones: lines with no hidden comment get one, ticked ones move to History
    for name, prefix in ITEM_SECTIONS.items():
        for line in page.sections.pop(name, []):  # a page built in code, not parsed from a file
            item = _parse_item(line, page.ids(), prefix)
            if item is not None:
                page.items(name).append(item)
        keep: list[OpenItem] = []
        for o in page.items(name):
            if o.raw:
                keep.append(o)
                continue
            if not o.id:
                o.id = _new_id(page.ids())
                o.since = o.since or ctx.today
                o.src = o.src or [ctx.src or "user"]
                if name == "Open" and not o.owner:
                    o.owner = "me"
            if not o.done:
                keep.append(o)
            elif name == "Open":
                _history(page, ctx, f'done "{o.text}" — owner: {o.owner or "me"} · since {o.since}')
            else:
                _history(page, ctx, f'milestone reached "{o.text}"')
        if name == "Milestones":
            page.milestones = keep
        else:
            page.opens = keep
    fm["open_items"] = sum(1 for o in page.opens if not o.raw and not o.done)
    # Records: newest first, capped
    recs, seen = [], set()
    for line in page.lines("Records"):
        m = _RECORD_RE.match(line)
        key = _link_target(m.group(2)) if m else line
        if key in seen:
            continue
        seen.add(key)
        recs.append(line)
    recs.sort(key=lambda l: l[2:12], reverse=True)
    recs = recs[:RECORDS_MAX]
    page.sections["Records"] = recs
    if page.type == "howto" and recs:
        fm["last_done"] = recs[0][2:12]
    fm["sources"] = count_sources(ctx.root, page, ctx.ids)
    _rotate_history(page, ctx.root)
    for name in ("Open", "Records", "Related", "History"):
        if name not in SECTIONS.get(page.type, SECTIONS["topic"]) and not page.sections.get(name):
            page.sections.pop(name, None)
    fm["updated"] = store.now_iso()


def _fm_values(fm: dict[str, Any]) -> dict[str, Any]:
    """Frontmatter as plain strings, so a number written and read back as a
    number, or a date read back as text, still compares equal."""
    return {k: [_s(x) for x in v] if isinstance(v, (list, tuple)) else _s(v) for k, v in fm.items()}


def _page_diff(page: Page, back: Page) -> list[str]:
    """What the file says against what the code meant to write. Empty is good."""
    out: list[str] = []
    if _s(back.title).strip() != _s(page.title).strip():
        out.append("title")
    if back.lead.strip() != page.lead.strip():
        out.append("lead")
    want = [(f.id, f.text, f.since, list(f.src)) for f in page.facts]
    got = [(f.id, f.text, f.since, list(f.src)) for f in back.facts]
    if got != want:
        out.append(f"facts ({len(got)} of {len(want)})")
    for name in ITEM_SECTIONS:
        if [o.line() for o in back.items(name)] != [o.line() for o in page.items(name)]:
            out.append(f"section {name}")
    for name in dict.fromkeys(list(page.sections) + list(back.sections)):
        if name == "Facts":
            continue
        if _trim(list(page.sections.get(name) or [])) != _trim(list(back.sections.get(name) or [])):
            out.append(f"section {name}")
    if back.notes.strip() != page.notes.strip():
        out.append("notes")
    missing = [k for k in CODE_OWNED + ("type", "title") if k not in back.fm]
    if missing:
        out.append("keys " + ", ".join(missing))
    elif _fm_values(_ordered_fm(page.fm)) != _fm_values(back.fm):
        out.append("frontmatter")
    return out


def _commit(root: Path, page: Page, text: str, ctx: _Ctx, op_name: str) -> dict[str, Any]:
    """Write a page, read it back and compare it with what was meant.

    The text the file had is kept under ``_cache/prev/`` first. If the page that
    comes back is not the page that went in, the previous text goes back, a
    Review line and a log line say so, and the caller answers written false."""
    target = root / page.path
    had_text = read_text(target) if target.is_file() else None
    if had_text is not None:
        _atomic_write(root / PREV_DIR / (page.stem[len("Wiki/"):] + ".md.prev"), had_text)
    _atomic_write(target, text)
    try:
        back_text = read_text(target)
        back = parse_page(back_text, page.path)
    except (fmt.FrontmatterError, UnicodeDecodeError, ValueError) as exc:
        problems = [f"unreadable ({exc})"]
    else:
        problems = _page_diff(page, back)
        if f"# {page.title}" not in back_text.split("\n") and "title" not in problems:
            problems.append("title")
        if ctx.strict and measure(page.type, text)["over"]:
            problems.append("over-cap")
        if _index_line(page.path, back.fm) != _index_line(page.path, page.fm):
            problems.append("index-line")
    if problems:
        if had_text is not None:
            _atomic_write(target, had_text)
        else:
            target.unlink(missing_ok=True)
        detail = ", ".join(problems[:3])
        tail = "previous text restored" if had_text is not None else "the new page was not kept"
        _review_add(root, f"- [ ] [[{page.stem}]] — write check failed ({detail}); {tail} ({op_name}, {ctx.where})")
        _log(root, "restore", page.stem, ctx.where, f"write check failed: {detail}")
        _reconcile().forget(root, page.stem)  # the file is not what the code meant: read it fresh next time
        return {"verified": False, "problems": problems}
    ctx.touched.add(page.stem)
    _reconcile().note_write(root, page, text)  # so the next pass knows this text came from the code
    return {"verified": True, "problems": []}


def _write_page(page: Page, ctx: _Ctx) -> dict[str, Any]:
    """A write next to the op path (links, flags, records): checked like any
    other, but a page that is already over its cap is not refused here."""
    text = format_page(page)
    sizes = measure(page.type, text)
    strict, ctx.strict = ctx.strict, False
    try:
        _commit(ctx.root, page, text, ctx, "write")
    finally:
        ctx.strict = strict
    return sizes


def _link_sections(page: Page) -> set[str]:
    out = set()
    for name, lines in page.sections.items():
        if name in ("People", "Topics", "Contacts", "Related"):
            out |= {_link_target(m.group(1)) for l in lines if (m := _LINK_LINE_RE.match(l))}
    return out


def _add_link_to(root: Path, target_path: str, section: str, stem: str, role: str, touched: Optional[set[str]] = None) -> None:
    """Write the reverse side of a related / role op on the other page."""
    if not (root / target_path).is_file():
        return
    other = _load(root, target_path)
    if stem in _link_sections(other) and not role:
        return
    if _put_link(other.lines(section), stem, role, section != "Related"):
        ctx = _Ctx(root=root, src="user", since=_today(), record=None, touched=touched if touched is not None else set())
        _finalize(other, ctx)
        _write_page(other, ctx)


def _write_ops(root: Path, path: str, ops: list[Any], ctx: _Ctx, op_name: str) -> dict[str, Any]:
    ctx.strict = True
    page = _load(root, path)
    before = len(page.lines("History"))
    applied, refused = _apply_ops(page, ops, ctx)
    record_added = False
    if ctx.record:
        record_added = _add_record_line(page, ctx.record["link"], ctx.record["date"], ctx.record["summary"])
        if record_added and not applied:
            _history(page, ctx, "seen")
    # wiki links inside Facts become Related links (symmetric)
    linked = _link_sections(page)
    for f in page.facts:
        for t in {_link_target(m.group(1)) for m in _LINK_RE.finditer(f.text)}:
            if t.startswith("Wiki/") and t != page.stem and t not in linked and (root / page_path(t)).is_file():
                _put_link(page.lines("Related"), t, "", False)
                ctx.deferred.append((page_path(t), "Related", page.stem, ""))
                linked.add(t)
    _finalize(page, ctx)
    text = format_page(page)
    sizes = measure(page.type, text)
    for line in ctx.review:
        _review_add(root, line)
    if sizes["over"] and applied:
        return {
            "path": path,
            "written": False,
            "applied": [],
            "refused": [{"op": a["op"], "reason": "cap", **{k: v for k, v in sizes.items() if k != "over"}, "detail": CAP_HINT} for a in applied] + refused,
            "sizes": {k: v for k, v in sizes.items() if k != "over"},
        }
    check = _commit(root, page, text, ctx, op_name)
    if not check["verified"]:
        return {
            "path": path,
            "written": False,
            "applied": [],
            "refused": [{"op": a["op"], "reason": "verify-failed", "problems": check["problems"]} for a in applied] + refused,
            "sizes": {k: v for k, v in sizes.items() if k != "over"},
        }
    for target, section, stem, role in ctx.deferred:
        _add_link_to(root, target, section, stem, role, ctx.touched)
    if ctx.record:
        _link_record(root, ctx.record["path"], page.stem)
    counts: dict[str, int] = {}
    for a in applied:
        counts[a.get("result") or a["op"]] = counts.get(a.get("result") or a["op"], 0) + 1
    detail = ", ".join(f"{k} {v}" for k, v in counts.items()) or ("seen" if record_added else "noop")
    if refused:
        detail += f", refused {len(refused)}"
    _log(root, op_name, page.stem, ctx.where, detail)
    return {
        "path": path,
        "written": True,
        "applied": applied,
        "refused": refused,
        "record_added": record_added,
        "history_added": len(page.lines("History")) - before,
        "sizes": {k: v for k, v in sizes.items() if k != "over"},
    }


# ------------------------------------------------------------------ create


def _decided_date(value: Any) -> str:
    s = _s(value).strip()
    if not s:
        raise VaultError("A decision page needs decided: the date the decision was made (YYYY-MM-DD).")
    if not _DATE_RE.match(s):
        raise VaultError(f"decided must be a date like 2026-08-25, got {s!r}.")
    return s[:10]


def _by_links(root: Path, value: Any) -> list[str]:
    """``by``: the people who made the decision, each a link to a page that exists."""
    items = value if isinstance(value, (list, tuple)) else [value]
    out = []
    for item in items:
        ref = _s(item).strip()
        if not ref:
            continue
        try:
            path = page_path(ref)
        except VaultError as exc:
            raise VaultError(f"by: {exc}") from None
        if not (root / path).is_file():
            raise VaultError(f"by: no such page: {_stem(path)}.")
        out.append(f"[[{_stem(path)}]]")
    if not out:
        raise VaultError("A decision page needs by: who made the decision, as links to their pages.")
    return out


def _create_page(
    root: Path,
    page_type: str,
    title: str,
    aliases: Optional[list[str]],
    lead: str,
    summary: str,
    facts: Optional[list[dict[str, Any]]],
    ctx: _Ctx,
    created_by: str,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if page_type not in TYPES:
        raise VaultError(f"Unknown page type {page_type!r}. Known: {', '.join(TYPES)}.")
    try:
        title = _check_title(title)
    except WikiRefusal as r:
        raise VaultError(f"Bad title: {r.reason} {r.info}") from None
    extra = dict(extra or {})
    _refuse_code_owned(extra)
    aliases = [a for a in (aliases or []) if _s(a).strip()]
    hit = _find_by_name(_all_pages(root), title, aliases, _s(extra.get("email")))
    if hit:
        return {"created": False, "reason": "exists", "path": hit[0], "match": _index_line(*hit), "detail": "A page with this title, alias or address exists. Use it, or pick another title."}
    summary = " ".join(_s(summary).split())
    if len(summary) > SUMMARY_CHARS:
        raise VaultError(f"summary is {len(summary)} chars; the cap is {SUMMARY_CHARS}.")
    if _words(lead) > LEAD_WORDS:
        raise VaultError(f"lead is {_words(lead)} words; the cap is {LEAD_WORDS}.")
    folder = TYPE_FOLDER[page_type]
    if page_type == "me":
        p = root / WIKI_DIR / "Me.md"
        if p.is_file():
            return {"created": False, "reason": "exists", "path": rel(root, p)}
    else:
        base = (notes.person_filename(title) if page_type == "person" else slugify(title)) + ".md"
        p = store._free_filename(root / WIKI_DIR / folder, base)
    fm: dict[str, Any] = {"type": page_type, "title": title, "aliases": aliases, "summary": summary, "status": "active" if lead.strip() else "draft"}
    if page_type == "person":
        fm["name"] = title
        fm["email"] = _s(extra.pop("email", ""))
        fm["last_contact"] = _s(extra.pop("last_contact", ""))
    if page_type == "decision":
        fm["status"] = "current"
        fm["decided"] = _decided_date(extra.pop("decided", ""))
        fm["by"] = _by_links(root, extra.pop("by", None))
    fm.update({k: v for k, v in extra.items() if v not in (None, "")})
    fm["created_by"] = created_by
    page = Page(path=rel(root, p), fm=fm, title=title, lead=lead.strip())
    _history(page, ctx, "page created")
    ctx.creating = True  # a decision takes its facts here and nowhere else
    try:
        applied, refused = _apply_ops(page, [dict(f, op="add") for f in (facts or []) if isinstance(f, dict)], ctx)
    finally:
        ctx.creating = False
    if page_type == "decision":
        # the people who decided are linked both ways, like a role op would
        for link in page.fm.get("by") or []:
            who = _link_target(link)
            _put_link(page.lines("People"), who, "decided", True)
            ctx.deferred.append((page_path(who), _section_for("person", "decision"), page.stem, "decided"))
        # nobody was asked: the model wrote this from a record, so it is flagged and listed for the user
        page.fm["flags"] = [UNCONFIRMED_FLAG]
        choice = page.facts[0].text if page.facts else (summary or title)
        ctx.review.append(f'- [ ] [[{page.stem}]] — unconfirmed decision: "{choice}" — confirm or drop ({ctx.where})')
    if ctx.record:
        _add_record_line(page, ctx.record["link"], ctx.record["date"], ctx.record["summary"])
    _finalize(page, ctx)
    text = format_page(page)
    sizes = measure(page_type, text)
    if sizes["over"]:
        raise VaultError(f"Refused: the new page would be {sizes['lines']} lines / {sizes['chars']} chars (cap {sizes['max_lines']} / {sizes['max_chars']}). {CAP_HINT}")
    ctx.strict = True
    check = _commit(root, page, text, ctx, "create")
    if not check["verified"]:
        raise VaultError(f"Refused: the new page did not come back as written ({', '.join(check['problems'])}); nothing was kept.")
    for target, section, stem, role in ctx.deferred:
        _add_link_to(root, target, section, stem, role, ctx.touched)
    for line in ctx.review:
        _review_add(root, line)
    if ctx.record:
        _link_record(root, ctx.record["path"], page.stem)
    _log(root, "create", page.stem, ctx.where, f"{page_type}, facts {len(applied)}" + (f", refused {len(refused)}" if refused else ""))
    return {"created": True, "path": page.path, "applied": applied, "refused": refused, "sizes": {k: v for k, v in sizes.items() if k != "over"}}


# ------------------------------------------------------------------ public: tools


def match(text: str, people: Optional[list[str]] = None, domains: Optional[list[str]] = None, limit: int = 8) -> dict[str, Any]:
    from administrator_vault import wiki_search  # imported here: the engine imports this module

    root = store.vault_root()
    hand = _hand_edit_count(root)
    pages = _all_pages(root)
    named = wiki_search.page_candidates(text, root)  # the alias (4) and word (2) rules
    addrs = {_s(a).strip().lower() for a in (people or []) if _s(a).strip()}
    doms = {_s(d).strip().lower().lstrip("@") for d in (domains or []) if _s(d).strip()}
    doms |= {a.rsplit("@", 1)[-1] for a in addrs if "@" in a}
    scored = []
    for path, fm in pages:
        score, why = 0, []
        by_name = named.get(_stem(path), (0, []))[0]
        if by_name >= 4:
            score, why = max(score, 4), why + ["alias"]
        if fm.get("type") == "person":
            mine = {_s(fm.get("email")).lower()} | {a.lower() for a in _aliases(fm)}
            if mine & addrs:
                score, why = max(score, 3), why + ["address"]
        if fm.get("type") == "org":
            mine = {_s(d).lower().lstrip("@") for d in (fm.get("domains") or [])}
            if mine & doms:
                score, why = max(score, 1), why + ["domain"]
        if score < 2 and by_name == 2:
            score, why = max(score, 2), why + ["words"]
        if score:
            scored.append((score, _s(fm.get("verified") or fm.get("created")), path, fm, why))
    scored.sort(key=lambda t: t[1], reverse=True)
    scored.sort(key=lambda t: -t[0])
    out = {
        "pages": [{"path": p, "line": _index_line(p, fm), "score": s, "why": why} for s, _v, p, fm, why in scored[: max(1, int(limit or 8))]],
        "candidates": _candidates_over(root, pages),
    }
    if hand:
        out["hand_edits"] = hand
    return out


def read(path: str, sections: Optional[list[str]] = None, max_chars: int = 2000) -> dict[str, Any]:
    root = store.vault_root()
    hand = _hand_edit_count(root)
    page = _load(root, page_path(path))
    redirected = None
    if page.type == "redirect" and _s(page.fm.get("redirect")):  # a merged page: follow it
        redirected = page.stem
        page = _load(root, page_path(_s(page.fm.get("redirect"))))
    wanted = [s.strip().lower() for s in (sections or ["lead", "facts"]) if _s(s).strip()]
    out: dict[str, Any] = {"path": page.path, "title": page.title, "frontmatter": page.fm}
    if hand:
        out["hand_edits"] = hand
    if redirected:
        out["redirected_from"] = redirected
    for s in wanted:
        if s == "lead":
            out["lead"] = page.lead
        elif s == "facts":
            out["facts"] = [f.as_dict() for f in page.facts]
        elif s == "notes":
            out["notes"] = page.notes
        else:
            name = next((n for n in page.sections if n.lower() == s), s.capitalize())
            # the Open and Milestones lines live in page.opens / page.milestones, not in sections
            lines = [o.line() for o in page.items(name)] if name in ITEM_SECTIONS else page.sections.get(name, [])
            out.setdefault("sections", {})[name] = "\n".join(lines)
    if max_chars and max_chars > 0:
        for _ in range(200):
            if len(json.dumps(out, ensure_ascii=False)) <= max_chars:
                break
            secs = out.get("sections") or {}
            big = max(secs, key=lambda k: len(secs[k]), default=None)
            if big and len(secs[big]) > 200:
                secs[big] = secs[big][: len(secs[big]) // 2].rstrip() + " …"
            elif out.get("facts"):
                out["facts"].pop()
                out["facts_truncated"] = True
            elif len(out.get("lead", "")) > 200:
                out["lead"] = out["lead"][: len(out["lead"]) // 2].rstrip() + " …"
            else:
                break
    return out


def ingest(record_path: str, pages: Optional[list[dict[str, Any]]] = None, created_by: str = CREATED_BY) -> dict[str, Any]:
    root = store.vault_root()
    rec = _record_info(root, record_path)
    with _wiki_lock(root):
        adopted = _hand_edits(root, True)
        confirmed = _settle_ticked_decisions(root)  # a decision the user ticked in Review.md
        results = []
        touched: set[str] = set()
        for spec in pages or []:
            if not isinstance(spec, dict):
                results.append({"written": False, "refused": [{"reason": "bad-page-spec"}]})
                continue
            ctx = _Ctx(root=root, src=rec["src"], since=rec["date"], record=rec, touched=touched)
            new = spec.get("new")
            ops = spec.get("ops") or []
            if isinstance(new, dict):
                res = _create_page(root, _s(new.get("type")), _s(new.get("title")), new.get("aliases"), _s(new.get("lead")), _s(new.get("summary")), None, ctx, created_by,
                                   {k: v for k, v in new.items() if k not in ("type", "title", "aliases", "lead", "summary")})
                if res["created"] and ops:
                    ctx2 = _Ctx(root=root, src=rec["src"], since=rec["date"], record=rec, touched=touched)
                    ctx2.creating = True  # the ops of the same call still belong to the page's creation
                    more = _write_ops(root, res["path"], ops, ctx2, "ingest")
                    res.update(applied=res["applied"] + more["applied"], refused=res["refused"] + more["refused"], written=more["written"], sizes=more["sizes"])
                    if _s(new.get("type")).strip().lower() == "decision":
                        _name_the_decision(root, res["path"])
                elif res["created"]:
                    res["written"] = True
                results.append(res)
                continue
            path = page_path(_s(spec.get("path")))
            results.append(_write_ops(root, path, ops, ctx, "ingest"))
        cand = _candidate_note(root, rec["path"], rec["subject"], rec["date"], rec["summary"])
        ingested = _today()
        _mark_ingested(root, rec["path"], ingested)
        _write_index(root, touched)
    out = {"record": rec["link"], "ingested": ingested, "pages": results, "candidate": cand}
    if adopted:
        out["adopted"] = adopted
    if confirmed:
        out["confirmed_decisions"] = confirmed
    return out


def create(
    type: str,
    title: str,
    aliases: Optional[list[str]] = None,
    lead: str = "",
    summary: str = "",
    facts: Optional[list[dict[str, Any]]] = None,
    src: str = "user",
    created_by: str = CREATED_BY,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    root = store.vault_root()
    with _wiki_lock(root):
        adopted = _hand_edits(root, True)
        ctx = _Ctx(root=root, src=_s(src).strip() or "user", since=_today(), record=None)
        res = _create_page(root, _s(type).strip().lower(), title, aliases, _s(lead), _s(summary), facts, ctx, created_by, extra)
        if res["created"]:
            _write_index(root, ctx.touched)
    if adopted:
        res["adopted"] = adopted
    return res


def apply(path: str, ops: list[dict[str, Any]], created_by: str = CREATED_BY, src: str = "user") -> dict[str, Any]:
    root = store.vault_root()
    path = page_path(path)
    with _wiki_lock(root):
        adopted = _hand_edits(root, True)
        ctx = _Ctx(root=root, src=_s(src).strip() or "user", since=_today(), record=None)
        res = _write_ops(root, path, ops or [], ctx, "apply")
        _write_index(root, ctx.touched)
    if adopted:
        res["adopted"] = adopted
    return res


def log(since: Optional[str] = None, page: Optional[str] = None, limit: int = 50) -> dict[str, Any]:
    root = store.vault_root()
    hand = _hand_edit_count(root)
    p = root / LOG_PATH
    lines = [l for l in read_text(p).split("\n") if l.startswith("- [")] if p.is_file() else []
    if since:
        lines = [l for l in lines if (m := _LOG_RE.match(l)) and m.group(1) >= since]
    if page:
        want = _link_target(page).lower()
        lines = [l for l in lines if (m := _LOG_RE.match(l)) and want in m.group(3).lower()]
    out = {"path": LOG_PATH, "total": len(lines), "lines": lines[-max(1, int(limit or 50)) :]}
    if hand:
        out["hand_edits"] = hand
    return out


def review(action: str = "list", item: Optional[str] = None, resolution_ops: Optional[list[dict[str, Any]]] = None, created_by: str = CREATED_BY) -> dict[str, Any]:
    root = store.vault_root()
    open_lines, done_lines = _review_text(root)
    if action == "list":
        out = {"path": REVIEW_PATH, "open": [{"n": i + 1, "text": l} for i, l in enumerate(open_lines)], "done": len(done_lines)}
        hand = _hand_edit_count(root)  # a listing only says how many; resolve is what adopts them
        if hand:
            out["hand_edits"] = hand
        return out
    if action != "resolve":
        raise VaultError("action must be 'list' or 'resolve'.")
    key = _s(item).strip()
    if not key:
        raise VaultError("item is required: its number in the Open list or a part of its text.")
    idx = int(key) - 1 if key.isdigit() and 0 < int(key) <= len(open_lines) else next((i for i, l in enumerate(open_lines) if key in l), None)
    if idx is None:
        raise VaultError(f"No open review item matches {item!r}.")
    line = open_lines[idx]
    applied = None
    touched: set[str] = set()
    with _wiki_lock(root):
        adopted = _hand_edits(root, True)
        target = next((_link_target(m.group(1)) for m in _LINK_RE.finditer(line) if m.group(1).startswith("Wiki/")), None)
        if resolution_ops:
            if not target:
                raise VaultError("The review line names no wiki page; resolution_ops need one.")
            ctx = _Ctx(root=root, src="user", since=_today(), record=None, touched=touched)
            applied = _write_ops(root, page_path(target), resolution_ops, ctx, "review")
        open_lines, done_lines = _review_text(root)
        if line in open_lines:
            open_lines.remove(line)
        done_lines.append(line.replace("- [ ] ", "- [x] ", 1) + f" — done {_today()}")
        _write_review(root, open_lines, done_lines)
        if target and not any(f"[[{target}]]" in l for l in open_lines):
            tp = root / page_path(target)
            if tp.is_file():
                pg = _load(root, rel(root, tp))
                flags = [f for f in (pg.fm.get("flags") or []) if f not in ("contradiction", UNCONFIRMED_FLAG)]
                if flags != list(pg.fm.get("flags") or []):
                    pg.fm["flags"] = flags
                    ctx = _Ctx(root=root, src="user", since=_today(), record=None, touched=touched)
                    _finalize(pg, ctx)
                    _write_page(pg, ctx)
        _log(root, "review", target or "-", "user", "resolved: " + line[6:80])
        _write_index(root, touched)
    out = {"resolved": line, "page": target, "applied": applied}
    if adopted:
        out["adopted"] = adopted
    return out


def prep_pages(root: Path, person_paths: list[str], subject: str, people: Optional[list[str]] = None, facts_max: int = 8, topics_max: int = 3) -> list[dict[str, Any]]:
    """The ``wiki`` list of vault_prep_context: the attendees' person pages plus
    the topic and decision pages matched on the subject, each as
    {path, type, title, status, lead, open, facts}."""
    out = []
    seen: set[str] = set()
    paths = [p for p in person_paths if p and p.startswith(WIKI_DIR + "/")]
    if _s(subject).strip():
        from administrator_vault import wiki_search  # imported here: the engine imports this module

        named = wiki_search.page_candidates(subject, root)
        topics = [(p, fm) for p, fm in _all_pages(root) if fm.get("type") in ("topic", "decision") and _stem(p) in named]
        topics.sort(key=lambda t: _stem(t[0]))
        topics.sort(key=lambda t: _s(t[1].get("verified") or t[1].get("created")), reverse=True)
        # within the same score: the projects first, then the decisions, then the other topics
        topics.sort(key=lambda t: 0 if _is_project(t[1]) else 1 if _s(t[1].get("type")) == "decision" else 2)
        topics.sort(key=lambda t: -named[_stem(t[0])][0])
        paths += [p for p, _fm in topics[:topics_max]]
    for path in paths:
        if path in seen or not (root / path).is_file():
            continue
        seen.add(path)
        try:
            page = _load(root, path)
        except VaultError:
            continue
        if page.type not in TYPES:
            continue
        out.append({
            "path": path,
            "type": page.type,
            "title": page.title,
            "status": _s(page.fm.get("status")),
            "lead": page.lead,
            "open": [o.line() for o in page.opens],
            "facts": [f.as_dict() for f in page.facts[:facts_max]],
        })
    return out


# ------------------------------------------------------------------ public: commitments


COMMITMENTS_MAX = 200


def _owner_display(owner: Any, titles: dict[str, str]) -> str:
    """The owner as a person reads it: ``me``, the linked page's title, or the plain name."""
    value = _s(owner).strip()
    if not value:
        return ""
    if value.lower() == "me":
        return "me"
    target = _link_target(value)
    if target.startswith("Wiki/"):
        return titles.get(target) or target.rsplit("/", 1)[-1]
    return value


def commitments(
    root: Path,
    owner: Optional[str] = None,
    due_before: Optional[str] = None,
    page: Optional[str] = None,
    include_done: bool = False,
    limit: int = COMMITMENTS_MAX,
) -> list[dict[str, Any]]:
    """The open items of the wiki pages, oldest ``since`` first.

    ``owner`` keeps only the user's own items (``me``) or only the ones someone
    else owes (``others``); ``due_before`` keeps the items due before that date;
    ``page`` keeps to one page. Ticked items are left out unless
    ``include_done``."""
    want = _s(owner).strip().lower() or None
    if want not in (None, "me", "others"):
        raise VaultError("owner must be 'me', 'others' or nothing.")
    before = _s(due_before).strip()[:10]
    only = _stem(page_path(_s(page))) if _s(page).strip() else ""
    listing = _all_pages(root)
    titles = {_stem(p): _s(fm.get("title") or fm.get("name")) or _stem(p).rsplit("/", 1)[-1] for p, fm in listing}
    keyed: list[tuple[tuple[str, str, int], dict[str, Any]]] = []
    for path, _fm in listing:
        stem = _stem(path)
        if only and stem != only:
            continue
        try:
            pg = _load(root, path)
        except (VaultError, fmt.FrontmatterError, UnicodeDecodeError):
            continue
        for n, o in enumerate(pg.opens):
            if o.raw or (o.done and not include_done):
                continue
            own = _s(o.owner).strip()
            if want == "me" and own.lower() != "me":
                continue
            if want == "others" and (not own or own.lower() == "me"):
                continue
            if before and not (o.due and o.due[:10] < before):
                continue
            keyed.append(((_s(o.since) or "9999", stem, n), {
                "page": path, "stem": stem, "type": pg.type, "title": pg.title,
                "owner_name": _owner_display(o.owner, titles), **o.as_dict(),
            }))
    keyed.sort(key=lambda pair: pair[0])
    return [row for _key, row in keyed][: max(1, int(limit or COMMITMENTS_MAX))]


# ------------------------------------------------------------------ public: save_email hook


def record_person(
    name: str,
    email: str,
    aliases: Optional[list[str]],
    last_contact: str,
    company: Optional[str],
    record_path: str,
    record_date: str,
    summary: str,
    created_by: str = CREATED_BY,
    existing: Optional[str] = None,
) -> dict[str, Any]:
    """Create the draft person page for a sender, or add the record line to the
    existing one (aliases merged, last_contact moved forward). Used by save_email."""
    root = store.vault_root()
    link = _link(record_path)
    with _wiki_lock(root):
        adopted = _hand_edits(root, True)
        ctx = _Ctx(root=root, src="user", since=record_date or _today(), record=None)
        if existing:
            page = _load(root, existing)
            for a in aliases or []:
                _add_alias(page, a)
            old = _s(page.fm.get("last_contact"))
            if not old or notes.sort_value("person", {"last_contact": last_contact}) > notes.sort_value("person", {"last_contact": old}):
                page.fm["last_contact"] = last_contact
            if company and not page.fm.get("org"):
                page.fm["org"] = company
            _add_record_line(page, link, record_date, summary)
            _finalize(page, ctx)
            _write_page(page, ctx)
            action = "appended"
        else:
            lead = f"{name} ({email})" + (f" — {company}." if company else ".")
            res = _create_page(root, "person", name, aliases, lead, "", None, ctx, created_by, {"email": email, "last_contact": last_contact, "org": company or ""})
            if not res["created"]:
                return {"path": res["path"], "action": "exists"}
            page = _load(root, res["path"])
            page.fm["status"] = "draft"  # the model writes the real lead on first ingest
            _add_record_line(page, link, record_date, summary)
            _finalize(page, ctx)
            _write_page(page, ctx)
            action = "created"
        _link_record(root, record_path, page.stem)
        _log(root, "record", page.stem, link, action)
        _write_index(root, ctx.touched)
    out = {"path": page.path, "action": action}
    if adopted:
        out["adopted"] = adopted
    return out


_BODY_RECORD_RE = re.compile(r"^\s*- (\d{4}-\d{2}-\d{2}) — (\[\[[^\]]+\]\])\s*(.*?)\s*$")
_STATUS_TAIL_RE = re.compile(r"^\((?:todo|waiting|done|fyi|held|upcoming|cancelled|canceled|prep)\)$", re.IGNORECASE)


def _records_from_body(body: str) -> list[tuple[str, str, str]]:
    """``- <date> — [[record]] (status)`` lines of an old-style person body -> (date, link, summary)."""
    out = []
    for line in _s(body).split("\n"):
        m = _BODY_RECORD_RE.match(line)
        if not m:
            continue
        tail = m.group(3).strip()
        tail = "" if _STATUS_TAIL_RE.match(tail) else tail.lstrip("—- ").strip()
        out.append((m.group(1), m.group(2), tail))
    return out


def person_write(fm: dict[str, Any], body: str, mode: str = "create") -> dict[str, Any]:
    """``vault_write("person", …)``: the page is kept by the wiki, so the old note
    shape is turned into the contract. create -> a draft page (lead
    ``<name> (<email>) — <org>.``); append -> aliases merged, ``last_contact``
    moved forward, ``status`` replaced when given. Record lines in the body
    (``- <date> — [[Emails/…]] (status)``) become ``## Records`` lines; any other
    body text is dropped. Answer shape as ``store.write``."""
    root = store.vault_root()
    name = _s(fm.get("name")).strip()
    email = _s(fm.get("email")).strip()
    ident = {"email": email}
    hit = store.find("person", ident)
    if hit["found"] and mode == "create":
        raise VaultError(f"A person note with this identity already exists: {hit['path']}.")
    if not hit["found"] and mode == "append":
        raise VaultError(f"No person note with identity {ident} to append to.")
    aliases = fm.get("aliases") or []
    aliases = [_s(a) for a in ([aliases] if isinstance(aliases, str) else aliases) if _s(a).strip()]
    records = _records_from_body(body)
    last_contact = _s(fm.get("last_contact"))
    org = _s(fm.get("org") or fm.get("company")).strip()
    with _wiki_lock(root):
        adopted = _hand_edits(root, True)
        ctx = _Ctx(root=root, src="user", since=_today(), record=None)
        changed: list[str] = []
        if hit["found"]:
            page = _load(root, hit["path"])
            old_aliases = list(_aliases(page.fm))
            for a in aliases:
                _add_alias(page, a)
            if _aliases(page.fm) != old_aliases:
                changed.append("aliases")
            old_lc = _s(page.fm.get("last_contact"))
            if last_contact and (not old_lc or notes.sort_value("person", {"last_contact": last_contact}) > notes.sort_value("person", {"last_contact": old_lc})):
                page.fm["last_contact"] = last_contact
                changed.append("last_contact")
            if _s(fm.get("status")) and _s(fm.get("status")) != _s(page.fm.get("status")):
                page.fm["status"] = _s(fm.get("status"))
                changed.append("status")
            if org and not _s(page.fm.get("org")):
                page.fm["org"] = org
                changed.append("org")
            for day, link, summary in records:
                _add_record_line(page, link, day, summary)
            _finalize(page, ctx)
            _write_page(page, ctx)
            _log(root, "record", page.stem, "user", "appended")
            _write_index(root, ctx.touched)
            out = {"path": page.path, "action": "appended", "identity": ident, "update_heading": None, "frontmatter_changed": changed}
            if adopted:
                out["adopted"] = adopted
            return out
        title = name or email.split("@", 1)[0]
        lead = f"{title} ({email})" + (f" — {org}." if org else ".")
        extra = {"email": email, "last_contact": last_contact, "org": org}
        res = _create_page(root, "person", title, aliases, lead, "", None, ctx, _s(fm.get("created_by")) or CREATED_BY, extra)
        if not res["created"]:
            raise VaultError(f"A person page with this name or address already exists: {res['path']}.")
        page = _load(root, res["path"])
        page.fm["status"] = _s(fm.get("status")) or "draft"  # the model writes the real lead on first ingest
        for day, link, summary in records:
            _add_record_line(page, link, day, summary)
        _finalize(page, ctx)
        _write_page(page, ctx)
        _write_index(root, ctx.touched)
    out = {"path": page.path, "action": "created", "identity": ident}
    if adopted:
        out["adopted"] = adopted
    return out


__all__ = [
    "CREATED_BY", "WIKI_DIR", "TYPES", "SECTIONS", "CAPS", "Page", "Fact", "OpenItem",
    "parse_page", "format_page", "measure", "page_path", "slugify", "init_files", "new_page_id",
    "match", "read", "ingest", "create", "apply", "log", "review", "record_person", "person_write", "prep_pages",
    "commitments",
]
