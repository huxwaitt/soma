"""v0.5 helpers: the parts of the soma workflows that only move,
compare or format data, done in code so the model never reads them.

Every function takes the JSON the model already got from the outlook tools
(or nothing) and reads / writes the vault through ``store``. Nothing here
imports Outlook code; the vault server runs without Outlook.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from soma_vault import frontmatter as fmt
from soma_vault import notes, store, wiki
from soma_vault.notes import ADMIN_DIR, NoteError
from soma_vault.store import VaultError, read_text, rel, resolve, write_text

CREATED_BY = "soma/0.4.1"
RULES_PATH = f"{ADMIN_DIR}/Rules.md"
FOLLOWUPS_PATH = f"{ADMIN_DIR}/Follow-ups.md"
CACHE_DIR = f"{ADMIN_DIR}/Attachments/_cache"
COLLECT_PATH = f"{wiki.CACHE_DIR}/collect.json"
COLLECT_SOURCES = ("teams", "outlook", "notes")
COLLECT_ASK_HOURS = 24
COLLECT_DEFAULT_FOLDERS = ("Meetings", "Emails", "Daily", "Weekly")  # under Soma/
COLLECT_NEVER_READ = ("Wiki", "Attachments", "_views", "_backup")  # under Soma/
TOKENS_PATH = f"{wiki.CACHE_DIR}/tokens.json"
TOKEN_COMMANDS = ("collect-information", "load-history")
TOKEN_RUNS = 20  # the runs kept per command; older ones fall off the front

LABELS = ("act", "reply", "waiting", "fyi", "noise")
DAILY_HEADER = ["#", "Label", "From", "Subject", "Received", "Why", "Note"]
CALENDAR_HEADER = ["Start", "End", "Subject", "Location", "Organizer"]
TRANSCRIPT_MAX_LINES = 400
DOCUMENT_CHARS = 40000  # more text than this goes to Attachments/<slug>/text.md
DOCUMENT_SECTION_CHARS = 300  # what the record keeps of each part when it does

_COMMENT_RE = re.compile(r"<!--\s*([A-Za-z_]+):\s*(.*?)\s*-->")
_ENTRY_RE = re.compile(r"<!--\s*entry_id:\s*(.*?)\s*-->")
_OCC_RE = re.compile(r"<!--\s*occurrence_key:\s*(.*?)\s*-->")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_UNCHECKED_RE = re.compile(r"^\s*- \[ \] ")
_CHECKED_RE = re.compile(r"^\s*- \[x\] (.*)$", re.IGNORECASE)
_EMAIL_LINE_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) — \[\[Emails/")
_CHAT_ID_RE = re.compile(r"<!--\s*id:\s*(.*?)\s*-->")
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
# skills/meetings/references/transcript.md, step 1
_TURN_RE = re.compile(r"^\[?\d{0,2}:?\d{0,2}\]?\s*([A-Z][^:]{1,40}): ")
_TURN_NUMBERED_RE = re.compile(r"^\d{1,3}[.)]\s+([A-Z][^:]{1,40}): ")
_SCAFFOLD_RE = re.compile(r"^(PART \d+ of \d+|continue( from the last turn you gave)?|END OF TRANSCRIPT)\s*$", re.IGNORECASE)


# ------------------------------------------------------------------ small helpers


def _s(v: Any) -> str:
    return "" if v is None else str(v)


def _date_of(value: Any) -> str:
    s = _s(value).strip()
    return s[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", s) else ""


def _hhmm(value: Any) -> str:
    m = re.match(r"^\d{4}-\d{2}-\d{2}[T ](\d{2}:\d{2})", _s(value).strip())
    return m.group(1) if m else _s(value)


def _parse_dt(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(_s(value).strip())
    except ValueError:
        return None


def _parse_date(value: Any, what: str) -> date:
    d = _date_of(value)
    if not d:
        raise VaultError(f"'{what}' must be an ISO date, got {value!r}.")
    return date.fromisoformat(d)


def _received_cell(received: Any, note_date: str) -> str:
    d = _date_of(received)
    return _hhmm(received) if d == note_date else f"{d} {_hhmm(received)}".strip()


def _stem(path: str) -> str:
    """``Soma/Emails/x.md`` -> ``Emails/x`` (the wikilink target)."""
    p = path[len(ADMIN_DIR) + 1 :] if path.startswith(ADMIN_DIR + "/") else path
    return p[:-3] if p.endswith(".md") else p


def _link(path: str) -> str:
    return f"[[{_stem(path)}]]"


def _short(text: Any, n: int) -> str:
    s = " ".join(_s(text).split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _sections(body: str) -> list[tuple[int, str, int, int]]:
    """(level, heading, first line index after the heading, end index) per heading."""
    lines = body.split("\n")
    heads = [(i, len(m.group(1)), m.group(2)) for i, line in enumerate(lines) if (m := _HEADING_RE.match(line))]
    out = []
    for n, (i, level, text) in enumerate(heads):
        end = len(lines)
        for j, lvl, _t in heads[n + 1 :]:
            if lvl <= level:
                end = j
                break
        out.append((level, text, i + 1, end))
    return out


def _tables(lines: list[str], lo: int, hi: int) -> list[list[dict[str, str]]]:
    """Every markdown table inside lines[lo:hi] as a list of row dicts (header -> cell)."""
    tables: list[list[dict[str, str]]] = []
    i = lo
    while i < hi:
        if lines[i].lstrip().startswith("|"):
            block = []
            while i < hi and lines[i].lstrip().startswith("|"):
                block.append(lines[i])
                i += 1
            if len(block) >= 2:
                header = store._cells(block[0])
                rows = []
                for line in block[2:]:
                    cells = store._cells(line)
                    rows.append({header[k]: (cells[k] if k < len(cells) else "") for k in range(len(header))})
                    rows[-1]["_line"] = line
                tables.append(rows)
        else:
            i += 1
    return tables


def _strip_comment(text: str) -> str:
    return _COMMENT_RE.sub("", text).strip()


def _wikilink_targets(text: str) -> list[str]:
    return [m.group(1).strip() for m in _WIKILINK_RE.finditer(text)]


def _people(root: Path) -> list[tuple[str, dict[str, Any]]]:
    return [(rel(root, p), fm) for p, fm in store._iter_notes(root, "person")]


def _person_for(people: list[tuple[str, dict[str, Any]]], address: str) -> Optional[tuple[str, dict[str, Any]]]:
    wanted = _s(address).strip().lower()
    if not wanted:
        return None
    for path, fm in people:
        if notes.matches("person", fm, {"email": wanted}):
            return path, fm
    return None


def _recipient_list(mail: dict[str, Any], kind: str) -> list[dict[str, str]]:
    recips = mail.get("recipients") or []
    out = [
        {"name": _s(r.get("name")), "address": _s(r.get("address"))}
        for r in recips
        if isinstance(r, dict) and _s(r.get("type")).lower() == kind
    ]
    if not out and not recips:
        raw = _s(mail.get(kind)).strip()
        out = [{"name": part.strip(), "address": ""} for part in raw.split(";") if part.strip()]
    return out


def _iso_week(week: str) -> tuple[date, date]:
    m = re.match(r"^(\d{4})-W(\d{2})$", _s(week).strip())
    if not m:
        raise VaultError(f"week must look like 2026-W34, got {week!r}.")
    start = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    return start, start + timedelta(days=6)


def _week_of(d: date) -> tuple[date, date]:
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


# ------------------------------------------------------------------ Rules.md


def rules_template(created_by: str = CREATED_BY) -> str:
    fm = fmt.format_frontmatter({"type": "rules", "source": "soma", "created_by": created_by})
    return fm + (
        "\n# Rules\n\n"
        "Rules the inbox applies before the model reads a mail. Edit the tables; the plugin only reads this file.\n"
        "`Field` is `from` (the sender's address), `domain` (the part after `@`), `name` (the sender's display name) "
        "or `subject`. `Match` is a case-insensitive part of the value, or a pattern with `*` / `?`.\n\n"
        "## Labels\n\n"
        "Label a mail without reading it. Labels: act, reply, waiting, fyi, noise.\n\n"
        "| Match | Field | Label |\n| --- | --- | --- |\n\n"
        "## Never save\n\n"
        "Mail that never goes into a daily note (left out before labelling). The same rows also keep it "
        "out of `/soma:collect-information` and `/soma:load-history`.\n\n"
        "| Match | Field |\n| --- | --- |\n\n"
        "## Fyi senders\n\n"
        "One address or domain per line; mail from these is always `fyi`.\n\n"
    )


def _ensure_rules(root: Path, created_by: str = CREATED_BY) -> Path:
    p = resolve(root, RULES_PATH)
    if not p.is_file():
        write_text(p, rules_template(created_by))
    return p


def rules_get() -> dict[str, Any]:
    root = store.vault_root()
    p = _ensure_rules(root)
    _fm, _block, body = fmt.split_note(read_text(p))
    lines = body.split("\n")
    labels: list[dict[str, str]] = []
    never: list[dict[str, str]] = []
    fyi: list[str] = []
    for _level, heading, lo, hi in _sections(body):
        h = heading.strip().lower()
        if h == "labels":
            for table in _tables(lines, lo, hi):
                for row in table:
                    if row.get("Match") and row.get("Label"):
                        labels.append({"match": row["Match"], "field": row.get("Field", "from").lower() or "from", "label": row["Label"].lower()})
        elif h == "never save":
            for table in _tables(lines, lo, hi):
                for row in table:
                    if row.get("Match"):
                        never.append({"match": row["Match"], "field": row.get("Field", "from").lower() or "from"})
        elif h == "fyi senders":
            for line in lines[lo:hi]:
                s = line.strip()
                if s.startswith(("- ", "* ")):
                    v = s[2:].strip().strip("`")
                    if v:
                        fyi.append(v)
    return {"path": rel(root, p), "labels": labels, "never_save": never, "fyi_senders": fyi}


def _field_value(item: dict[str, Any], field: str) -> str:
    addr = _s(item.get("from_address")).strip()
    if field == "from":
        return addr
    if field == "domain":
        return addr.rsplit("@", 1)[-1] if "@" in addr else ""
    if field == "name":
        return _s(item.get("from_name") or item.get("from"))
    if field == "subject":
        return _s(item.get("subject"))
    return ""


def _hit(match: str, value: str) -> bool:
    m, v = match.strip().lower(), value.strip().lower()
    if not m or not v:
        return False
    if any(ch in m for ch in "*?"):
        return fnmatch.fnmatchcase(v, m)
    return m in v


def _builtin(item: dict[str, Any], people: list[tuple[str, dict[str, Any]]]) -> tuple[Optional[str], Optional[str]]:
    headers = item.get("headers") or {}
    if not isinstance(headers, dict):
        headers = {}
    subject = _s(item.get("subject")).strip()
    subject_l = subject.lower()
    mclass = _s(item.get("message_class"))
    addr = _s(item.get("from_address")).strip().lower()
    local = addr.split("@", 1)[0]
    if headers.get("list_unsubscribe"):
        return "fyi", "built-in: List-Unsubscribe header"
    if headers.get("auto_submitted") and _s(headers.get("auto_submitted")).lower() != "no":
        return "noise", "built-in: Auto-Submitted header"
    if subject_l.startswith(("automatic reply", "automatische antwort", "autoreply", "auto-reply", "out of office")):
        return "noise", "built-in: automatic reply"
    if mclass.startswith("IPM.Schedule.Meeting.Resp") or subject_l.startswith(("accepted:", "tentative:", "declined:", "zusage:", "absage:")):
        return "noise", "built-in: meeting response"
    if local.replace("-", "").replace("_", "").replace(".", "") in ("noreply", "donotreply", "dontreply") or local.startswith(("noreply", "no-reply", "donotreply", "do-not-reply")):
        return "fyi", "built-in: no-reply sender"
    hit = _person_for(people, addr)
    if hit and _s(hit[1].get("status")).lower() == "fyi":
        return "fyi", f"built-in: person note {_link(hit[0])} has status fyi"
    return None, None


def rules_match(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Label the items, and split them into the ones worth reading and the rest.

    ``kept`` is what a person wrote and no rule sends away; ``dropped`` says
    why each of the others went, so a command can report a count without the
    model reading a single preview. ``bulk`` comes from the mail listing
    (outlook_list_mails with ``bulk`` in ``fields``); an item without the key
    is treated as not bulk. Nothing is written.
    """
    root = store.vault_root()
    rules = rules_get()
    people = _people(root)
    results = []
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    counts = {"bulk": 0, "never_save": 0, "kept": 0}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        label, rule = _builtin(item, people)
        never = False
        never_rule = ""
        for r in rules["never_save"]:
            if _hit(r["match"], _field_value(item, r["field"])):
                never = True
                never_rule = f"Never save: {r['match']} ({r['field']})"
                rule = rule or never_rule
                break
        if label is None:
            addr = _s(item.get("from_address")).strip().lower()
            domain = addr.rsplit("@", 1)[-1] if "@" in addr else ""
            for s in rules["fyi_senders"]:
                sl = s.lower()
                if sl == addr or sl == domain or (sl.startswith("@") and sl[1:] == domain):
                    label, rule = "fyi", f"Fyi senders: {s}"
                    break
        if label is None:
            for r in rules["labels"]:
                if r["label"] in LABELS and _hit(r["match"], _field_value(item, r["field"])):
                    label, rule = r["label"], f"Labels: {r['match']} ({r['field']}) → {r['label']}"
                    break
        entry_id = _s(item.get("entry_id"))
        if item.get("bulk"):
            dropped.append({"entry_id": entry_id, "why": f"bulk: {_s(item.get('bulk_why')) or 'automatic mail'}"})
            counts["bulk"] += 1
        elif never:
            dropped.append({"entry_id": entry_id, "why": f"rule: {never_rule}"})
            counts["never_save"] += 1
        else:
            kept.append(item)
        results.append({"entry_id": entry_id, "label": label, "never_save": never, "rule": rule})
    counts["kept"] = len(kept)
    return {"results": results, "kept": kept, "dropped": dropped, "counts": counts, "rules_path": rules["path"]}


