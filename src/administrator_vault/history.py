"""``vault_load_history``: read the past into the wiki, one window at a time.

The pass walks Outlook's inbox, Outlook's sent items and the Teams chats from a
start date (90 days back by default) forward to the day collect-information
already covers, and hands the model one window of days at a time. Nothing here
reads mail or chats: ``next`` returns the exact call the model makes, and the
model reports back with ``done``.

The state lives in ``Administrator/Wiki/_cache/history.json`` — the place each
source got to, the ids already seen, the totals, and the window that is open
right now. It is written after ``plan`` and after every ``done``, so a crash
costs at most one window: ``next`` then hands the open window out again
unchanged, and reading the same records twice is harmless (``save_email``
upserts, ``save_chat`` drops message ids it already has, and an ingest skips a
page whose Records already name the record).

The "last collected" stamps of ``workflows.collect_sources`` are only read, to
fix the upper bound of each source at plan time. This module never moves them.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from administrator_vault import store, wiki
from administrator_vault.store import VaultError, read_text, resolve
from administrator_vault.wiki import _atomic_write, _s
from administrator_vault.workflows import _collect_stamps, _date_of, _local, _parse_dt

VERSION = 1
PATH = f"{wiki.CACHE_DIR}/history.json"
SOURCES = ("outlook_inbox", "outlook_sent", "teams")
SOURCE_WORDS = {"outlook_inbox": "Outlook inbox", "outlook_sent": "Outlook sent items", "teams": "Teams chats"}
STREAM = {"outlook_inbox": "outlook", "outlook_sent": "outlook", "teams": "teams"}  # where the seen ids are kept
STAMP = {"outlook_inbox": "outlook", "outlook_sent": "outlook", "teams": "teams"}  # the collect stamp that bounds it
FOLDER = {"outlook_inbox": "inbox", "outlook_sent": "sent"}
MAIL_FIELDS = ("entry_id", "internet_message_id", "subject", "from", "from_address", "to", "received", "preview")
DEFAULT_DAYS = 90
DEFAULT_BATCH = 25
BATCH_MAX = 100
DEFAULT_WINDOW = 7
WINDOW_MIN = 1
WINDOW_MAX = 30
PAGES_MAX = 1000  # how many touched pages the state keeps
PAGES_SHOWN = 40  # how many of them status hands back (totals.pages is the count)
LINT_LINE = "Run /administrator:lint."


# ------------------------------------------------------------------ small helpers


def _dt(value: Any, what: str) -> datetime:
    """An ISO date or datetime as an aware datetime; a naive one is local time."""
    s = _s(value).strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    parsed = _parse_dt(s)
    if parsed is None:
        raise VaultError(f"'{what}' must be an ISO date or datetime, got {value!r}.")
    return _local(parsed)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _now(value: Any = None) -> datetime:
    if value in (None, ""):
        return datetime.now().astimezone()
    return _dt(value, "now")


def _day(value: Any) -> str:
    """``2026-06-01T09:00:00+02:00`` -> ``2026-06-01``."""
    return _date_of(value)


def _days_between(later: datetime, earlier: datetime) -> int:
    return max(0, math.ceil((later - earlier).total_seconds() / 86400))


# ------------------------------------------------------------------ the state file


def _blank(since: datetime, batch: int, until_max: dict[str, str], started: datetime) -> dict[str, Any]:
    return {
        "version": VERSION,
        "since": _iso(since),
        "started": _iso(started),
        "batch": batch,
        "window_days": DEFAULT_WINDOW,
        "until_max": until_max,
        "sources": {s: {"place": None, "done": False, "listed": 0, "saved": 0} for s in SOURCES},
        "current": None,
        "batches_done": 0,
        "records_saved": 0,
        "pages_touched": [],
        # id -> the date the record carried, so a window listed again names only its own ids
        "seen": {"outlook": {}, "teams": {}},
        "calls": 0,
        "finished": None,
    }


def read_state(root: Path) -> Optional[dict[str, Any]]:
    """The state, or None when no pass was planned (or the file cannot be read)."""
    p = root / PATH
    if not p.is_file():
        return None
    try:
        data = json.loads(read_text(p))
    except (ValueError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return None
    if not isinstance(data.get("sources"), dict) or not isinstance(data.get("until_max"), dict):
        return None
    if any(s not in data["sources"] or s not in data["until_max"] for s in SOURCES):
        return None
    if not _s(data.get("since")):
        return None
    for key, default in (
        ("batch", DEFAULT_BATCH), ("window_days", DEFAULT_WINDOW), ("batches_done", 0),
        ("records_saved", 0), ("calls", 0), ("started", ""), ("finished", None),
    ):
        data.setdefault(key, default)
    for source in SOURCES:
        info = data["sources"][source]
        if not isinstance(info, dict):
            return None
        for key, default in (("place", None), ("done", False), ("listed", 0), ("saved", 0)):
            info.setdefault(key, default)
    if not isinstance(data.get("pages_touched"), list):
        data["pages_touched"] = []
    cur = data.get("current")
    if not (isinstance(cur, dict) and cur.get("source") in SOURCES and all(cur.get(k) not in (None, "") for k in ("n", "since", "until"))):
        data["current"] = None  # an open window the file cannot describe is forgotten; next hands out a fresh one
    seen = data.get("seen") or {}
    data["seen"] = {stream: _seen_map(seen.get(stream)) for stream in ("outlook", "teams")}
    return data


def _seen_map(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return {_s(k): _s(v) for k, v in raw.items()}
    if isinstance(raw, list):  # a list of bare ids: kept, with no date to place them
        return {_s(v): "" for v in raw}
    return {}


def _write_state(root: Path, state: dict[str, Any]) -> None:
    _atomic_write(resolve(root, PATH), json.dumps(state, ensure_ascii=False, indent=1))


def _need_state(root: Path, action: str) -> dict[str, Any]:
    state = read_state(root)
    if state is None:
        raise VaultError(f"No pass is running: call vault_load_history(action='plan') before '{action}'.")
    return state


# ------------------------------------------------------------------ places and windows


def _place(state: dict[str, Any], source: str) -> str:
    return _s(state["sources"][source].get("place")) or _s(state["since"])


def _cap(state: dict[str, Any], source: str) -> str:
    return _s(state["until_max"].get(source))


def _left_days(state: dict[str, Any], source: str) -> int:
    if state["sources"][source].get("done"):
        return 0
    return _days_between(_dt(_cap(state, source), "until_max"), _dt(_place(state, source), "place"))


def _mark_done(state: dict[str, Any], now: datetime) -> None:
    """A source is finished once its place reached the bound fixed at plan time."""
    for source in SOURCES:
        info = state["sources"][source]
        if _dt(_place(state, source), "place") >= _dt(_cap(state, source), "until_max"):
            info["done"] = True
    if all(state["sources"][s].get("done") for s in SOURCES) and not state.get("finished"):
        state["finished"] = _iso(now)


def _open_source(state: dict[str, Any]) -> Optional[str]:
    for source in SOURCES:
        if not state["sources"][source].get("done"):
            return source
    return None


def _window(state: dict[str, Any], source: str) -> tuple[str, str]:
    since = _dt(_place(state, source), "place")
    cap = _dt(_cap(state, source), "until_max")
    until = min(since + timedelta(days=int(state["window_days"])), cap)
    return _iso(since), _iso(until)


def _list_with(source: str, since: str, until: str) -> str:
    """The exact call the model makes for this window."""
    if source == "teams":
        return (
            f'teams_list_chats(since="{since}", until="{until}", include_messages=true, '
            f"per_chat=20, max_chars=300, limit=15)"
        )
    fields = "[" + ", ".join(f'"{f}"' for f in MAIL_FIELDS) + "]"
    return (
        f'outlook_list_mails(folder="{FOLDER[source]}", since="{since}", until="{until}", '
        f"limit=100, preview_chars=80, fields={fields})"
    )


def _skip_ids(state: dict[str, Any], source: str, since: str, until: str) -> list[str]:
    """The ids of that source already seen inside this window."""
    lo, hi = _day(since), _day(until)
    seen = state["seen"].get(STREAM[source]) or {}
    return sorted(i for i, when in seen.items() if not when or lo <= when <= hi)


def _next_hint(state: dict[str, Any]) -> Optional[dict[str, Any]]:
    source = _open_source(state)
    if source is None:
        return None
    since, until = _window(state, source)
    return {"source": source, "since": since, "until": until}


def _totals(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "batches": state["batches_done"],
        "records": state["records_saved"],
        "pages": max(int(state.get("pages_count") or 0), len(state["pages_touched"])),
        "calls": state["calls"],
        "sources": {
            s: {
                "listed": state["sources"][s]["listed"],
                "saved": state["sources"][s]["saved"],
                "done": bool(state["sources"][s]["done"]),
                "left_days": _left_days(state, s),
            }
            for s in SOURCES
        },
    }


def _summary(state: dict[str, Any]) -> str:
    per = ", ".join(f"{SOURCE_WORDS[s]} {state['sources'][s]['saved']}" for s in SOURCES)
    return (
        f"All sources are done: {state['records_saved']} records saved in {state['batches_done']} batches "
        f"({per}), {max(int(state.get('pages_count') or 0), len(state['pages_touched']))} pages touched. {LINT_LINE}"
    )


# ------------------------------------------------------------------ status


def status(root: Path, now: datetime) -> dict[str, Any]:
    """The state plus the collect stamps, the days left per source and how many
    records each source listed against how many were saved."""
    stamps = _collect_stamps(root)
    state = read_state(root)
    if state is None:
        note = "No pass has been planned: vault_load_history(action='plan') starts one."
        if not any(stamps.get(STAMP[s]) for s in SOURCES):
            note += " There is no 'last collected' stamp yet, so a pass would stop at now — collect-information first."
        return {"started": False, "path": PATH, "stamps": stamps, "note": note}
    _mark_done(state, now)
    out = {k: v for k, v in state.items() if k != "seen"}
    out["path"] = PATH
    out["stamps"] = stamps
    out["pages_touched"] = state["pages_touched"][-PAGES_SHOWN:]
    out["seen_counts"] = {stream: len(ids) for stream, ids in state["seen"].items()}
    out["left_days"] = {s: _left_days(state, s) for s in SOURCES}
    out["sources"] = {
        s: {
            **state["sources"][s],
            "until_max": _cap(state, s),
            "left_days": _left_days(state, s),
            "gap": state["sources"][s]["listed"] - state["sources"][s]["saved"],
        }
        for s in SOURCES
    }
    out["totals"] = _totals(state)
    out["next_hint"] = _next_hint(state)
    if state.get("finished"):
        out["note"] = _summary(state)
    elif state.get("current"):
        cur = state["current"]
        out["note"] = (
            f"Batch {cur['n']} is open ({SOURCE_WORDS[cur['source']]} {_day(cur['since'])}–{_day(cur['until'])}): "
            "list it again with action='next', then report it with action='done'."
        )
    else:
        left = sum(out["left_days"].values())
        out["note"] = f"{left} days left over the three sources; action='next' hands out the following window."
    return out


# ------------------------------------------------------------------ plan


def plan(root: Path, since: Any, batch: int, reset: bool, now: datetime) -> dict[str, Any]:
    """Fix the start date and, per source, the day the pass stops at (the collect
    stamp, else now). Writes the state and nothing else."""
    try:
        batch = int(batch)
    except (TypeError, ValueError):
        raise VaultError(f"'batch' must be a whole number, got {batch!r}.") from None
    if not 1 <= batch <= BATCH_MAX:
        raise VaultError(f"'batch' must be between 1 and {BATCH_MAX}, got {batch}.")
    old = read_state(root)
    if old is not None and not old.get("finished") and not reset:
        return {
            "planned": False,
            "refused": "already-running",
            "note": (
                f"A pass is already running ({old['batches_done']} batches done, "
                f"{old['records_saved']} records saved). Carry on with action='next', "
                "or start over with plan and reset=true."
            ),
            "status": status(root, now),
        }
    if since in (None, ""):
        start = (now - timedelta(days=DEFAULT_DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start = _dt(since, "since")
    stamps = _collect_stamps(root)
    until_max = {}
    for source in SOURCES:
        stamp = stamps.get(STAMP[source])
        until_max[source] = _iso(_dt(stamp, "stamp")) if stamp else _iso(now)
    state = _blank(start, batch, until_max, now)
    kept_ids = 0
    if old is not None and not reset:  # the finished pass hands its ids on
        state["seen"] = {stream: dict(old["seen"].get(stream) or {}) for stream in ("outlook", "teams")}
        kept_ids = sum(len(ids) for ids in state["seen"].values())
    _mark_done(state, now)
    _write_state(root, state)
    caps = [_dt(v, "until_max") for v in until_max.values()]
    out = {
        "planned": True,
        "path": PATH,
        "since": state["since"],
        "batch": batch,
        "window_days": state["window_days"],
        "until_max": until_max,
        "stamps": stamps,
        "days": _days_between(max(caps), start),
        "left_days": {s: _left_days(state, s) for s in SOURCES},
        "batches_estimate": sum(math.ceil(_left_days(state, s) / state["window_days"]) for s in SOURCES),
        "sources": {s: {**state["sources"][s], "until_max": until_max[s], "left_days": _left_days(state, s)} for s in SOURCES},
        "started_over": bool(old is not None and reset),
        "kept_ids": kept_ids,
        "next_hint": _next_hint(state),
    }
    parts = [
        f"Reading {SOURCE_WORDS['outlook_inbox']}, {SOURCE_WORDS['outlook_sent']} and {SOURCE_WORDS['teams']} "
        f"from {_day(state['since'])} forward, {batch} records per batch, "
        f"about {out['batches_estimate']} batches."
    ]
    if not any(stamps.get(STAMP[s]) for s in SOURCES):
        parts.append("No 'last collected' stamp yet, so each source stops at now; collect-information keeps its own stamps.")
    if state.get("finished"):
        parts.append("Every source is already covered by collect-information — there is nothing older to read.")
    if out["started_over"]:
        parts.append("The previous pass was dropped; records already saved are not read again by name, only skipped downstream.")
    elif kept_ids:
        parts.append(f"The {kept_ids} ids the finished pass read are kept, so what it covered comes back as skip_ids.")
    out["note"] = " ".join(parts)
    return out


# ------------------------------------------------------------------ next


def next_batch(root: Path, now: datetime) -> dict[str, Any]:
    """The window to list. An open batch is handed out again unchanged instead of
    a second one being started."""
    state = _need_state(root, "next")
    _mark_done(state, now)
    current = state.get("current")
    if current:
        since, until = _s(current["since"]), _s(current["until"])
        return {
            "batch_no": current["n"],
            "source": current["source"],
            "since": since,
            "until": until,
            "expected": current["expected"],
            "skip_ids": _skip_ids(state, current["source"], since, until),
            "list_with": _list_with(current["source"], since, until),
            "reissued": True,
            "issued": current.get("issued"),
            "note": (
                f"Batch {current['n']} is still open, so this is the same window again. "
                "Report it with action='done' before asking for another one."
            ),
        }
    source = _open_source(state)
    if source is None:
        _write_state(root, state)
        return {
            "batch_no": None,
            "source": None,
            "all_done": True,
            "finished": state.get("finished"),
            "totals": _totals(state),
            "note": _summary(state),
        }
    since, until = _window(state, source)
    batch_no = int(state["batches_done"]) + 1
    state["current"] = {
        "n": batch_no,
        "source": source,
        "since": since,
        "until": until,
        "expected": int(state["batch"]),
        "issued": _iso(now),
    }
    _write_state(root, state)
    return {
        "batch_no": batch_no,
        "source": source,
        "since": since,
        "until": until,
        "expected": int(state["batch"]),
        "skip_ids": _skip_ids(state, source, since, until),
        "list_with": _list_with(source, since, until),
        "reissued": False,
        "issued": state["current"]["issued"],
        "note": (
            f"{SOURCE_WORDS[source]}, {_day(since)}–{_day(until)}: list it with the call above, turn the list "
            f"oldest first, drop skip_ids and automated mail, and work on the first {state['batch']}."
        ),
    }


# ------------------------------------------------------------------ done


def _saved_entries(raw: Any) -> list[dict[str, str]]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise VaultError("payload['saved'] must be a list of {id, path, received}.")
    out = []
    for entry in raw:
        if isinstance(entry, str):
            entry = {"id": entry}
        if not isinstance(entry, dict):
            raise VaultError("payload['saved'] must be a list of {id, path, received}.")
        ident = _s(entry.get("id")).strip()
        if not ident:
            raise VaultError("Every saved record needs an 'id' (the mail's id, or 'chat_id|date' for a chat).")
        out.append({"id": ident, "path": _s(entry.get("path")).strip(), "received": _s(entry.get("received")).strip()})
    return out


def _string_list(raw: Any, what: str) -> list[str]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise VaultError(f"payload[{what!r}] must be a list of strings.")
    return [s for s in (_s(v).strip() for v in raw) if s]


def _adapt(window_days: int, listed: int, batch: int) -> int:
    """A window that listed far more than one batch is halved, one that listed
    far less is doubled; 1 to 30 days."""
    if listed > 2 * batch:
        return max(WINDOW_MIN, window_days // 2)
    if listed < batch / 2:
        return min(WINDOW_MAX, window_days * 2)
    return window_days


def done(root: Path, payload: Any, now: datetime) -> dict[str, Any]:
    """Record what the model saved, move the place, and hand back the totals."""
    state = _need_state(root, "done")
    current = state.get("current")
    if not current:
        raise VaultError("No batch is open: call vault_load_history(action='next') first.")
    if payload in (None, ""):
        payload = {}
    if not isinstance(payload, dict):
        raise VaultError("'payload' must be an object with saved, skipped_ids, reached, exhausted, pages and calls.")
    source = _s(current["source"])
    stream = STREAM[source]
    since, until = _s(current["since"]), _s(current["until"])
    saved = _saved_entries(payload.get("saved"))
    skipped = _string_list(payload.get("skipped_ids"), "skipped_ids")
    pages = _string_list(payload.get("pages"), "pages")
    exhausted = bool(payload.get("exhausted"))
    reached_raw = payload.get("reached")
    if exhausted:
        place = _dt(until, "until")
    else:
        if reached_raw in (None, ""):
            raise VaultError("payload needs 'reached' (the received time of the last record worked) unless exhausted is true.")
        place = min(max(_dt(reached_raw, "reached"), _dt(since, "since")), _dt(until, "until"))
    stalled = not exhausted and place <= _dt(since, "since")

    seen = state["seen"].setdefault(stream, {})
    for entry in saved:
        seen[entry["id"]] = _day(entry["received"]) or _day(place)
    for ident in skipped:
        seen.setdefault(ident, _day(place) or _day(until))

    listed_raw = payload.get("listed")
    try:
        listed = int(listed_raw) if listed_raw not in (None, "") else len(saved) + len(skipped)
    except (TypeError, ValueError):
        listed = len(saved) + len(skipped)
    listed = max(listed, len(saved) + len(skipped))
    batch = int(state["batch"])
    state["window_days"] = _adapt(int(state["window_days"]), listed, batch)

    info = state["sources"][source]
    info["place"] = _iso(place)
    info["listed"] = int(info["listed"]) + listed
    info["saved"] = int(info["saved"]) + len(saved)
    merged = list(dict.fromkeys([*state["pages_touched"], *pages]))
    state["pages_count"] = max(int(state.get("pages_count") or 0), len(merged))
    state["pages_touched"] = merged[-PAGES_MAX:]
    state["batches_done"] = int(state["batches_done"]) + 1
    state["records_saved"] = int(state["records_saved"]) + len(saved)
    try:
        state["calls"] = int(state["calls"]) + max(0, int(payload.get("calls") or 0))
    except (TypeError, ValueError):
        pass
    state["current"] = None
    was_done = bool(info["done"])
    _mark_done(state, now)
    source_done = bool(info["done"]) and not was_done
    all_done = all(state["sources"][s]["done"] for s in SOURCES)
    _write_state(root, state)

    hint = _next_hint(state)
    shown = ", ".join(pages[:3]) + (f" +{len(pages) - 3} more" if len(pages) > 3 else "")
    out = {
        "batch": int(current["n"]),
        "source": source,
        "saved": len(saved),
        "skipped": len(skipped),
        "listed": listed,
        "place": info["place"],
        "window_days": state["window_days"],
        "source_done": source_done,
        "all_done": all_done,
        "totals": _totals(state),
        "next_hint": hint,
        "stalled": stalled,
    }
    line = f"Batch {out['batch']}: {len(saved)} saved"
    if stalled:
        line += " — the place did not move: 'reached' was not later than the window's start, so the same window comes back; send the received time of the last record worked, or exhausted: true"
    if pages:
        line += f", pages {shown}"
    if all_done:
        out["finished"] = state["finished"]
        out["summary"] = _summary(state)
        out["note"] = f"{line}. {_summary(state)}"
    else:
        parts = [line]
        if source_done:
            parts.append(f"{SOURCE_WORDS[source]} is done")
        parts.append(f"next window {_day(hint['since'])}–{_day(hint['until'])} ({SOURCE_WORDS[hint['source']]}) — continue?")
        out["note"] = "; ".join(parts)
    return out


# ------------------------------------------------------------------ the tool


def load_history(
    action: str = "status",
    since: Optional[str] = None,
    batch: int = DEFAULT_BATCH,
    payload: Optional[dict[str, Any]] = None,
    reset: bool = False,
    now: Optional[str] = None,
) -> dict[str, Any]:
    """What ``vault_load_history`` answers. ``now`` is only for tests."""
    root = store.vault_root()
    at = _now(now)
    if action == "status":
        return status(root, at)
    if action == "plan":
        return plan(root, since, batch, bool(reset), at)
    if action == "next":
        return next_batch(root, at)
    if action == "done":
        return done(root, payload, at)
    raise VaultError(f"action must be 'status', 'plan', 'next' or 'done', got {action!r}.")


__all__ = ["PATH", "SOURCES", "load_history", "plan", "next_batch", "done", "status", "read_state"]
