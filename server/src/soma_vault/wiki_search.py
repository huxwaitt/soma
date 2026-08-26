"""The wiki search engine: ranked facts read from the pages themselves.

Code only, no model and no embeddings. The unit of search is one fact bullet
(with its page's title, aliases, kind, status and sources), plus one document
per page (title, aliases, lead, Records summaries) and one per History line
that holds superseded text. ``## Notes`` is never read: the documents are
built from ``wiki.parse_page``, which keeps Notes apart.

Four candidate lists are fused by reciprocal rank fusion: words (BM25F over
the query widened with the alias table), exact (quoted phrases, ids, dates,
amounts and ``/regex/`` over the raw text), name (fuzzy over titles, aliases
and person filenames) and linked (pages linked from the best word hits).
The fused score is then multiplied by floored priors for status, recency and
how well the fact is backed.

``Wiki/_cache/search.json.gz`` is only a cache: every call stats the files,
hashes the changed ones and re-reads only those. Delete it and nothing is
lost.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from soma_vault import frontmatter as fmt
from soma_vault import store, wiki
from soma_vault.wiki import (
    CACHE_DIR, TYPE_FOLDER, TYPES, WIKI_DIR, _LINK_RE, _RECORD_RE, _STOP, _aliases, _link_sections,
    _link_target, _norm_name, _record_src_id, _s, _stem, _unquote, src_record,
)

_HASH_RE = re.compile(r"^[0-9a-f]{16}$")  # a document record id

SCHEMA_VERSION = 2  # 2: open items carry an owner, a due date and an id
SEARCH_CACHE = f"{CACHE_DIR}/search.json.gz"
QUERY_LOG = f"{CACHE_DIR}/queries.log"

FIELDS = ("title", "aliases", "lead", "fact", "records", "ctx")
W = {"title": 3.0, "aliases": 2.5, "lead": 1.5, "fact": 1.0, "records": 0.7, "ctx": 0.5}
B = {"title": 0.3, "aliases": 0.3, "lead": 0.75, "fact": 0.5, "records": 0.75, "ctx": 0.3}
K1 = 1.2
RRF_K = 60

STATUS_PRIOR = {"active": 1.0, "draft": 0.8, "dormant": 0.6, "closed": 0.35, "superseded": 0.35, "retired": 0.15}
SUPERSEDED_PRIOR = 0.35
PRIOR_FLOOR = 0.05
HALF_LIFE_DAYS = 365.0
EXPANSIONS = 3
EXPANSION_WEIGHT = 0.6
FUZZY_JACCARD = 0.4
FUZZY_JW = 0.88
ALIAS_JW = 0.92
NEIGHBOUR_SEEDS = 5
FACTS_PER_PAGE = 3
BRIEF_PAGES = 3
BRIEF_FACTS = 4
BRIEF_LEAD_CHARS = 240
BRIEF_LINKED = 3
QUERY_LOG_MAX = 2000
QUERY_LOG_KEEP = 1000
OPEN_ITEMS_MAX = 200
UNANSWERED_MIN = 2  # a question asked once is not yet a gap in the wiki
UNANSWERED_DAYS = 30
ONE_SOURCE_DAYS = 180  # one source and no confirmation since then: the brief says so

_WORD_RE = re.compile(r"\w{2,}", re.UNICODE)
_QUOTED_QUERY_RE = re.compile(r'"([^"]+)"')
_REGEX_QUERY_RE = re.compile(r"^(?:/(.+)/|re:(\S.*))$", re.DOTALL)
_ID_TOKEN_RE = re.compile(r"^[a-z]:\S{2,}$", re.IGNORECASE)
_HISTORY_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) — (?:superseded|retired) \"((?:[^\"\\]|\\.)*)\"")
_DECIDED_RE = re.compile(r"\b(agreed|decided|approved|due|deadline|signed|closes)\b", re.IGNORECASE)
_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# root -> (signature, Index): a second query in the same process reads no file
_LIVE: dict[str, tuple[tuple, "Index"]] = {}
_LIVE_MAX = 4


# ------------------------------------------------------------------ small helpers


def _blake(data: bytes) -> str:
    return hashlib.blake2b(data, digest_size=16).hexdigest()


def _today() -> str:
    return date.today().isoformat()


_DAYS: dict[tuple[str, str], Optional[int]] = {}  # the same few dates are asked for again and again


def _days_between(day: str, today: str) -> Optional[int]:
    key = (_s(day)[:10], today[:10])
    if key not in _DAYS:
        if len(_DAYS) > 8192:
            _DAYS.clear()
        try:
            _DAYS[key] = (date.fromisoformat(key[1]) - date.fromisoformat(key[0])).days if _DAY_RE.match(key[0]) else None
        except ValueError:
            _DAYS[key] = None
    return _DAYS[key]


def _decay(days: Optional[int]) -> float:
    """1.0 today, 0.5 after a year."""
    if days is None or days <= 0:
        return 1.0
    return math.exp(-math.log(2) * days / HALF_LIFE_DAYS)


def _neg_day(day: str) -> int:
    """Sort key that puts the newest date first next to ascending keys."""
    digits = re.sub(r"\D", "", _s(day)[:10])
    return -int(digits) if digits else 0


def _stem_word(w: str) -> str:
    """Light suffix stripping, alphabetic words of five letters or more only."""
    if len(w) < 5 or not w.isalpha():
        return w
    if w.endswith("ies"):
        return w[:-3] + "y"
    for suf in ("ing", "es", "ed", "s"):
        if w.endswith(suf):
            if suf == "s" and w.endswith("ss"):
                continue
            rest = w[: -len(suf)]
            if len(rest) >= 4:
                return rest
    return w


def tokenize(text: str) -> list[str]:
    """The one tokeniser, used for documents and for queries alike."""
    out = []
    for w in _WORD_RE.findall(_s(text).lower()):
        if w in _STOP or not w.strip("_"):
            continue
        out.append(_stem_word(w))
    return out


def _counts(text: str) -> dict[str, int]:
    tf: dict[str, int] = {}
    for t in tokenize(text):
        tf[t] = tf.get(t, 0) + 1
    return tf


def literals(query: str) -> list[str]:
    """Quoted phrases plus the tokens that must be found exactly as written:
    ids, addresses, dates and amounts."""
    q = _s(query)
    out = [p.strip().lower() for p in _QUOTED_QUERY_RE.findall(q) if p.strip()]
    for raw in _QUOTED_QUERY_RE.sub(" ", q).split():
        tok = raw.strip(".,;:!?()[]").strip()
        if len(tok) < 2:
            continue
        if any(c.isdigit() for c in tok) or any(c in "@|<#" for c in tok) or _ID_TOKEN_RE.match(tok):
            out.append(tok.lower())
    seen: set[str] = set()
    return [t for t in out if not (t in seen or seen.add(t))]


def regex_of(query: str) -> Optional[re.Pattern]:
    """``/…/`` or ``re:…`` — the whole query, not a part of it."""
    m = _REGEX_QUERY_RE.match(_s(query).strip())
    if not m:
        return None
    try:
        return re.compile(m.group(1) or m.group(2), re.IGNORECASE)
    except re.error:
        return None


def expand(terms: list[str], alias_table: dict[str, set[str]], df: Optional[dict[str, int]] = None) -> list[tuple[str, float]]:
    """The query terms at weight 1.0 plus up to three alias terms each at 0.6,
    rarest first, never widened a second time."""
    df = df or {}
    have = list(dict.fromkeys(terms))
    out: list[tuple[str, float]] = [(t, 1.0) for t in have]
    seen = set(have)
    for t in have:
        added = 0
        for other in sorted(alias_table.get(t, ()), key=lambda x: (df.get(x, 0), x)):
            if other in seen:
                continue
            out.append((other, EXPANSION_WEIGHT))
            seen.add(other)
            added += 1
            if added >= EXPANSIONS:
                break
    return out


def _grams(text: str, n: int = 3) -> set[str]:
    s = " ".join(_s(text).split())
    if len(s) < n:
        return {s} if s else set()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _jaro(a: str, b: str) -> float:
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if not la or not lb:
        return 0.0
    window = max(0, max(la, lb) // 2 - 1)
    a_hit = [False] * la
    b_hit = [False] * lb
    matches = 0
    for i, ch in enumerate(a):
        for j in range(max(0, i - window), min(i + window + 1, lb)):
            if not b_hit[j] and b[j] == ch:
                a_hit[i] = b_hit[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    trans = 0
    k = 0
    for i in range(la):
        if not a_hit[i]:
            continue
        while not b_hit[k]:
            k += 1
        if a[i] != b[k]:
            trans += 1
        k += 1
    trans //= 2
    return (matches / la + matches / lb + (matches - trans) / matches) / 3


def _jaro_winkler(a: str, b: str) -> float:
    j = _jaro(a, b)
    prefix = 0
    for x, y in zip(a[:4], b[:4]):
        if x != y:
            break
        prefix += 1
    return j + prefix * 0.1 * (1 - j)


def _stream_of(src: str) -> str:
    """Which kind of source a fact's src string names; the locator is left out."""
    s = src_record(_s(src).strip()).strip()
    if not s or s.lower() == "user":
        return "user"
    if s.startswith("<") and "@" in s:
        return "mail"
    if _HASH_RE.match(s):
        return "file"
    if "|" in s:
        left = s.split("|", 1)[0]
        if "@thread" in left or "@unq" in left or left.startswith("19:"):
            return "chat"
        return "meeting"
    return "other"


