"""Tests for calendar identity fields (global_id / occurrence_key), attendee
SMTP + response mapping, organizer resolution and get_event_by_key.
All run against fake COM objects."""

import datetime as dt
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="client modules import pywin32"
)


# ---------------------------------------------------------------- fakes --


class FakeAccessor:
    def __init__(self, props):
        self.props = props

    def GetProperty(self, tag):
        if tag not in self.props:
            raise RuntimeError("MAPI_E_NOT_FOUND")
        return self.props[tag]


class FakeExchangeUser:
    def __init__(self, smtp):
        self.PrimarySmtpAddress = smtp


class FakeAddressEntry:
    def __init__(self, address="", exch=None):
        self.Address = address
        self._exch = exch

    def GetExchangeUser(self):
        return self._exch


class FakeRecipient:
    def __init__(self, name, address, rtype=1, response=0, exch=None, props=None):
        self.Name = name
        self.Address = address
        self.Type = rtype
        self.MeetingResponseStatus = response
        self.AddressEntry = FakeAddressEntry(address, exch)
        self.PropertyAccessor = FakeAccessor(props or {})


class FakeAppointment:
    Class = 26

    def __init__(self, entry_id, start, *, global_id="GID", recipients=(), organizer_entry=None, props=None, **kw):
        self.EntryID = entry_id
        self.GlobalAppointmentID = global_id
        self.Subject = f"Subj {entry_id}"
        self.Start = start
        self.End = start + dt.timedelta(hours=1)
        self.Location = "Room 1"
        self.Organizer = "Alice Org"
        self.RecurrenceState = 0
        self.ResponseStatus = 3
        self.AllDayEvent = False
        self.Body = "body"
        self.Recipients = list(recipients)
        self.ReminderMinutesBeforeStart = 15
        self.Categories = ""
        self.PropertyAccessor = FakeAccessor(props or {})
        self._organizer_entry = organizer_entry
        for k, v in kw.items():
            setattr(self, k, v)

    def GetOrganizer(self):
        if self._organizer_entry is None:
            raise RuntimeError("no organizer")
        return self._organizer_entry


class FakeItems:
    def __init__(self, items):
        self._items = items
        self.IncludeRecurrences = False
        self.sorted_by = None
        self.restrict = None

    def Sort(self, key, desc=False):
        self.sorted_by = key

    def Restrict(self, flt):
        self.restrict = flt
        return self

    def __iter__(self):
        return iter(self._items)


class FakeNamespace:
    def __init__(self, items):
        self.items = FakeItems(items)
        self._by_id = {i.EntryID: i for i in items}

    def GetDefaultFolder(self, kind):
        assert kind == 9
        return type("Cal", (), {"Items": self.items})()

    def GetItemFromID(self, entry_id, store_id=None):
        return self._by_id[entry_id]


def _t(day, hour=9):
    return dt.datetime(2026, 3, day, hour, 0, 0)


# --------------------------------------------------- ids / shape ---------


def test_event_gains_global_id_and_occurrence_key():
    from outlook_mcp.client.calendar import _event_full, _event_summary
    from outlook_mcp.utils.formatting import to_iso

    ev = FakeAppointment("e1", _t(1), global_id="ABC123", RecurrenceState=2)
    s = _event_summary(ev)
    assert s["global_id"] == "ABC123"
    assert s["occurrence_key"] == "ABC123|" + to_iso(_t(1))
    assert s["is_recurring"] is True
    assert s["recurrence_state"] == "occurrence"
    assert s["response_status"] == "accepted"
    # existing keys intact
    for key in ("entry_id", "subject", "start", "end", "location", "organizer", "all_day", "preview"):
        assert key in s
    f = _event_full(ev)
    assert f["body"] == "body" and f["reminder_minutes"] == 15 and "attendees" in f


def test_global_id_missing_yields_empty_string():
    from outlook_mcp.client.calendar import _event_summary

    ev = FakeAppointment("e1", _t(1))
    del ev.GlobalAppointmentID
    s = _event_summary(ev)
    assert s["global_id"] == ""
    assert s["occurrence_key"].startswith("|")
    assert s["recurrence_state"] == "not_recurring"


def test_occurrences_of_same_series_have_distinct_keys():
    from outlook_mcp.client.calendar import _event_summary

    a = _event_summary(FakeAppointment("m", _t(1), global_id="G", RecurrenceState=2))
    b = _event_summary(FakeAppointment("m", _t(8), global_id="G", RecurrenceState=2))
    assert a["global_id"] == b["global_id"]
    assert a["occurrence_key"] != b["occurrence_key"]


# --------------------------------------------------- attendees -----------


