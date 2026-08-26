"""vault_load_history: planning a pass over the past, the window handed out per
batch, the place it got to, the window that grows and shrinks, and the report
when every source is finished."""

from __future__ import annotations

import asyncio
import json

import pytest

from administrator_vault import history, store, workflows
from administrator_vault.server import build_server
from administrator_vault.store import VaultError

CB = "administrator/0.4.0"
NOW = "2026-08-24T09:00:00+02:00"
STATE = "Administrator/Wiki/_cache/history.json"


@pytest.fixture
def vault(tmp_path, monkeypatch):
    root = tmp_path / "Vault"
    root.mkdir()
    monkeypatch.setenv("ADMINISTRATOR_VAULT", str(root))
    monkeypatch.delenv("ADMINISTRATOR_VAULT_NAME", raising=False)
    store.init(created_by=CB)
    return root


def stamps(outlook="2026-08-20T18:00:00+02:00", teams="2026-08-18T18:00:00+02:00"):
    if outlook:
        workflows.collect_sources("advance", source="outlook", at=outlook)
    if teams:
        workflows.collect_sources("advance", source="teams", at=teams)


def run(action, **kw):
    kw.setdefault("now", NOW)
    return history.load_history(action, **kw)


def state_of(vault):
    return json.loads((vault / STATE).read_text(encoding="utf-8"))


def finish(payload=None, **kw):
    """One done payload with the parts the model reports."""
    out = {"saved": [], "skipped_ids": [], "exhausted": True, "pages": [], "calls": 1}
    out.update(payload or {})
    out.update(kw)
    return out


# ------------------------------------------------------------------ plan


def test_plan_defaults_and_the_bounds_from_the_collect_stamps(vault):
    before = run("status")
    assert before == {
        "started": False,
        "path": STATE,
        "stamps": {"teams": None, "outlook": None, "notes": None},
        "note": before["note"],
    }
    assert "collect-information first" in before["note"] and not (vault / STATE).exists()

    stamps()
    p = run("plan")
    assert p["planned"] is True and p["batch"] == 25 and p["window_days"] == 7
    assert p["since"] == "2026-05-26T00:00:00+02:00"  # today - 90 days, 00:00
    assert p["until_max"] == {
        "outlook_inbox": "2026-08-20T18:00:00+02:00",
        "outlook_sent": "2026-08-20T18:00:00+02:00",
        "teams": "2026-08-18T18:00:00+02:00",
    }
    assert p["left_days"] == {"outlook_inbox": 87, "outlook_sent": 87, "teams": 85}
    assert p["days"] == 87 and p["batches_estimate"] == 39
    assert p["next_hint"] == {"source": "outlook_inbox", "since": p["since"], "until": "2026-06-02T00:00:00+02:00"}
    assert "25 records per batch" in p["note"]

    written = state_of(vault)
    assert written["version"] == 1 and written["current"] is None and written["finished"] is None
    assert written["sources"]["teams"] == {"place": None, "done": False, "listed": 0, "saved": 0}
    assert written["seen"] == {"outlook": {}, "teams": {}}
    # the stamps are read, never moved
    assert workflows.collect_sources("read", now=NOW)["stamps"]["outlook"] == "2026-08-20T18:00:00+02:00"


def test_plan_without_stamps_stops_at_now_and_takes_a_given_start_date(vault):
    p = run("plan", since="2026-08-01T00:00:00+02:00", batch=10)
    assert p["until_max"] == {s: NOW for s in history.SOURCES}
    assert p["since"] == "2026-08-01T00:00:00+02:00" and p["batch"] == 10
    assert "stops at now" in p["note"]

    with pytest.raises(VaultError):
        run("plan", since="last spring", reset=True)
    with pytest.raises(VaultError):
        run("plan", batch=0, reset=True)
    with pytest.raises(VaultError):
        run("nope")