# ------------------------------------------------------------------ inbox prepare / write daily


def _daily_notes_in(root: Path, start: date, end: date) -> list[tuple[str, dict[str, Any], str]]:
    out = []
    for p, fm in store._iter_notes(root, "daily"):
        d = _date_of(fm.get("date"))
        if d and start.isoformat() <= d <= end.isoformat():
            out.append((rel(root, p), fm, fmt.split_note(read_text(p))[2]))
    return out


def _entry_ids_in(text: str) -> set[str]:
    return {store._unescape_cell(m.group(1)) for m in _ENTRY_RE.finditer(text)}


def _cache_path(root: Path, day: str) -> Path:
    return resolve(root, f"{CACHE_DIR}/inbox-{day}.json")


def inbox_prepare(items: list[dict[str, Any]], date_str: str) -> dict[str, Any]:
    root = store.vault_root()
    day = _parse_date(date_str, "date")
    week_start, week_end = _week_of(day)
    seen: set[str] = set()
    for _path, _fm, body in _daily_notes_in(root, week_start, week_end):
        seen |= _entry_ids_in(body)
    matched = {r["entry_id"]: r for r in rules_match(items)["results"]}
    to_label: list[dict[str, Any]] = []
    already: list[str] = []
    never: list[str] = []
    labelled = 0
    done: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        eid = _s(item.get("entry_id"))
        if not eid or eid in done:
            continue
        done.add(eid)
        if eid in seen:
            already.append(eid)
            continue
        r = matched.get(eid) or {"label": None, "never_save": False, "rule": None}
        if r["never_save"]:
            never.append(eid)
            continue
        slim = {
            "entry_id": eid,
            "internet_message_id": _s(item.get("internet_message_id")),
            "from_address": _s(item.get("from_address")),
            "from_name": _s(item.get("from_name") or item.get("from")),
            "subject": _s(item.get("subject")),
            "received": _s(item.get("received")),
            "label": r["label"],
            "rule": r["rule"],
        }
        if r["label"]:
            labelled += 1
        else:
            slim["preview"] = _short(item.get("preview"), 120)
        to_label.append(slim)
    cache = _cache_path(root, day.isoformat())
    write_text(cache, json.dumps({"date": day.isoformat(), "items": to_label}, ensure_ascii=False, indent=1))
    return {
        "to_label": to_label,
        "already_seen": already,
        "never_save": never,
        "labelled_by_rule": labelled,
        "cache": rel(root, cache),
    }


def _email_note_for(root: Path, imid: str, eid: str) -> Optional[tuple[str, dict[str, Any]]]:
    ident = {"internet_message_id": imid, "entry_id": eid}
    if not (imid or eid):
        return None
    for p, fm in store._iter_notes(root, "email"):
        if notes.matches("email", fm, ident):
            return rel(root, p), fm
    return None


def _daily_rows(root: Path, items: list[dict[str, Any]], labels_by_id: dict[str, dict[str, Any]], note_date: str, start_no: int) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        eid = _s(item.get("entry_id"))
        lab = labels_by_id.get(eid) or {}
        label = _s(lab.get("label") or item.get("label")).lower()
        if label not in LABELS:
            continue
        reason = _s(lab.get("reason")) or _s(item.get("rule")) or ""
        hit = _email_note_for(root, _s(item.get("internet_message_id")), eid)
        rows.append(
            {
                "entry_id": eid,
                "label": label,
                "from": _s(item.get("from_name") or item.get("from") or item.get("from_address")),
                "subject": _s(item.get("subject")),
                "received": _s(item.get("received")),
                "why": _short(reason, 80),
                "note_path": hit[0] if hit else None,
            }
        )
    order = {lab: n for n, lab in enumerate(LABELS)}
    # newest first, then by label order (both sorts are stable)
    rows.sort(key=lambda r: notes.sort_value("email", {"received": r["received"]}), reverse=True)
    rows.sort(key=lambda r: order[r["label"]])
    for n, r in enumerate(rows, start_no):
        r["no"] = n
        r["received_cell"] = _received_cell(r["received"], note_date)
        r["note_cell"] = ((_link(r["note_path"]) + " ") if r["note_path"] else "") + f"<!-- entry_id: {r['entry_id']} -->"
    return rows


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    out = [store._row_line(header), "| " + " | ".join("---" for _ in header) + " |"]
    out += [store._row_line(r) for r in rows]
    return out


