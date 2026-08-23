"""Free/busy decoding and meeting-time search against fake COM objects."""

import datetime as dt
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="client modules import pywin32"
)


# ---------------------------------------------------------------- fakes --


class FakeRecipient:
    """``digits`` is a dict {midnight datetime -> freebusy string}; a
    plain string applies to any start date."""

    def __init__(self, address, resolved=True, digits=""):
        self.Address = address
        self.Name = address
        self._resolved = resolved
        self._digits = digits
        self.calls = []

    def Resolve(self):
        return self._resolved

    def FreeBusy(self, start, interval, full):
        self.calls.append((start, interval, full))
        if isinstance(self._digits, dict):
            return self._digits.get(start, "")
        return self._digits


class FakeNamespace:
    def __init__(self, recipients, me="me@corp.com"):
        self._recipients = recipients
        self.CurrentUser = FakeRecipient(me)

    def CreateRecipient(self, addr):
        return self._recipients[addr]


def _d(day, hour=0, minute=0):
    return dt.datetime(2026, 3, day, hour, minute)  # 2026-03-02 is a Monday


def _digits_for_day(busy_hours, interval=30):
    """Build a 24h freebusy string with given busy hours (status '2')."""
    out = []
    for i in range(24 * 60 // interval):
        h = (i * interval) / 60
        out.append("2" if any(bs <= h < be for bs, be in busy_hours) else "0")
    return "".join(out)


# ------------------------------------------------------- get_free_busy ----


def test_slots_decode_status_and_cover_window_only():
    from outlook_mcp.client.freebusy import get_free_busy

    # 60-min slots: 00-09 free, 09 tentative, 10 busy, 11 oof, 12 elsewhere, rest free
    digits = "0" * 9 + "1234" + "0" * 11
    ns = FakeNamespace({"a@corp.com": FakeRecipient("a@corp.com", digits=digits)})
    out = get_free_busy(None, ns, addresses=["a@corp.com"], start="2026-03-02T09:00", end="2026-03-02T13:00", interval_minutes=60, busy_blocks_only=False)
    p = out["people"][0]
    assert p["resolved"] and p["has_data"]
    assert [s["status"] for s in p["slots"]] == ["tentative", "busy", "oof", "elsewhere"]
    assert p["slots"][0]["start"].startswith("2026-03-02T09:00")
    assert p["slots"][-1]["end"].startswith("2026-03-02T13:00")
    assert out["unknown"] == []
    # FreeBusy was asked from midnight of the start date with the interval
    assert ns._recipients["a@corp.com"].calls[0][:2] == (_d(2), 60)


def test_interval_handling_partial_overlap_slots_included():
    from outlook_mcp.client.freebusy import get_free_busy

    digits = _digits_for_day([(9, 10)], interval=30)
    ns = FakeNamespace({"a@corp.com": FakeRecipient("a@corp.com", digits=digits)})
    out = get_free_busy(None, ns, addresses=["a@corp.com"], start="2026-03-02T09:15", end="2026-03-02T10:15", interval_minutes=30, busy_blocks_only=False)
    slots = out["people"][0]["slots"]
    # 09:00-09:30 overlaps 09:15 so it is included; 10:00-10:30 too
    assert [s["start"][11:16] for s in slots] == ["09:00", "09:30", "10:00"]
    assert [s["status"] for s in slots] == ["busy", "busy", "free"]
    assert out["interval_minutes"] == 30


def test_busy_blocks_merge_adjacent_same_status():
    from outlook_mcp.client.freebusy import get_free_busy

    # 30-min: 09:00-10:30 busy, 10:30-11:00 tentative, 11:00-11:30 busy
    digits = "0" * 18 + "222" + "1" + "2" + "0" * (48 - 23)
    ns = FakeNamespace({"a@corp.com": FakeRecipient("a@corp.com", digits=digits)})
    out = get_free_busy(None, ns, addresses=["a@corp.com"], start="2026-03-02T08:00", end="2026-03-02T12:00")
    blocks = [(b["start"][11:16], b["end"][11:16], b["status"]) for b in out["people"][0]["busy_blocks"]]
    assert blocks == [("09:00", "10:30", "busy"), ("10:30", "11:00", "tentative"), ("11:00", "11:30", "busy")]


def test_unresolved_and_blank_freebusy_go_to_unknown():
    from outlook_mcp.client.freebusy import get_free_busy

    ns = FakeNamespace(
        {
            "ext@other.com": FakeRecipient("ext@other.com", resolved=False),
            "blank@corp.com": FakeRecipient("blank@corp.com", digits=""),
            "ok@corp.com": FakeRecipient("ok@corp.com", digits="0" * 48),
        }
    )
    out = get_free_busy(None, ns, addresses=["ext@other.com", "blank@corp.com", "ok@corp.com"], start="2026-03-02T09:00", end="2026-03-02T10:00", busy_blocks_only=False)
    assert out["unknown"] == ["ext@other.com", "blank@corp.com"]
    by = {p["address"]: p for p in out["people"]}
    assert by["ext@other.com"]["resolved"] is False and by["ext@other.com"]["slots"] == []
    assert by["blank@corp.com"]["resolved"] is True and by["blank@corp.com"]["has_data"] is False
    assert by["ok@corp.com"]["has_data"] is True and len(by["ok@corp.com"]["slots"]) == 2


def test_multi_day_window_chains_freebusy_calls():
    from outlook_mcp.client.freebusy import get_free_busy

    # Each call returns one day (24 slots of 60 min); the lookup must keep asking.
    rec = FakeRecipient("a@corp.com", digits={_d(2): "0" * 24, _d(3): "2" * 24, _d(4): "0" * 24})
    ns = FakeNamespace({"a@corp.com": rec})
    out = get_free_busy(None, ns, addresses=["a@corp.com"], start="2026-03-02T00:00", end="2026-03-04T00:00", interval_minutes=60, busy_blocks_only=False)
    assert [c[0] for c in rec.calls] == [_d(2), _d(3), _d(4)]
    assert len(out["people"][0]["slots"]) == 48
    assert out["people"][0]["busy_blocks"][0]["start"].startswith("2026-03-03T00:00")


def test_free_busy_caps_and_validation():
    from outlook_mcp.client.freebusy import get_free_busy
    from outlook_mcp.errors import OutlookError

    ns = FakeNamespace({})
    with pytest.raises(OutlookError, match="cap is 20"):
        get_free_busy(None, ns, addresses=[f"u{i}@corp.com" for i in range(21)], start="2026-03-02", end="2026-03-03")
    with pytest.raises(OutlookError, match="cap is 62"):
        get_free_busy(None, ns, addresses=["a@corp.com"], start="2026-03-02", end="2026-06-02")
    with pytest.raises(OutlookError, match="after start"):
        get_free_busy(None, ns, addresses=["a@corp.com"], start="2026-03-02", end="2026-03-02")
    with pytest.raises(OutlookError, match="at least one"):
        get_free_busy(None, ns, addresses=[], start="2026-03-02", end="2026-03-03")


# -------------------------------------------------- find_meeting_times ----


def _ns_for_meeting():
    # a: busy 09:00-10:00 ; me: busy 11:00-12:00 (15-min digits, one day then blank)
    a = FakeRecipient("a@corp.com", digits={_d(2): _digits_for_day([(9, 10)], 15)})
    me = FakeRecipient("me@corp.com", digits={_d(2): _digits_for_day([(11, 12)], 15)})
    ns = FakeNamespace({"a@corp.com": a, "me@corp.com": me})
    ns.CurrentUser = FakeRecipient("me@corp.com")
    return ns


def test_find_meeting_times_respects_working_hours_and_busy():
    from outlook_mcp.client.freebusy import find_meeting_times

    out = find_meeting_times(None, _ns_for_meeting(), addresses=["a@corp.com"], start="2026-03-02T00:00", end="2026-03-03T00:00", duration_minutes=60, max_results=100)
    starts = [c["start"][11:16] for c in out["items"]]
    assert starts[0] == "10:00"  # nothing before work_start or during a's 09-10 block
    assert not any("09:" in s for s in starts)
    # 10:15..11:45 would overlap me's 11-12 block for a 60-min meeting
    assert starts[:3] == ["10:00", "12:00", "12:15"]
    assert starts[-1] == "16:00"  # last 60-min slot ending by 17:00
    assert out["items"][0]["free"] == ["a@corp.com", "me@corp.com"]
    assert out["items"][0]["unknown"] == []
    assert out["addresses"] == ["a@corp.com", "me@corp.com"]


def test_find_meeting_times_buffer_and_duration():
    from outlook_mcp.client.freebusy import find_meeting_times

    out = find_meeting_times(None, _ns_for_meeting(), addresses=["a@corp.com"], start="2026-03-02T00:00", end="2026-03-03T00:00", duration_minutes=30, buffer_minutes=15, max_results=100)
    starts = [c["start"][11:16] for c in out["items"]]
    assert "10:00" not in starts and "10:15" in starts  # 15-min margin after a's 09-10 block
    assert "10:30" not in starts and "10:15" in starts  # 10:30+30+15 touches me's 11:00
    assert "12:00" not in starts and "12:15" in starts
    assert out["items"][0]["end"][11:16] == "10:45"
    assert out["duration_minutes"] == 30


def test_find_meeting_times_weekday_filter_and_max_results():
    from outlook_mcp.client.freebusy import find_meeting_times

    # Sat 7th and Sun 8th are free but must be skipped; Mon 9th is free.
    free_day = "0" * 96
    a = FakeRecipient("a@corp.com", digits={_d(7): free_day, _d(8): free_day, _d(9): free_day})
    ns = FakeNamespace({"a@corp.com": a})
    out = find_meeting_times(None, ns, addresses=["a@corp.com"], start="2026-03-07T00:00", end="2026-03-10T00:00", duration_minutes=30, include_self=False, max_results=3)
    assert out["count"] == 3
    assert all(c["start"].startswith("2026-03-09") for c in out["items"])
    assert [c["start"][11:16] for c in out["items"]] == ["09:00", "09:15", "09:30"]

    out2 = find_meeting_times(None, ns, addresses=["a@corp.com"], start="2026-03-07T00:00", end="2026-03-08T00:00", duration_minutes=30, include_self=False, weekdays_only=False, max_results=2)
    assert [c["start"][:16] for c in out2["items"]] == ["2026-03-07T09:00", "2026-03-07T09:15"]


def test_find_meeting_times_unknown_people_listed_not_blocking():
    from outlook_mcp.client.freebusy import find_meeting_times

    ns = FakeNamespace(
        {
            "a@corp.com": FakeRecipient("a@corp.com", digits={_d(2): "0" * 96}),
            "ext@other.com": FakeRecipient("ext@other.com", resolved=False),
        }
    )
    out = find_meeting_times(None, ns, addresses=["a@corp.com", "ext@other.com"], start="2026-03-02T00:00", end="2026-03-03T00:00", duration_minutes=30, include_self=False, max_results=1)
    assert out["unknown"] == ["ext@other.com"]
    assert out["items"][0]["free"] == ["a@corp.com"] and out["items"][0]["unknown"] == ["ext@other.com"]


def test_find_meeting_times_validation():
    from outlook_mcp.client.freebusy import find_meeting_times
    from outlook_mcp.errors import OutlookError

    ns = FakeNamespace({})
    with pytest.raises(OutlookError, match="HH:MM"):
        find_meeting_times(None, ns, addresses=["a@corp.com"], start="2026-03-02", end="2026-03-03", duration_minutes=30, work_start="nine")
    with pytest.raises(OutlookError, match="work_end"):
        find_meeting_times(None, ns, addresses=["a@corp.com"], start="2026-03-02", end="2026-03-03", duration_minutes=30, work_start="17:00", work_end="09:00")