def test_plan_refuses_while_a_pass_is_running_and_reset_starts_over(vault):
    stamps()
    run("plan")
    run("next")
    run("done", payload=finish(pages=["Wiki/People/Jane Doe"]))

    again = run("plan")
    assert again["planned"] is False and again["refused"] == "already-running"
    assert "reset=true" in again["note"] and again["status"]["batches_done"] == 1

    fresh = run("plan", since="2026-08-10T00:00:00+02:00", reset=True)
    assert fresh["planned"] is True and fresh["started_over"] is True
    s = run("status")
    assert s["batches_done"] == 0 and s["records_saved"] == 0 and s["seen_counts"] == {"outlook": 0, "teams": 0}
    assert s["sources"]["outlook_inbox"]["place"] is None


# ------------------------------------------------------------------ next


def test_next_hands_out_one_window_per_source_in_order_with_the_call_to_make(vault):
    stamps()
    run("plan", since="2026-08-13T00:00:00+02:00")

    one = run("next")
    assert one["batch_no"] == 1 and one["source"] == "outlook_inbox" and one["reissued"] is False
    assert one["since"] == "2026-08-13T00:00:00+02:00" and one["until"] == "2026-08-20T00:00:00+02:00"
    assert one["expected"] == 25 and one["skip_ids"] == []
    assert one["list_with"] == (
        'outlook_list_mails(folder="inbox", since="2026-08-13T00:00:00+02:00", until="2026-08-20T00:00:00+02:00", '
        'limit=100, preview_chars=80, fields=["entry_id", "internet_message_id", "subject", "from", '
        '"from_address", "to", "received", "bulk", "bulk_why", "preview"])'
    )
    # the call the model is told to make as it stands carries the two keys
    # vault_rules(action="match") reads, so no window is listed without them
    assert '"bulk", "bulk_why"' in one["list_with"]
    assert "oldest first" in one["note"]

    # the window listed one batch: its size stays, and the place is its end
    run("done", payload=finish(saved=[{"id": f"<m{n}@x>", "path": f"Administrator/Emails/{n}.md", "received": "2026-08-15T10:00:00+02:00"} for n in range(12)],
                               listed=25))
    two = run("next")
    assert two["batch_no"] == 2 and two["source"] == "outlook_inbox"
    assert two["since"] == "2026-08-20T00:00:00+02:00" and two["until"] == "2026-08-20T18:00:00+02:00"
    assert two["skip_ids"] == []  # the ids of the first window are dated outside this one
    run("done", payload=finish())

    sent = run("next")
    assert sent["batch_no"] == 3 and sent["source"] == "outlook_sent"
    assert sent["since"] == "2026-08-13T00:00:00+02:00" and 'folder="sent"' in sent["list_with"]
    assert sent["until"] == "2026-08-20T18:00:00+02:00"
    run("done", payload=finish())

    chats = run("next")
    assert chats["source"] == "teams" and chats["until"] == "2026-08-18T18:00:00+02:00"
    assert chats["list_with"] == (
        'teams_list_chats(since="2026-08-13T00:00:00+02:00", until="2026-08-18T18:00:00+02:00", '
        "include_messages=true, per_chat=12, max_chars=200, limit=15)"
    )


def test_next_names_the_ids_of_that_window_already_seen(vault):
    stamps()
    run("plan", since="2026-08-13T00:00:00+02:00")
    run("next")
    run("done", payload=finish(
        saved=[{"id": "<in@x>", "path": "Administrator/Emails/a.md", "received": "2026-08-14T10:00:00+02:00"},
               {"id": "<late@x>", "path": "Administrator/Emails/b.md", "received": "2026-08-21T10:00:00+02:00"}],
        skipped_ids=["<noise@x>"], reached="2026-08-14T12:00:00+02:00", exhausted=False))

    again = run("next")
    assert again["since"] == "2026-08-14T12:00:00+02:00"
    assert again["skip_ids"] == ["<in@x>", "<noise@x>"]  # <late@x> is dated after this window
    assert "<late@x>" not in again["skip_ids"]
    # a Teams id is kept apart from the mail ids
    assert state_of(vault)["seen"]["teams"] == {}


def test_next_hands_the_open_window_out_again_instead_of_a_second_one(vault):
    stamps()
    run("plan", since="2026-08-13T00:00:00+02:00")
    one = run("next")
    again = run("next")
    assert again["reissued"] is True and "still open" in again["note"]
    for key in ("batch_no", "source", "since", "until", "expected", "list_with"):
        assert again[key] == one[key]
    assert state_of(vault)["batches_done"] == 0 and state_of(vault)["current"]["n"] == 1

    run("done", payload=finish())
    with pytest.raises(VaultError):  # done needs a batch to be open
        run("done", payload=finish())