def _calendar_rows(events: list[dict[str, Any]], existing_keys: set[str]) -> tuple[list[list[str]], list[dict[str, Any]]]:
    rows, kept = [], []
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        key = _s(ev.get("occurrence_key")) or (_s(ev.get("global_id")) + "|" + _s(ev.get("start")))
        if key in existing_keys:
            continue
        existing_keys.add(key)
        all_day = bool(ev.get("all_day"))
        organizer = _s(ev.get("organizer") or ev.get("organizer_address"))
        rows.append(
            [
                "all day" if all_day else _hhmm(ev.get("start")),
                "all day" if all_day else _hhmm(ev.get("end")),
                _s(ev.get("subject")),
                _s(ev.get("location")),
                (organizer + f" <!-- occurrence_key: {key} -->").strip(),
            ]
        )
        kept.append(dict(ev, occurrence_key=key))
    return rows, kept


def _clashes(events: list[dict[str, Any]]) -> list[str]:
    timed = []
    for ev in events:
        if ev.get("all_day"):
            continue
        a, b = _parse_dt(ev.get("start")), _parse_dt(ev.get("end"))
        if a and b:
            timed.append((a, b, ev))
    out = []
    for i in range(len(timed)):
        for j in range(i + 1, len(timed)):
            a1, b1, e1 = timed[i]
            a2, b2, e2 = timed[j]
            if a1 < b2 and a2 < b1:
                out.append(
                    f"Clash: {_s(e1.get('subject'))} ({_hhmm(e1.get('start'))}–{_hhmm(e1.get('end'))}) overlaps "
                    f"{_s(e2.get('subject'))} ({_hhmm(e2.get('start'))}–{_hhmm(e2.get('end'))})"
                )
    return out


def _no_prep(root: Path, events: list[dict[str, Any]]) -> list[str]:
    out = []
    for ev in events:
        if ev.get("all_day"):
            continue
        ident = {"occurrence_key": _s(ev.get("occurrence_key")), "global_id": ""}
        found = any(notes.matches("meeting", fm, ident) for _p, fm in store._iter_notes(root, "meeting"))
        if not found:
            out.append(f"No prep note: {_s(ev.get('subject'))}")
    return out


def _open_commitment(
    root: Path,
    people: list[tuple[str, dict[str, Any]]],
    since: str,
    who_name: str,
    who_addr: str,
    what: str,
    record_path: Optional[str],
    src: str,
    owner_link: Optional[str] = None,
    due: Optional[str] = None,
) -> bool:
    """A thread the user is waiting on becomes an open item on the counterpart's
    person page (a draft page is created when there is none). The owner says who
    owes it; the record is added to that page's Records. True when it was written."""
    hit = _person_for(people, who_addr)
    path = hit[0] if hit else None
    if path is None:
        name = _s(who_name).strip() or _s(who_addr).strip()
        if not name:
            return False
        try:
            if record_path:
                res = wiki.record_person(
                    name=name, email=_s(who_addr).strip(), aliases=[], last_contact=since, company=None,
                    record_path=record_path, record_date=since, summary=_short(what, 120), created_by=CREATED_BY,
                )
            else:
                res = wiki.create("person", name, extra={"email": _s(who_addr).strip()}, created_by=CREATED_BY)
        except (VaultError, NoteError):
            return False
        path = _s(res.get("path"))
        if not path:
            return False
    rec = None
    if record_path:
        try:
            rec = wiki._record_info(root, record_path)
        except VaultError:
            rec = None
    op: dict[str, Any] = {
        "op": "open", "text": _short(notes.strip_prefixes(what), 80),
        "owner": owner_link or f"[[{wiki._stem(path)}]]", "since": since, "src": src or "user",
    }
    if due:
        op["due"] = due
    with wiki._wiki_lock(root):
        ctx = wiki._Ctx(root=root, src=src or "user", since=since or wiki._today(), record=rec)
        res = wiki._write_ops(root, path, [op], ctx, "apply")
        wiki._write_index(root, ctx.touched)
    return bool(res.get("written") and res.get("applied"))


def write_daily(
    date_str: str,
    labels: list[dict[str, Any]],
    items: Optional[list[dict[str, Any]]] = None,
    events: Optional[list[dict[str, Any]]] = None,
    watch_out: Optional[list[str]] = None,
    since: str = "",
    inbox_checked: str = "",
    tokens_used: Optional[int] = None,
    folder: str = "inbox",
    created_by: str = CREATED_BY,
) -> dict[str, Any]:
    root = store.vault_root()
    day = _parse_date(date_str, "date").isoformat()
    if items is None:
        cache = _cache_path(root, day)
        if not cache.is_file():
            raise VaultError(f"No items given and no cached list for {day}; run vault_inbox_prepare first or pass items.")
        items = json.loads(read_text(cache)).get("items") or []
    labels_by_id = {_s(l.get("entry_id")): l for l in (labels or []) if isinstance(l, dict)}
    inbox_checked = inbox_checked or store.now_iso()
    since = since or ""
    events = [e for e in (events or []) if isinstance(e, dict)]
    people = _people(root)

    hit = store.find("daily", {"date": day})
    existing_text = read_text(resolve(root, hit["path"])) if hit["found"] else ""
    seen = _entry_ids_in(existing_text)
    existing_keys = {store._unescape_cell(m.group(1)) for m in _OCC_RE.finditer(existing_text)}
    start_no = 1
    if existing_text:
        nums = [int(c[0]) for line in existing_text.split("\n") if line.startswith("|") and (c := store._cells(line)) and c[0].isdigit()]
        start_no = (max(nums) + 1) if nums else 1

    fresh, dups = [], 0
    done: set[str] = set()
    for it in items:
        eid = _s(it.get("entry_id")) if isinstance(it, dict) else ""
        if not eid or eid in done:
            continue
        done.add(eid)
        if eid in seen:
            dups += 1
        else:
            fresh.append(it)
    rows = _daily_rows(root, fresh, labels_by_id, day, start_no)
    unlabelled = [_s(i.get("entry_id")) for i in fresh if _s(i.get("entry_id")) not in {r["entry_id"] for r in rows}]

    cal_rows, new_events = _calendar_rows(events, existing_keys)
    watch = list(dict.fromkeys([w for w in (watch_out or []) if _s(w).strip()] + _clashes(events) + _no_prep(root, events)))
    if existing_text:
        watch = [w for w in watch if ("- " + w) not in existing_text]

    if hit["found"] and not rows and not cal_rows and not watch:
        return {"path": hit["path"], "action": "unchanged", "rows_written": 0, "duplicates_skipped": dups, "followups_added": 0, "promised": 0, "unlabelled": unlabelled}

    h = "###" if hit["found"] else "##"
    heading =f"{h} Inbox (since {since})" if folder.lower() == "inbox" else f"{h} Inbox ({folder}, since {since})"
    body: list[str] = []
    if not hit["found"]:
        body += [f"# {day}", ""]
    if rows or not hit["found"]:
        body += [heading, ""]
        body += _table(DAILY_HEADER, [[str(r["no"]), r["label"], r["from"], r["subject"], r["received_cell"], r["why"], r["note_cell"]] for r in rows])
        body += ["", "Labels: **act** (do something), **reply** (answer), **waiting** (they owe me), **fyi** (read), **noise** (ignore).", ""]
    todo = [r for r in rows if r["label"] in ("act", "reply")]
    waiting = [r for r in rows if r["label"] == "waiting"]
    if todo or not hit["found"]:
        body += [f"{h} To do", ""]
        body += [f"- [ ] {r['label']} — {r['subject']} ({r['from']})" + (f" — {_link(r['note_path'])}" if r["note_path"] else "") for r in todo] or ["- none"]
        body.append("")
    followups_added = 0
    if waiting or not hit["found"]:
        body += [f"{h} Waiting on", ""]
        body += [f"- {r['from']} — {r['subject']} (since {_date_of(r['received'])}) → open item on their page" for r in waiting] or ["- none"]
        body.append("")
        by_id = {_s(i.get("entry_id")): i for i in fresh if isinstance(i, dict)}
        for r in waiting:
            it = by_id.get(r["entry_id"], {})
            src = _s(it.get("internet_message_id")) or _s(r["entry_id"])
            if _open_commitment(root, people, _date_of(r["received"]), r["from"], _s(it.get("from_address")), r["subject"], r["note_path"], src):
                followups_added += 1
                people = _people(root)  # a new person page may have been written
    promised: list[dict[str, Any]] = []
    if not hit["found"]:  # once a day: what the user promised and owes within the week
        promised = wiki.commitments(root, owner="me", due_before=(_parse_date(day, "date") + timedelta(days=8)).isoformat())
        body += [f"{h} Promised", ""]
        body += [f"- {c['text']} — due {c['due']} — [[{c['stem']}]]" for c in promised] or ["- none"]
        body.append("")
    if cal_rows:
        body += [f"{h} Calendar", ""] + _table(CALENDAR_HEADER, cal_rows) + [""]
    if watch or (events and not hit["found"]):
        body += [f"{h} Watch out", ""] + ([f"- {w}" for w in watch] or ["- nothing"]) + [""]
    text = "\n".join(body).rstrip("\n")

    fm = {
        "type": "daily",
        "source": "outlook",
        "date": day,
        "folder": folder,
        "since": since,
        "inbox_checked": inbox_checked,
        "mails_seen": len(rows),
        "status": "todo",
        "created_by": created_by,
    }
    if tokens_used is not None:
        fm["tokens_used"] = int(tokens_used)
    if hit["found"]:
        fm = dict(hit["frontmatter"], inbox_checked=inbox_checked)
        res = store.write("daily", fm, text, "append")
    else:
        res = store.write("daily", fm, text, "create")
    return {
        "path": res["path"],
        "action": res["action"],
        "rows_written": len(rows),
        "duplicates_skipped": dups,
        "followups_added": followups_added,
        "promised": len(promised),
        "calendar_rows": len(cal_rows),
        "unlabelled": unlabelled,
    }


