"""Free/busy lookup and meeting-time search.

Built on ``Recipient.FreeBusy`` (Exchange only). Outlook returns a
string with one digit per interval starting at **midnight of the start
date**: ``0`` free, ``1`` tentative, ``2`` busy, ``3`` out of office,
``4`` working elsewhere. People outside the tenant resolve but have no
free/busy data, which surfaces as an empty string.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from outlook_mcp.client.folders import _safe_get
from outlook_mcp.client.mail import recipient_smtp
from outlook_mcp.errors import OutlookError
from outlook_mcp.utils.formatting import from_iso, to_iso

MAX_ADDRESSES = 20
MAX_DAYS = 62
# One FreeBusy call is documented to return about a month; we walk the
# window in chunks and stop when Outlook returns nothing more.
_MAX_CHUNKS = 8

_STATUS_MAP = {
    "0": "free",
    "1": "tentative",
    "2": "busy",
    "3": "oof",
    "4": "elsewhere",
}


def _status(ch: str) -> str:
    # Anything unrecognised is treated as busy so we never propose a slot
    # on top of data we do not understand.
    return _STATUS_MAP.get(ch, "busy")


def _parse_window(start: str, end: str) -> tuple[dt.datetime, dt.datetime]:
    start_dt = from_iso(start)
    end_dt = from_iso(end)
    if start_dt is None or end_dt is None:
        raise OutlookError("Both start and end are required (ISO-8601).")
    if end_dt <= start_dt:
        raise OutlookError("end must be after start.")
    if end_dt - start_dt > dt.timedelta(days=MAX_DAYS):
        raise OutlookError(f"Window too large: cap is {MAX_DAYS} days.")
    return start_dt, end_dt


def _validate_addresses(addresses: list[str]) -> list[str]:
    cleaned: list[str] = []
    for addr in addresses or []:
        a = (addr or "").strip()
        if a and a.lower() not in {c.lower() for c in cleaned}:
            cleaned.append(a)
    if not cleaned:
        raise OutlookError("Pass at least one address.")
    if len(cleaned) > MAX_ADDRESSES:
        raise OutlookError(f"Too many addresses: cap is {MAX_ADDRESSES}.")
    return cleaned


def _fetch_digits(recipient: Any, day: dt.datetime, interval_minutes: int, minutes_needed: int) -> str:
    """Concatenate FreeBusy strings until ``minutes_needed`` is covered."""
    digits = ""
    cursor = day
    for _ in range(_MAX_CHUNKS):
        try:
            chunk = recipient.FreeBusy(cursor, interval_minutes, True)
        except Exception:
            chunk = ""
        if not isinstance(chunk, str) or not chunk:
            break
        digits += chunk
        if len(digits) * interval_minutes >= minutes_needed:
            break
        cursor = cursor + dt.timedelta(minutes=len(chunk) * interval_minutes)
    return digits


def _slots_for(
    digits: str,
    day: dt.datetime,
    interval_minutes: int,
    start_dt: dt.datetime,
    end_dt: dt.datetime,
) -> list[dict[str, Any]]:
    step = dt.timedelta(minutes=interval_minutes)
    out: list[dict[str, Any]] = []
    for i, ch in enumerate(digits):
        s = day + step * i
        e = s + step
        if e <= start_dt:
            continue
        if s >= end_dt:
            break
        out.append({"start": s, "end": e, "status": _status(ch)})
    return out


def _merge_blocks(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for slot in slots:
        if slot["status"] == "free":
            continue
        if blocks and blocks[-1]["status"] == slot["status"] and blocks[-1]["end"] == slot["start"]:
            blocks[-1]["end"] = slot["end"]
        else:
            blocks.append(dict(slot))
    return blocks


def _iso_slots(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"start": to_iso(s["start"]), "end": to_iso(s["end"]), "status": s["status"]} for s in slots]


def _lookup(
    namespace: Any,
    addresses: list[str],
    start_dt: dt.datetime,
    end_dt: dt.datetime,
    interval_minutes: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return raw (datetime-valued) per-person results plus the unknown list."""
    day = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    minutes_needed = int((end_dt - day).total_seconds() // 60) + interval_minutes

    people: list[dict[str, Any]] = []
    unknown: list[str] = []
    for addr in addresses:
        entry: dict[str, Any] = {"address": addr, "resolved": False, "has_data": False, "slots": [], "busy_blocks": []}
        try:
            rec = namespace.CreateRecipient(addr)
            resolved = bool(rec.Resolve())
        except Exception:
            rec, resolved = None, False
        if not resolved:
            unknown.append(addr)
            people.append(entry)
            continue
        entry["resolved"] = True
        digits = _fetch_digits(rec, day, interval_minutes, minutes_needed)
        if not digits:
            unknown.append(addr)
            people.append(entry)
            continue
        entry["has_data"] = True
        entry["slots"] = _slots_for(digits, day, interval_minutes, start_dt, end_dt)
        entry["busy_blocks"] = _merge_blocks(entry["slots"])
        people.append(entry)
    return people, unknown


def get_free_busy(
    outlook: Any,
    namespace: Any,
    *,
    addresses: list[str],
    start: str,
    end: str,
    interval_minutes: int = 30,
    busy_blocks_only: bool = True,
) -> dict[str, Any]:
    """Per-person free/busy.

    ``busy_blocks_only`` (default) leaves out the per-slot ``slots`` array —
    for a week at 30 minutes that is 336 entries per person — and keeps the
    merged ``busy_blocks``, which is what a reader needs anyway.
    """
    if not 1 <= interval_minutes <= 1440:
        raise OutlookError("interval_minutes must be between 1 and 1440.")
    addrs = _validate_addresses(addresses)
    start_dt, end_dt = _parse_window(start, end)
    people, unknown = _lookup(namespace, addrs, start_dt, end_dt, interval_minutes)
    for p in people:
        if busy_blocks_only:
            p.pop("slots", None)
        else:
            p["slots"] = _iso_slots(p["slots"])
        p["busy_blocks"] = _iso_slots(p["busy_blocks"])
    return {
        "start": to_iso(start_dt),
        "end": to_iso(end_dt),
        "interval_minutes": interval_minutes,
        "count": len(people),
        "people": people,
        "unknown": unknown,
    }


def _parse_hhmm(value: str, label: str) -> dt.time:
    try:
        h, m = value.strip().split(":")
        return dt.time(int(h), int(m))
    except Exception as exc:
        raise OutlookError(f"{label} must look like 'HH:MM' (got '{value}').") from exc


def _self_address(namespace: Any) -> str:
    user = _safe_get(namespace, "CurrentUser")
    if user is None:
        return ""
    return recipient_smtp(user) or _safe_get(user, "Name", "") or ""


def find_meeting_times(
    outlook: Any,
    namespace: Any,
    *,
    addresses: list[str],
    start: str,
    end: str,
    duration_minutes: int,
    work_start: str = "09:00",
    work_end: str = "17:00",
    buffer_minutes: int = 0,
    weekdays_only: bool = True,
    include_self: bool = True,
    max_results: int = 10,
    include_slots: bool = False,
) -> dict[str, Any]:
    """Candidate times when everyone with free/busy data is free.

    With ``include_slots`` the result also carries ``people[]`` (each
    person's ``slots`` and ``busy_blocks``); off by default because those
    arrays are the bulk of the payload and the candidates already say who
    was checked.
    """
    if duration_minutes < 1:
        raise OutlookError("duration_minutes must be at least 1.")
    if buffer_minutes < 0:
        raise OutlookError("buffer_minutes cannot be negative.")
    ws = _parse_hhmm(work_start, "work_start")
    we = _parse_hhmm(work_end, "work_end")
    if we <= ws:
        raise OutlookError("work_end must be after work_start.")

    addrs = list(addresses or [])
    if include_self:
        me = _self_address(namespace)
        if me and me.lower() not in {a.lower() for a in addrs}:
            addrs.append(me)
    addrs = _validate_addresses(addrs)
    start_dt, end_dt = _parse_window(start, end)

    # Slot granularity: 15 min is fine enough for typical durations without
    # blowing up the FreeBusy string; shorter meetings use their own length.
    interval = min(15, duration_minutes)
    people, unknown = _lookup(namespace, addrs, start_dt, end_dt, interval)
    known = [p for p in people if p["has_data"]]

    busy_by_addr: dict[str, list[tuple[dt.datetime, dt.datetime]]] = {
        p["address"]: [(b["start"], b["end"]) for b in p["busy_blocks"]] for p in known
    }

    def clear(addr: str, s: dt.datetime, e: dt.datetime) -> bool:
        return all(not (bs < e and be > s) for bs, be in busy_by_addr[addr])

    duration = dt.timedelta(minutes=duration_minutes)
    buffer = dt.timedelta(minutes=buffer_minutes)
    step = dt.timedelta(minutes=interval)

    candidates: list[dict[str, Any]] = []
    day = start_dt.date()
    while day <= end_dt.date() and len(candidates) < max_results:
        if weekdays_only and day.weekday() >= 5:
            day += dt.timedelta(days=1)
            continue
        day_start = dt.datetime.combine(day, ws)
        day_end = dt.datetime.combine(day, we)
        t = max(day_start, start_dt)
        # Align to the slot grid so candidates land on tidy boundaries.
        offset = (t - day_start) % step
        if offset:
            t += step - offset
        while t + duration <= day_end and t + duration <= end_dt:
            s, e = t - buffer, t + duration + buffer
            if all(clear(p["address"], s, e) for p in known):
                candidates.append(
                    {
                        "start": to_iso(t),
                        "end": to_iso(t + duration),
                        "free": [p["address"] for p in known],
                        "unknown": list(unknown),
                    }
                )
                if len(candidates) >= max_results:
                    break
            t += step
        day += dt.timedelta(days=1)

    out: dict[str, Any] = {
        "start": to_iso(start_dt),
        "end": to_iso(end_dt),
        "duration_minutes": duration_minutes,
        "addresses": addrs,
        "unknown": unknown,
        "count": len(candidates),
        "items": candidates,
    }
    if include_slots:
        for p in people:
            p["slots"] = _iso_slots(p["slots"])
            p["busy_blocks"] = _iso_slots(p["busy_blocks"])
        out["people"] = people
    return out
