"""Calendar (appointment / meeting) COM operations."""

from __future__ import annotations

import datetime as dt
from typing import Any

from outlook_mcp.client.folders import _safe_get, get_item_by_id
from outlook_mcp.client.mail import _looks_smtp, recipient_smtp
from outlook_mcp.constants import (
    OL_APPOINTMENT_ITEM,
    OL_FOLDER_CALENDAR,
    OL_MEETING,
    OL_MEETING_ACCEPTED,
    OL_MEETING_DECLINED,
    OL_MEETING_TENTATIVE,
    OL_RECURS_DAILY,
    OL_RECURS_MONTHLY,
    OL_RECURS_WEEKLY,
    OL_RECURS_YEARLY,
    OL_TO,
)
from outlook_mcp.errors import OutlookError
from outlook_mcp.schemas import Recurrence
from outlook_mcp.utils.fields import apply_fields
from outlook_mcp.utils.formatting import from_iso, to_iso, truncate


_RECURRENCE_TYPE_MAP = {
    "daily": OL_RECURS_DAILY,
    "weekly": OL_RECURS_WEEKLY,
    "monthly": OL_RECURS_MONTHLY,
    "yearly": OL_RECURS_YEARLY,
}

# PR_SMTP_ADDRESS read off the AppointmentItem itself — on a received
# meeting this is the organizer's SMTP address.
ORGANIZER_SMTP_PROPTAG = "http://schemas.microsoft.com/mapi/proptag/0x39FE001F"

# OlMeetingRecipientType
_ATTENDEE_TYPE_MAP = {1: "required", 2: "optional", 3: "resource"}
# OlResponseStatus
_RESPONSE_MAP = {
    0: "none",
    1: "organizer",
    2: "tentative",
    3: "accepted",
    4: "declined",
    5: "notresponded",
}
# OlRecurrenceState
_RECURRENCE_STATE_MAP = {0: "not_recurring", 1: "master", 2: "occurrence", 3: "exception"}


def _response_name(code: Any) -> str:
    return _RESPONSE_MAP.get(code, "none")


def organizer_smtp(ev: Any) -> str:
    """Return the organizer's SMTP address, resolving Exchange DNs.

    Order: ``GetOrganizer().GetExchangeUser().PrimarySmtpAddress``;
    ``GetOrganizer().Address`` when already SMTP; ``PR_SMTP_ADDRESS`` on
    the item via PropertyAccessor; finally the ``Organizer`` display name.
    """
    try:
        entry = ev.GetOrganizer()
    except Exception:
        entry = None
    if entry is not None:
        try:
            exchange_user = entry.GetExchangeUser()
            if exchange_user is not None and _looks_smtp(exchange_user.PrimarySmtpAddress):
                return exchange_user.PrimarySmtpAddress
        except Exception:
            pass
        address = _safe_get(entry, "Address", "")
        if _looks_smtp(address):
            return address
    accessor = _safe_get(ev, "PropertyAccessor")
    if accessor is not None:
        try:
            value = accessor.GetProperty(ORGANIZER_SMTP_PROPTAG)
            if _looks_smtp(value):
                return value
        except Exception:
            pass
    return _safe_get(ev, "Organizer", "") or ""


