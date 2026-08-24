"""administrator_vault.timeblock: the planner on a fixed week (budget rule,
peak placement, existing blocks, priorities from file and wiki), the plan
note, and the audit with Held rows."""

from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

from administrator_vault import frontmatter as fmt
from administrator_vault import store, timeblock, wiki
from administrator_vault.server import build_server
from administrator_vault.store import VaultError

CB = "administrator/0.3.0"
W = "Administrator/Wiki"
WEEK = "2026-W35"  # Mon 24 Aug - Sun 30 Aug 2026
TODAY = date(2026, 8, 24)

PREFS = {
    "work_start": "09:00",
    "work_end": "17:00",
    "buffer_minutes": 15,
    "no_meeting_blocks": ["Fri 13:00-17:00"],
    "peak_hours": ["09:00-12:00"],
    "focus_block_minutes": 90,
    "focus_blocks_per_day": 2,
    "admin_blocks_per_day": 2,
    "admin_block_minutes": 45,
    "slack_share": 0.2,
}
PRIORITIES = [
    {"rank": 1, "name": "Acme contract", "page": "[[Wiki/Topics/acme-contract]]"},
    {"rank": 2, "name": "Hiring a PM", "page": None},
    {"rank": 3, "name": "Offsite", "page": None},
]


@pytest.fixture
def vault(tmp_path, monkeypatch):
    root = tmp_path / "Vault"
    root.mkdir()
    monkeypatch.setenv("ADMINISTRATOR_VAULT", str(root))
    monkeypatch.delenv("ADMINISTRATOR_VAULT_NAME", raising=False)
    store.init(created_by=CB)
    return root


def text_of(vault, path):
    return (vault / path).read_text(encoding="utf-8")


def ev(subject, start, end, attendees=1, **over):
    e = {
        "subject": subject, "start": start, "end": end, "all_day": False,
        "attendee_count": attendees, "is_meeting": attendees > 0,
        "occurrence_key": f"G|{start}", "entry_id": f"E{start}", "busy_status": "busy",
    }
    e.update(over)
    return e


def week_events():
    return [
        ev("Supplier sync", "2026-08-25T10:00:00", "2026-08-25T11:20:00"),  # Tue, ends off the quarter hour
        ev("Board", "2026-08-26T09:00:00", "2026-08-26T13:00:00"),  # Wed: 7 h of meetings
        ev("1:1s", "2026-08-26T13:30:00", "2026-08-26T16:30:00"),
        ev("[Focus] Acme contract", "2026-08-27T09:00:00", "2026-08-27T10:30:00", 0),  # Thu: an existing block
        ev("Lunch walk", "2026-08-27T12:00:00", "2026-08-27T13:00:00", 0, busy_status="free"),  # free: ignored
    ]


def blocks_of(plan, day):
    return next(d for d in plan["days"] if d["date"] == day)["blocks"]


def times(blocks):
    return [(b["start"][11:16], b["end"][11:16], b["kind"]) for b in blocks]


# ------------------------------------------------------------------ plan