# ------------------------------------------------------------------ files and cache


def _page_files(root: Path) -> list[tuple[str, Path, int, int]]:
    """Every wiki page file as (vault-relative path, path, size, mtime_ns), index
    files left out. One directory read per folder: the sizes and times come with
    the listing."""
    wiki_dir = root / WIKI_DIR
    if not wiki_dir.is_dir():
        return []
    out: list[tuple[str, Path, int, int]] = []
    me = wiki_dir / "Me.md"
    if me.is_file():
        st = me.stat()
        out.append((f"{WIKI_DIR}/Me.md", me, st.st_size, st.st_mtime_ns))
    for folder in dict.fromkeys(f for f in TYPE_FOLDER.values() if f):
        try:
            with os.scandir(wiki_dir / folder) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            if not e.name.endswith(".md") or e.name == "Index.md" or not e.is_file():
                continue
            st = e.stat()
            out.append((f"{WIKI_DIR}/{folder}/{e.name}", Path(e.path), st.st_size, st.st_mtime_ns))
    return out


def _read_cache(root: Path) -> Optional[dict[str, Any]]:
    p = root / SEARCH_CACHE
    if not p.is_file():
        return None
    try:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError, EOFError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        return None
    if not isinstance(data.get("manifest"), dict) or not isinstance(data.get("files"), dict):
        return None
    return data


