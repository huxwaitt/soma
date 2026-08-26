"""show_as / categories on create_event and update_event, and the
busy_status / categories / attendee_count / is_meeting keys on event
summaries. All run against fake COM objects."""

import datetime as dt
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="client modules import pywin32"
)


# ---------------------------------------------------------------- fakes --


class FakeRecipients:
    def __init__(self):
        self._items = []

    @property
    def Count(self):
        return len(self._items)

    def Add(self, addr):
        rec = type("Rec", (), {"Name": addr, "Address": addr, "Type": 0, "MeetingResponseStatus": 0})()
        self._items.append(rec)
        return rec

    def ResolveAll(self):
        return True

    def __iter__(self):
        return iter(self._items)

    def __bool__(self):
        return True


class FakeAppt:
    def __init__(self, *, entry_id="E1", global_id="GID1", meeting_status=0, busy_status=2, categories=""):
        self.EntryID = entry_id
        self.GlobalAppointmentID = global_id
        self.Subject = ""
        self.Start = dt.datetime(2026, 3, 2, 9, 0)
        self.End = dt.datetime(2026, 3, 2, 10, 0)
        self.Location = ""
        self.Body = ""
        self.MeetingStatus = meeting_status
        self.BusyStatus = busy_status
        self.Categories = categories
        self.RecurrenceState = 0
        self.ResponseStatus = 0
        self.AllDayEvent = False
        self.Recipients = FakeRecipients()
        self.saved = 0
        self.sent = 0
        self.writes = []

    def __setattr__(self, name, value):
        if name in ("BusyStatus", "Categories") and "writes" in self.__dict__:
            self.writes.append(name)
        object.__setattr__(self, name, value)

    def Save(self):
        self.saved += 1

    def Send(self):
        self.sent += 1


class FakeOutlook:
    def __init__(self, appt):
        self._appt = appt

    def CreateItem(self, kind):
        return self._appt


class FakeNamespace:
    def __init__(self, appt):
        self._appt = appt

    def GetItemFromID(self, entry_id, store_id=None):
        return self._appt


def _create(appt, **kw):
    from outlook_mcp.client import calendar as c

    return c.create_event(
        FakeOutlook(appt), None, subject="Block", start="2026-03-02T09:00:00", end="2026-03-02T10:00:00", **kw
    )


# --------------------------------------------------- create_event --------


def test_create_event_defaults_to_busy_and_no_categories():
    appt = FakeAppt(busy_status=0)
    out = _create(appt)
    assert appt.BusyStatus == 2
    assert appt.Categories == ""
    assert "Categories" not in appt.writes
    assert out["show_as"] == "busy" and out["categories"] == ""
    assert appt.saved == 1 and appt.sent == 0


@pytest.mark.parametrize(
    "name, code",
    [("free", 0), ("tentative", 1), ("busy", 2), ("oof", 3), ("working_elsewhere", 4)],
)
def test_create_event_maps_show_as_to_busy_status(name, code):
    appt = FakeAppt()
    out = _create(appt, show_as=name)
    assert appt.BusyStatus == code
    assert out["show_as"] == name


def test_create_event_accepts_case_and_dash_variants():
    appt = FakeAppt()
    _create(appt, show_as=" Working-Elsewhere ")
    assert appt.BusyStatus == 4


def test_create_event_writes_categories():
    appt = FakeAppt()
    out = _create(appt, show_as="free", categories="Soma, Focus")
    assert appt.Categories == "Soma, Focus"
    assert out["categories"] == "Soma, Focus"
    assert out["show_as"] == "free"
    # written before Save, so the values land in the saved item
    assert appt.writes == ["BusyStatus", "Categories"] and appt.saved == 1


def test_create_event_rejects_unknown_show_as_before_touching_outlook():
    from outlook_mcp.errors import OutlookError

    appt = FakeAppt()

    class NoCreate:
        def CreateItem(self, kind):
            raise AssertionError("CreateItem must not be called")

    from outlook_mcp.client import calendar as c

    with pytest.raises(OutlookError, match="show_as must be one of.*'working_elsewhere'.*got 'away'"):
        c.create_event(NoCreate(), None, subject="x", start="2026-03-02T09:00:00", end="2026-03-02T10:00:00", show_as="away")
    assert appt.saved == 0


# --------------------------------------------------- update_event --------