def test_a_crash_leaves_the_open_window_to_be_handed_out_unchanged(vault):
    stamps()
    run("plan", since="2026-08-13T00:00:00+02:00")
    one = run("next")
    saved_state = state_of(vault)

    # the session ends here: nothing but the state file is left
    assert saved_state["current"]["n"] == 1 and saved_state["current"]["since"] == one["since"]
    after = run("next")
    assert after["reissued"] is True and after["since"] == one["since"] and after["until"] == one["until"]
    assert after["batch_no"] == one["batch_no"] and after["list_with"] == one["list_with"]

    r = run("done", payload=finish(saved=[{"id": "<a@x>", "path": "Administrator/Emails/a.md", "received": "2026-08-14T09:00:00+02:00"}]))
    assert r["batch"] == 1 and r["saved"] == 1 and state_of(vault)["current"] is None


def test_next_and_done_need_a_plan(vault):
    with pytest.raises(VaultError):
        run("next")
    with pytest.raises(VaultError):
        run("done", payload=finish())


# ------------------------------------------------------------------ done


def test_done_moves_the_place_to_reached_or_to_the_end_of_the_window(vault):
    stamps()
    run("plan", since="2026-08-13T00:00:00+02:00")
    run("next")
    r = run("done", payload=finish(reached="2026-08-16T08:30:00+02:00", exhausted=False,
                                   saved=[{"id": "<a@x>", "path": "Administrator/Emails/a.md", "received": "2026-08-15T10:00:00+02:00"}],
                                   pages=["Wiki/People/Jane Doe", "Wiki/Topics/q3-budget"]))
    assert r["place"] == "2026-08-16T08:30:00+02:00" and r["saved"] == 1 and r["skipped"] == 0
    assert r["source_done"] is False and r["all_done"] is False
    assert r["totals"]["records"] == 1 and r["totals"]["pages"] == 2 and r["totals"]["calls"] == 1
    assert r["totals"]["sources"]["outlook_inbox"] == {"listed": 1, "saved": 1, "done": False, "left_days": 5}
    assert r["next_hint"]["since"] == "2026-08-16T08:30:00+02:00"
    assert r["note"].startswith("Batch 1: 1 saved, pages Wiki/People/Jane Doe, Wiki/Topics/q3-budget; next window 2026-08-16")
    assert r["note"].endswith("— continue?")

    run("next")
    r = run("done", payload=finish())  # exhausted: the place is the end of the window
    assert r["place"] == "2026-08-20T18:00:00+02:00" and r["source_done"] is True
    assert r["next_hint"]["source"] == "outlook_sent"
    assert "Outlook inbox is done" in r["note"]
    assert state_of(vault)["sources"]["outlook_inbox"]["done"] is True

    run("next")
    with pytest.raises(VaultError):  # a window that was not exhausted has to say where it got to
        run("done", payload={"saved": [], "exhausted": False})


def test_done_grows_and_shrinks_the_window(vault):
    stamps(outlook="2026-08-20T18:00:00+02:00")
    run("plan", since="2026-01-01T00:00:00+01:00", batch=25)
    assert run("next")["until"] == "2026-01-08T00:00:00+01:00"

    run("done", payload=finish(listed=60, reached="2026-01-02T00:00:00+01:00", exhausted=False))  # over two batches: halved
    assert state_of(vault)["window_days"] == 3
    two = run("next")
    assert two["since"] == "2026-01-02T00:00:00+01:00" and two["until"] == "2026-01-05T00:00:00+01:00"

    run("done", payload=finish(listed=200, reached="2026-01-03T00:00:00+01:00", exhausted=False))
    assert state_of(vault)["window_days"] == 1
    run("next")
    run("done", payload=finish(listed=100, reached="2026-01-04T00:00:00+01:00", exhausted=False))
    assert state_of(vault)["window_days"] == 1  # never under a day

    run("next")
    run("done", payload=finish(listed=2))  # far under a batch: doubled
    assert state_of(vault)["window_days"] == 2
    for _ in range(6):
        run("next")
        run("done", payload=finish(listed=0))
    assert state_of(vault)["window_days"] == 30  # never over a month


