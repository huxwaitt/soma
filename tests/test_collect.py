"""vault_collect_sources (stamps, ask rule, never backwards) and vault_changed_notes
(default folders, last Update excerpt, collect_folders, the never-read list, refusals)."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta

import pytest

from administrator_vault import frontmatter as fmt
from administrator_vault import store, wiki, workflows
from administrator_vault.server import build_server
from administrator_vault.store import VaultError

CB = "administrator/0.4.0"
W = "Administrator/Wiki"


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


def email(n=1, subject="Budget Q3", received="2026-08-22T09:14:00+02:00", body="## Summary\n\nJane asks for numbers.\n", wiki_key=None):
    fm = {
        "type": "email", "source": "outlook", "internet_message_id": f"<m{n}@example.com>", "entry_id": f"00A{n}", "conversation_id": "C1",
        "subject": subject, "from": "jane.doe@example.com", "from_name": "Jane Doe", "from_link": "[[Wiki/People/Jane Doe]]", "to": [], "cc": [],
        "received": received, "status": "todo", "created_by": CB,
    }
    if wiki_key:
        fm["wiki"] = wiki_key
    return store.write("email", fm, f"# {subject}\n\n{body}")["path"]


def touch(vault, path, when: datetime):
    os.utime(vault / path, (when.timestamp(), when.timestamp()))


# ------------------------------------------------------------------ stamps


def test_collect_sources_read_advance_and_the_ask_rule(vault):
    r = workflows.collect_sources("read", now="2026-08-22T09:00:00+02:00")
    assert r["stamps"] == {"teams": None, "outlook": None, "notes": None} and r["age_hours"] == {"teams": None, "outlook": None, "notes": None}
    assert r["ask"] is True and r["default_since"] == "2026-08-22T00:00:00+02:00" and r["last_collected"] == "never"
    assert not (vault / W / "_cache" / "collect.json").exists()

    a = workflows.collect_sources("advance", at="2026-08-21T18:10:00+02:00")
    assert a["advanced"] == ["teams", "outlook", "notes"] and a["refused"] == []
    assert a["stamps"] == {s: "2026-08-21T18:10:00+02:00" for s in ("teams", "outlook", "notes")}
    assert json.loads(text_of(vault, f"{W}/_cache/collect.json")) == a["stamps"]

    r = workflows.collect_sources("read", now="2026-08-22T09:00:00+02:00")
    assert r["ask"] is False and r["age_hours"] == {"teams": 14.8, "outlook": 14.8, "notes": 14.8}
    assert r["default_since"] == "2026-08-21T18:10:00+02:00"
    assert r["last_collected"] == datetime.fromisoformat("2026-08-21T18:10:00+02:00").strftime("%a") + " 21 Aug 18:10"

    # one source forward; another one backwards is refused and left alone
    a = workflows.collect_sources("advance", source="teams", at="2026-08-22T08:00:00+02:00")
    assert a["advanced"] == ["teams"] and a["stamps"]["teams"] == "2026-08-22T08:00:00+02:00" and a["stamps"]["outlook"] == "2026-08-21T18:10:00+02:00"
    a = workflows.collect_sources("advance", source="outlook", at="2026-08-20T08:00:00+02:00")
    assert a["advanced"] == [] and a["refused"] == [{"source": "outlook", "reason": "older-than-stamp", "stamp": "2026-08-21T18:10:00+02:00", "at": "2026-08-20T08:00:00+02:00"}]
    assert a["stamps"]["outlook"] == "2026-08-21T18:10:00+02:00"

    # older than 24 h on any source -> ask; since is the oldest stamp, the words come from the newest
    r = workflows.collect_sources("read", now="2026-08-23T09:00:00+02:00")
    assert r["ask"] is True and r["age_hours"]["outlook"] == 38.8 and r["age_hours"]["teams"] == 25.0
    assert r["default_since"] == "2026-08-21T18:10:00+02:00" and r["last_collected"].endswith("22 Aug 08:00")

    # advance without at uses now; the day-only form and a naive time are taken as local
    a = workflows.collect_sources("advance", source="notes", now="2026-08-23T09:00:00+02:00")
    assert a["stamps"]["notes"] == "2026-08-23T09:00:00+02:00"
    a = workflows.collect_sources("advance", source="notes", at="2026-08-24")
    assert a["advanced"] == ["notes"] and a["stamps"]["notes"].startswith("2026-08-24T00:00:00")

    with pytest.raises(VaultError):
        workflows.collect_sources("advance", source="mail")
    with pytest.raises(VaultError):
        workflows.collect_sources("advance", at="yesterday")
    with pytest.raises(VaultError):
        workflows.collect_sources("nope")


def test_collect_sources_tokens_keeps_the_last_runs_and_the_ratios(vault):
    def tokens(pi, po, ai, ao, command="collect-information"):
        return workflows.collect_sources("tokens", now="2026-08-22T09:00:00+02:00", payload={
            "command": command, "predicted_in": pi, "predicted_out": po, "actual_in": ai, "actual_out": ao})

    r = tokens(1000, 500, 1500, 400)
    assert r["command"] == "collect-information" and r["runs"] == 1 and r["ratio_in"] == 1.5 and r["ratio_out"] == 0.8
    assert r["last"] == {"at": "2026-08-22T09:00:00+02:00", "predicted_in": 1000, "predicted_out": 500, "actual_in": 1500, "actual_out": 400}
    assert json.loads(text_of(vault, f"{W}/_cache/tokens.json"))["collect-information"] == [r["last"]]

    # the median, not the mean: one wild run does not move the ratio
    tokens(1000, 500, 1000, 500)
    r = tokens(1000, 500, 4000, 2500)
    assert r["runs"] == 3 and r["ratio_in"] == 1.5 and r["ratio_out"] == 1.0

    # each command is counted on its own, and read carries the calibration
    lh = tokens(200, 100, 400, 100, command="load-history")
    assert lh["runs"] == 1 and lh["ratio_in"] == 2.0 and lh["ratio_out"] == 1.0
    read = workflows.collect_sources("read", now="2026-08-22T09:00:00+02:00")
    assert read["tokens"] == {"collect-information": {"runs": 3, "ratio_in": 1.5, "ratio_out": 1.0},
                              "load-history": {"runs": 1, "ratio_in": 2.0, "ratio_out": 1.0}}

    # only the last 20 runs per command stay on file
    for i in range(20):
        tokens(100, 100, 100 + i, 100)
    kept = json.loads(text_of(vault, f"{W}/_cache/tokens.json"))["collect-information"]
    assert len(kept) == 20 and kept[0]["actual_in"] == 100 and kept[-1]["actual_in"] == 119
    assert workflows.collect_sources("read", now="2026-08-22T09:00:00+02:00")["tokens"]["collect-information"]["runs"] == 20

    # a bad command or a count that is not a number is an error, and nothing is written
    bad = [{"command": "daily", "predicted_in": 1, "predicted_out": 1, "actual_in": 1, "actual_out": 1},
           {"command": "collect-information", "predicted_in": 0, "predicted_out": 1, "actual_in": 1, "actual_out": 1},
           {"command": "collect-information", "predicted_in": "lots", "predicted_out": 1, "actual_in": 1, "actual_out": 1},
           {"command": "collect-information", "predicted_in": 1, "predicted_out": 1, "actual_in": -1, "actual_out": 1},
           {"command": "collect-information", "predicted_in": 1, "predicted_out": 1, "actual_in": True, "actual_out": 1},
           {"command": "collect-information", "predicted_in": 1, "predicted_out": 1, "actual_in": 1}]
    for payload in bad:
        with pytest.raises(VaultError):
            workflows.collect_sources("tokens", payload=payload)
    with pytest.raises(VaultError):
        workflows.collect_sources("tokens")
    assert len(json.loads(text_of(vault, f"{W}/_cache/tokens.json"))["collect-information"]) == 20


def test_a_vault_with_no_runs_on_file_has_no_calibration(vault):
    assert workflows.collect_sources("read", now="2026-08-22T09:00:00+02:00")["tokens"] == {}


# ------------------------------------------------------------------ changed notes


def test_changed_notes_defaults_excerpt_and_caps(vault):
    now = datetime.now().astimezone()
    since = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    old = email(1, "Old one")
    touch(vault, old, now - timedelta(hours=3))
    fresh = email(2, "Fresh one", wiki_key=["[[Wiki/Topics/q3-budget]]"])
    updated = email(3, "Updated one")
    store.write("email", fmt.split_note(text_of(vault, updated))[0], "### Summary\n\nSecond look: the deadline moved.\n", "append")
    touch(vault, fresh, now - timedelta(minutes=30))
    touch(vault, updated, now - timedelta(minutes=10))
    # never read: wiki pages, attachments, views, backups
    wiki.create("topic", "Q3 budget", lead="Numbers.", summary="Numbers.")
    for extra in ("Attachments/x.md", "_views/y.md", "_backup/z.md"):
        (vault / "Administrator" / extra).parent.mkdir(parents=True, exist_ok=True)
        (vault / "Administrator" / extra).write_text("# never\n", encoding="utf-8")
    (vault / "Administrator" / "Daily").mkdir(exist_ok=True)
    (vault / "Administrator" / "Daily" / "2026-08-22.md").write_text("---\ntype: daily\n---\n# 2026-08-22\n\nA plain day.\n", encoding="utf-8")

    r = workflows.changed_notes(since)
    paths = [n["path"] for n in r["notes"]]
    assert paths == [fresh, updated, "Administrator/Daily/2026-08-22.md"]  # oldest first; the old one is out
    assert r["count"] == 3 and r["total"] == 3 and r["capped"] is False
    assert r["folders"] == ["Administrator/Meetings", "Administrator/Emails", "Administrator/Daily", "Administrator/Weekly"] and r["skipped"] == [] and r["missing"] == []
    n_fresh, n_upd, n_daily = r["notes"]
    assert n_fresh["type"] == "email" and n_fresh["ingested"] is True and n_fresh["from_update"] is False and n_fresh["truncated"] is False
    assert n_fresh["excerpt"].startswith("# Fresh one\n\n## Summary\n\nJane asks for numbers.") and n_fresh["modified"].startswith(str(now.year))
    assert n_upd["ingested"] is False and n_upd["from_update"] is True and n_upd["excerpt"] == "### Summary\n\nSecond look: the deadline moved."
    assert n_daily["type"] == "daily" and n_daily["excerpt"] == "# 2026-08-22\n\nA plain day."
    assert not any("Wiki/" in p or "Attachments/" in p or "_views/" in p or "_backup/" in p for p in paths)

    # caps: max_chars cuts and marks, limit caps and marks
    r = workflows.changed_notes(since, max_chars=12, limit=2)
    assert r["count"] == 2 and r["total"] == 3 and r["capped"] is True
    assert r["notes"][0]["truncated"] is True and r["notes"][0]["excerpt"] == "# Fresh one…"
    assert workflows.changed_notes(since, max_chars=0)["notes"][0]["truncated"] is False

    # a since after everything: nothing
    assert workflows.changed_notes((datetime.now().astimezone() + timedelta(minutes=5)).isoformat(timespec="seconds"))["notes"] == []
    with pytest.raises(VaultError):
        workflows.changed_notes("last week")


def test_changed_notes_collect_folders_skip_list_and_refusals(vault):
    now = datetime.now().astimezone()
    since = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    (vault / "Projects" / "sub").mkdir(parents=True)
    (vault / "Projects" / "plan.md").write_text("# Plan\n\nShip the thing.\n", encoding="utf-8")
    (vault / "Projects" / "sub" / "deep.md").write_text("---\ntype: note\n---\nDeep.\n", encoding="utf-8")
    (vault / "Projects" / "notes.txt").write_text("not markdown", encoding="utf-8")
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "hidden.md").write_text("# hidden\n", encoding="utf-8")
    pref = vault / "Administrator" / "Preferences.md"
    pref.write_text(text_of(vault, "Administrator/Preferences.md").replace("collect_folders: []", "collect_folders:\n  - Projects\n  - Missing"), encoding="utf-8")
    assert store.read_preferences()["preferences"]["collect_folders"] == ["Projects", "Missing"]

    r = workflows.changed_notes(since)
    paths = [n["path"] for n in r["notes"]]
    assert "Projects/plan.md" in paths and "Projects/sub/deep.md" in paths and not any("notes.txt" in p or ".obsidian" in p for p in paths)
    assert r["folders"][-1] == "Projects" and r["missing"] == ["Missing"]
    plan = next(n for n in r["notes"] if n["path"] == "Projects/plan.md")
    assert plan["type"] == "" and plan["ingested"] is False and plan["excerpt"] == "# Plan\n\nShip the thing."
    assert next(n for n in r["notes"] if n["path"] == "Projects/sub/deep.md")["type"] == "note"
    # nothing in the vault was written
    assert not (vault / "Projects" / "plan.md").read_text(encoding="utf-8").startswith("---")

    # explicit folders replace the default set; the never-read folders are skipped with a reason
    r = workflows.changed_notes(since, folders=["Projects", "Administrator/Wiki", "Administrator/Attachments", "Administrator/_views", "Administrator/_backup", "Administrator/Emails"])
    assert r["folders"] == ["Projects", "Administrator/Emails"]
    assert [s["folder"] for s in r["skipped"]] == ["Administrator/Wiki", "Administrator/Attachments", "Administrator/_views", "Administrator/_backup"]
    assert all(s["reason"] == "never read" for s in r["skipped"])
    # the whole vault as a folder still skips the never-read list and dot-folders
    r = workflows.changed_notes(since, folders=["."])
    paths = [n["path"] for n in r["notes"]]
    assert "Projects/plan.md" in paths and not any(p.startswith(("Administrator/Wiki/", ".obsidian")) for p in paths)
    assert not any("Preferences.md" in p for p in paths) or "Administrator/Preferences.md" in paths  # user files under Administrator/ are fine to list

    for bad in (["../elsewhere"], ["C:/Users/x"], ["/abs"], ["Projects/../../out"]):
        with pytest.raises(VaultError):
            workflows.changed_notes(since, folders=bad)


def test_server_collect_tools_round_trip(vault):
    server = build_server()

    def call(name, args):
        out = asyncio.run(server.call_tool(name, args))
        return json.loads(out[0].text if isinstance(out, list) else out[0][0].text)

    r = call("vault_collect_sources", {"action": "read", "now": "2026-08-22T09:00:00+02:00"})
    assert r["ask"] is True and r["last_collected"] == "never"
    a = call("vault_collect_sources", {"action": "advance", "source": "teams", "at": "2026-08-22T08:00:00+02:00"})
    assert a["advanced"] == ["teams"]
    t = call("vault_collect_sources", {"action": "tokens", "payload": {
        "command": "collect-information", "predicted_in": 8000, "predicted_out": 1000, "actual_in": 9600, "actual_out": 900}})
    assert t["runs"] == 1 and t["ratio_in"] == 1.2 and t["ratio_out"] == 0.9
    assert call("vault_collect_sources", {"action": "read", "now": "2026-08-22T09:00:00+02:00"})["tokens"] == {
        "collect-information": {"runs": 1, "ratio_in": 1.2, "ratio_out": 0.9}}
    since = (datetime.now().astimezone() - timedelta(hours=1)).isoformat(timespec="seconds")
    email(1)
    r = call("vault_changed_notes", {"since": since, "max_chars": 20})
    assert r["count"] == 1 and r["notes"][0]["path"] == "Administrator/Emails/2026-08-22 Budget Q3.md" and r["notes"][0]["truncated"] is True
    with pytest.raises(Exception):
        call("vault_changed_notes", {"since": since, "folders": ["../x"]})