# ------------------------------------------------------------------ save email


def _vault_link(root: Path, path_or_rel: str) -> Optional[str]:
    """A wikilink for an exported file, given an absolute path or a vault-relative one."""
    s = _s(path_or_rel).strip().replace("\\", "/")
    if not s:
        return None
    p = Path(s)
    if p.is_absolute():
        try:
            s = p.resolve().relative_to(root.resolve()).as_posix()
        except (ValueError, OSError):
            return None
    s = s.lstrip("/")
    if not s.startswith(ADMIN_DIR + "/"):
        return None
    name = s.rsplit("/", 1)[-1]
    target = s[:-3] if s.endswith(".md") else s
    return f"[[{target}|{name}]]"


def _thread_content(thread: Optional[list[dict[str, Any]]], body_text: str) -> str:
    """The '## Content' text of an email record.

    One mail keeps its body as it is. A thread becomes one
    '### m<n> — <date> <from>' section per mail, oldest first: from the
    ``thread`` items when they were given, else from the '###' headings the
    caller already wrote into the body."""
    mails = [m for m in (thread or []) if isinstance(m, dict)]
    if mails:
        out: list[str] = []
        for n, m in enumerate(sorted(mails, key=lambda m: _s(m.get("received") or m.get("date"))), 1):
            when = _s(m.get("received") or m.get("date"))
            day = f"{_date_of(when)} {_hhmm(when)}".strip() if when else ""
            who = _s(m.get("from") or m.get("from_address")).strip()
            text = _s(m.get("body_trimmed") if m.get("body_trimmed") else m.get("body")).replace("\r\n", "\n").strip("\n")
            out += [f"### m{n} — {' '.join(x for x in (day, who) if x)}".rstrip(" —"), "", text, ""]
        return "\n".join(out).strip("\n")
    lines = body_text.split("\n")
    # two or more '###' headings are a thread the caller wrote out; one is just text
    if sum(1 for l in lines if (m := _HEADING_RE.match(l)) and len(m.group(1)) == 3) < 2:
        return body_text
    out, n = [], 0
    for line in lines:
        m = _HEADING_RE.match(line)
        if m and len(m.group(1)) == 3:
            n += 1
            rest = re.sub(r"^m\d+\s+—\s+", "", m.group(2).strip())
            out.append(f"### m{n} — {rest.replace(' — ', ' ')}")
        else:
            out.append(line)
    return "\n".join(out)


def _kb(size: Any) -> str:
    try:
        n = int(size)
    except (TypeError, ValueError):
        return ""
    return f"{max(1, round(n / 1024))} KB"


def save_email(
    mail: dict[str, Any],
    summary: str,
    action_items: Optional[list[str]] = None,
    attachments_saved: Optional[list[str]] = None,
    msg_file: Optional[str] = None,
    status: Optional[str] = None,
    self_addresses: Optional[list[str]] = None,
    company: Optional[str] = None,
    thread: Optional[list[dict[str, Any]]] = None,
    created_by: str = CREATED_BY,
) -> dict[str, Any]:
    if not isinstance(mail, dict) or not (_s(mail.get("entry_id")) or _s(mail.get("internet_message_id"))):
        raise NoteError("mail must be the JSON from outlook_get_mail with entry_id / internet_message_id.")
    root = store.vault_root()
    selves = {a.strip().lower() for a in (self_addresses or []) if a}
    from_addr = _s(mail.get("from_address")).strip()
    from_name = _s(mail.get("from")).strip() or from_addr.split("@", 1)[0]
    received = _s(mail.get("received"))
    to_list = _recipient_list(mail, "to")
    cc_list = _recipient_list(mail, "cc")
    action_items = [a for a in (action_items or []) if _s(a).strip()]
    from_self = from_addr.lower() in selves
    if status is None:
        status = "waiting" if (from_self and action_items) else ("todo" if action_items else "fyi")
    if status not in ("todo", "waiting", "done", "fyi"):
        raise NoteError(f"status must be todo, waiting, done or fyi, got {status!r}.")

    people = _people(root)
    person_hit = _person_for(people, from_addr)
    person_name = person_hit[1].get("name") if person_hit else from_name
    person_path = person_hit[0] if person_hit else f"{notes.folder_of('person')}/{notes.person_filename(from_name, from_addr)}.md"
    from_link = _link(person_path) if from_addr and not from_self else ""

    fm: dict[str, Any] = {
        "type": "email",
        "source": "outlook",
        "entry_id": _s(mail.get("entry_id")),
        "internet_message_id": _s(mail.get("internet_message_id")),
        "conversation_id": _s(mail.get("conversation_id")),
        "subject": _s(mail.get("subject")),
        "from": from_addr,
        "from_name": from_name,
        "from_link": from_link,
        "to": [r["address"] or r["name"] for r in to_list],
        "cc": [r["address"] or r["name"] for r in cc_list],
        "received": received,
        "status": status,
    }
    atts = [a for a in (mail.get("attachments") or []) if isinstance(a, dict)]
    saved_links = [l for l in (_vault_link(root, p) for p in (attachments_saved or [])) if l]
    msg_link = _vault_link(root, msg_file) if msg_file else None
    if atts:
        fm["has_attachments"] = True
    if saved_links:
        fm["attachments"] = saved_links
    if msg_link:
        fm["msg_file"] = msg_link
    fm["created_by"] = created_by

    existing = store.find("email", {"internet_message_id": fm["internet_message_id"], "entry_id": fm["entry_id"]})
    lines = [f"# {fm['subject']}", ""]
    if not existing["found"]:
        lines += [f"**From:** {(from_link + ' ') if from_link else ''}<{from_addr}>".replace(" <>", ""),
                  "**To:** " + ", ".join(f"{r['name']} <{r['address']}>" if r["address"] and r["name"] else (r["address"] or r["name"]) for r in to_list)]
        if cc_list:
            lines.append("**Cc:** " + ", ".join(f"{r['name']} <{r['address']}>" if r["address"] and r["name"] else (r["address"] or r["name"]) for r in cc_list))
        lines += [f"**Received:** {_date_of(received)} {_hhmm(received)}", ""]
    else:
        lines = ["Saved again via /soma:save.", ""]
    lines += ["## Summary" if not existing["found"] else "### Summary", "", _s(summary).strip() or "(no summary)", ""]
    lines += ["## Action items" if not existing["found"] else "### Action items", ""]
    lines += [a if a.lstrip().startswith("- ") else f"- [ ] {a.strip()}" for a in action_items] or ["- none"]
    lines.append("")
    if not existing["found"]:
        body_text = _s(mail.get("body_trimmed") if mail.get("body_trimmed") else mail.get("body")).replace("\r\n", "\n").strip("\n")
        lines += ["## Content", "", _thread_content(thread, body_text), ""]
    if atts or msg_link:
        lines += ["## Files" if not existing["found"] else "### Files", ""]
        if msg_link:
            lines.append(f"- {msg_link} (original message)")
        for a in atts:
            name = _s(a.get("filename"))
            link = next((l for l in saved_links if l.endswith(f"|{name}]]")), None)
            size = _kb(a.get("size_bytes"))
            if link:
                lines.append(f"- {link}" + (f" ({size})" if size else ""))
            elif a.get("inline") or a.get("is_inline"):
                lines.append(f"- {name}" + (f" ({size}, inline image, not exported)" if size else " (inline image, not exported)"))
            else:
                lines.append(f"- {name}" + (f" ({size}, not exported)" if size else " (not exported)"))
        lines.append("")
    body = "\n".join(lines).rstrip("\n")
    res = store.write("email", fm, body, "upsert")
    path = res["path"]

    person_action = None
    if from_addr and not from_self:
        # the person page lives in the wiki: a draft page on first sight, a Records line after that
        aliases = []
        if person_hit:
            if from_name and from_name.lower() != _s(person_hit[1].get("name")).lower():
                aliases.append(from_name)
            if from_addr.lower() != _s(person_hit[1].get("email")).lower():
                aliases.append(from_addr)
        pres = wiki.record_person(
            name=person_name or from_name,
            email=person_hit[1].get("email") if person_hit else from_addr,
            aliases=aliases,
            last_contact=received,
            company=company,
            record_path=path,
            record_date=_date_of(received),
            summary=_short(summary, 120),
            created_by=created_by,
            existing=person_hit[0] if person_hit else None,
        )
        person_path, person_action = pres["path"], pres["action"]
    else:
        person_path = None

    followup_added = False
    if status == "waiting":
        # the counterpart is the one who owes the answer: the first recipient of the user's own mail, else the sender
        if from_self and to_list:
            who_name, who_addr = to_list[0]["name"], to_list[0]["address"]
        else:
            who_name, who_addr = from_name, from_addr
        src = fm["internet_message_id"] or fm["entry_id"]
        followup_added = _open_commitment(root, _people(root), _date_of(received), who_name, who_addr, fm["subject"], path, src)
    return {"path": path, "action": res["action"], "status": status, "person_path": person_path, "person_action": person_action, "followup_added": followup_added}


# --------------------------------------------------------------- save document


