"""Time blocks: plan a week's focus and admin blocks, write the plan note,
audit how the week went.

The planner is plain code over the JSON the model already has: the week's
events from ``outlook_list_events`` (subject, start, end, all_day,
attendee_count, is_meeting, occurrence_key, entry_id, busy_status; local ISO
times), the preferences of ``Preferences.md`` and the ranked list of
``Priorities.md`` plus the pressing wiki topics. ``plan`` never reads the
clock: ``today`` is passed in (the tool defaults it to ``date.today()``),
and the same inputs always give the same plan.

Subjects: ``[Focus] <priority>`` and ``[Admin] Email and small tasks``.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from soma_vault import frontmatter as fmt
from soma_vault import store, wiki, workflows
from soma_vault.notes import ADMIN_DIR, NoteError
from soma_vault.store import VaultError, read_text, resolve
from soma_vault.workflows import CREATED_BY, _iso_week, _s

PRIORITIES_PATH = f"{ADMIN_DIR}/Priorities.md"
FOCUS_PREFIX = "[Focus]"
ADMIN_PREFIX = "[Admin]"
ADMIN_SUBJECT = f"{ADMIN_PREFIX} Email and small tasks"
NO_PRIORITY = "Deep work"  # the focus subject when Priorities.md is empty
PLAN_HEADER = ["Day", "Start", "End", "Kind", "Subject", "Priority"]
# The Plan row hides "<occurrence_key> # plan": vault_row treats a key found anywhere in the
# file as a duplicate, and the Held row of the same block is keyed by the bare occurrence_key.
PLAN_KEY_SUFFIX = " # plan"
HELD_HEADER = ["Day", "Block", "Result", "Note"]
HELD_RESULTS = ("held", "moved", "skipped")
DUE_WINDOW_DAYS = 30
ROUND_MINUTES = 15
LUNCH = 13 * 60  # admin blocks: one ends at or before this line, one at the end of the day
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
WORKING_DAYS = 5  # Mon-Fri
PLAN_KEYS = (
    "work_start", "work_end", "buffer_minutes", "no_meeting_blocks", "peak_hours", "focus_block_minutes",
    "focus_blocks_per_day", "admin_blocks_per_day", "admin_block_minutes", "slack_share",
)

_NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+(.*?)\s*$")
_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]*))?\]\]")
_HINT_RE = re.compile(r"^\(.*\)$")  # the template's "(your first priority — …)" line
_ANY_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_RANGE_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")
_DAY_RANGE_RE = re.compile(r"^\s*([A-Za-z]{3})[A-Za-z]*\s+(\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2})\s*$")

Interval = tuple[int, int]  # minutes since midnight, [start, end)


# ------------------------------------------------------------------ small helpers


def _hhmm_minutes(value: Any, what: str) -> int:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", _s(value))
    if not m or int(m.group(1)) > 24 or int(m.group(2)) > 59:
        raise VaultError(f"{what} must look like HH:MM, got {value!r}.")
    return int(m.group(1)) * 60 + int(m.group(2))


def _minutes_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _parse_range(value: Any, what: str) -> Interval:
    """``"09:00-12:00"`` -> (540, 720)."""
    m = _RANGE_RE.match(_s(value))
    if not m:
        raise VaultError(f"{what} must look like HH:MM-HH:MM, got {value!r}.")
    lo = int(m.group(1)) * 60 + int(m.group(2))
    hi = int(m.group(3)) * 60 + int(m.group(4))
    if hi <= lo:
        raise VaultError(f"{what} must end after it starts, got {value!r}.")
    return lo, hi


def _parse_day_range(value: Any) -> Optional[tuple[int, Interval]]:
    """``"Fri 13:00-17:00"`` -> (4, (780, 1020)); None for a line that does not parse."""
    m = _DAY_RANGE_RE.match(_s(value))
    if not m:
        return None
    day = m.group(1).lower()
    idx = next((i for i, name in enumerate(WEEKDAYS) if name.lower() == day), None)
    if idx is None:
        return None
    try:
        return idx, _parse_range(m.group(2), "no_meeting_blocks")
    except VaultError:
        return None


def _parse_local(value: Any) -> Optional[datetime]:
    """A local naive datetime from an ISO string (an offset, when present, is dropped)."""
    try:
        dt = datetime.fromisoformat(_s(value).strip())
    except ValueError:
        return None
    return dt.replace(tzinfo=None)


def _parse_day(value: Any, what: str) -> date:
    if isinstance(value, date):
        return value
    d = workflows._date_of(value)
    if not d:
        raise VaultError(f"'{what}' must be an ISO date, got {value!r}.")
    return date.fromisoformat(d)


def _subtract(intervals: list[Interval], cut: Interval) -> list[Interval]:
    out: list[Interval] = []
    for lo, hi in intervals:
        if cut[1] <= lo or cut[0] >= hi:
            out.append((lo, hi))
            continue
        if lo < cut[0]:
            out.append((lo, cut[0]))
        if cut[1] < hi:
            out.append((cut[1], hi))
    return out


def _intersect(intervals: list[Interval], with_: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for lo, hi in intervals:
        for a, b in with_:
            s, e = max(lo, a), min(hi, b)
            if e > s:
                out.append((s, e))
    return sorted(out)


def _round_up(minutes: int) -> int:
    return -(-minutes // ROUND_MINUTES) * ROUND_MINUTES


def _round_down(minutes: int) -> int:
    return minutes // ROUND_MINUTES * ROUND_MINUTES


def _day_label(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]} {d.day} {d:%b}"


def _kind_of(subject: Any) -> str:
    s = _s(subject).strip()
    if s.startswith(FOCUS_PREFIX):
        return "focus"
    if s.startswith(ADMIN_PREFIX):
        return "admin"
    return ""


def _priority_of(subject: Any) -> str:
    return _s(subject).strip()[len(FOCUS_PREFIX) :].strip()


def _event_minutes(ev: dict[str, Any], day: date, window: Interval) -> Optional[Interval]:
    """The part of a timed event that falls inside the day's window, else None."""
    start, end = _parse_local(ev.get("start")), _parse_local(ev.get("end"))
    if start is None or end is None or end <= start:
        return None
    day_start = datetime.combine(day, datetime.min.time())
    lo = int((start - day_start).total_seconds() // 60)
    hi = int((end - day_start).total_seconds() // 60)
    s, e = max(lo, window[0]), min(hi, window[1])
    return (s, e) if e > s else None


def _is_all_day(ev: dict[str, Any]) -> bool:
    return bool(ev.get("all_day"))


def _busy(ev: dict[str, Any]) -> bool:
    return _s(ev.get("busy_status")).strip().lower() != "free"


def _is_meeting(ev: dict[str, Any]) -> bool:
    try:
        n = int(ev.get("attendee_count") or 0)
    except (TypeError, ValueError):
        n = 0
    return n > 0 or bool(ev.get("is_meeting"))


def _covers_day(ev: dict[str, Any], day: date) -> bool:
    """Does an all-day event (start / end as dates or datetimes, end exclusive) cover this day?"""
    start = workflows._date_of(ev.get("start"))
    end = workflows._date_of(ev.get("end")) or start
    if not start:
        return False
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    if d1 <= d0:
        d1 = d0 + timedelta(days=1)
    return d0 <= day < d1


# ------------------------------------------------------------------ priorities


def _priority_from_line(text: str, pages: list[tuple[str, dict[str, Any]]]) -> Optional[dict[str, Any]]:
    """{name, page} from one numbered line: a wiki link (the page's title when it resolves) or plain words."""
    text = _ANY_COMMENT_RE.sub("", text).strip()
    if not text or _HINT_RE.match(text):
        return None
    m = _LINK_RE.search(text)
    if m:
        stem = wiki._link_target(m.group(1))
        hit = next((pg for pg in pages if wiki._stem(pg[0]) == stem), None)
        name = _s(hit[1].get("title")) if hit else (m.group(2) or stem.rsplit("/", 1)[-1]).strip()
        return {"name": name or stem, "page": wiki._link(hit[0]) if hit else f"[[{stem}]]"}
    return {"name": " ".join(text.split()), "page": None}


def _active_topics(pages: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Every topic page still being worked on as {name, page, path, fm, due (date or None),
    open_items}, soonest due first, then most open items."""
    out = []
    for path, fm in pages:
        if fm.get("type") != "topic" or _s(fm.get("status") or "active") not in wiki.LIVE_STATUSES:
            continue
        due = workflows._date_of(fm.get("due"))
        try:
            open_items = int(fm.get("open_items") or 0)
        except (TypeError, ValueError):
            open_items = 0
        name = _s(fm.get("title")) or wiki._stem(path).rsplit("/", 1)[-1]
        out.append({"name": name, "page": wiki._link(path), "path": path, "fm": fm, "due": date.fromisoformat(due) if due else None, "open_items": open_items})
    out.sort(key=lambda t: (t["due"] or date.max, -t["open_items"], t["name"].lower()))
    return out


def _pressing_topics(pages: list[tuple[str, dict[str, Any]]], today: date) -> list[dict[str, Any]]:
    """Active topic pages with a due date within DUE_WINDOW_DAYS (past ones included) or open items."""
    limit = today + timedelta(days=DUE_WINDOW_DAYS)
    return [{"name": t["name"], "page": t["page"]} for t in _active_topics(pages) if (t["due"] is not None and t["due"] <= limit) or t["open_items"] > 0]


def _numbered_lines(body: str) -> list[str]:
    """The text after the number of every ``1.`` / ``1)`` line, the template's hint line left out."""
    out = []
    for line in body.split("\n"):
        m = _NUMBERED_RE.match(line)
        if m and not _HINT_RE.match(_ANY_COMMENT_RE.sub("", m.group(1)).strip()):
            out.append(m.group(1))
    return out


def _deadline_items(root: Path, until: date, found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """{name, page, due} per commitment of the user's own falling due by ``until``
    whose page or wording is not already in the list."""
    out: list[dict[str, Any]] = []
    named = {wiki._link_target(_s(f.get("page"))) for f in found if f.get("page")}
    for c in wiki.commitments(root, owner="me", due_before=(until + timedelta(days=1)).isoformat()):
        item = {"name": c["text"], "page": f"[[{c['stem']}]]", "due": c["due"]}
        if c["stem"] in named or any(wiki._norm(f["name"]) == wiki._norm(c["text"]) for f in found + out):
            continue
        out.append(item)
    out.sort(key=lambda i: (i["due"], i["name"].lower()))
    return out


def read_priorities(root: Path, today: date, until: Optional[date] = None) -> list[dict[str, Any]]:
    """[{rank, name, page, due}]: the numbered lines of Priorities.md first, then
    the user's own commitments due by ``until`` (the end of the week being
    planned), then the pressing wiki topics not already named."""
    pages = wiki._all_pages(root)
    found: list[dict[str, Any]] = []
    p = root / PRIORITIES_PATH
    if p.is_file():
        try:
            body = fmt.split_note(read_text(p))[2]
        except (fmt.FrontmatterError, UnicodeDecodeError):
            body = ""
        for text in _numbered_lines(body):
            item = _priority_from_line(text, pages)
            if item:
                found.append(item)
    if until is not None:
        found += _deadline_items(root, until, found)
    for topic in _pressing_topics(pages, today):
        if not any(_same_priority(f, topic) for f in found):
            found.append(topic)
    out, seen = [], set()
    for item in found:
        # one line per page, but two commitments on the same page are two entries
        key = ((item["page"] or "").lower(), wiki._norm(item["name"])) if item.get("due") else ((item["page"] or item["name"]).lower(), "")
        if key in seen:
            continue
        seen.add(key)
        out.append({"rank": len(out) + 1, "name": item["name"], "page": item["page"], "due": item.get("due")})
    return out


def _same_priority(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a.get("page") and b.get("page") and wiki._link_target(a["page"]) == wiki._link_target(b["page"]):
        return True
    return wiki._norm(a.get("name") or "") == wiki._norm(b.get("name") or "")


# ------------------------------------------------------------------ plan


def _plan_preferences(preferences: dict[str, Any]) -> dict[str, Any]:
    """The planner's keys, typed and checked, defaults filled in."""
    prefs = dict(store.PREFERENCE_DEFAULTS)
    prefs.update({k: v for k, v in (preferences or {}).items() if v not in (None, "")})
    used = {k: store._coerce_preference(k, prefs[k]) for k in PLAN_KEYS}
    used["_work"] = (_hhmm_minutes(used["work_start"], "work_start"), _hhmm_minutes(used["work_end"], "work_end"))
    if used["_work"][1] <= used["_work"][0]:
        raise VaultError("work_end must be after work_start.")
    used["_peak"] = [_parse_range(r, "peak_hours") for r in used["peak_hours"]]
    used["_no_meeting"] = [r for r in (_parse_day_range(v) for v in used["no_meeting_blocks"]) if r]
    if not 0 <= used["slack_share"] < 1:
        raise VaultError(f"slack_share must be between 0 and 1, got {used['slack_share']!r}.")
    for key in ("focus_block_minutes", "admin_block_minutes"):
        if used[key] <= 0:
            raise VaultError(f"{key} must be above 0.")
    return used


def _block(day: date, lo: int, hi: int, kind: str, subject: str, priority: Optional[dict[str, Any]], existing: bool, ev: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "date": day.isoformat(),
        "day": _day_label(day),
        "start": f"{day.isoformat()}T{_minutes_hhmm(lo)}:00",
        "end": f"{day.isoformat()}T{_minutes_hhmm(hi)}:00",
        "minutes": hi - lo,
        "kind": kind,
        "subject": subject,
        "priority": priority["name"] if priority else None,
        "page": priority["page"] if priority else None,
        "existing": existing,
    }
    if ev is not None:
        out["occurrence_key"] = _s(ev.get("occurrence_key"))
        out["entry_id"] = _s(ev.get("entry_id"))
    return out


def _place_focus(free: list[Interval], peak: list[Interval], minutes: int) -> Optional[Interval]:
    """The block inside the largest free piece within peak hours, else the largest piece outside."""
    inside = _intersect(free, peak)
    outside = free
    for piece in peak:
        outside = _subtract(outside, piece)
    for pieces in (inside, outside):
        fit = [(lo, hi) for lo, hi in pieces if hi - _round_up(lo) >= minutes]
        if fit:
            lo, hi = max(fit, key=lambda p: (p[1] - p[0], -p[0]))
            start = _round_up(lo)
            return start, start + minutes
    return None


def _place_admin(free: list[Interval], peak: list[Interval], minutes: int, n: int) -> Optional[Interval]:
    """Admin block number ``n`` (0-based) outside peak hours: the first ends at
    or before the lunch line, the second at the end of the day, more in the
    earliest gap; any fitting gap when the wanted half has none."""
    outside = free
    for piece in peak:
        outside = _subtract(outside, piece)
    fit = [(lo, hi) for lo, hi in outside if _round_down(hi) - _round_up(lo) >= minutes]
    if not fit:
        return None

    def end_aligned(lo: int, hi: int) -> Interval:
        end = _round_down(hi)
        return end - minutes, end

    def start_aligned(lo: int, hi: int) -> Interval:
        start = _round_up(lo)
        return start, start + minutes

    if n == 0:
        morning = [(lo, min(hi, LUNCH)) for lo, hi in fit if lo < LUNCH]
        morning = [(lo, hi) for lo, hi in morning if _round_down(hi) - _round_up(lo) >= minutes]
        if morning:
            return end_aligned(*max(morning, key=lambda p: p[1]))
        return start_aligned(*fit[0])
    if n == 1:
        afternoon = [(max(lo, LUNCH), hi) for lo, hi in fit if hi > LUNCH]
        afternoon = [(lo, hi) for lo, hi in afternoon if _round_down(hi) - _round_up(lo) >= minutes]
        if afternoon:
            return end_aligned(*max(afternoon, key=lambda p: p[1]))
        return end_aligned(*fit[-1])
    return start_aligned(*fit[0])


def plan(week: str, events: list[dict[str, Any]], today: Any, preferences: dict[str, Any], priorities: list[dict[str, Any]], missing_keys: Optional[list[str]] = None, now: Any = None, peak_hours: Optional[list[str]] = None) -> dict[str, Any]:
    """Plan focus and admin blocks for ``week`` (``2026-W35``) on the working
    days from ``today`` on. Pure: the same inputs give the same plan.

    Per day: the work window minus the events (with ``buffer_minutes`` on
    both sides; ``[Focus]`` / ``[Admin]`` appointments are kept as
    ``existing`` blocks without a buffer, events marked free are ignored)
    minus the ``no_meeting_blocks``. Bookable minutes are
    ``(1 - slack_share) * work minutes - meeting minutes``; a day with none
    left goes to ``skipped_days``. Focus blocks go to the largest free piece
    inside ``peak_hours`` first, admin blocks outside them, one before lunch
    and one at the end of the day when possible. Rank 1 of ``priorities``
    takes every other focus block of the week, the others follow in order.
    ``now`` (``HH:MM``, local) only matters on ``today``: nothing is placed
    before it, and a day whose work hours are over is skipped. ``peak_hours``
    replaces the preferences' peak hours for this plan only."""
    start, end = _iso_week(week)
    today_d = _parse_day(today, "today")
    now_min = _hhmm_minutes(now, "now") if now not in (None, "") else None
    if peak_hours is not None:
        preferences = dict(preferences or {}, peak_hours=list(peak_hours))
    prefs = _plan_preferences(preferences)
    work_lo, work_hi = prefs["_work"]
    work_minutes = work_hi - work_lo
    focus_len, admin_len = prefs["focus_block_minutes"], prefs["admin_block_minutes"]
    ranked = [{"rank": p.get("rank") or i + 1, "name": _s(p.get("name")), "page": p.get("page"), "due": _s(p.get("due"))[:10] or None}
              for i, p in enumerate(priorities or []) if _s(p.get("name"))]

    days: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    new_focus: list[dict[str, Any]] = []
    for offset in range(WORKING_DAYS):
        day = start + timedelta(days=offset)
        if day < today_d:
            skipped.append({"date": day.isoformat(), "reason": "already past"})
            continue
        todays = [ev for ev in events or [] if isinstance(ev, dict)]
        blocking = [ev for ev in todays if _is_all_day(ev) and _busy(ev) and _covers_day(ev, day)]
        if blocking:
            skipped.append({"date": day.isoformat(), "reason": f"all day: {_s(blocking[0].get('subject')).strip() or '(no subject)'}"})
            continue
        free: list[Interval] = [(work_lo, work_hi)]
        if day == today_d and now_min is not None:
            if _round_up(now_min) >= work_hi:
                skipped.append({"date": day.isoformat(), "reason": f"work hours are over at {_minutes_hhmm(now_min)}"})
                continue
            if _round_up(now_min) > work_lo:
                free = _subtract(free, (work_lo, _round_up(now_min)))
        meeting_minutes = 0
        existing: list[dict[str, Any]] = []
        for ev in todays:
            if _is_all_day(ev) or not _busy(ev):
                continue
            span = _event_minutes(ev, day, (work_lo, work_hi))
            if span is None:
                continue
            kind = _kind_of(ev.get("subject"))
            if kind:
                subject = _s(ev.get("subject")).strip()
                prio = _priority_of(subject) if kind == "focus" else None
                existing.append(_block(day, span[0], span[1], kind, subject, {"name": prio, "page": None} if prio else None, True, ev))
                free = _subtract(free, span)
                continue
            meeting_minutes += span[1] - span[0]
            free = _subtract(free, (span[0] - prefs["buffer_minutes"], span[1] + prefs["buffer_minutes"]))
        for weekday, rng in prefs["_no_meeting"]:
            if weekday == day.weekday():
                free = _subtract(free, rng)
        bookable = int((1 - prefs["slack_share"]) * work_minutes) - meeting_minutes
        if bookable <= 0:
            skipped.append(
                {
                    "date": day.isoformat(),
                    "reason": f"meetings take {meeting_minutes} of {work_minutes} work minutes; the slack share of {prefs['slack_share']:g} leaves nothing to book",
                    "meeting_minutes": meeting_minutes,
                    "existing": existing,
                }
            )
            continue
        blocks = list(existing)
        left = bookable - sum(b["minutes"] for b in existing)
        n_focus = sum(1 for b in existing if b["kind"] == "focus")
        while n_focus < prefs["focus_blocks_per_day"] and left >= focus_len:
            span = _place_focus(free, prefs["_peak"], focus_len)
            if span is None:
                break
            b = _block(day, span[0], span[1], "focus", "", None, False)
            blocks.append(b)
            new_focus.append(b)
            free = _subtract(free, span)
            left -= focus_len
            n_focus += 1
        n_admin = sum(1 for b in existing if b["kind"] == "admin")
        while n_admin < prefs["admin_blocks_per_day"] and left >= admin_len:
            span = _place_admin(free, prefs["_peak"], admin_len, n_admin)
            if span is None:
                break
            blocks.append(_block(day, span[0], span[1], "admin", ADMIN_SUBJECT, None, False))
            free = _subtract(free, span)
            left -= admin_len
            n_admin += 1
        blocks.sort(key=lambda b: b["start"])
        booked = sum(b["minutes"] for b in blocks)
        days.append(
            {
                "date": day.isoformat(),
                "day": _day_label(day),
                "work_minutes": work_minutes,
                "meeting_minutes": meeting_minutes,
                "bookable_minutes": bookable,
                "booked_minutes": booked,
                "slack_minutes": work_minutes - meeting_minutes - booked,
                "blocks": blocks,
            }
        )

    # a deadline pass first: what falls due this week gets a block before its due day
    free_focus = list(range(len(new_focus)))
    deadlines: list[dict[str, Any]] = []
    for p in sorted([r for r in ranked if r.get("due")], key=lambda r: (_s(r["due"]), r["rank"])):
        due = _s(p["due"])
        before = [i for i in free_focus if new_focus[i]["date"] < due]
        on_day = [i for i in free_focus if new_focus[i]["date"] == due]
        pick = before[-1] if before else (on_day[-1] if on_day else (free_focus[0] if free_focus else None))
        if pick is not None:
            free_focus.remove(pick)
            b = new_focus[pick]
            b["priority"], b["page"] = p["name"], p["page"]
            b["subject"] = f"{FOCUS_PREFIX} {p['name']}"
        deadlines.append({"name": p["name"], "due": due, "page": p["page"],
                          "block_date": new_focus[pick]["date"] if pick is not None else None})
    # rank 1 takes every other new focus block left; the rest cycle in rank order
    rest = [r for r in ranked if not r.get("due")] or ranked
    others = rest[1:]
    k = 0
    for i, idx in enumerate(free_focus):
        b = new_focus[idx]
        if not rest:
            prio = None
        elif i % 2 == 0 or not others:
            prio = rest[0]
        else:
            prio = others[k % len(others)]
            k += 1
        b["priority"] = prio["name"] if prio else None
        b["page"] = prio["page"] if prio else None
        b["subject"] = f"{FOCUS_PREFIX} {prio['name'] if prio else NO_PRIORITY}"
    placed = {wiki._norm(b["priority"]) for d in days for b in d["blocks"] if b["kind"] == "focus" and b["priority"]}
    missed = {wiki._norm(d["name"]): f"no focus block before {d['due']}" for d in deadlines if d["block_date"] is None}
    unplaced = [dict(p, reason=missed.get(wiki._norm(p["name"]), "no focus block left this week")) for p in ranked if wiki._norm(p["name"]) not in placed]
    focus_minutes = sum(b["minutes"] for d in days for b in d["blocks"] if b["kind"] == "focus")
    admin_minutes = sum(b["minutes"] for d in days for b in d["blocks"] if b["kind"] == "admin")
    kept = min((d["slack_minutes"] / d["work_minutes"] for d in days if d["work_minutes"]), default=None)
    return {
        "week": week,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "today": today_d.isoformat(),
        "priorities": ranked,
        "days": days,
        "totals": {
            "focus_minutes": focus_minutes,
            "admin_minutes": admin_minutes,
            "new_blocks": sum(1 for d in days for b in d["blocks"] if not b["existing"]),
            "existing_blocks": sum(1 for d in days for b in d["blocks"] if b["existing"]),
            "slack_share_kept": round(kept, 2) if kept is not None else None,
        },
        "deadlines": deadlines,
        "unplaced": unplaced,
        "skipped_days": skipped,
        "preferences_used": {k: prefs[k] for k in PLAN_KEYS},
        "missing_keys": list(missing_keys or []),
    }


def time_block_plan(week: str, events: list[dict[str, Any]], today: Optional[str] = None, now: Optional[str] = None, peak_hours: Optional[list[str]] = None) -> dict[str, Any]:
    """``vault_time_block(action="plan")``: ``plan`` with the vault's preferences and priorities
    (``peak_hours`` overrides the file's for this run; nothing is written)."""
    root = store.vault_root()
    today_d = _parse_day(today, "today") if today else date.today()
    prefs = store.read_preferences()
    week_end = _iso_week(week)[1]
    return plan(week, events, today_d, prefs["preferences"], read_priorities(root, today_d, week_end), prefs["missing"], now=now, peak_hours=peak_hours)


# ------------------------------------------------------------------ write


def _block_key(b: dict[str, Any]) -> str:
    return _s(b.get("occurrence_key")).strip() or _s(b.get("entry_id")).strip() or f"{_s(b.get('start'))} {_s(b.get('subject'))}".strip()


def _plan_rows(blocks: list[dict[str, Any]]) -> list[str]:
    rows = []
    for b in sorted(blocks, key=lambda b: _s(b.get("start"))):
        start = _parse_local(b.get("start"))
        day = _day_label(start.date()) if start else _s(b.get("day"))
        cells = [day, workflows._hhmm(b.get("start")), workflows._hhmm(b.get("end")), _s(b.get("kind")), _s(b.get("subject")), _s(b.get("priority")) or "—"]
        cells[-1] = f"{cells[-1]} <!-- occurrence_key: {_block_key(b)}{PLAN_KEY_SUFFIX} -->"
        rows.append(store._row_line(cells))
    return rows


def write(week: str, blocks: list[dict[str, Any]], created_by: str = CREATED_BY) -> dict[str, Any]:
    """``vault_time_block(action="write")``: Time-blocks/<week>.md with the ``## Plan``
    table (one row per block, hidden occurrence_key), an empty ``## Held``
    table for the day's answers and ``## Notes``. A second write for the
    same week appends the new plan under ``## Update``."""
    start, end = _iso_week(week)
    blocks = [b for b in blocks or [] if isinstance(b, dict) and _s(b.get("start"))]
    if not blocks:
        raise NoteError("blocks is empty; pass the plan blocks with the create results.")
    existing = store.find("time-block", {"week": week})
    fm: dict[str, Any] = {
        "type": "time-block",
        "source": "soma",
        "week": week,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "planned": len(blocks),
        "created_by": created_by,
    }
    table = workflows._table(PLAN_HEADER, []) + _plan_rows(blocks)
    if existing["found"]:
        old = existing["frontmatter"]
        fm["planned"] = int(old.get("planned") or 0) + len(blocks)
        fm["created_by"] = _s(old.get("created_by")) or created_by
        lines = ["### Plan", ""] + table
    else:
        held = workflows._table(HELD_HEADER, [])
        lines = [
            f"# Time blocks — {week}",
            "",
            f"Week of {_day_label(start)} to {_day_label(end)}. Planned by /soma:time-block; "
            "the appointments live in Outlook, this note keeps the plan and how it went.",
            "",
            "## Plan",
            "",
            *table,
            "",
            "## Held",
            "",
            *held,
            "",
            "## Notes",
            "",
        ]
    res = store.write("time-block", fm, "\n".join(lines), "upsert")
    return {"path": res["path"], "action": res["action"], "week": week, "blocks": len(blocks), "planned": fm["planned"]}


# ------------------------------------------------------------------ audit


def read_held_rows(root: Path, week: str) -> list[dict[str, str]]:
    """The rows of every Held table in Time-blocks/<week>.md as
    {day, block, result, note, key} (key = the hidden occurrence_key)."""
    hit = store.find("time-block", {"week": week})
    if not hit["found"]:
        return []
    body = fmt.split_note(read_text(resolve(root, hit["path"])))[2]
    lines = body.split("\n")
    out = []
    for level, heading, lo, hi in workflows._sections(body):
        if heading.strip().lower() != "held":
            continue
        for rows in workflows._tables(lines, lo, hi):
            for row in rows:
                cells = {k.lower(): v for k, v in row.items() if k != "_line"}
                key = (store._comment_key(row["_line"]) or "").split(" # ", 1)[0].strip()
                out.append(
                    {
                        "day": workflows._strip_comment(cells.get("day", "")),
                        "block": workflows._strip_comment(cells.get("block", "")),
                        "result": workflows._strip_comment(cells.get("result", "")).lower(),
                        "note": workflows._strip_comment(cells.get("note", "")),
                        "key": key,
                    }
                )
    return out


def _hours(minutes: int) -> float:
    return round(minutes / 60, 1)


def _held_for(ev: dict[str, Any], day: date, held_rows: list[dict[str, str]]) -> Optional[dict[str, str]]:
    key = _s(ev.get("occurrence_key")).strip()
    eid = _s(ev.get("entry_id")).strip()
    subject = _s(ev.get("subject")).strip()
    ids = {k for k in (key, eid) if k}
    for row in held_rows:
        if row["key"] and row["key"] in ids:
            return row
    label = _day_label(day)
    for row in held_rows:
        if not row["key"] and row["day"] == label and row["block"] == subject:
            return row
    return None


def audit(week: str, events: list[dict[str, Any]], held_rows: Optional[list[dict[str, str]]] = None, preferences: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """``vault_time_block(action="audit")``: hours per kind for the week's timed events
    (focus, admin, meeting, other; all-day and free-marked events skipped), the Held rows
    applied (skipped blocks count as unplanned, moved ones keep their
    minutes), per-priority planned and held hours, and the lines for the
    weekly note's ``## Time`` section."""
    start, end = _iso_week(week)
    prefs = _plan_preferences(preferences or {})
    work_lo, work_hi = prefs["_work"]
    work_minutes = (work_hi - work_lo) * WORKING_DAYS
    held_rows = held_rows or []
    minutes = {"meeting": 0, "focus": 0, "admin": 0, "other": 0, "unplanned": 0}
    counts = {"planned": 0, "held": 0, "moved": 0, "skipped": 0, "unanswered": 0}
    per_priority: dict[str, dict[str, Any]] = {}
    for ev in events or []:
        if not isinstance(ev, dict) or _is_all_day(ev) or not _busy(ev):
            continue
        s, e = _parse_local(ev.get("start")), _parse_local(ev.get("end"))
        if s is None or e is None or e <= s or not (start <= s.date() <= end):
            continue
        length = int((e - s).total_seconds() // 60)
        kind = _kind_of(ev.get("subject")) or ("meeting" if _is_meeting(ev) else "other")
        if kind in ("focus", "admin"):
            counts["planned"] += 1
            row = _held_for(ev, s.date(), held_rows)
            result = row["result"] if row else ""
            if result in HELD_RESULTS:
                counts[result] += 1
            else:
                counts["unanswered"] += 1
            if result != "skipped":
                minutes[kind] += length  # a skipped block's minutes fall into unplanned below
            if kind == "focus":
                name = _priority_of(ev.get("subject")) or NO_PRIORITY
                entry = per_priority.setdefault(name, {"name": name, "planned": 0, "held": 0})
                entry["planned"] += length
                if result in ("held", "moved"):
                    entry["held"] += length
        else:
            minutes[kind] += length
    booked = minutes["meeting"] + minutes["focus"] + minutes["admin"] + minutes["other"]
    minutes["unplanned"] = max(0, work_minutes - booked)
    hours = {k: _hours(v) for k, v in minutes.items()}
    work_hours = _hours(work_minutes)
    shares = {k: (round(v / work_minutes, 2) if work_minutes else None) for k, v in minutes.items()}
    prio_out = [
        {"name": p["name"], "planned_hours": _hours(p["planned"]), "held_hours": _hours(p["held"])}
        for p in sorted(per_priority.values(), key=lambda p: (-p["planned"], p["name"].lower()))
    ]

    def pct(k: str) -> str:
        return f" ({round(100 * shares[k])}%)" if shares[k] is not None else ""

    lines = [
        f"Meetings {hours['meeting']:g} h{pct('meeting')}, focus {hours['focus']:g} h{pct('focus')}, "
        f"admin {hours['admin']:g} h{pct('admin')}, other {hours['other']:g} h{pct('other')}, "
        f"unplanned {hours['unplanned']:g} h{pct('unplanned')} of {work_hours:g} work hours.",
    ]
    if counts["planned"]:
        parts = [f"{counts['held']} held", f"{counts['moved']} moved", f"{counts['skipped']} skipped"]
        if counts["unanswered"]:
            parts.append(f"{counts['unanswered']} unanswered")
        lines.append(f"Blocks: {counts['planned']} planned — {', '.join(parts)}.")
    else:
        lines.append("Blocks: none planned this week.")
    if prio_out:
        lines.append("Focus: " + "; ".join(f"{p['name']} {p['planned_hours']:g} h planned, {p['held_hours']:g} h held" for p in prio_out) + ".")
    return {
        "week": week,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "hours": hours,
        "work_hours": work_hours,
        "shares": shares,
        "per_priority": prio_out,
        "blocks": counts,
        "held_rows": len(held_rows),
        "lines": lines,
    }


def time_audit(week: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    """``vault_time_block(action="audit")``: ``audit`` with the week note's Held rows and the vault's preferences."""
    root = store.vault_root()
    return audit(week, events, read_held_rows(root, week), store.read_preferences()["preferences"])