def test_plan_fixed_week_budget_rule_peak_first_and_existing_blocks():
    plan = timeblock.plan(WEEK, week_events(), TODAY, PREFS, PRIORITIES)
    assert plan["week"] == WEEK and plan["start"] == "2026-08-24" and plan["end"] == "2026-08-30" and plan["today"] == "2026-08-24"
    assert [d["date"] for d in plan["days"]] == ["2026-08-24", "2026-08-25", "2026-08-27", "2026-08-28"]

    # Monday: both focus blocks inside peak hours, admin before lunch and at the end of the day
    mon = blocks_of(plan, "2026-08-24")
    assert times(mon) == [("09:00", "10:30", "focus"), ("10:30", "12:00", "focus"), ("12:15", "13:00", "admin"), ("16:15", "17:00", "admin")]
    assert mon[0]["subject"] == "[Focus] Acme contract" and mon[0]["priority"] == "Acme contract" and mon[0]["page"] == "[[Wiki/Topics/acme-contract]]"
    assert mon[1]["subject"] == "[Focus] Hiring a PM" and mon[2]["subject"] == "[Admin] Email and small tasks" and mon[2]["priority"] is None
    assert all(b["existing"] is False and b["minutes"] in (90, 45) for b in mon)
    day = next(d for d in plan["days"] if d["date"] == "2026-08-24")
    assert day["work_minutes"] == 480 and day["meeting_minutes"] == 0 and day["bookable_minutes"] == 384 and day["booked_minutes"] == 270 and day["slack_minutes"] == 210

    # Tuesday: the meeting plus buffer breaks the peak window; focus goes outside, the start is rounded to 15 min
    tue = blocks_of(plan, "2026-08-25")
    assert times(tue) == [("12:00", "13:30", "focus"), ("13:30", "15:00", "focus"), ("15:00", "15:45", "admin"), ("16:15", "17:00", "admin")]
    assert next(d for d in plan["days"] if d["date"] == "2026-08-25")["meeting_minutes"] == 80
    assert not any(b["start"] < "2026-08-25T11:35" and b["end"] > "2026-08-25T09:45" for b in tue)

    # Wednesday: meetings alone exceed the budget -> nothing booked, listed with the reason
    assert [s["date"] for s in plan["skipped_days"]] == ["2026-08-26"]
    assert plan["skipped_days"][0]["reason"].startswith("meetings take 420 of 480 work minutes")

    # Thursday: the existing block is kept, reported, and not booked again
    thu = blocks_of(plan, "2026-08-27")
    assert times(thu)[:2] == [("09:00", "10:30", "focus"), ("10:30", "12:00", "focus")]
    assert thu[0]["existing"] is True and thu[0]["occurrence_key"] == "G|2026-08-27T09:00:00" and thu[0]["priority"] == "Acme contract"
    assert sum(1 for b in thu if b["kind"] == "focus") == 2 and sum(1 for b in thu if b["existing"]) == 1

    # Friday: the no-meeting afternoon is left alone
    fri = blocks_of(plan, "2026-08-28")
    assert all(b["end"] <= "2026-08-28T13:00:00" for b in fri) and times(fri)[-1] == ("12:15", "13:00", "admin")

    # rank 1 takes every other new focus block; the others follow in order
    focus = [b["priority"] for d in plan["days"] for b in d["blocks"] if b["kind"] == "focus" and not b["existing"]]
    assert focus == ["Acme contract", "Hiring a PM", "Acme contract", "Offsite", "Acme contract", "Hiring a PM", "Acme contract"]
    assert plan["priorities"] == PRIORITIES and plan["unplaced"] == []
    assert plan["totals"] == {"focus_minutes": 720, "admin_minutes": 315, "new_blocks": 14, "existing_blocks": 1, "slack_share_kept": 0.27}
    assert plan["preferences_used"]["peak_hours"] == ["09:00-12:00"] and plan["missing_keys"] == []
    # deterministic
    assert timeblock.plan(WEEK, week_events(), TODAY, PREFS, PRIORITIES) == plan


def test_plan_from_today_on_all_day_events_and_no_priorities():
    events = week_events() + [{"subject": "Holiday", "start": "2026-08-28T00:00:00", "end": "2026-08-29T00:00:00", "all_day": True, "busy_status": "oof", "attendee_count": 0}]
    plan = timeblock.plan(WEEK, events, date(2026, 8, 26), PREFS, [])
    assert [d["date"] for d in plan["days"]] == ["2026-08-27"]
    assert [(s["date"], s["reason"]) for s in plan["skipped_days"]] == [
        ("2026-08-24", "already past"), ("2026-08-25", "already past"),
        ("2026-08-26", plan["skipped_days"][2]["reason"]), ("2026-08-28", "all day: Holiday"),
    ]
    new = [b for b in blocks_of(plan, "2026-08-27") if b["kind"] == "focus" and not b["existing"]]
    assert new[0]["subject"] == "[Focus] Deep work" and new[0]["priority"] is None
    # a free all-day event does not block the day
    events[-1]["busy_status"] = "free"
    assert "2026-08-28" in [d["date"] for d in timeblock.plan(WEEK, events, date(2026, 8, 26), PREFS, []) ["days"]]
    # the week is over: nothing to plan
    assert timeblock.plan(WEEK, [], date(2026, 9, 7), PREFS, [])["days"] == []
    # a priority with no block left is reported
    many = PRIORITIES + [{"rank": 4, "name": "Fourth"}, {"rank": 5, "name": "Fifth"}]
    one_day = timeblock.plan(WEEK, [], date(2026, 8, 28), PREFS, many)
    assert [u["name"] for u in one_day["unplaced"]] == ["Offsite", "Fourth", "Fifth"]
    with pytest.raises(VaultError):
        timeblock.plan("35", [], TODAY, PREFS, [])
    with pytest.raises(VaultError):
        timeblock.plan(WEEK, [], TODAY, dict(PREFS, slack_share=1.5), [])