def _attendees(ev: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    recipients = _safe_get(ev, "Recipients")
    if not recipients:
        return out
    try:
        for r in recipients:
            out.append(
                {
                    "name": _safe_get(r, "Name", ""),
                    "address": recipient_smtp(r),
                    "type": _ATTENDEE_TYPE_MAP.get(_safe_get(r, "Type"), "required"),
                    "response": _response_name(_safe_get(r, "MeetingResponseStatus")),
                }
            )
    except Exception:
        pass
    return out


def occurrence_key(global_id: str, start_iso: str | None) -> str:
    """``global_id|start`` — unique per occurrence of a recurring series.

    ``GlobalAppointmentID`` is shared by every occurrence of a series (and
    is stable across mailboxes, unlike EntryID), so the start time is
    appended to pin down a single instance.
    """
    return f"{global_id}|{start_iso or ''}"


def _event_summary(ev: Any) -> dict[str, Any]:
    recur_state = _safe_get(ev, "RecurrenceState", 0)
    global_id = _safe_get(ev, "GlobalAppointmentID", "") or ""
    start_iso = to_iso(_safe_get(ev, "Start"))
    return {
        "entry_id": _safe_get(ev, "EntryID"),
        "global_id": global_id,
        "occurrence_key": occurrence_key(global_id, start_iso),
        "subject": _safe_get(ev, "Subject", ""),
        "start": start_iso,
        "end": to_iso(_safe_get(ev, "End")),
        "location": _safe_get(ev, "Location", ""),
        "organizer": _safe_get(ev, "Organizer", ""),
        "organizer_address": organizer_smtp(ev),
        "attendees": _attendees(ev),
        "response_status": _response_name(_safe_get(ev, "ResponseStatus")),
        "is_recurring": bool(recur_state),
        "recurrence_state": _RECURRENCE_STATE_MAP.get(recur_state, "not_recurring"),
        "all_day": bool(_safe_get(ev, "AllDayEvent", False)),
        "preview": truncate(_safe_get(ev, "Body", ""), 200),
    }


def _event_full(ev: Any) -> dict[str, Any]:
    return {
        **_event_summary(ev),
        "body": _safe_get(ev, "Body", ""),
        "reminder_minutes": _safe_get(ev, "ReminderMinutesBeforeStart"),
        "categories": _safe_get(ev, "Categories", ""),
    }


def _apply_recurrence(appt: Any, spec: Recurrence) -> None:
    pattern = appt.GetRecurrencePattern()
    pattern.RecurrenceType = _RECURRENCE_TYPE_MAP[spec.type]
    pattern.Interval = spec.interval
    if spec.occurrences is not None:
        pattern.Occurrences = spec.occurrences
    if spec.end_date is not None:
        pattern.PatternEndDate = from_iso(spec.end_date)


def list_events(
    outlook: Any,
    namespace: Any,
    *,
    start: str | None = None,
    end: str | None = None,
    limit: int = 50,
    include_recurrences: bool = True,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    start_dt = from_iso(start) or dt.datetime.now()
    end_dt = from_iso(end) or (start_dt + dt.timedelta(days=14))

    results: list[dict[str, Any]] = []
    for ev in _iter_window(namespace, start_dt, end_dt, include_recurrences):
        results.append(_event_summary(ev))
        if len(results) >= limit:
            break

    return apply_fields(
        {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "count": len(results),
            "items": results,
        },
        fields,
    )


def _iter_window(
    namespace: Any,
    start_dt: dt.datetime,
    end_dt: dt.datetime,
    include_recurrences: bool = True,
) -> Any:
    """Yield calendar items whose Start lies in ``[start_dt, end_dt]``."""
    cal = namespace.GetDefaultFolder(OL_FOLDER_CALENDAR)
    items = cal.Items
    # Outlook requires the collection sorted ascending by [Start] BEFORE
    # IncludeRecurrences is set, or recurring series expand incorrectly.
    items.Sort("[Start]")
    if include_recurrences:
        items.IncludeRecurrences = True

    # Jet filter dates must be 12-hour + AM/PM; %H with %p would emit
    # e.g. "14:30 PM", which Outlook misparses for afternoon times.
    restrict = (
        f"[Start] >= '{start_dt.strftime('%m/%d/%Y %I:%M %p')}' AND "
        f"[Start] <= '{end_dt.strftime('%m/%d/%Y %I:%M %p')}'"
    )
    return items.Restrict(restrict)


def get_event(
    outlook: Any, namespace: Any, *, entry_id: str, fields: list[str] | None = None
) -> dict[str, Any]:
    return apply_fields(_event_full(get_item_by_id(namespace, entry_id)), fields)


def _naive(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=None, microsecond=0)
    return None


def get_event_by_key(
    outlook: Any,
    namespace: Any,
    *,
    occurrence_key: str | None = None,
    global_id: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
) -> dict[str, Any]:
    """Find an event by ``GlobalAppointmentID`` (optionally pinned to a start).

    ``occurrence_key`` (``global_id|start``) matches exactly one occurrence
    of a recurring series; a bare ``global_id`` returns the first item of
    the series inside the window. The window defaults to one day either
    side of the key's start, or ``now .. +14d`` for a bare ``global_id``.
    """
    want_start: dt.datetime | None = None
    if occurrence_key:
        gid, sep, start_part = occurrence_key.partition("|")
        if not sep or not gid:
            raise OutlookError("occurrence_key must look like '<global_id>|<ISO start>'.")
        global_id = gid
        want_start = _naive(from_iso(start_part)) if start_part else None
    if not global_id:
        raise OutlookError("Pass occurrence_key or global_id.")

    start_dt = from_iso(window_start)
    end_dt = from_iso(window_end)
    if start_dt is None:
        start_dt = (want_start - dt.timedelta(days=1)) if want_start else dt.datetime.now()
    if end_dt is None:
        end_dt = (want_start + dt.timedelta(days=1)) if want_start else start_dt + dt.timedelta(days=14)

    for ev in _iter_window(namespace, start_dt, end_dt, True):
        if (_safe_get(ev, "GlobalAppointmentID", "") or "") != global_id:
            continue
        if want_start is not None and _naive(_safe_get(ev, "Start")) != want_start:
            continue
        return _event_full(ev)

    raise OutlookError(
        f"No event with global_id '{global_id}'"
        + (f" starting {want_start.isoformat()}" if want_start else "")
        + f" between {start_dt.isoformat()} and {end_dt.isoformat()}."
    )


def create_event(
    outlook: Any,
    namespace: Any,
    *,
    subject: str,
    start: str,
    end: str,
    location: str | None = None,
    body: str | None = None,
    attendees: list[str] | None = None,
    is_online_meeting: bool = False,
    reminder_minutes: int | None = 15,
    recurrence: Recurrence | None = None,
) -> dict[str, Any]:
    appt = outlook.CreateItem(OL_APPOINTMENT_ITEM)
    appt.Subject = subject
    appt.Start = from_iso(start)
    appt.End = from_iso(end)
    if location:
        appt.Location = location
    if body:
        appt.Body = body
    if reminder_minutes is not None:
        appt.ReminderSet = True
        appt.ReminderMinutesBeforeStart = reminder_minutes
    if attendees:
        appt.MeetingStatus = OL_MEETING
        for addr in attendees:
            rec = appt.Recipients.Add(addr)
            rec.Type = OL_TO
        appt.Recipients.ResolveAll()
    if recurrence is not None:
        _apply_recurrence(appt, recurrence)
    appt.Save()
    if attendees:
        appt.Send()
    global_id = _safe_get(appt, "GlobalAppointmentID", "") or ""
    start_iso = to_iso(appt.Start)
    return {
        "status": "created",
        "entry_id": appt.EntryID,
        "global_id": global_id,
        "occurrence_key": occurrence_key(global_id, start_iso),
        "subject": appt.Subject,
        "start": start_iso,
        "end": to_iso(appt.End),
        "invite_sent": bool(attendees),
    }


def update_event(
    outlook: Any,
    namespace: Any,
    *,
    entry_id: str,
    subject: str | None = None,
    start: str | None = None,
    end: str | None = None,
    location: str | None = None,
    body: str | None = None,
    send_update: bool = True,
) -> dict[str, Any]:
    """Update scalar fields of an event.

    If the event is a meeting the user organises (``MeetingStatus`` ==
    olMeeting) and ``send_update`` is true, ``Send()`` is called after
    ``Save()`` so attendees receive the updated invite — without it the
    change is local only and Outlook shows it as a pending update.
    """
    ev = get_item_by_id(namespace, entry_id)
    if subject is not None:
        ev.Subject = subject
    if start is not None:
        ev.Start = from_iso(start)
    if end is not None:
        ev.End = from_iso(end)
    if location is not None:
        ev.Location = location
    if body is not None:
        ev.Body = body
    ev.Save()
    is_meeting = _safe_get(ev, "MeetingStatus", 0) == 1
    has_attendees = bool(_safe_get(_safe_get(ev, "Recipients"), "Count", 0))
    sent = False
    if send_update and is_meeting and has_attendees:
        ev.Send()
        sent = True
    return {"status": "updated", "entry_id": entry_id, "update_sent": sent}


def delete_event(outlook: Any, namespace: Any, *, entry_id: str) -> dict[str, Any]:
    ev = get_item_by_id(namespace, entry_id)
    subject = _safe_get(ev, "Subject", "")
    ev.Delete()
    return {"status": "deleted", "subject": subject, "entry_id": entry_id}


def respond_event(
    outlook: Any,
    namespace: Any,
    *,
    entry_id: str,
    response: str,
    send_response: bool = True,
) -> dict[str, Any]:
    ev = get_item_by_id(namespace, entry_id)
    code = {
        "accept": OL_MEETING_ACCEPTED,
        "tentative": OL_MEETING_TENTATIVE,
        "decline": OL_MEETING_DECLINED,
    }.get(response.lower())
    if code is None:
        raise OutlookError("response must be one of: 'accept', 'tentative', 'decline'.")
    resp = ev.Respond(code, True)
    if send_response and resp is not None:
        resp.Send()
    return {"status": "responded", "response": response}