def test_update_event_leaves_show_as_and_categories_alone_when_omitted():
    from outlook_mcp.client import calendar as c

    appt = FakeAppt(busy_status=1, categories="Keep")
    out = c.update_event(None, FakeNamespace(appt), entry_id="E1", subject="New")
    assert appt.BusyStatus == 1 and appt.Categories == "Keep"
    assert appt.writes == []
    assert out["status"] == "updated" and appt.saved == 1


def test_update_event_writes_show_as_and_categories():
    from outlook_mcp.client import calendar as c

    appt = FakeAppt(busy_status=2, categories="Old")
    c.update_event(None, FakeNamespace(appt), entry_id="E1", show_as="oof", categories="Soma")
    assert appt.BusyStatus == 3 and appt.Categories == "Soma"
    assert appt.saved == 1 and appt.sent == 0


def test_update_event_empty_categories_clears_them():
    from outlook_mcp.client import calendar as c

    appt = FakeAppt(categories="Old")
    c.update_event(None, FakeNamespace(appt), entry_id="E1", categories="")
    assert appt.Categories == ""


def test_update_event_rejects_unknown_show_as_before_saving():
    from outlook_mcp.client import calendar as c
    from outlook_mcp.errors import OutlookError

    appt = FakeAppt()
    with pytest.raises(OutlookError, match="show_as must be one of"):
        c.update_event(None, FakeNamespace(appt), entry_id="E1", show_as="maybe")
    assert appt.saved == 0 and appt.writes == []


# --------------------------------------------------- _event_summary ------


def test_event_summary_has_busy_status_categories_count_and_is_meeting():
    from outlook_mcp.client.calendar import _event_full, _event_summary

    appt = FakeAppt(meeting_status=0, busy_status=2, categories="Soma")
    s = _event_summary(appt)
    assert s["busy_status"] == "busy"
    assert s["categories"] == "Soma"
    assert s["attendee_count"] == 0
    assert s["is_meeting"] is False
    # previous keys intact
    for key in ("entry_id", "global_id", "occurrence_key", "subject", "start", "end", "attendees", "preview"):
        assert key in s
    f = _event_full(appt)
    assert f["categories"] == "Soma" and "body" in f and "reminder_minutes" in f


def test_event_summary_counts_attendees_and_flags_meetings():
    from outlook_mcp.client.calendar import _event_summary

    appt = FakeAppt(meeting_status=3, busy_status=1)  # olMeetingReceived
    appt.Recipients.Add("bob@example.com")
    appt.Recipients.Add("eve@example.com")
    s = _event_summary(appt)
    assert s["attendee_count"] == 2 and len(s["attendees"]) == 2
    assert s["is_meeting"] is True
    assert s["busy_status"] == "tentative"


@pytest.mark.parametrize("code, name", [(0, "free"), (1, "tentative"), (2, "busy"), (3, "oof"), (4, "working_elsewhere")])
def test_event_summary_busy_status_names(code, name):
    from outlook_mcp.client.calendar import _event_summary

    assert _event_summary(FakeAppt(busy_status=code))["busy_status"] == name


def test_event_summary_missing_busy_status_defaults_to_busy():
    from outlook_mcp.client.calendar import _event_summary

    appt = FakeAppt()
    del appt.BusyStatus
    del appt.Categories
    s = _event_summary(appt)
    assert s["busy_status"] == "busy" and s["categories"] == ""


def test_list_events_fields_filter_keeps_new_keys():
    from outlook_mcp.client.calendar import list_events

    appt = FakeAppt(meeting_status=1, busy_status=3, categories="Soma")
    appt.Recipients.Add("bob@example.com")

    class Items:
        IncludeRecurrences = False

        def Sort(self, key, desc=False):
            pass

        def Restrict(self, flt):
            return self

        def __iter__(self):
            return iter([appt])

    class NS:
        def GetDefaultFolder(self, kind):
            return type("Cal", (), {"Items": Items()})()

    out = list_events(
        None, NS(), start="2026-03-02", end="2026-03-03",
        fields=["subject", "busy_status", "categories", "attendee_count", "is_meeting"],
    )
    assert out["count"] == 1
    item = out["items"][0]
    assert item == {
        "entry_id": "E1",
        "subject": "",
        "busy_status": "oof",
        "categories": "Soma",
        "attendee_count": 1,
        "is_meeting": True,
    }