def test_slack_share_is_never_violated():
    days = ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28"]
    for n, share in ((0, 0.2), (1, 0.2), (2, 0.5), (3, 0.0), (4, 0.35), (6, 0.2)):
        events = []
        for i, day in enumerate(days):
            for k in range(min(n, i + 1)):
                start = 9 + k * 2
                events.append(ev(f"M{k}", f"{day}T{start:02d}:00:00", f"{day}T{start:02d}:{[30, 50, 45][k % 3]:02d}:00"))
        prefs = dict(PREFS, slack_share=share, no_meeting_blocks=[], focus_blocks_per_day=3, admin_blocks_per_day=3)
        plan = timeblock.plan(WEEK, events, TODAY, prefs, PRIORITIES)
        for d in plan["days"]:
            assert d["slack_minutes"] >= share * d["work_minutes"] - 1e-9, (n, share, d)
            assert d["booked_minutes"] <= d["bookable_minutes"]
            # no two blocks overlap and none overlaps a meeting or its buffer
            spans = sorted((b["start"], b["end"]) for b in d["blocks"])
            assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))
            for e in events:
                if e["start"][:10] == d["date"]:
                    assert not any(s < e["end"] and t > e["start"] for s, t in spans)
        assert plan["totals"]["slack_share_kept"] is None or plan["totals"]["slack_share_kept"] >= share - 0.005


# ------------------------------------------------------------------ priorities


def test_priorities_from_file_then_pressing_wiki_topics(vault):
    # the template's hint line alone gives no priorities
    assert timeblock.read_priorities(vault, TODAY) == []
    acme = wiki.create("topic", "Acme contract", lead="The supplier contract.", extra={"due": "2026-09-10"})["path"]
    soon = wiki.create("topic", "Office move", lead="x", extra={"due": "2026-09-20"})["path"]
    far = wiki.create("topic", "Strategy 2027", lead="x", extra={"due": "2026-12-01"})["path"]
    opened = wiki.create("topic", "Hiring a PM", lead="x")["path"]
    wiki.apply(opened, [{"op": "open", "text": "Post the ad", "src": "user"}])
    closed = wiki.create("topic", "Old thing", lead="x", extra={"due": "2026-08-30"})["path"]
    wiki.apply(closed, [{"op": "status", "value": "closed"}])
    wiki.create("topic", "Quiet topic", lead="x")
    wiki.create("person", "Jane Doe", extra={"email": "jane@example.com"})
    assert int(fmt.split_note(text_of(vault, opened))[0]["open_items"]) == 1

    pri = vault / "Administrator" / "Priorities.md"
    pri.write_text(
        text_of(vault, "Administrator/Priorities.md").replace(
            "1. (your first priority — a topic page link such as [[Wiki/Topics/acme-supplier-contract]] or plain words)",
            "1. [[Wiki/Topics/acme-contract]]\n2. Hiring a PM <!-- hire by October -->\n3. [[Wiki/Topics/not-a-page|Something new]]\n\n- not a numbered line\n",
        ),
        encoding="utf-8",
    )
    got = timeblock.read_priorities(vault, TODAY)
    assert got == [
        {"rank": 1, "name": "Acme contract", "page": "[[Wiki/Topics/acme-contract]]"},
        {"rank": 2, "name": "Hiring a PM", "page": None},
        {"rank": 3, "name": "Something new", "page": "[[Wiki/Topics/not-a-page]]"},
        {"rank": 4, "name": "Office move", "page": "[[Wiki/Topics/office-move]]"},
    ]
    assert acme.endswith("acme-contract.md") and soon.endswith("office-move.md") and far.endswith("strategy-2027.md")
    # later the far topic is inside the window, the overdue one still counts, the closed one never does
    later = timeblock.read_priorities(vault, date(2026, 11, 5))
    assert [p["name"] for p in later] == ["Acme contract", "Hiring a PM", "Something new", "Office move", "Strategy 2027"]

    # the tool reads Preferences.md and Priorities.md itself
    plan = timeblock.time_block_plan(WEEK, week_events(), "2026-08-24")
    assert [p["name"] for p in plan["priorities"]] == ["Acme contract", "Hiring a PM", "Something new", "Office move"]
    assert plan["missing_keys"] == [] and plan["preferences_used"]["no_meeting_blocks"] == ["Fri 13:00-17:00"]
    assert blocks_of(plan, "2026-08-24")[0]["page"] == "[[Wiki/Topics/acme-contract]]"