def test_attendees_resolve_smtp_and_map_type_response():
    from outlook_mcp.client.calendar import _event_summary
    from outlook_mcp.client.mail import RECIPIENT_SMTP_PROPTAG

    recs = [
        FakeRecipient("Bob", "bob@x.com", 1, 3),
        FakeRecipient("Eve", "/O=EX/CN=eve", 2, 2, exch=FakeExchangeUser("eve@corp.com")),
        FakeRecipient("Room", "/O=EX/CN=room", 3, 5, props={RECIPIENT_SMTP_PROPTAG: "room@corp.com"}),
        FakeRecipient("Org", "/O=EX/CN=org", 1, 1),
        FakeRecipient("Dan", "dan@x.com", 1, 4),
    ]
    out = _event_summary(FakeAppointment("e1", _t(1), recipients=recs))["attendees"]
    assert out == [
        {"name": "Bob", "address": "bob@x.com", "type": "required", "response": "accepted"},
        {"name": "Eve", "address": "eve@corp.com", "type": "optional", "response": "tentative"},
        {"name": "Room", "address": "room@corp.com", "type": "resource", "response": "notresponded"},
        {"name": "Org", "address": "/O=EX/CN=org", "type": "required", "response": "organizer"},
        {"name": "Dan", "address": "dan@x.com", "type": "required", "response": "declined"},
    ]


def test_attendees_empty_when_no_recipients():
    from outlook_mcp.client.calendar import _event_summary

    ev = FakeAppointment("e1", _t(1))
    ev.Recipients = None
    assert _event_summary(ev)["attendees"] == []


# --------------------------------------------------- organizer -----------


def test_organizer_address_via_exchange_user():
    from outlook_mcp.client.calendar import organizer_smtp

    ev = FakeAppointment(
        "e1", _t(1), organizer_entry=FakeAddressEntry("/O=EX/CN=alice", FakeExchangeUser("alice@corp.com"))
    )
    assert organizer_smtp(ev) == "alice@corp.com"


def test_organizer_address_via_property_accessor_then_display_name():
    from outlook_mcp.client.calendar import ORGANIZER_SMTP_PROPTAG, _event_summary, organizer_smtp

    ev = FakeAppointment("e1", _t(1), props={ORGANIZER_SMTP_PROPTAG: "alice@corp.com"})
    assert organizer_smtp(ev) == "alice@corp.com"
    assert _event_summary(ev)["organizer_address"] == "alice@corp.com"

    ev2 = FakeAppointment("e2", _t(1))  # GetOrganizer raises, no proptag
    assert organizer_smtp(ev2) == "Alice Org"
    assert _event_summary(ev2)["organizer"] == "Alice Org"


# --------------------------------------------------- get_event_by_key ----


def test_get_event_by_key_hits_correct_occurrence():
    from outlook_mcp.client.calendar import get_event_by_key, occurrence_key
    from outlook_mcp.utils.formatting import to_iso

    occ1 = FakeAppointment("m", _t(1), global_id="G", RecurrenceState=2)
    occ2 = FakeAppointment("m", _t(8), global_id="G", RecurrenceState=2)
    other = FakeAppointment("o", _t(8), global_id="H")
    ns = FakeNamespace([occ1, other, occ2])

    key = occurrence_key("G", to_iso(_t(8)))
    out = get_event_by_key(None, ns, occurrence_key=key)
    assert out["start"] == to_iso(_t(8)) and out["global_id"] == "G"
    assert out["occurrence_key"] == key
    assert out["body"] == "body"
    # iterated with recurrences expanded, sorted by start, windowed round the key
    assert ns.items.IncludeRecurrences is True
    assert ns.items.sorted_by == "[Start]"
    assert "03/07/2026" in ns.items.restrict and "03/09/2026" in ns.items.restrict


def test_get_event_by_global_id_returns_first_in_window():
    from outlook_mcp.client.calendar import get_event_by_key

    occ1 = FakeAppointment("m", _t(1), global_id="G")
    occ2 = FakeAppointment("m", _t(8), global_id="G")
    ns = FakeNamespace([occ1, occ2])
    out = get_event_by_key(None, ns, global_id="G", window_start="2026-03-01", window_end="2026-03-31")
    assert out["entry_id"] == "m" and out["start"].startswith("2026-03-01")
    assert "03/01/2026" in ns.items.restrict and "03/31/2026" in ns.items.restrict


def test_get_event_by_key_miss_raises():
    from outlook_mcp.client.calendar import get_event_by_key
    from outlook_mcp.errors import OutlookError

    ns = FakeNamespace([FakeAppointment("m", _t(1), global_id="G")])
    with pytest.raises(OutlookError, match="No event with global_id 'Z'"):
        get_event_by_key(None, ns, global_id="Z", window_start="2026-03-01", window_end="2026-03-31")
    # right id, wrong start
    with pytest.raises(OutlookError):
        get_event_by_key(None, ns, occurrence_key="G|2026-03-02T09:00:00")
    with pytest.raises(OutlookError):
        get_event_by_key(None, ns)
    with pytest.raises(OutlookError):
        get_event_by_key(None, ns, occurrence_key="no-separator")