def _write_cache(root: Path, manifest: dict[str, Any], files: dict[str, Any]) -> None:
    p = root / SEARCH_CACHE
    tmp = p.with_name(p.name + ".tmp")
    data = {"schema": SCHEMA_VERSION, "built": store.now_iso(), "manifest": manifest, "files": files}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, p)
    except OSError:  # a cache that cannot be written is not an error
        tmp.unlink(missing_ok=True)


# ------------------------------------------------------------------ the index


class Index:
    """The forward index (one entry per file) plus the postings, built in memory."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.files: dict[str, dict[str, Any]] = {}
        self.by_stem: dict[str, dict[str, Any]] = {}
        self.docs: list[dict[str, Any]] = []
        self.post: dict[str, dict[int, dict[str, int]]] = {}
        self.df: dict[str, int] = {}
        self.avglen: dict[str, float] = {}
        self.inbound: dict[str, int] = {}
        self.page_doc: dict[str, int] = {}
        self.alias_terms: dict[str, set[str]] = {}
        self.names: list[tuple[str, str, set[str]]] = []  # (name without punctuation, stem, 3-grams)
        self.name_grams: dict[str, set[int]] = {}
        self._priors: dict[tuple, float] = {}
        self.reparsed: list[str] = []
        self.hashed: list[str] = []
        self.rebuilt = False
        self.reused = False

    # -------------------------------------------------------------- loading

    @classmethod
    def load(cls, root: Path) -> "Index":
        files = _page_files(root)
        sig = tuple(sorted((path, size, mtime) for path, _p, size, mtime in files))
        live = _LIVE.get(str(root))
        if live and live[0] == sig:
            ix = live[1]
            ix.reused, ix.reparsed, ix.hashed = True, [], []
            return ix
        ix = cls(root)
        ix._scan(files)
        if len(_LIVE) >= _LIVE_MAX:
            _LIVE.pop(next(iter(_LIVE)))
        _LIVE[str(root)] = (sig, ix)
        return ix

    def _scan(self, files: list[tuple[str, Path, int, int]]) -> None:
        cached = _read_cache(self.root)
        self.rebuilt = cached is None
        manifest: dict[str, Any] = (cached or {}).get("manifest") or {}
        old_files: dict[str, Any] = (cached or {}).get("files") or {}
        new_manifest: dict[str, Any] = {}
        new_files: dict[str, Any] = {}
        changed = False
        for path, p, size, mtime in files:
            old = manifest.get(path)
            entry = old_files.get(path)
            known = isinstance(old, list) and len(old) == 3 and isinstance(entry, dict)
            if known and old[0] == size and old[1] == mtime:
                new_manifest[path] = list(old)
                new_files[path] = entry
                continue
            try:
                data = p.read_bytes()
            except OSError:
                continue
            digest = _blake(data)
            self.hashed.append(path)
            new_manifest[path] = [size, mtime, digest]
            changed = True
            if known and old[2] == digest:  # touched, not edited
                new_files[path] = entry
                continue
            new_files[path] = self._index_file(path, data.decode("utf-8", "replace").replace("\r\n", "\n"))
            self.reparsed.append(path)
        if set(new_manifest) != set(manifest):
            changed = True
        self.files = new_files
        if changed:
            _write_cache(self.root, new_manifest, new_files)
        self._build()

    def _index_file(self, path: str, text: str) -> dict[str, Any]:
        blank = {"stem": _stem(path), "kind": "", "title": "", "aliases": [], "status": "draft", "verified": "",
                 "summary": "", "lead": "", "open": [], "links": [], "docs": []}
        try:
            page = wiki.parse_page(text, path)
        except (fmt.FrontmatterError, ValueError):
            return blank
        fm = page.fm
        stem = page.stem
        title = page.title or _s(fm.get("title") or fm.get("name"))
        aliases = _aliases(fm)
        entry: dict[str, Any] = dict(
            blank, stem=stem, kind=page.type, title=title, aliases=aliases,
            status=_s(fm.get("status")) or "draft", verified=_s(fm.get("verified") or fm.get("created"))[:10],
            summary=_s(fm.get("summary")), lead=page.lead,
            # the open items as a reader sees them; the hidden comment is not part of a brief
            open=[o.line().split('<!--')[0].rstrip() for o in page.opens if not o.done],
        )
        links = {t for t in _link_sections(page) if t.startswith("Wiki/") and t != stem}
        for key in ("owner", "org", "redirect"):
            target = _link_target(_s(fm.get(key)))
            if target.startswith("Wiki/") and target != stem:
                links.add(target)
        for f in page.facts:
            for m in _LINK_RE.finditer(f.text):
                t = _link_target(m.group(1))
                if t.startswith("Wiki/") and t != stem:
                    links.add(t)
        entry["links"] = sorted(links)
        if page.type not in TYPES:  # a redirect or a page without the contract: stats only
            return entry
        records: list[str] = []
        rec_days: dict[str, str] = {}
        ids: dict[str, str] = {}
        for line in page.sections.get("Records", []):
            m = _RECORD_RE.match(line)
            if not m:
                continue
            parts = line.split(" — ", 2)
            records.append(parts[2] if len(parts) > 2 else "")
            ident = _record_src_id(self.root, _link_target(m.group(2)), ids)
            if m.group(1) > rec_days.get(ident, ""):
                rec_days[ident] = m.group(1)
        ctx_text = " ".join([title] + aliases)
        docs: list[dict[str, Any]] = entry["docs"]
        docs.append(_doc(
            key=f"p:{stem}", pos=0, text=page.lead or entry["summary"] or title, since=entry["verified"],
            src=[], streams=len({_stream_of(s) for f in page.facts for s in f.src}), conf=entry["verified"],
            superseded=False, fact_id=None,
            fields={"title": title, "aliases": " ".join(aliases),
                    "lead": " ".join([page.lead, entry["summary"]]).strip(), "records": " ".join(records)},
            raw=" ".join([stem, title] + aliases + [page.lead, entry["summary"]] + records),
        ))
        for i, f in enumerate(page.facts):
            docs.append(_doc(
                key=f"f:{stem}#{f.id}", pos=i + 1, text=f.text, since=f.since, src=list(f.src),
                streams=len({_stream_of(s) for s in f.src}),
                conf=max([f.since] + [rec_days[r] for s in f.src if (r := src_record(s)) in rec_days]),
                superseded=False, fact_id=f.id, fields={"fact": f.text, "ctx": ctx_text},
                raw=" ".join([f"f:{f.id}", f.text, f.since] + list(f.src) + [title] + aliases + [stem]),
            ))
        n = 0
        for line in page.sections.get("History", []):
            m = _HISTORY_RE.match(line)
            if not m:
                continue
            n += 1
            old_text = _unquote(m.group(2))
            docs.append(_doc(
                key=f"h:{stem}#{n}", pos=1000 + n, text=old_text, since=m.group(1), src=[], streams=0,
                conf=m.group(1), superseded=True, fact_id=None, fields={"fact": old_text, "ctx": ctx_text},
                raw=" ".join([old_text, m.group(1), title] + aliases + [stem]),
            ))
        return entry

    def _build(self) -> None:
        totals: dict[str, int] = {}
        counts: dict[str, int] = {}
        for path in sorted(self.files):
            entry = self.files[path]
            self.by_stem[entry["stem"]] = entry
            for cached in entry.get("docs") or []:
                i = len(self.docs)
                doc = dict(cached, path=path, stem=entry["stem"])
                self.docs.append(doc)
                if doc["key"].startswith("p:"):
                    self.page_doc[entry["stem"]] = i
                for field, tfs in doc["tf"].items():
                    for term, n in tfs.items():
                        self.post.setdefault(term, {}).setdefault(i, {})[field] = n
                for field, length in doc["len"].items():
                    totals[field] = totals.get(field, 0) + length
                    counts[field] = counts.get(field, 0) + 1
            names = [entry["title"]] + list(entry["aliases"] or [])
            if entry["kind"] == "person":
                names.append(Path(path).stem)
            terms: set[str] = set()
            for name in names:
                norm = _norm_name(name)
                if norm and len(norm) >= 3 and not any(norm == n for n, s, _g in self.names if s == entry["stem"]):
                    grams = _grams(norm)
                    for g in grams:
                        self.name_grams.setdefault(g, set()).add(len(self.names))
                    self.names.append((norm, entry["stem"], grams))
                terms |= set(tokenize(name))
            for t in terms:
                self.alias_terms.setdefault(t, set()).update(terms - {t})
            for target in entry.get("links") or []:
                self.inbound[target] = self.inbound.get(target, 0) + 1
        self.avglen = {f: (totals[f] / counts[f]) if counts.get(f) else 1.0 for f in FIELDS}
        self.df = {term: len(posting) for term, posting in self.post.items()}

    # -------------------------------------------------------------- the four lists

    def bm25(self, qterms: list[tuple[str, float]]) -> list[int]:
        n_docs = len(self.docs) or 1
        scores: dict[int, float] = {}
        for term, weight in qterms:
            posting = self.post.get(term)
            if not posting:
                continue
            df = len(posting)
            idf = math.log((n_docs - df + 0.5) / (df + 0.5) + 1)
            for i, fields in posting.items():
                doc = self.docs[i]
                tfc = 0.0
                for field, tf in fields.items():
                    avg = self.avglen.get(field) or 1.0
                    tfc += W[field] * tf / (1 - B[field] + B[field] * doc["len"].get(field, 0) / avg)
                scores[i] = scores.get(i, 0.0) + weight * idf * tfc * (K1 + 1) / (tfc + K1)
        return [i for i, _ in sorted(scores.items(), key=lambda kv: (-kv[1], self.docs[kv[0]]["key"]))]

    def matched_terms(self, i: int, terms: list[str]) -> int:
        """How many distinct query terms one document holds."""
        return sum(1 for t in set(terms) if i in self.post.get(t, {}))

    def exact(self, lits: list[str], rx: Optional[re.Pattern]) -> list[int]:
        if not lits and rx is None:
            return []
        found: dict[int, int] = {}
        for i, doc in enumerate(self.docs):
            n = sum(1 for lit in lits if lit in doc["raw"])
            if rx is not None and rx.search(doc["raw"]):
                n += 1
            if n:
                found[i] = n
        return [i for i, _ in sorted(found.items(), key=lambda kv: (-kv[1], self.docs[kv[0]]["key"]))]

    def fuzzy(self, query: str, jaccard_min: float = FUZZY_JACCARD, jw_min: float = FUZZY_JW) -> dict[str, float]:
        """Stems whose title, alias or person filename reads like a part of the query."""
        words = _norm_name(query).split()
        windows = []
        for size in (1, 2, 3):
            for i in range(len(words) - size + 1):
                part = words[i : i + size]
                w = " ".join(part)
                if len(w) >= 3 and not all(x in _STOP for x in part):
                    windows.append((w, _grams(w)))
        best: dict[str, float] = {}
        for w, wgrams in windows:
            near: set[int] = set()
            for g in wgrams:  # only names that share a three-letter run can reach either bar
                near |= self.name_grams.get(g, set())
            for i in sorted(near):
                norm, stem, grams = self.names[i]
                jac = _jaccard(grams, wgrams)
                jw = _jaro_winkler(norm, w)
                if (jac >= jaccard_min or jw >= jw_min) and max(jac, jw) > best.get(stem, 0.0):
                    best[stem] = max(jac, jw)
        return best

    def neighbours(self, stems: list[str]) -> list[int]:
        targets: set[str] = set()
        for stem in stems:
            entry = self.by_stem.get(stem)
            if entry:
                targets |= {t for t in entry.get("links") or [] if t not in stems}
        ordered = sorted(targets, key=lambda s: (-self.inbound.get(s, 0), s))
        return [self.page_doc[s] for s in ordered if s in self.page_doc]

    # -------------------------------------------------------------- priors

    def priors(self, doc: dict[str, Any], today: str) -> float:
        key = (doc["path"], doc["superseded"], doc.get("streams") or 0, _s(doc.get("conf")), today)
        if key not in self._priors:
            entry = self.files.get(doc["path"]) or {}
            status = SUPERSEDED_PRIOR if doc["superseded"] else STATUS_PRIOR.get(_s(entry.get("status")), 0.8)
            recency = 0.7 + 0.3 * _decay(_days_between(_s(entry.get("verified")), today))
            c = 0.5 * min(doc.get("streams") or 0, 3) / 3 + 0.5 * _decay(_days_between(_s(doc.get("conf")), today))
            self._priors[key] = max(PRIOR_FLOOR, status * recency * (0.6 + 0.4 * c))
        return self._priors[key]


def _doc(key: str, pos: int, text: str, since: str, src: list[str], streams: int, conf: str,
         superseded: bool, fact_id: Optional[str], fields: dict[str, str], raw: str) -> dict[str, Any]:
    tf = {name: _counts(value) for name, value in fields.items() if _s(value).strip()}
    return {
        "key": key, "pos": pos, "text": text, "since": since, "src": src, "streams": streams, "conf": conf,
        "superseded": superseded, "fact_id": fact_id, "tf": tf,
        "len": {name: sum(counts.values()) for name, counts in tf.items()},
        "raw": " ".join(raw.lower().split()),
    }


# ------------------------------------------------------------------ the query


def _fuse(lists: list[tuple[str, list[int]]]) -> tuple[dict[int, float], dict[int, list[str]]]:
    fused: dict[int, float] = {}
    why: dict[int, list[str]] = {}
    for name, docs in lists:
        for rank, i in enumerate(docs, start=1):
            fused[i] = fused.get(i, 0.0) + 1 / (RRF_K + rank)
            why.setdefault(i, []).append(name)
    return fused, why


def _hit(ix: Index, i: int, score: float, why: list[str], today: str) -> dict[str, Any]:
    doc = ix.docs[i]
    entry = ix.files.get(doc["path"]) or {}
    return {
        "page": doc["stem"],
        "kind": _s(entry.get("kind")),
        "title": _s(entry.get("title")),
        "fact_id": doc["fact_id"],
        "text": doc["text"],
        "since": doc["since"],
        "src": list(doc["src"]),
        "score": round(score, 6),
        "why": list(why),
        "superseded": bool(doc["superseded"]),
        "streams": doc.get("streams") or 0,
        "confirmed": _days_between(_s(doc.get("conf")), today),
    }


def search(
    query: str,
    kinds: Optional[list[str]] = None,
    limit: int = 10,
    since: Optional[str] = None,
    include_superseded: bool = False,
    root: Optional[Path] = None,
    today: Optional[str] = None,
    log: bool = True,
) -> list[dict[str, Any]]:
    """Ranked facts for a question: the four lists fused, then the priors."""
    root = root or store.vault_root()
    today = _s(today)[:10] or _today()
    ix = Index.load(root)
    words = ix.bm25(expand(tokenize(query), ix.alias_terms, ix.df))
    exact = ix.exact(literals(query), regex_of(query))
    seeds: list[str] = []
    for i in words + exact:
        stem = ix.docs[i]["stem"]
        if stem not in seeds:
            seeds.append(stem)
        if len(seeds) >= NEIGHBOUR_SEEDS:
            break
    fuzzy = sorted(ix.fuzzy(query).items(), key=lambda kv: (-kv[1], kv[0]))
    named = [ix.page_doc[s] for s, _sim in fuzzy if s in ix.page_doc]
    fused, why = _fuse([("words", words), ("exact", exact), ("name", named), ("linked", ix.neighbours(seeds))])
    want = {_s(k).strip().lower() for k in (kinds or []) if _s(k).strip()}
    floor = _s(since)[:10]
    scored = []
    for i, base in fused.items():
        doc = ix.docs[i]
        entry = ix.files.get(doc["path"]) or {}
        if doc["superseded"] and not include_superseded:
            continue
        if want and _s(entry.get("kind")) not in want:
            continue
        if floor and _s(doc["since"])[:10] < floor:
            continue
        scored.append((-base * ix.priors(doc, today), _neg_day(doc["since"]), doc["stem"], doc["pos"], i))
    scored.sort()
    hits: list[dict[str, Any]] = []
    per_page: dict[str, int] = {}
    for score, _d, _st, _p, i in scored:
        doc = ix.docs[i]
        if doc["fact_id"]:
            if per_page.get(doc["stem"], 0) >= FACTS_PER_PAGE:
                continue
            per_page[doc["stem"]] = per_page.get(doc["stem"], 0) + 1
        hits.append(_hit(ix, i, -score, why[i], today))
        if len(hits) >= max(1, int(limit or 10)):
            break
    if log:
        _log_query(root, query, len(hits), hits[0]["page"] if hits else "-")
    return hits


def page_candidates(text: str, root: Optional[Path] = None) -> dict[str, tuple[int, list[str]]]:
    """What ``wiki.match`` consumes: stem -> (score, why). 4 = a name of the page
    is written in the text (or nearly is), 2 = the page holds at least two of
    the text's words."""
    root = root or store.vault_root()
    ix = Index.load(root)
    out: dict[str, tuple[int, list[str]]] = {}
    t_norm = _norm_name(text)
    for norm, stem, _g in ix.names:
        if stem in out or norm not in t_norm:  # the cheap test first: the name must be in the text
            continue
        if norm == t_norm or re.search(r"(?<!\w)" + re.escape(norm) + r"(?!\w)", t_norm):
            out[stem] = (4, ["alias"])
    for stem in ix.fuzzy(text, jaccard_min=2.0, jw_min=ALIAS_JW):
        out.setdefault(stem, (4, ["alias"]))
    terms = tokenize(text)
    if len(set(terms)) >= 2:
        for stem, i in ix.page_doc.items():
            if stem not in out and ix.matched_terms(i, terms) >= 2:
                out[stem] = (2, ["words"])
    return out


