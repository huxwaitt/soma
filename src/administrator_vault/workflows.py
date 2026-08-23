"""v0.5 helpers: the parts of the administrator workflows that only move,
compare or format data, done in code so the model never reads them.

Every function takes the JSON the model already got from the outlook tools
(or nothing) and reads / writes the vault through ``store``. Nothing here
imports Outlook code; the vault server runs without Outlook.
"""

from __future__ import annotations

import fnmatch
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from administrator_vault import frontmatter as fmt
from administrator_vault import notes, store, wiki
from administrator_vault.notes import ADMIN_DIR, NoteError
from administrator_vault.store import VaultError, read_text, rel, resolve, write_text

CREATED_BY = "administrator/0.2.0"
RULES_PATH = f"{ADMIN_DIR}/Rules.md"
FOLLOWUPS_PATH = f"{ADMIN_DIR}/Follow-ups.md"
CACHE_DIR = f"{ADMIN_DIR}/Attachments/_cache"

LABELS = ("act", "reply", "waiting", "fyi", "noise")
DAILY_HEADER = ["#", "Label", "From", "Subject", "Received", "Why", "Note"]
CALENDAR_HEADER = ["Start", "End", "Subject", "Location", "Organizer"]
TRANSCRIPT_MAX_LINES = 400

_COMMENT_RE = re.compile(r"<!--\s*([A-Za-z_]+):\s*(.*?)\s*-->")
_ENTRY_RE = re.compile(r"<!--\s*entry_id:\s*(.*?)\s*-->")
_OCC_RE = re.compile(r"<!--\s*occurrence_key:\s*(.*?)\s*-->")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_UNCHECKED_RE = re.compile(r"^\s*- \[ \] ")
_CHECKED_RE = re.compile(r"^\s*- \[x\] (.*)$", re.IGNORECASE)
_EMAIL_LINE_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) — \[\[Emails/")
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
    """``Administrator/Emails/x.md`` -> ``Emails/x`` (the wikilink target)."""
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
    fm = fmt.format_frontmatter({"type": "rules", "source": "administrator", "created_by": created_by})
    return fm + (
        "\n# Rules\n\n"
        "Rules the inbox applies before the model reads a mail. Edit the tables; the plugin only reads this file.\n"
        "`Field` is `from` (the sender's address), `domain` (the part after `@`), `name` (the sender's display name) "
        "or `subject`. `Match` is a case-insensitive part of the value, or a pattern with `*` / `?`.\n\n"
        "## Labels\n\n"
        "Label a mail without reading it. Labels: act, reply, waiting, fyi, noise.\n\n"
        "| Match | Field | Label |\n| --- | --- | --- |\n\n"
        "## Never save\n\n"
        "Mail that never goes into a daily note (left out before labelling).\n\n"
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
    root = store.vault_root()
    rules = rules_get()
    people = _people(root)
    results = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        label, rule = _builtin(item, people)
        never = False
        for r in rules["never_save"]:
            if _hit(r["match"], _field_value(item, r["field"])):
                never = True
                rule = rule or f"Never save: {r['match']} ({r['field']})"
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
        results.append({"entry_id": _s(item.get("entry_id")), "label": label, "never_save": never, "rule": rule})
    return {"results": results, "rules_path": rules["path"]}


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


def _followup_row(root: Path, people: list[tuple[str, dict[str, Any]]], since: str, who_name: str, who_addr: str, what: str, email_path: Optional[str], today: str, key: str, label: str = "entry_id") -> bool:
    hit = _person_for(people, who_addr)
    who = _link(hit[0]) if hit else (who_name or who_addr)
    row = [since, who, _short(notes.strip_prefixes(what), 80), _link(email_path) if email_path else "", today]
    try:
        return bool(store.append_row(FOLLOWUPS_PATH, "Open", row, key, key_label=label)["appended"])
    except VaultError:
        return False


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
        return {"path": hit["path"], "action": "unchanged", "rows_written": 0, "duplicates_skipped": dups, "followups_added": 0, "unlabelled": unlabelled}

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
        body += [f"- {r['from']} — {r['subject']} (since {_date_of(r['received'])}) → also in [[Follow-ups]]" for r in waiting] or ["- none"]
        body.append("")
        by_id = {_s(i.get("entry_id")): i for i in fresh if isinstance(i, dict)}
        for r in waiting:
            it = by_id.get(r["entry_id"], {})
            if _followup_row(root, people, _date_of(r["received"]), r["from"], _s(it.get("from_address")), r["subject"], r["note_path"], day, r["entry_id"]):
                followups_added += 1
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
        lines = ["Saved again via /administrator:save.", ""]
    lines += ["## Summary" if not existing["found"] else "### Summary", "", _s(summary).strip() or "(no summary)", ""]
    lines += ["## Action items" if not existing["found"] else "### Action items", ""]
    lines += [a if a.lstrip().startswith("- ") else f"- [ ] {a.strip()}" for a in action_items] or ["- none"]
    lines.append("")
    if not existing["found"]:
        body_text = _s(mail.get("body_trimmed") if mail.get("body_trimmed") else mail.get("body")).replace("\r\n", "\n").strip("\n")
        lines += ["## Body", "", body_text, ""]
    if atts or msg_link:
        lines += ["## Attachments" if not existing["found"] else "### Attachments", ""]
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
        if from_self and to_list:
            who_name, who_addr = to_list[0]["name"], to_list[0]["address"]
        else:
            who_name, who_addr = from_name, from_addr
        followup_added = _followup_row(root, people, _date_of(received), who_name, who_addr, fm["subject"], path, date.today().isoformat(), fm["entry_id"] or fm["internet_message_id"], "entry_id" if fm["entry_id"] else "internet_message_id")
    return {"path": path, "action": res["action"], "status": status, "person_path": person_path, "person_action": person_action, "followup_added": followup_added}


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


def _followups_open(root: Path) -> list[dict[str, str]]:
    p = resolve(root, FOLLOWUPS_PATH)
    if not p.is_file():
        return []
    body = fmt.split_note(read_text(p))[2]
    lines = body.split("\n")
    for _level, heading, lo, hi in _sections(body):
        if heading.strip().lower() == "open":
            tables = _tables(lines, lo, hi)
            return tables[0] if tables else []
    return []


def _row_mentions(row: dict[str, str], names: set[str], addresses: set[str], paths: set[str]) -> bool:
    who = row.get("Who", "")
    targets = {t.lower() for t in _wikilink_targets(who)}
    if targets & {p.lower() for p in paths}:
        return True
    plain = _strip_comment(who).lower()
    return plain in names or plain in addresses


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
    rows = [row["_line"] for row in _followups_open(root) if _row_mentions(row, names, addresses, paths)]
    subject = _s(subject).strip() or (_s(existing["frontmatter"].get("subject")) if existing["found"] else "")
    wiki_pages = wiki.prep_pages(root, [e["path"] for e in people_out if e["path"]], subject, sorted(addresses))
    return {
        "existing_note": existing["path"] if existing["found"] else None,
        "existing_status": _s(existing["frontmatter"].get("status")) if existing["found"] else None,
        "previous_occurrence": previous,
        "people": people_out,
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
    for row in _followups_open(root):
        since = _date_of(row.get("Since"))
        age = (ref - date.fromisoformat(since)).days if since else None
        waiting.append({"since": since, "who": _strip_comment(row.get("Who", "")), "what": _strip_comment(row.get("What", "")), "email": _strip_comment(row.get("Email", "")), "age_days": age})
    waiting.sort(key=lambda w: w["since"] or "9999")

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

    from administrator_vault import wiki_lint  # local import: wiki_lint imports wiki, which workflows already loads

    return {
        "week": week,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "open_from_inbox": open_rows,
        "waiting": waiting,
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
        "Transcript added via /administrator:notes.",
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