def test_done_counts_a_saved_record_once_per_id_and_keeps_the_pages(vault):
    stamps()
    run("plan", since="2026-08-13T00:00:00+02:00")
    run("next")
    run("done", payload=finish(saved=[{"id": "<a@x>", "path": "Administrator/Emails/a.md", "received": "2026-08-14T10:00:00+02:00"}],
                               pages=["Wiki/People/Jane Doe"], calls=6))
    run("next")
    run("done", payload=finish(saved=[{"id": "<a@x>", "path": "Administrator/Emails/a.md", "received": "2026-08-14T10:00:00+02:00"},
                                      {"id": "<b@x>", "path": "Administrator/Emails/b.md", "received": "2026-08-21T10:00:00+02:00"}],
                               pages=["Wiki/People/Jane Doe", "Wiki/Orgs/acme"], calls=4))
    s = run("status")
    assert s["seen_counts"]["outlook"] == 2 and s["records_saved"] == 3
    assert s["pages_touched"] == ["Wiki/People/Jane Doe", "Wiki/Orgs/acme"]
    assert s["calls"] == 10
    run("next")
    with pytest.raises(VaultError):  # every saved record needs its id
        run("done", payload=finish(saved=[{"path": "Administrator/Emails/c.md"}]))


def test_yes_to_all_is_kept_with_its_cap_and_the_running_cost(vault):
    stamps()
    run("plan", since="2026-08-01T00:00:00+02:00", batch=5)
    w = run("next")
    assert w["auto"] is False and w["cap"] is None and w["cost"] == {"in": 0, "out": 0, "total": 0}

    r = run("done", payload=finish(auto=True, cap=500_000, tokens={"in": 40_000, "out": 6_000}))
    assert r["auto"] is True and r["cap"] == 500_000
    assert r["cost"] == {"in": 40_000, "out": 6_000, "total": 46_000}
    assert "carrying on, 46000 tokens spent of 500000" in r["note"] and "continue?" not in r["note"]

    w = run("next")
    assert w["auto"] is True and w["cap"] == 500_000 and w["cost"]["total"] == 46_000
    assert "Running cost 46000 tokens of the 500000 the user allowed." in w["note"]

    r = run("done", payload=finish(tokens={"in": 9_000, "out": 1_000}))  # the mode is kept, the cost adds up
    assert r["auto"] is True and r["cap"] == 500_000 and r["cost"]["total"] == 56_000
    kept = state_of(vault)
    assert kept["auto"] is True and kept["cap"] == 500_000 and kept["tokens_in"] == 49_000

    st = run("status")
    assert st["auto"] is True and st["cap"] == 500_000 and st["cost"]["total"] == 56_000


def test_yes_to_all_can_be_taken_back_and_a_bad_cap_is_refused(vault):
    stamps()
    run("plan", since="2026-08-01T00:00:00+02:00", batch=5)
    run("next")
    run("done", payload=finish(auto=True, cap=500_000))
    run("next")
    r = run("done", payload=finish(auto=False, cap=None))
    assert r["auto"] is False and r["cap"] is None and r["note"].endswith("— continue?")
    assert state_of(vault)["cap"] is None

    run("next")
    with pytest.raises(VaultError):
        run("done", payload=finish(cap=0))
    with pytest.raises(VaultError):
        run("done", payload=finish(tokens=["40000"]))