def _document_file(root: Path, path: Any) -> Path:
    """The file to read, from an absolute path or a vault-relative one."""
    raw = _s(path).strip().strip('"')
    if not raw:
        raise VaultError("save needs the path of a file to read.")
    p = Path(raw.replace("\\", "/"))
    if not p.is_absolute():
        p = root / raw.replace("\\", "/").lstrip("/")
    if not p.is_file():
        raise VaultError(f"No such file: {raw}")
    return p


def _document_hash(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _document_by_path(root: Path, path_value: str) -> Optional[tuple[str, dict[str, Any]]]:
    """The document record made from this file before, whatever its hash is now."""
    wanted = _s(path_value).strip().replace("\\", "/").lower()
    for p, fm in store._iter_notes(root, "document"):
        if _s(fm.get("path")).strip().replace("\\", "/").lower() == wanted:
            return rel(root, p), fm
    return None


def _record_path(root: Path, record: Any) -> str:
    """A record named as a vault-relative path or a wikilink, as a path."""
    s = _s(record).strip()
    if not s:
        return ""
    if s.startswith("[["):
        s = f"{ADMIN_DIR}/{wiki._link_target(s)}.md"
    p = resolve(root, s)
    if not p.is_file():
        raise VaultError(f"No such record: {_s(record)!r}.")
    return rel(root, p)


def _document_sections(sections: list[dict[str, Any]], text_link: str) -> list[str]:
    """The '## Content' lines: whole sections, or their first characters plus a
    link to the text file when the document went over the cap."""
    out: list[str] = []
    for s in sections:
        out += [f"### {s['locator']} — {s['heading']}", ""]
        if text_link:
            head = s["text"][:DOCUMENT_SECTION_CHARS].rstrip()
            out += [head + (f"… (full text: {text_link})" if len(s["text"]) > len(head) else ""), ""]
        else:
            out += [s["text"], ""]
    return out


def save_document(
    path: str,
    summary: str = "",
    action_items: Optional[list[str]] = None,
    from_email: Optional[str] = None,
    created_by: str = CREATED_BY,
) -> dict[str, Any]:
    """Read a file into ``Soma/Documents/<date> <slug>.md``.

    The same file again (same hash) is left alone; the same path with new
    content gets an '## Update' with the parts that are there now. With
    ``from_email`` the two records link to each other."""
    from soma_vault import documents

    root = store.vault_root()
    p = _document_file(root, path)
    given = _s(path).strip().replace("\\", "/")
    digest = _document_hash(p)
    action_items = [a for a in (action_items or []) if _s(a).strip()]

    email_path = _record_path(root, from_email) if from_email else ""
    email_link = _link(email_path) if email_path else ""

    same = store.find("document", {"hash": digest})
    if same["found"]:
        fm = same["frontmatter"]
        # the file is the one already on file; a mail it came with is still worth linking
        linked = _link_mail(root, same["path"], email_path, p.name) if email_path else False
        return {
            "path": same["path"], "action": "unchanged", "record_id": _s(fm.get("record_id")) or digest,
            "format": _s(fm.get("format")), "parts": fm.get("parts"), "chars": fm.get("chars"),
            "empty": not fm.get("chars"), "text_file": _s(fm.get("text_file")) or None, "sections": [],
            "from_email": _link(email_path) if email_path else _s(fm.get("from_email")), "linked": linked,
        }

    ex = documents.extract(p)
    day = ""
    if email_path:
        hit = store.read(email_path)
        day = _date_of(hit["frontmatter"].get("received") or hit["frontmatter"].get("date"))
    if not day:
        day = datetime.fromtimestamp(p.stat().st_mtime).date().isoformat()

    title = notes.sanitize(p.stem) or p.name
    slug_name = notes.slug(p.stem)
    text_file, text_link = "", ""
    if ex["chars"] > DOCUMENT_CHARS:
        text_file = f"{ADMIN_DIR}/Attachments/{slug_name}/text.md"
        write_text(resolve(root, text_file), documents.full_text(ex) + "\n")
        text_link = _link(text_file)

    fm: dict[str, Any] = {
        "type": "document",
        "source": "file",
        "record_id": digest,
        "title": title,
        "date": day,
        "path": given,
        "hash": digest,
        "format": ex["format"],
        "parts": ex["parts"],
        "chars": ex["chars"],
        "from_email": email_link,
        "text_file": text_link,
        "created_by": created_by,
    }

    old = _document_by_path(root, given)
    lines: list[str] = []
    if old:
        lines += ["The file changed; the parts below replace the ones above.", ""]
    else:
        lines += [f"# {title}", "", f"**File:** `{given}`",
                  f"**Read:** {ex['format']}, {ex['parts']} part{'' if ex['parts'] == 1 else 's'}, {ex['chars']} characters"]
        if email_link:
            lines.append(f"**From mail:** {email_link}")
        lines.append("")
    head = "###" if old else "##"
    lines += [f"{head} Summary", "", _s(summary).strip() or "(no summary)", ""]
    lines += [f"{head} Action items", ""]
    lines += [a if a.lstrip().startswith("- ") else f"- [ ] {a.strip()}" for a in action_items] or ["- none"]
    lines += ["", f"{head} Content", ""]
    if ex["empty"]:
        lines += ["No text could be read (scanned?).", ""]
    else:
        lines += _document_sections(ex["sections"], text_link)
    if not old:
        lines += ["## Files", "", f"- `{given}` — the file this was read from"]
        if email_link:
            lines.append(f"- {email_link} — arrived as an attachment of this mail")
        lines.append("")
    body = "\n".join(lines).rstrip("\n")

    if old:
        # the record keeps the id it was born with, so facts already citing it still count as one source
        fm["record_id"] = _s(old[1].get("record_id")) or digest
        res = store._append(root, old[0], notes.with_core_keys("document", fm), body, {"hash": digest})
    else:
        res = store.write("document", fm, body, "create")
    doc_path = res["path"]

    linked = _link_mail(root, doc_path, email_path, p.name) if email_path else False

    return {
        "path": doc_path,
        "action": res["action"],
        "record_id": _s(fm["record_id"]),
        "format": ex["format"],
        "parts": ex["parts"],
        "chars": ex["chars"],
        "empty": ex["empty"],
        "text_file": text_file or None,
        "sections": [{"locator": s["locator"], "heading": s["heading"], "chars": s["chars"]} for s in ex["sections"]],
        "from_email": email_link,
        "linked": linked,
    }


def _link_mail(root: Path, doc_path: str, email_path: str, filename: str) -> bool:
    """Put each of the two records on the other's '## Files' list, through an Update."""
    doc_link, mail_link = _link(doc_path), _link(email_path)
    done = False
    if mail_link not in read_text(resolve(root, doc_path)):
        store._append(root, doc_path, {"from_email": mail_link},
                      f"### Files\n\n- {mail_link} — arrived as an attachment of this mail", {})
        done = True
    if doc_link not in read_text(resolve(root, email_path)):
        store._append(root, email_path, {},
                      f"### Files\n\n- {doc_link} — {filename}, read into the vault", {})
        done = True
    return done


# ------------------------------------------------------------------ prep context


def _unchecked(body: str) -> list[str]:
    out = []
    closed = False
    for line in body.split("\n"):
        m = _HEADING_RE.match(line)
        if m:
            closed = m.group(2).strip().lower() == "closed"
            continue
        if not closed and _UNCHECKED_RE.match(line):
            out.append(line.strip())
    return out


def _email_lines(body: str, limit: int = 3) -> list[str]:
    found = [line.strip() for line in body.split("\n") if _EMAIL_LINE_RE.match(line.strip())]
    found.sort(key=lambda l: l[2:12], reverse=True)
    return found[:limit]


def _mentions(item: dict[str, Any], names: set[str], addresses: set[str], paths: set[str]) -> bool:
    """Is this commitment about one of the people in the meeting? Either it sits
    on their page, or they own it."""
    if item["stem"].lower() in {p.lower() for p in paths}:
        return True
    owner = _s(item.get("owner"))
    targets = {t.lower() for t in _wikilink_targets(owner)}
    if targets & {p.lower() for p in paths}:
        return True
    plain = _s(item.get("owner_name")).strip().lower()
    return bool(plain) and plain != "me" and (plain in names or plain in addresses)


def prep_context(occurrence_key: str, global_id: str = "", attendees: Optional[list[Any]] = None, subject: str = "") -> dict[str, Any]:
    root = store.vault_root()
    occurrence_key = _s(occurrence_key).strip()
    global_id = _s(global_id).strip() or (occurrence_key.split("|", 1)[0] if "|" in occurrence_key else "")
    this_start = occurrence_key.split("|", 1)[1] if "|" in occurrence_key else ""
    existing = store.find("meeting", {"occurrence_key": occurrence_key, "global_id": ""}) if occurrence_key else {"found": False, "path": None}
    previous = None
    if global_id:
        cands = [(rel(root, p), fm) for p, fm in store._iter_notes(root, "meeting") if _s(fm.get("global_id")) == global_id]
        cands = [c for c in cands if c[0] != existing["path"] and (not this_start or notes.sort_value("meeting", c[1]) < notes.sort_value("meeting", {"start": this_start}))]
        cands.sort(key=lambda c: notes.sort_value("meeting", c[1]), reverse=True)
        if cands:
            path, fm = cands[0]
            body = fmt.split_note(read_text(resolve(root, path)))[2]
            previous = {"path": path, "date": _date_of(fm.get("start")), "open_actions": _unchecked(body)}

    people_all = _people(root)
    people_out = []
    names: set[str] = set()
    addresses: set[str] = set()
    paths: set[str] = set()
    for a in attendees or []:
        if isinstance(a, dict):
            addr, name = _s(a.get("address")).strip(), _s(a.get("name")).strip()
        else:
            addr, name = _s(a).strip(), ""
        if not addr and not name:
            continue
        addresses.add(addr.lower())
        if name:
            names.add(name.lower())
        hit = _person_for(people_all, addr)
        entry: dict[str, Any] = {"email": addr, "name": name or (hit[1].get("name") if hit else ""), "path": None, "last_contact": "", "company": "", "last_emails": []}
        if hit:
            paths.add(_stem(hit[0]))
            names.add(_s(hit[1].get("name")).lower())
            body = fmt.split_note(read_text(resolve(root, hit[0])))[2]
            entry.update({"path": hit[0], "last_contact": _s(hit[1].get("last_contact")), "company": _s(hit[1].get("org") or hit[1].get("company")), "last_emails": _email_lines(body)})
        people_out.append(entry)
    commitments = [c for c in wiki.commitments(root) if _mentions(c, names, addresses, paths)]
    rows = [f"{c['since']} — {c['owner_name']}: {c['text']}" for c in commitments if _s(c["owner"]).lower() != "me"]
    subject = _s(subject).strip() or (_s(existing["frontmatter"].get("subject")) if existing["found"] else "")
    wiki_pages = wiki.prep_pages(root, [e["path"] for e in people_out if e["path"]], subject, sorted(addresses))
    return {
        "existing_note": existing["path"] if existing["found"] else None,
        "existing_status": _s(existing["frontmatter"].get("status")) if existing["found"] else None,
        "previous_occurrence": previous,
        "people": people_out,
        "commitments": commitments,
        "followups_open": rows,
        "wiki": wiki_pages,
    }


# ------------------------------------------------------------------ weekly facts


def weekly_facts(week: str, today: Optional[str] = None) -> dict[str, Any]:
    root = store.vault_root()
    start, end = _iso_week(week)
    today_d = _parse_date(today, "today") if today else date.today()
    ref = min(end, today_d)

    open_rows = []
    for path, fm, body in sorted(_daily_notes_in(root, start, end), key=lambda t: _date_of(t[1].get("date"))):
        lines = body.split("\n")
        ticked = {m.group(1).strip().lower() for line in lines if (m := _CHECKED_RE.match(line))}
        for table in _tables(lines, 0, len(lines)):
            for row in table:
                label = row.get("Label", "").strip().lower()
                if label not in ("act", "reply"):
                    continue
                subject = row.get("Subject", "")
                if any(subject.lower() in t for t in ticked):
                    continue
                note_cell = row.get("Note", "")
                eid = next((store._unescape_cell(m.group(1)) for m in _ENTRY_RE.finditer(note_cell)), "")
                note_links = _wikilink_targets(note_cell)
                hit = _email_note_for(root, "", eid) if eid else None
                if hit and _s(hit[1].get("status")).lower() == "done":
                    continue
                open_rows.append({"date": _date_of(fm.get("date")), "label": label, "subject": subject, "from": row.get("From", ""), "entry_id": eid, "note": f"[[{note_links[0]}]]" if note_links else (hit and _link(hit[0])) or None, "daily": path})

    waiting = []
    for c in wiki.commitments(root, owner="others"):
        since = _date_of(c["since"])
        age = (ref - date.fromisoformat(since)).days if since else None
        waiting.append({"since": since, "who": c["owner_name"], "what": c["text"],
                        "email": f"[[{c['record']}]]" if c["record"] else "", "age_days": age})
    waiting.sort(key=lambda w: w["since"] or "9999")
    promised_overdue = [
        {"due": c["due"], "what": c["text"], "page": c["stem"], "id": c["id"],
         "days_over": (ref - date.fromisoformat(c["due"])).days}
        for c in wiki.commitments(root, owner="me", due_before=today_d.isoformat())
    ]
    promised_overdue.sort(key=lambda p: p["due"])

    held, no_notes = [], []
    for p, fm in store._iter_notes(root, "meeting"):
        d = _date_of(fm.get("start"))
        if not d or not (start.isoformat() <= d <= end.isoformat()):
            continue
        path = rel(root, p)
        st = _s(fm.get("status")).lower()
        if st == "held":
            held.append({"path": path, "subject": _s(fm.get("subject")), "date": d, "unchecked_actions": _unchecked(fmt.split_note(read_text(p))[2])})
        elif st == "upcoming" and d < today_d.isoformat():
            no_notes.append({"path": path, "subject": _s(fm.get("subject")), "date": d})
    held.sort(key=lambda h: h["date"])

    quiet = []
    for path, fm in _people(root):
        lc = _date_of(fm.get("last_contact"))
        if not lc:
            continue
        days = (end - date.fromisoformat(lc)).days
        if days > 30:
            quiet.append({"name": _s(fm.get("name")), "email": _s(fm.get("email")), "path": path, "last_contact": lc, "days": days})
    quiet.sort(key=lambda q: q["last_contact"])

    from soma_vault import wiki_lint  # local import: wiki_lint imports wiki, which workflows already loads

    return {
        "week": week,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "open_from_inbox": open_rows,
        "waiting": waiting,
        "promised_overdue": promised_overdue,
        "meetings_held": held,
        "no_notes": no_notes,
        "quiet_people": quiet[:20],
        "wiki": wiki_lint.summary(root),
    }


# ------------------------------------------------------------------ transcript


def _turn_name(line: str) -> Optional[str]:
    m = _TURN_RE.match(line) or _TURN_NUMBERED_RE.match(line)
    return m.group(1).strip() if m else None


def clean_transcript(text: str) -> tuple[list[str], list[str], list[str]]:
    """(transcript lines, turn speaker names in order, names from a trailing Speakers: block)."""
    raw = [l.rstrip() for l in text.replace("\r\n", "\n").split("\n")]
    listed: list[str] = []
    # trailing "Speakers:" block
    idx = next((i for i in range(len(raw) - 1, -1, -1) if raw[i].strip().lower() == "speakers:"), None)
    if idx is not None and all(not _turn_name(l) for l in raw[idx + 1 :]):
        listed = [l.strip().lstrip("-* ").strip() for l in raw[idx + 1 :] if l.strip()]
        raw = raw[:idx]
    lines = [l for l in raw if not _SCAFFOLD_RE.match(l.strip())]
    first = next((i for i, l in enumerate(lines) if _turn_name(l)), None)
    if first is None:
        return [], [], listed
    lines = lines[first:]
    while lines and not lines[-1].strip():
        lines.pop()
    turns = [n for l in lines if (n := _turn_name(l))]
    return lines, turns, listed


def attach_transcript(meeting_path: str, transcript_path: str, created_by: str = CREATED_BY) -> dict[str, Any]:
    root = store.vault_root()
    tp = resolve(root, transcript_path)
    if not rel(root, tp).startswith(f"{ADMIN_DIR}/Attachments/"):
        raise VaultError(f"transcript_path must be under {ADMIN_DIR}/Attachments/, got {transcript_path!r}.")
    if not tp.is_file():
        raise VaultError(f"No such file: {transcript_path!r}.")
    mp = resolve(root, meeting_path)
    if not mp.is_file():
        raise VaultError(f"No such note: {meeting_path!r}.")
    mfm, _block, _body = fmt.split_note(read_text(mp))
    if mfm.get("type") != "meeting":
        raise VaultError(f"{meeting_path!r} is not a meeting note.")

    lines, turns, listed = clean_transcript(read_text(tp))
    if not turns:
        raise VaultError("No transcript turns found (lines like '[13:02] Jane Doe: …').")
    seen: dict[str, str] = {}
    for n in listed + turns:
        if n.lower() not in seen:
            seen[n.lower()] = n
    speakers = list(seen.values())
    links = [t for t in _wikilink_targets(" ".join(_s(l) for l in (mfm.get("attendee_links") or []) + [mfm.get("organizer_link") or ""]))]
    by_name = {t.rsplit("/", 1)[-1].lower(): t for t in links}
    speaker_cells = [f"[[{by_name[s.lower()]}]]" if s.lower() in by_name else s for s in speakers]

    head = [
        "Transcript added via /soma:notes.",
        "",
        "### Transcript",
        "",
        "**Speakers:** " + ", ".join(speaker_cells),
        "",
    ]
    linked = len(lines) > TRANSCRIPT_MAX_LINES
    if linked:
        body = head + [f"Full text: {_vault_link(root, rel(root, tp))} ({len(turns)} turns, {len(speakers)} speakers, {len(lines)} lines)"]
    else:
        body = head + [f"> [!note]- Transcript ({len(turns)} turns, {len(speakers)} speakers)"] + ["> " + l for l in lines]
    res = store.write("meeting", dict(mfm, created_by=mfm.get("created_by") or created_by), "\n".join(body), "append")
    return {
        "path": res["path"],
        "turns": len(turns),
        "speakers": speakers,
        "speaker_links": speaker_cells,
        "lines": len(lines),
        "appended_lines": len(body),
        "linked": linked,
        "update_heading": res["update_heading"],
    }


# ------------------------------------------------------------------ save chat


def _norm_name(text: Any) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", _s(text).lower()).split())


def _member_names(chat: dict[str, Any]) -> list[str]:
    out = []
    for m in chat.get("members") or []:
        name = _s(m.get("name") or m.get("displayName")).strip() if isinstance(m, dict) else _s(m).strip()
        if name and name not in out:
            out.append(name)
    return out


def _chat_line(m: dict[str, Any], mid: str) -> str:
    text = " ".join(_s(m.get("text")).split())
    return f"- {_hhmm(m.get('time'))} **{_s(m.get('sender')).strip() or '(unknown)'}**: {text} <!-- id: {mid} -->"


def _save_chat_day(root: Path, chat: dict[str, Any], day: str, msgs: list[dict[str, Any]], selves: set[str], created_by: str) -> dict[str, Any]:
    chat_id = _s(chat.get("id")).strip()
    title = _s(chat.get("title")).strip() or chat_id
    record_id = f"{chat_id}|{day}"
    existing = store.find("chat", {"chat_id": chat_id, "date": day})
    old_text = read_text(resolve(root, existing["path"])) if existing["found"] else ""
    seen = {m.group(1) for m in _CHAT_ID_RE.finditer(old_text)}
    fresh: list[tuple[str, dict[str, Any]]] = []
    dups = 0
    done: set[str] = set()
    for m in msgs:
        mid = _s(m.get("id")).strip() or f"{_s(m.get('time'))} {_s(m.get('sender'))}".strip()
        if mid in done:
            continue
        done.add(mid)
        if mid in seen:
            dups += 1
        else:
            fresh.append((mid, m))
    out: dict[str, Any] = {"date": day, "record_id": record_id, "added": len(fresh), "skipped_duplicates": dups, "people": [], "unknown_people": []}
    if existing["found"] and not fresh:
        out.update(path=existing["path"], action="unchanged", messages=existing["frontmatter"].get("messages"))
        return out

    times = [_s(m.get("time")) for _mid, m in fresh]
    old_fm = existing["frontmatter"] if existing["found"] else {}
    last = max(times + [_s(old_fm.get("last"))])
    fm: dict[str, Any] = {
        "type": "chat",
        "source": "teams",
        "chat_id": chat_id,
        "chat_title": title,
        "chat_type": _s(chat.get("type")),
        "date": day,
        "account": _s(chat.get("account")),
        "members": _member_names(chat),
        "record_id": record_id,
        "messages": int(old_fm.get("messages") or 0) + len(fresh),
        "first": _s(old_fm.get("first")) or min(times),
        "last": last,
        "created_by": _s(old_fm.get("created_by")) or created_by,
    }
    lines = [f"# {title} — {day}", "", "**Members:** " + ", ".join(fm["members"]), "", "## Messages", ""] if not existing["found"] else ["### Messages", ""]
    lines += [_chat_line(m, mid) for mid, m in fresh]
    res = store.write("chat", fm, "\n".join(lines), "upsert")
    out.update(path=res["path"], action=res["action"], messages=fm["messages"])

    # senders with a person page get a Records line; nobody gets a page without an address
    pages = [pg for pg in wiki._all_pages(root) if pg[1].get("type") == "person"]
    senders: dict[str, list[dict[str, Any]]] = {}
    for _mid, m in fresh:
        name = _s(m.get("sender")).strip()
        if not name or m.get("is_self") or _norm_name(name) in selves:
            continue
        senders.setdefault(name, []).append(m)
    for name, theirs in senders.items():
        hit = wiki._find_by_name(pages, name, [])
        if not hit:
            out["unknown_people"].append(name)
            continue
        first_text = " ".join(_s(theirs[0].get("text")).split())
        pres = wiki.record_person(
            name=_s(hit[1].get("title") or hit[1].get("name")) or name,
            email=_s(hit[1].get("email")),
            aliases=[],
            last_contact=max(_s(m.get("time")) for m in theirs),
            company=None,
            record_path=res["path"],
            record_date=day,
            summary=_short(f"{title}: {first_text}", 120),
            created_by=created_by,
            existing=hit[0],
        )
        out["people"].append({"name": name, "page": pres["path"]})
    return out


def save_chat(chat: dict[str, Any], messages: list[dict[str, Any]], self_names: Optional[list[str]] = None, created_by: str = CREATED_BY) -> Any:
    """Write or extend the day record(s) of one Teams chat.

    ``chat`` is the object teams_list_chats returned (id, title, type,
    members, account); ``messages`` are its messages ({id, time, sender,
    is_self, text}) in any order. One record per chat per day: the day comes
    from each message's time, so messages spanning several days give several
    records and the answer is then a list of per-day results (a dict for one
    day). A second call the same day appends only messages whose ids are not
    in the file yet and moves ``messages`` / ``last`` forward."""
    if not isinstance(chat, dict) or not _s(chat.get("id")).strip():
        raise NoteError("chat must be the JSON from teams_list_chats with an id.")
    root = store.vault_root()
    selves = {_norm_name(n) for n in (self_names or []) if _norm_name(n)}
    by_day: dict[str, list[dict[str, Any]]] = {}
    no_time = 0
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        day = _date_of(m.get("time"))
        if not day:
            no_time += 1
            continue
        by_day.setdefault(day, []).append(m)
    if not by_day:
        raise NoteError("messages is empty, or no message has an ISO time.")
    results = []
    for day in sorted(by_day):
        msgs = sorted(by_day[day], key=lambda m: _s(m.get("time")))
        results.append(_save_chat_day(root, chat, day, msgs, selves, created_by))
    if no_time:
        results[0]["skipped_no_time"] = no_time
    return results[0] if len(results) == 1 else results


# ------------------------------------------------------------------ collect stamps


def _local(dt: datetime) -> datetime:
    """An aware datetime; a naive one is taken as local time."""
    return dt.astimezone() if dt.tzinfo is None else dt


def _stamp_words(dt: datetime) -> str:
    """``Thu 21 Aug 18:10`` — the wording of the "Last collected" line."""
    return f"{dt:%a} {dt.day} {dt:%b} {dt:%H:%M}"


def _collect_stamps(root: Path) -> dict[str, Optional[str]]:
    p = root / COLLECT_PATH
    data: dict[str, Any] = {}
    if p.is_file():
        try:
            data = json.loads(read_text(p)) or {}
        except ValueError:
            data = {}
    return {src: (_s(data.get(src)) or None) for src in COLLECT_SOURCES}


def _token_runs(root: Path) -> dict[str, list[dict[str, Any]]]:
    """The runs kept per command in Wiki/_cache/tokens.json, newest last."""
    p = root / TOKENS_PATH
    data: dict[str, Any] = {}
    if p.is_file():
        try:
            data = json.loads(read_text(p)) or {}
        except ValueError:
            data = {}
    out: dict[str, list[dict[str, Any]]] = {}
    for command in TOKEN_COMMANDS:
        rows = data.get(command)
        out[command] = [r for r in rows if isinstance(r, dict)][-TOKEN_RUNS:] if isinstance(rows, list) else []
    return out


def _token_number(value: Any, name: str, low: float) -> float:
    """One of the four counts: a plain number, ``low`` or more."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
        raise VaultError(f"payload['{name}'] must be a number, got {value!r}.")
    if float(value) < low:
        raise VaultError(f"payload['{name}'] must be {low:g} or more, got {value!r}.")
    n = float(value)
    return int(n) if n.is_integer() else n


def _token_ratios(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """How many runs are on file and the median actual/predicted of each side.
    A run whose predicted count is missing or not a number is left out."""
    def ratio(side: str) -> Optional[float]:
        seen = []
        for r in runs:
            pred, act = r.get(f"predicted_{side}"), r.get(f"actual_{side}")
            if isinstance(pred, (int, float)) and not isinstance(pred, bool) and float(pred) > 0 \
                    and isinstance(act, (int, float)) and not isinstance(act, bool):
                seen.append(float(act) / float(pred))
        if not seen:
            return None
        seen.sort()
        mid = len(seen) // 2
        return round(seen[mid] if len(seen) % 2 else (seen[mid - 1] + seen[mid]) / 2, 2)

    return {"runs": len(runs), "ratio_in": ratio("in"), "ratio_out": ratio("out")}


def collect_sources(action: str = "read", source: Optional[str] = None, at: Optional[str] = None,
                    now: Optional[str] = None, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """The "last collected" stamp per source (teams, outlook, notes) in
    Wiki/_cache/collect.json. ``read`` reports them with their age, the ask
    rule and the token calibration; ``advance`` moves one (or all) to ``at``,
    never backwards; ``tokens`` files what one run of a command predicted and
    what it cost, in Wiki/_cache/tokens.json. ``now`` is only for tests."""
    root = store.vault_root()
    if now:
        now_dt = _parse_dt(now)
        if now_dt is None:
            raise VaultError(f"'now' must be an ISO datetime, got {now!r}.")
        now_dt = _local(now_dt)
    else:
        now_dt = datetime.now().astimezone()
    stamps = _collect_stamps(root)
    if action == "read":
        ages: dict[str, Optional[float]] = {}
        ask = False
        known: list[datetime] = []
        for src in COLLECT_SOURCES:
            dt = _parse_dt(stamps[src]) if stamps[src] else None
            if dt is None:
                ages[src] = None
                ask = True
                continue
            dt = _local(dt)
            known.append(dt)
            hours = round((now_dt - dt).total_seconds() / 3600, 1)
            ages[src] = hours
            if hours > COLLECT_ASK_HOURS:
                ask = True
        oldest = min(known) if known else None
        newest = max(known) if known else None
        default_since = oldest if oldest else now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return {
            "path": COLLECT_PATH,
            "stamps": stamps,
            "age_hours": ages,
            "ask": ask,
            "default_since": default_since.isoformat(timespec="seconds"),
            "last_collected": _stamp_words(newest) if newest else "never",
            "tokens": {c: _token_ratios(r) for c, r in _token_runs(root).items() if r},
        }
    if action == "advance":
        if source is not None and source not in COLLECT_SOURCES:
            raise VaultError(f"source must be one of {', '.join(COLLECT_SOURCES)}, got {source!r}.")
        targets = [source] if source else list(COLLECT_SOURCES)
        if at:
            at_dt = _parse_dt(at)
            if at_dt is None:
                raise VaultError(f"'at' must be an ISO datetime, got {at!r}.")
            at_dt = _local(at_dt)
        else:
            at_dt = now_dt
        at_iso = at_dt.isoformat(timespec="seconds")
        advanced, refused = [], []
        for src in targets:
            cur = _parse_dt(stamps[src]) if stamps[src] else None
            if cur is not None and at_dt < _local(cur):
                refused.append({"source": src, "reason": "older-than-stamp", "stamp": stamps[src], "at": at_iso})
                continue
            stamps[src] = at_iso
            advanced.append(src)
        if advanced:
            write_text(resolve(root, COLLECT_PATH), json.dumps(stamps, ensure_ascii=False, indent=1))
        return {"path": COLLECT_PATH, "stamps": stamps, "advanced": advanced, "refused": refused}
    if action == "tokens":
        if not isinstance(payload, dict):
            raise VaultError("action 'tokens' needs payload={command, predicted_in, predicted_out, actual_in, actual_out}.")
        command = _s(payload.get("command")).strip()
        if command not in TOKEN_COMMANDS:
            raise VaultError(f"payload['command'] must be one of {', '.join(TOKEN_COMMANDS)}, got {payload.get('command')!r}.")
        run = {
            "at": now_dt.isoformat(timespec="seconds"),
            "predicted_in": _token_number(payload.get("predicted_in"), "predicted_in", 1),
            "predicted_out": _token_number(payload.get("predicted_out"), "predicted_out", 1),
            "actual_in": _token_number(payload.get("actual_in"), "actual_in", 0),
            "actual_out": _token_number(payload.get("actual_out"), "actual_out", 0),
        }
        kept = _token_runs(root)
        kept[command] = (kept[command] + [run])[-TOKEN_RUNS:]
        write_text(resolve(root, TOKENS_PATH), json.dumps(kept, ensure_ascii=False, indent=1))
        return {"path": TOKENS_PATH, "command": command, **_token_ratios(kept[command]), "last": run}
    raise VaultError(f"action must be 'read', 'advance' or 'tokens', got {action!r}.")


# ------------------------------------------------------------------ changed notes


def _collect_folder(root: Path, raw: Any) -> Path:
    """A vault-relative folder as an absolute path; anything that leaves the vault is refused."""
    s = _s(raw).strip().replace("\\", "/")
    if not s:
        raise VaultError("A collect folder is empty.")
    if s.startswith("/") or re.match(r"^[A-Za-z]:", s):
        raise VaultError(f"Collect folders must be vault-relative, not absolute: {raw!r}.")
    parts = [p for p in s.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise VaultError(f"Collect folders may not contain '..': {raw!r}.")
    p = root.joinpath(*parts) if parts else root
    try:
        p.resolve().relative_to(root.resolve())
    except ValueError:
        raise VaultError(f"Refused: {raw!r} resolves outside the vault.") from None
    return p


def _never_read(root: Path, p: Path) -> bool:
    r = rel(root, p)
    parts = r.split("/")
    if any(part.startswith(".") for part in parts):
        return True
    return len(parts) >= 2 and parts[0] == ADMIN_DIR and parts[1] in COLLECT_NEVER_READ


def _document_folder(root: Path, raw: Any) -> Path:
    """A watched document folder: vault-relative, or a full path on the machine."""
    s = _s(raw).strip().replace("\\", "/")
    if not s:
        raise VaultError("A document folder is empty.")
    p = Path(s)
    if not p.is_absolute():
        parts = [part for part in s.split("/") if part not in ("", ".")]
        if any(part == ".." for part in parts):
            raise VaultError(f"Document folders may not contain '..': {raw!r}.")
        p = root.joinpath(*parts) if parts else root
    return p


def _shown_path(root: Path, file: Path) -> str:
    """A watched file's path: vault-relative when it is in the vault, else as it is."""
    try:
        return file.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return file.as_posix()


def changed_documents(root: Path, since_dt: datetime, folders: list[str], limit: int) -> dict[str, Any]:
    """The files in the watched folders modified after ``since``, oldest first.

    Nothing is read out of them here: a file becomes a record only when
    vault_save(kind="document") is called on it."""
    from soma_vault import documents

    found: list[tuple[datetime, dict[str, Any]]] = []
    checked: list[str] = []
    missing: list[str] = []
    seen: set[Path] = set()
    for raw in folders:
        p = _document_folder(root, raw)
        shown = _shown_path(root, p)
        if not p.is_dir():
            missing.append(shown)
            continue
        checked.append(shown)
        for file in sorted(p.rglob("*")):
            if file in seen or file.suffix.lower() not in documents.FORMATS or not file.is_file():
                continue
            if any(part.startswith((".", "~$")) for part in file.parts):
                continue
            seen.add(file)
            try:
                stat = file.stat()
                modified = datetime.fromtimestamp(stat.st_mtime).astimezone()
            except OSError:
                continue
            if modified <= since_dt:
                continue
            found.append((modified, {
                "path": _shown_path(root, file),
                "kind": "document",
                "modified": modified.isoformat(timespec="seconds"),
                "size": stat.st_size,
                "format": documents.FORMATS[file.suffix.lower()],
            }))
    found.sort(key=lambda f: (f[0], f[1]["path"]))
    return {"documents": [item for _m, item in found[:limit]], "document_folders": checked,
            "documents_total": len(found), "missing": missing}


def _last_update(body: str) -> tuple[str, bool]:
    """(the last '## Update …' section's text, True) or (the whole body, False)."""
    lines = body.split("\n")
    last = None
    for level, heading, lo, hi in _sections(body):
        if level == 2 and heading.strip().startswith("Update "):
            last = (lo, hi)
    if last:
        return "\n".join(lines[last[0] : last[1]]).strip(), True
    return body.strip(), False


def changed_notes(since: str, folders: Optional[list[str]] = None, max_chars: int = 1200, limit: int = 20) -> dict[str, Any]:
    """Markdown notes modified after ``since``, oldest first, from
    Soma/Meetings, Emails, Daily, Weekly and the ``collect_folders``
    of Preferences.md (or the given ``folders``). Wiki/, Attachments/,
    _views/, _backup/ and dot-folders are never read.

    The files in the ``document_folders`` of Preferences.md that changed in
    the same window come back under ``documents``, listed and not read."""
    root = store.vault_root()
    since_dt = _parse_dt(since)
    if since_dt is None:
        raise VaultError(f"'since' must be an ISO date or datetime, got {since!r}.")
    since_dt = _local(since_dt)
    prefs = store.read_preferences()["preferences"]
    if folders is None:
        raw = [f"{ADMIN_DIR}/{f}" for f in COLLECT_DEFAULT_FOLDERS] + [_s(f) for f in (prefs.get("collect_folders") or [])]
    else:
        raw = [_s(f) for f in folders]
    docs = changed_documents(root, since_dt, [_s(f) for f in (prefs.get("document_folders") or [])], limit)
    checked: list[str] = []
    skipped: list[dict[str, str]] = []
    missing: list[str] = []
    seen: set[Path] = set()
    items: list[dict[str, Any]] = []
    for f in raw:
        p = _collect_folder(root, f)
        r = rel(root, p) if p != root else "."
        if p != root and _never_read(root, p):
            skipped.append({"folder": r, "reason": "never read"})
            continue
        if not p.is_dir():
            missing.append(r)
            continue
        checked.append(r)
        for file in sorted(p.rglob("*.md")):
            if file in seen or not file.is_file() or _never_read(root, file):
                continue
            seen.add(file)
            try:
                modified = datetime.fromtimestamp(file.stat().st_mtime).astimezone()
            except OSError:
                continue
            if modified <= since_dt:
                continue
            try:
                text = read_text(file)
            except (OSError, UnicodeDecodeError):
                continue
            try:
                fm, _block, body = fmt.split_note(text)
            except fmt.FrontmatterError:
                fm, body = {}, text
            excerpt, from_update = _last_update(body)
            truncated = bool(max_chars) and len(excerpt) > max_chars
            if truncated:
                excerpt = excerpt[:max_chars].rstrip() + "…"
            items.append(
                {
                    "path": rel(root, file),
                    "type": _s(fm.get("type")),
                    "modified": modified.isoformat(timespec="seconds"),
                    "ingested": bool(fm.get("wiki")),
                    "excerpt": excerpt,
                    "from_update": from_update,
                    "truncated": truncated,
                    "_t": modified,
                }
            )
    items.sort(key=lambda i: (i["_t"], i["path"]))
    out = [{k: v for k, v in i.items() if k != "_t"} for i in items[:limit]]
    return {
        "since": since_dt.isoformat(timespec="seconds"),
        "count": len(out),
        "total": len(items),
        "capped": len(items) > limit,
        "folders": checked,
        "skipped": skipped,
        "missing": missing + docs["missing"],
        "notes": out,
        "documents": docs["documents"],
        "documents_total": docs["documents_total"],
        "document_folders": docs["document_folders"],
    }