# ------------------------------------------------------------------ brief


def _hedge(doc: Optional[dict[str, Any]], today: str) -> str:
    """" (one source, unconfirmed since <date>)" for a fact that rests on one
    source and has not been confirmed for half a year, so the model hedges or
    asks instead of stating it."""
    if not doc or (doc.get("streams") or 0) != 1:
        return ""
    conf = _s(doc.get("conf")) or _s(doc.get("since"))
    days = _days_between(conf, today)
    if days is None or days <= ONE_SOURCE_DAYS:
        return ""
    return f" (one source, unconfirmed since {conf})"


def brief(question: str, max_chars: int = 1500, root: Optional[Path] = None, today: Optional[str] = None) -> dict[str, Any]:
    """One stitched answer: the best three pages with their lead, facts and open
    items, then the decisions and dated facts of the pages they link to. A fact
    with one source and no confirmation in 180 days is marked as such."""
    root = root or store.vault_root()
    today = _s(today)[:10] or _today()
    ix = Index.load(root)
    hits = search(question, limit=24, root=root, today=today, log=False)
    order: list[str] = []
    for h in hits:
        if h["page"] not in order and h["page"] in ix.by_stem:
            order.append(h["page"])
    order = order[:BRIEF_PAGES]
    rows: list[dict[str, Any]] = []  # {line, page?, fact?}
    seen: set[tuple[str, str]] = set()
    for stem in order:
        entry = ix.by_stem[stem]
        if rows:
            rows.append({"line": ""})
        rows.append({"line": f"[[{stem}|{entry['title']}]] · {entry['kind']} · {entry['status']} · {entry['verified']}",
                     "page": {"page": stem, "title": entry["title"], "kind": entry["kind"],
                              "status": entry["status"], "verified": entry["verified"]}})
        lead = " ".join(_s(entry.get("lead") or entry.get("summary")).split())
        if lead:
            rows.append({"line": lead[:BRIEF_LEAD_CHARS].rstrip() + (" …" if len(lead) > BRIEF_LEAD_CHARS else "")})
        by_id = {d["fact_id"]: d for d in entry.get("docs") or [] if d.get("fact_id")}
        n = 0
        for h in hits:
            if h["page"] != stem or not h["fact_id"] or n >= BRIEF_FACTS or (stem, h["fact_id"]) in seen:
                continue
            seen.add((stem, h["fact_id"]))
            n += 1
            rows.append({"line": f"- {h['text']} (f:{h['fact_id']}, {h['since']}){_hedge(by_id.get(h['fact_id']), today)}",
                         "fact": {"page": stem, "id": h["fact_id"], "text": h["text"], "since": h["since"]}})
        rows += [{"line": l} for l in entry.get("open") or []]
    linked = 0
    for stem in order:
        targets = ix.by_stem[stem].get("links") or []
        # the decisions the best pages link to come first: that is what a brief is asked for
        for target in sorted(targets, key=lambda t: 0 if _s((ix.by_stem.get(t) or {}).get("kind")) == "decision" else 1):
            other = ix.by_stem.get(target)
            if linked >= BRIEF_LINKED or target in order or not other:
                continue
            for doc in other.get("docs") or []:
                if linked >= BRIEF_LINKED or not doc["fact_id"] or (target, doc["fact_id"]) in seen:
                    continue
                if _s(other.get("kind")) == "decision" or (_DAY_RE.search(doc["text"]) and _DECIDED_RE.search(doc["text"])):
                    seen.add((target, doc["fact_id"]))
                    linked += 1
                    rows.append({
                        "line": f"Related: [[{target}|{other['title']}]] — {doc['text']} (f:{doc['fact_id']}, {doc['since']}){_hedge(doc, today)}",
                        "fact": {"page": target, "id": doc["fact_id"], "text": doc["text"], "since": doc["since"]},
                    })
    text = ""
    pages: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    for row in rows:
        grown = (text + "\n" + row["line"]) if text else row["line"]
        if max_chars and len(grown) > max_chars:
            break
        text = grown
        if row.get("page"):
            pages.append(row["page"])
        if row.get("fact"):
            facts.append(row["fact"])
    _log_query(root, question, len(hits), order[0] if order else "-")
    return {"text": text, "pages": pages, "facts": facts, "chars": len(text)}