def test_status_shows_the_days_left_and_the_records_listed_against_the_ones_saved(vault):
    stamps()
    run("plan", since="2026-08-13T00:00:00+02:00")
    run("next")
    run("done", payload=finish(listed=20, saved=[{"id": "<a@x>", "path": "Administrator/Emails/a.md", "received": "2026-08-14T10:00:00+02:00"}],
                               skipped_ids=["<n1@x>", "<n2@x>"]))
    s = run("status")
    assert s["started"] == NOW and s["path"] == STATE
    assert s["stamps"]["outlook"] == "2026-08-20T18:00:00+02:00"
    assert s["left_days"] == {"outlook_inbox": 1, "outlook_sent": 8, "teams": 6}
    assert s["sources"]["outlook_inbox"]["listed"] == 20 and s["sources"]["outlook_inbox"]["saved"] == 1
    assert s["sources"]["outlook_inbox"]["gap"] == 19  # listed but not saved: visible
    assert s["next_hint"]["source"] == "outlook_inbox" and "days left" in s["note"]
    assert "seen" not in s and s["seen_counts"] == {"outlook": 3, "teams": 0}

    run("next")
    assert "is open" in run("status")["note"]


def test_every_source_finished_reports_the_totals_and_the_lint_line(vault):
    stamps(outlook="2026-08-16T18:00:00+02:00", teams="2026-08-16T18:00:00+02:00")
    run("plan", since="2026-08-13T00:00:00+02:00")

    seen_sources = []
    last = None
    for n in range(3):
        w = run("next")
        seen_sources.append(w["source"])
        last = run("done", payload=finish(
            saved=[{"id": f"<{w['source']}-{n}@x>", "path": f"Administrator/Emails/{n}.md", "received": "2026-08-14T10:00:00+02:00"}],
            pages=[f"Wiki/People/P{n}"]))
    assert seen_sources == ["outlook_inbox", "outlook_sent", "teams"]
    assert last["all_done"] is True and last["source_done"] is True
    assert last["totals"]["records"] == 3 and last["next_hint"] is None
    assert last["finished"] == NOW
    assert last["summary"] == (
        "All sources are done: 3 records saved in 3 batches "
        "(Outlook inbox 1, Outlook sent items 1, Teams chats 1), 3 pages touched. Run /administrator:lint."
    )
    assert last["note"].startswith("Batch 3: 1 saved") and last["note"].endswith("Run /administrator:lint.")

    after = run("next")
    assert after["all_done"] is True and after["batch_no"] is None and after["source"] is None
    assert after["note"].endswith("Run /administrator:lint.")
    s = run("status")
    assert s["finished"] == NOW and s["left_days"] == {"outlook_inbox": 0, "outlook_sent": 0, "teams": 0}
    # a finished pass is not in the way of the next one
    assert run("plan", since="2026-08-01T00:00:00+02:00")["planned"] is True
    # and no stamp moved through any of it
    assert workflows.collect_sources("read", now=NOW)["stamps"] == {
        "teams": "2026-08-16T18:00:00+02:00", "outlook": "2026-08-16T18:00:00+02:00", "notes": None,
    }


def test_a_second_pass_keeps_the_ids_of_the_finished_one_and_reset_drops_them(vault):
    stamps(outlook="2026-08-16T18:00:00+02:00", teams="2026-08-16T18:00:00+02:00")
    run("plan", since="2026-08-13T00:00:00+02:00")
    for _ in range(3):
        w = run("next")
        run("done", payload=finish(
            saved=[{"id": f"<{w['source']}@x>", "path": "Administrator/Emails/a.md", "received": "2026-08-14T10:00:00+02:00"}],
            skipped_ids=[f"<{w['source']}-noise@x>"]))
    assert run("status")["finished"] == NOW

    # an earlier start date walks the same days again, so the ids have to come with it
    again = run("plan", since="2026-08-11T00:00:00+02:00")
    assert again["planned"] is True and again["started_over"] is False and again["kept_ids"] == 6
    assert "kept" in again["note"]
    assert run("status")["seen_counts"] == {"outlook": 4, "teams": 2}
    window = run("next")  # 11–16 Aug: the days the finished pass covered are in it
    assert window["since"] == "2026-08-11T00:00:00+02:00" and window["until"] == "2026-08-16T18:00:00+02:00"
    assert "<outlook_inbox@x>" in window["skip_ids"]  # not read a second time
    assert "<teams@x>" not in window["skip_ids"]  # the chat ids stay with the chats

    # starting over on purpose forgets them
    fresh = run("plan", since="2026-08-11T00:00:00+02:00", reset=True)
    assert fresh["started_over"] is True and fresh["kept_ids"] == 0
    assert run("status")["seen_counts"] == {"outlook": 0, "teams": 0}


