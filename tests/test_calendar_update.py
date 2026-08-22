"""create_event returns identity fields; update_event sends updates to attendees
for organised meetings (and only then)."""

import datetime as dt
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="client modules import pywin32"
)


class FakeRecipients:
    def __init__(self):
        self._items = []

    @property
    def Count(self):
        return len(self._items)

    def Add(self, addr):
        rec = type("Rec", (), {"Address": addr, "Type": 0})()
        self._items.append(rec)
        return rec

    def ResolveAll(self):
        return True

    def __iter__(self):
        return iter(self._items)


class FakeAppt:
    def __init__(self, *, entry_id="E1", global_id="GID1", meeting_status=0, with_attendee=False):
        self.EntryID = entry_id
        self.GlobalAppointmentID = global_id
        self.Subject = ""
        self.Start = dt.datetime(2026, 3, 2, 9, 0)
        self.End = dt.datetime(2026, 3, 2, 10, 0)
        self.Location = ""
        self.Body = ""
        self.MeetingStatus = meeting_status
        self.Recipients = FakeRecipients()
        if with_attendee:
            self.Recipients.Add("bob@example.com")
        self.saved = 0
        self.sent = 0

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


def test_create_event_returns_global_id_and_occurrence_key():
    from outlook_mcp.client import calendar as c

    appt = FakeAppt()
    out = c.create_event(
        FakeOutlook(appt), None, subject="Sync", start="2026-03-02T09:00:00", end="2026-03-02T10:00:00"
    )
    assert out["global_id"] == "GID1"
    assert out["occurrence_key"].startswith("GID1|2026-03-02T09:00:00")
    assert out["invite_sent"] is False
    assert appt.sent == 0


def test_create_event_with_attendees_sends_invite():
    from outlook_mcp.client import calendar as c

    appt = FakeAppt()
    out = c.create_event(
        FakeOutlook(appt), None, subject="Sync", start="2026-03-02T09:00:00",
        end="2026-03-02T10:00:00", attendees=["bob@example.com"],
    )
    assert out["invite_sent"] is True
    assert appt.sent == 1


def test_update_event_sends_update_for_organised_meeting():
    from outlook_mcp.client import calendar as c

    appt = FakeAppt(meeting_status=1, with_attendee=True)
    out = c.update_event(None, FakeNamespace(appt), entry_id="E1", start="2026-03-03T09:00:00")
    assert appt.saved == 1 and appt.sent == 1
    assert out["update_sent"] is True
    assert appt.Start == dt.datetime(2026, 3, 3, 9, 0)


def test_update_event_send_update_false_saves_only():
    from outlook_mcp.client import calendar as c

    appt = FakeAppt(meeting_status=1, with_attendee=True)
    out = c.update_event(None, FakeNamespace(appt), entry_id="E1", subject="New", send_update=False)
    assert appt.saved == 1 and appt.sent == 0
    assert out["update_sent"] is False


def test_update_event_plain_appointment_never_sends():
    from outlook_mcp.client import calendar as c

    appt = FakeAppt(meeting_status=0)
    out = c.update_event(None, FakeNamespace(appt), entry_id="E1", location="Room 2")
    assert appt.sent == 0
    assert out["update_sent"] is False


def test_update_event_received_meeting_does_not_send():
    # MeetingStatus 3 = olMeetingReceived: the user is an attendee, not the organiser.
    from outlook_mcp.client import calendar as c

    appt = FakeAppt(meeting_status=3, with_attendee=True)
    out = c.update_event(None, FakeNamespace(appt), entry_id="E1", body="note")
    assert appt.sent == 0
    assert out["update_sent"] is False