# ------------------------------------------------------------------ open items


def open_items(
    query: str = "",
    page: Optional[str] = None,
    owner: Optional[str] = None,
    due_before: Optional[str] = None,
    limit: int = 10,
    root: Optional[Path] = None,
    include_done: bool = False,
) -> list[dict[str, Any]]:
    """The commitments of one page, of the pages the query finds, or of every
    page. ``wiki.commitments`` does the reading and the owner / due filters;
    at most ``OPEN_ITEMS_MAX`` items come back."""
    root = root or store.vault_root()
    if _s(page).strip() or not _s(query).strip():
        return wiki.commitments(root, owner, due_before, page, include_done, OPEN_ITEMS_MAX)
    stems = {h["page"] for h in search(query, limit=max(4, int(limit or 10)), root=root)}
    return [r for r in wiki.commitments(root, owner, due_before, None, include_done, OPEN_ITEMS_MAX) if r["stem"] in stems]


# ------------------------------------------------------------------ the query log


def _log_query(root: Path, query: str, hits: int, top: str) -> None:
    p = root / QUERY_LOG
    line = "\t".join([store.now_iso(), " ".join(_s(query).split()) or "-", str(hits), top or "-"])
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")
        if p.stat().st_size > QUERY_LOG_MAX * 20:  # only a long file is worth counting
            lines = [l for l in p.read_text(encoding="utf-8").split("\n") if l.strip()]
            if len(lines) > QUERY_LOG_MAX:
                p.write_text("\n".join(lines[-QUERY_LOG_KEEP:]) + "\n", encoding="utf-8", newline="\n")
    except OSError:  # a log that cannot be written is not an error
        pass