def test_status_keeps_the_page_count_right_when_the_list_of_pages_is_long(vault):
    stamps()
    run("plan", since="2026-08-13T00:00:00+02:00", batch=1)
    run("next")
    run("done", payload=finish(pages=[f"Wiki/People/P{n:03d}" for n in range(120)]))
    s = run("status")
    assert s["totals"]["pages"] == 120  # the count is the whole of it
    assert len(s["pages_touched"]) == history.PAGES_SHOWN  # the list is the recent ones
    assert s["pages_touched"][-1] == "Wiki/People/P119"
    assert len(state_of(vault)["pages_touched"]) == 120


def test_a_state_file_that_lost_a_key_reads_as_no_pass_at_all(vault):
    stamps()
    run("plan", since="2026-08-13T00:00:00+02:00")
    good = state_of(vault)

    for drop in ("sources", "until_max", "since"):
        broken = {k: v for k, v in good.items() if k != drop}
        (vault / STATE).write_text(json.dumps(broken), encoding="utf-8")
        assert history.read_state(vault) is None
        assert run("status")["started"] is False

    thin = dict(good, sources={s: {} for s in history.SOURCES})
    thin.pop("window_days"), thin.pop("batches_done")
    (vault / STATE).write_text(json.dumps(thin), encoding="utf-8")
    assert run("status")["sources"]["teams"]["place"] is None
    assert run("next")["batch_no"] == 1  # the defaults stand in, nothing raises


# ------------------------------------------------------------------ server


def test_server_load_history_round_trip(vault):
    server = build_server()

    def call(args):
        out = asyncio.run(server.call_tool("vault_load_history", args))
        return json.loads(out[0].text if isinstance(out, list) else out[0][0].text)

    assert call({"action": "status", "now": NOW})["started"] is False
    stamps()
    p = call({"action": "plan", "since": "2026-08-13T00:00:00+02:00", "batch": 5, "now": NOW})
    assert p["planned"] is True and p["batch"] == 5
    w = call({"action": "next", "now": NOW})
    assert w["batch_no"] == 1 and w["source"] == "outlook_inbox" and w["expected"] == 5
    assert w["list_with"].startswith('outlook_list_mails(folder="inbox"')
    d = call({
        "action": "done",
        "now": NOW,
        "payload": {"saved": [{"id": "<a@x>", "path": "Administrator/Emails/a.md", "received": "2026-08-14T10:00:00+02:00"}],
                    "skipped_ids": [], "reached": "2026-08-15T00:00:00+02:00", "exhausted": False,
                    "pages": ["Wiki/People/Jane Doe"], "calls": 3},
    })
    assert d["batch"] == 1 and d["saved"] == 1 and d["place"] == "2026-08-15T00:00:00+02:00"
    s = call({"action": "status", "now": NOW})
    assert s["records_saved"] == 1 and s["sources"]["outlook_inbox"]["saved"] == 1
    with pytest.raises(Exception):
        call({"action": "sideways", "now": NOW})


def test_a_malformed_open_window_in_the_state_file_is_forgotten(vault):
    from administrator_vault import history, store
    history.load_history("plan", now=NOW) if "NOW" in globals() else history.load_history("plan")
    p = store.resolve(vault, history.PATH)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["current"] = {"source": "gmail", "since": "x"}
    p.write_text(json.dumps(data), encoding="utf-8")
    out = history.load_history("status")
    assert out["current"] is None
    nxt = history.load_history("next")
    assert nxt["source"] == "outlook_inbox" and nxt["reissued"] is False


def test_a_place_that_did_not_move_is_said_out_loud(vault):
    from administrator_vault import history
    history.load_history("plan", now=NOW) if "NOW" in globals() else history.load_history("plan")
    nxt = history.load_history("next")
    out = history.load_history("done", payload={"saved": [], "skipped_ids": [], "reached": nxt["since"], "exhausted": False, "pages": [], "calls": 1})
    assert out["stalled"] is True and "did not move" in out["note"]
    again = history.load_history("next")
    assert again["since"] == nxt["since"]