# ------------------------------------------------------------------ write + audit


def test_write_then_audit_with_held_rows(vault):
    plan = timeblock.plan(WEEK, week_events(), TODAY, PREFS, PRIORITIES)
    blocks = []
    for n, b in enumerate(b for d in plan["days"] for b in d["blocks"]):
        b = dict(b)
        if not b["existing"]:
            b["occurrence_key"], b["entry_id"] = f"NEW{n}|{b['start']}", f"E{n}"
        blocks.append(b)
    res = timeblock.write(WEEK, blocks, CB)
    path = f"Administrator/Time-blocks/{WEEK}.md"
    assert res == {"path": path, "action": "created", "week": WEEK, "blocks": 15, "planned": 15}
    text = text_of(vault, path)
    fm, _b, body = fmt.split_note(text)
    assert fm["type"] == "time-block" and fm["week"] == WEEK and fm["start"] == "2026-08-24" and fm["end"] == "2026-08-30" and fm["planned"] == 15 and fm["created_by"] == CB
    assert store.read(path)["sections"] == [f"Time blocks — {WEEK}", "Plan", "Held", "Notes"]
    assert "| Day | Start | End | Kind | Subject | Priority |" in body and "| Day | Block | Result | Note |" in body
    assert "| Mon 24 Aug | 09:00 | 10:30 | focus | [Focus] Acme contract | Acme contract <!-- occurrence_key: NEW0\\|2026-08-24T09:00:00 # plan --> |" in body
    assert "| Thu 27 Aug | 09:00 | 10:30 | focus | [Focus] Acme contract | Acme contract <!-- occurrence_key: G\\|2026-08-27T09:00:00 # plan --> |" in body
    assert "| Mon 24 Aug | 12:15 | 13:00 | admin | [Admin] Email and small tasks | — <!-- occurrence_key:" in body
    with pytest.raises(Exception):
        timeblock.write(WEEK, [], CB)

    # a re-plan appends under Update and moves planned forward
    again = timeblock.write(WEEK, blocks[:2], CB)
    assert again["action"] == "appended" and again["planned"] == 17
    text = text_of(vault, path)
    assert text.count("## Update ") == 1 and text.count("### Plan") == 1 and fmt.split_note(text)[0]["planned"] == 17

    # the Held rows the collect command writes, one per answered block
    keys = {b["subject"] + b["start"]: b["occurrence_key"] for b in blocks}
    for day, subject, start, result, note in (
        ("Mon 24 Aug", "[Focus] Acme contract", "2026-08-24T09:00:00", "held", ""),
        ("Mon 24 Aug", "[Focus] Hiring a PM", "2026-08-24T10:30:00", "moved", "to 14:00"),
        ("Mon 24 Aug", "[Admin] Email and small tasks", "2026-08-24T12:15:00", "skipped", "inbox zero already"),
        ("Thu 27 Aug", "[Focus] Acme contract", "2026-08-27T09:00:00", "Held", ""),
    ):
        r = store.append_row(path, "Held", [day, subject, result, note], dedupe_key=keys[subject + start], key_label="occurrence_key")
        assert r["appended"] is True
    assert store.append_row(path, "Held", ["Mon 24 Aug", "[Focus] Acme contract", "held", ""], dedupe_key=keys["[Focus] Acme contract2026-08-24T09:00:00"], key_label="occurrence_key")["appended"] is False
    rows = timeblock.read_held_rows(vault, WEEK)
    assert [(r["day"], r["result"], r["note"]) for r in rows] == [("Mon 24 Aug", "held", ""), ("Mon 24 Aug", "moved", "to 14:00"), ("Mon 24 Aug", "skipped", "inbox zero already"), ("Thu 27 Aug", "held", "")]
    assert rows[0]["key"] == "NEW0|2026-08-24T09:00:00"

    # the week as Outlook returns it afterwards: the meetings plus the planner appointments (the moved one at its new time)
    events = week_events()
    for b in blocks:
        if b["existing"]:
            continue
        e = ev(b["subject"], b["start"], b["end"], 0, occurrence_key=b["occurrence_key"], entry_id=b["entry_id"])
        if b["subject"] == "[Focus] Hiring a PM" and b["start"] == "2026-08-24T10:30:00":
            e["start"], e["end"] = "2026-08-24T14:00:00", "2026-08-24T15:30:00"
        events.append(e)
    events.append(ev("Dentist", "2026-08-25T16:00:00", "2026-08-25T17:00:00", 0))  # other
    events.append({"subject": "Holiday", "start": "2026-08-28T00:00:00", "end": "2026-08-29T00:00:00", "all_day": True, "attendee_count": 0})
    a = timeblock.audit(WEEK, events, rows, PREFS)
    assert a["blocks"] == {"planned": 15, "held": 2, "moved": 1, "skipped": 1, "unanswered": 11}
    assert a["work_hours"] == 40.0
    assert a["hours"] == {"meeting": 8.3, "focus": 12.0, "admin": 4.5, "other": 1.0, "unplanned": 14.2}
    assert a["shares"]["meeting"] == 0.21 and a["shares"]["unplanned"] == 0.35
    assert a["per_priority"] == [
        {"name": "Acme contract", "planned_hours": 7.5, "held_hours": 3.0},
        {"name": "Hiring a PM", "planned_hours": 3.0, "held_hours": 1.5},
        {"name": "Offsite", "planned_hours": 1.5, "held_hours": 0.0},
    ]
    assert a["lines"] == [
        "Meetings 8.3 h (21%), focus 12 h (30%), admin 4.5 h (11%), other 1 h (3%), unplanned 14.2 h (35%) of 40 work hours.",
        "Blocks: 15 planned — 2 held, 1 moved, 1 skipped, 11 unanswered.",
        "Focus: Acme contract 7.5 h planned, 3 h held; Hiring a PM 3 h planned, 1.5 h held; Offsite 1.5 h planned, 0 h held.",
    ]
    # the tool reads the note's rows and the vault's preferences itself; a week without a note has no rows
    assert timeblock.time_audit(WEEK, events)["blocks"] == a["blocks"]
    empty = timeblock.time_audit("2026-W34", [ev("Only meeting", "2026-08-18T09:00:00", "2026-08-18T10:00:00")])
    assert empty["held_rows"] == 0 and empty["hours"]["meeting"] == 1.0 and empty["hours"]["unplanned"] == 39.0
    assert empty["lines"][1] == "Blocks: none planned this week." and len(empty["lines"]) == 2
    # a row without a key still matches by day and block subject
    by_name = [{"day": "Tue 25 Aug", "block": "[Focus] Acme contract", "result": "skipped", "note": "", "key": ""}]
    assert timeblock.audit(WEEK, events, by_name, PREFS)["blocks"]["skipped"] == 1