def read_query_log(root: Path) -> list[tuple[str, str, int, str]]:
    """The query log as (when, query, hits, top page) rows."""
    p = root / QUERY_LOG
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").split("\n"):
        parts = line.split("\t")
        if len(parts) == 4:
            out.append((parts[0], parts[1], int(parts[2]) if parts[2].isdigit() else 0, parts[3]))
    return out


def _norm_query(query: str) -> str:
    """Two askings of the same question in other words count as one: lower case,
    one space between words, no question mark or full stop at the end."""
    return " ".join(_s(query).lower().split()).rstrip("?!. ")


def unanswered(root: Path, days: int = UNANSWERED_DAYS, today: Optional[str] = None,
               min_times: int = UNANSWERED_MIN) -> list[dict[str, Any]]:
    """The questions the wiki could not answer: asked in the last ``days``,
    no hit at all, and asked at least ``min_times`` times. Most asked first,
    as ``[{query, times, last}]`` with the newest wording of the question."""
    rows = read_query_log(root)
    if not rows:
        return []
    day = _s(today)[:10] or _today()
    floor = (date.fromisoformat(day) - timedelta(days=max(0, int(days or 0)))).isoformat()
    groups: dict[str, dict[str, Any]] = {}
    for when, query, hits, _top in rows:
        key = _norm_query(query)
        if hits or not key or key == "-" or when[:10] < floor:  # "-" is a call with no question
            continue
        g = groups.setdefault(key, {"query": query, "times": 0, "last": when[:10]})
        g["times"] += 1
        if when[:10] >= g["last"]:  # the wording the user used last is the one shown
            g["last"] = when[:10]
            g["query"] = " ".join(_s(query).split())
    out = [g for g in groups.values() if g["times"] >= max(1, int(min_times or 1))]
    out.sort(key=lambda g: (-g["times"], g["query"]))
    return out


# ------------------------------------------------------------------ the tool

_brief = brief
_open_items = open_items


def search_tool(
    query: str,
    kinds: Optional[list[str]] = None,
    limit: int = 10,
    since: Optional[str] = None,
    include_superseded: bool = False,
    brief: bool = False,
    max_chars: int = 1500,
    open_items: bool = False,
    owner: Optional[str] = None,
    due_before: Optional[str] = None,
    page: Optional[str] = None,
    include_done: bool = False,
) -> Any:
    """What ``vault_wiki_search`` answers: ranked facts, one stitched brief, or
    the open items of the pages that match.

    A search writes no page: pages the user changed by hand are counted, not
    read in. When there are any, the list answers come back as
    ``{hits, hand_edits}`` and the brief gains a ``hand_edits`` key, so the
    model can say so in one line; the next writing call takes them over."""
    from soma_vault import wiki_reconcile  # imported here: that module reads this one

    root = store.vault_root()
    hand = wiki_reconcile.detect(root)
    if open_items:
        items = _open_items(query, page, owner, due_before, limit, root, include_done)
        return {"hits": items, "hand_edits": hand} if hand else items
    if brief:
        out = _brief(query, max_chars, root)
        if hand:
            out["hand_edits"] = hand
        return out
    hits = search(query, kinds, limit if not _s(page).strip() else max(int(limit or 10), 50),
                  since, include_superseded, root)
    if _s(page).strip():
        stem = _stem(wiki.page_path(_s(page)))
        hits = [h for h in hits if h["page"] == stem][: max(1, int(limit or 10))]
    return {"hits": hits, "hand_edits": hand} if hand else hits


__all__ = [
    "SCHEMA_VERSION", "SEARCH_CACHE", "QUERY_LOG", "Index", "tokenize", "literals", "regex_of", "expand",
    "search", "brief", "open_items", "page_candidates", "unanswered", "search_tool", "read_query_log",
]