def test_server_time_block_tools_round_trip(vault):
    server = build_server()

    def call(name, args):
        out = asyncio.run(server.call_tool(name, args))
        return json.loads(out[0].text if isinstance(out, list) else out[0][0].text)

    plan = call("vault_time_block_plan", {"week": WEEK, "events": week_events(), "today": "2026-08-24"})
    assert plan["priorities"] == [] and [d["date"] for d in plan["days"]] == ["2026-08-24", "2026-08-25", "2026-08-27", "2026-08-28"]
    assert plan["days"][0]["blocks"][0]["subject"] == "[Focus] Deep work"
    blocks = [dict(b, occurrence_key=f"K{i}", entry_id=f"E{i}") for i, b in enumerate(b for d in plan["days"] for b in d["blocks"])]
    w = call("vault_time_block_write", {"week": WEEK, "blocks": blocks})
    assert w["action"] == "created" and w["path"] == f"Administrator/Time-blocks/{WEEK}.md"
    assert fmt.split_note(text_of(vault, w["path"]))[0]["created_by"] == CB
    a = call("vault_time_audit", {"week": WEEK, "events": week_events()})
    assert a["blocks"]["planned"] == 1 and a["hours"]["meeting"] == 8.3 and len(a["lines"]) == 3
    with pytest.raises(Exception):
        call("vault_time_block_plan", {"week": "nope", "events": []})


def test_now_keeps_today_free_before_the_clock(vault):
    plan = timeblock.time_block_plan(WEEK, week_events(), "2026-08-24", now="13:20")
    monday = next(d for d in plan["days"] if d["date"] == "2026-08-24")
    assert all(b["start"] >= "2026-08-24T13:30" for b in monday["blocks"] if not b["existing"])
    late = timeblock.time_block_plan(WEEK, week_events(), "2026-08-24", now="17:05")
    assert any(s["date"] == "2026-08-24" and s["reason"].startswith("work hours are over") for s in late["skipped_days"])
    other = next(d for d in late["days"] if d["date"] == "2026-08-25")
    assert other["blocks"]
