"""soma_vault: init, slug rules, write modes, identity, tables, listing."""

from __future__ import annotations

import asyncio
import json
import zipfile

import pytest

from soma_vault import frontmatter as fmt
from soma_vault import notes, store, wiki_lint
from soma_vault.server import build_server

CB = "soma/0.0.4"


@pytest.fixture
def vault(tmp_path, monkeypatch):
    root = tmp_path / "Vault"
    root.mkdir()
    monkeypatch.setenv("SOMA_VAULT", str(root))
    monkeypatch.delenv("SOMA_VAULT_NAME", raising=False)
    store.init(created_by=CB)
    return root


def legacy_followups(vault):
    """Follow-ups.md as 0.3.0 kept it: rows may still be added until the migration."""
    cols = "| --- | --- | --- | --- | --- |"
    head = ["| " + " | ".join(notes.FOLLOWUPS_OPEN_HEADER) + " |", cols]
    done = ["| " + " | ".join(notes.FOLLOWUPS_DONE_HEADER) + " |", cols]
    text = ["---", "type: followups", "source: outlook", "created_by: " + CB, "---", "",
            "# Follow-ups", "", "Things I am waiting on.", "", "## Open", ""] + head + ["", "## Done", ""] + done
    (vault / "Soma" / "Follow-ups.md").write_text(chr(10).join(text) + chr(10), encoding="utf-8")
    return "Soma/Follow-ups.md"


def email_fm(**over):
    fm = {
        "type": "email",
        "source": "outlook",
        "internet_message_id": "<abc@example.com>",
        "entry_id": "00AA",
        "conversation_id": "CONV1",
        "subject": "Re: Budget Q3",
        "from": "jane.doe@example.com",
        "from_name": "Jane Doe",
        "from_link": "[[Wiki/People/Jane Doe]]",
        "to": ["me@example.com"],
        "cc": [],
        "received": "2026-08-22T09:14:00+02:00",
        "status": "todo",
        "created_by": CB,
    }
    fm.update(over)
    return fm


def meeting_fm(**over):
    fm = {
        "type": "meeting",
        "source": "outlook",
        "global_id": "GID1",
        "occurrence_key": "GID1|2026-08-25T13:00:00+02:00",
        "subject": "Supplier sync",
        "start": "2026-08-25T13:00:00+02:00",
        "end": "2026-08-25T14:00:00+02:00",
        "location": "Room 4",
        "organizer": "jane.doe@example.com",
        "organizer_link": "[[Wiki/People/Jane Doe]]",
        "attendees": ["jane.doe@example.com"],
        "attendee_links": ["[[Wiki/People/Jane Doe]]"],
        "is_recurring": True,
        "status": "upcoming",
        "created_by": CB,
    }
    fm.update(over)
    return fm


def person_fm(**over):
    fm = {
        "type": "person",
        "source": "outlook",
        "name": "Jane Doe",
        "email": "Jane.Doe@example.com",
        "aliases": ["jdoe@example.com"],
        "last_contact": "2026-08-22T09:14:00+02:00",
        "created_by": CB,
    }
    fm.update(over)
    return fm


# ------------------------------------------------------------------ status/init


def test_status_without_env(monkeypatch):
    monkeypatch.delenv("SOMA_VAULT", raising=False)
    s = store.status()
    assert s["exists"] is False and s["soma_dir_exists"] is False
    assert set(s["folders"]) == set(notes.FOLDERS)


def test_init_creates_everything(vault):
    s = store.status()
    assert s["soma_dir_exists"]
    assert all(s["folders"].values()), s["folders"]
    assert all(s["files"].values()), s["files"]
    assert s["vault_name"] == "Vault"
    views = {p.name for p in (vault / "Soma" / "_views").glob("*.base")}
    assert views == {"People.base", "Follow-ups.base", "Meetings.base", "Emails.base", "Wiki.base"}
    wiki_dir = vault / "Soma" / "Wiki"
    assert {p.name for p in wiki_dir.glob("*.md")} == {"Index.md", "Log.md", "Review.md", "Wiki.md", "Questions.md"}
    schema_text = (wiki_dir / "Wiki.md").read_text(encoding="utf-8")
    assert "type: wiki-schema" in schema_text and "# The wiki — how pages work" in schema_text and "## Your notes on this schema" in schema_text
    assert all((wiki_dir / f).is_dir() for f in ("People", "Orgs", "Topics", "Howto"))
    fu = (vault / "Soma" / "Follow-ups.md").read_text(encoding="utf-8")
    assert "type: followups" in fu
    assert "## Open" in fu and "## Done" in fu
    assert "| Since | Who | What | Email | Last checked |" in fu
    pref = fmt.split_note((vault / "Soma" / "Preferences.md").read_text(encoding="utf-8"))[0]
    assert pref["work_start"] == "09:00" and pref["buffer_minutes"] == 15
    assert pref["preferred_days"] == ["Tue", "Wed", "Thu"]
    # second run: nothing created, everything skipped
    again = store.init(created_by=CB)
    assert again["created"] == []
    assert "Soma/Follow-ups.md" in again["skipped"]


def test_init_creates_priorities_and_the_planner_preferences(vault):
    prio = vault / "Soma" / "Priorities.md"
    text = prio.read_text(encoding="utf-8")
    assert "type: priorities" in text and "source: soma" in text and "## Priorities" in text
    assert "1. (your first priority" in text and "[[Wiki/Topics/acme-supplier-contract]]" in text
    assert store.status()["files"]["Priorities.md"] is True
    pref_text = (vault / "Soma" / "Preferences.md").read_text(encoding="utf-8")
    pref = fmt.split_note(pref_text)[0]
    assert pref["peak_hours"] == ["09:00-12:00"] and pref["focus_block_minutes"] == 90 and pref["focus_blocks_per_day"] == 2
    assert pref["admin_blocks_per_day"] == 2 and pref["admin_block_minutes"] == 45 and pref["collect_folders"] == []
    for key in ("peak_hours", "focus_block_minutes", "focus_blocks_per_day", "admin_blocks_per_day", "admin_block_minutes", "slack_share", "collect_folders"):
        assert f"- `{key}`" in pref_text, key  # every key has its one-line explanation
    # read_preferences: the file's values, typed, nothing missing
    r = store.read_preferences()
    assert r["path"] == "Soma/Preferences.md" and r["missing"] == []
    p = r["preferences"]
    assert p["slack_share"] == 0.2 and p["work_start"] == "09:00" and p["buffer_minutes"] == 15 and p["no_meeting_blocks"] == ["Fri 13:00-17:00"]
    # a 0.2.0 file without the planner keys: defaults filled in, missing listed
    (vault / "Soma" / "Preferences.md").write_text("---\ntype: preferences\nwork_start: \"08:00\"\nslack_share: 0.5\nmine: true\n---\n# P\n", encoding="utf-8")
    r = store.read_preferences()
    assert r["preferences"]["work_start"] == "08:00" and r["preferences"]["slack_share"] == 0.5 and r["preferences"]["peak_hours"] == ["09:00-12:00"]
    assert r["preferences"]["focus_block_minutes"] == 90 and r["preferences"]["mine"] is True
    assert "peak_hours" in r["missing"] and "collect_folders" in r["missing"] and "work_start" not in r["missing"] and "slack_share" not in r["missing"]
    # no file at all: every key missing, path None
    (vault / "Soma" / "Preferences.md").unlink()
    r = store.read_preferences()
    assert r["path"] is None and set(r["missing"]) == set(store.PREFERENCE_DEFAULTS) and r["preferences"]["admin_block_minutes"] == 45
    # Priorities.md is the user's: overwrite=true leaves it alone
    prio.write_text("---\ntype: priorities\n---\n# mine\n\n## Priorities\n\n1. [[Wiki/Topics/q3-budget]]\n", encoding="utf-8")
    res = store.init(overwrite=True, created_by=CB)
    assert "Soma/Priorities.md" in res["skipped"] and "# mine" in prio.read_text(encoding="utf-8")


def test_init_creates_the_questions_file(vault):
    q = vault / "Soma" / "Wiki" / "Questions.md"
    text = q.read_text(encoding="utf-8")
    fm = fmt.split_note(text)[0]
    assert fm["type"] == "wiki-questions" and fm["source"] == "soma" and fm["created_by"] == CB
    assert "# Questions" in text and "## Questions" in text
    # the two examples sit in a code block above the list, so the list itself is
    # empty and lint proposes no page named "example" on a brand new vault
    lines = [l for l in text.split("\n") if l.startswith("- ")]
    assert len(lines) == 2 and all("→ [[Wiki/Topics/example]]" in l for l in lines) and lines[1].endswith("f:abcd")
    assert text.index("```markdown") < text.index("## Questions")
    assert wiki_lint.read_questions(vault) == []
    assert "Wiki/Questions.md" in notes.FILES and store.status()["files"]["Wiki/Questions.md"] is True
    # the user's own list: a second init, with overwrite, leaves it alone
    q.write_text("---\ntype: wiki-questions\n---\n# mine\n\n## Questions\n\n- mine? → [[Wiki/Topics/q3-budget]]\n", encoding="utf-8")
    res = store.init(overwrite=True, created_by=CB)
    assert "Soma/Wiki/Questions.md" in res["skipped"] and "# mine" in q.read_text(encoding="utf-8")


def test_chat_and_time_block_note_rules():
    fm = {"type": "chat", "chat_id": "19:abc@thread.v2", "chat_title": "Re: Q3 budget", "date": "2026-08-21"}
    assert notes.base_filename("chat", fm) == "2026-08-21 Q3 budget.md"
    assert notes.folder_of("chat") == "Soma/Teams" and notes.folder_of("time-block") == "Soma/Time-blocks"
    assert notes.identity_of("chat", fm) == {"chat_id": "19:abc@thread.v2", "date": "2026-08-21"}
    ident = notes.normalize_identity("chat", "19:abc@thread.v2|2026-08-21")
    assert ident == {"chat_id": "19:abc@thread.v2", "date": "2026-08-21"} and notes.matches("chat", fm, ident)
    assert not notes.matches("chat", dict(fm, date="2026-08-22"), ident)
    with pytest.raises(notes.NoteError):
        notes.normalize_identity("chat", "19:abc@thread.v2")
    tb = {"type": "time-block", "week": "2026-W35", "start": "2026-08-24", "end": "2026-08-30"}
    assert notes.base_filename("time-block", tb) == "2026-W35.md" and notes.identity_of("time-block", tb) == {"week": "2026-W35"}
    assert notes.matches("time-block", tb, notes.normalize_identity("time-block", "2026-W35"))
    assert {"messages", "last", "planned"} <= set(notes.REPLACEABLE_KEYS)
    assert "Teams" in notes.FOLDERS and "Time-blocks" in notes.FOLDERS and "Documents" in notes.FOLDERS and "Priorities.md" in notes.FILES


def test_init_peak_hours(vault):
    res = store.init(overwrite=True, created_by=CB, peak_hours=["08:00-10:30", "14:00-16:00"])
    assert "Soma/Preferences.md" in res["created"]
    pref = fmt.split_note((vault / "Soma" / "Preferences.md").read_text(encoding="utf-8"))[0]
    assert pref["peak_hours"] == ["08:00-10:30", "14:00-16:00"]
    assert store.read_preferences()["preferences"]["peak_hours"] == ["08:00-10:30", "14:00-16:00"]
    with pytest.raises(store.VaultError):
        store.init(overwrite=True, created_by=CB, peak_hours=["9-12"])
    assert fmt.split_note(store.preferences_template("09:00", "17:00", 15, CB))[0]["peak_hours"] == ["09:00-12:00"]


def test_init_overwrite_keeps_followups(vault):
    fu = vault / "Soma" / "Follow-ups.md"
    fu.write_text("---\ntype: followups\n---\n# mine\n", encoding="utf-8")
    res = store.init(work_start="08:00", overwrite=True, created_by=CB)
    assert "Soma/Preferences.md" in res["created"]
    assert "Soma/Follow-ups.md" in res["skipped"]
    assert "# mine" in fu.read_text(encoding="utf-8")


def test_init_zips_the_vault_once_before_an_older_wiki_is_read_back(vault):
    """A vault written before this version keeps a copy of Soma/ before
    the first writing call reads its pages back and writes them again."""
    from soma_vault import wiki_reconcile

    assert store.init(created_by=CB)["backup"] is None  # no wiki pages: nothing to keep
    page = vault / "Soma" / "Wiki" / "Topics" / "q3-budget.md"
    page.write_text("---\ntype: topic\ntitle: Q3 budget\n---\n\n# Q3 budget\n", encoding="utf-8")
    cache = vault / "Soma" / "Wiki" / "_cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "queries.log").write_text("who keeps the ledger\n", encoding="utf-8")

    res = store.init(created_by=CB)
    assert res["backup"].startswith("Soma/_backup/") and res["backup"].endswith(".zip")
    with zipfile.ZipFile(vault / res["backup"]) as z:
        names = z.namelist()
    assert "Wiki/Topics/q3-budget.md" in names and "Preferences.md" in names
    assert not any(n.startswith("_backup/") or "_cache/" in n for n in names)

    wiki_reconcile.reconcile(vault)  # the state file is written; the copy was for that one pass
    assert store.init(created_by=CB)["backup"] is None


def test_vault_root_must_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("SOMA_VAULT", str(tmp_path / "nope"))
    with pytest.raises(store.VaultError):
        store.vault_root()
    monkeypatch.setenv("SOMA_VAULT", "relative/path")
    with pytest.raises(store.VaultError):
        store.vault_root()


# ----------------------------------------------------------------------- slug


@pytest.mark.parametrize(
    "subject,expected",
    [
        ("Re: Re: FW: Budget", "Budget"),
        ("AW: WG: TR: SV: Fwd:  Hello  world ", "Hello world"),
        ('What? <a>:"b"/c\\d|e*f', "What_ _a___b__c_d_e_f"),
        ("", "(no subject)"),
        ("Re:", "(no subject)"),
        ("Ends with dots...", "Ends with dots"),
        ("x" * 80, "x" * 60),
        ("tab\there\x01ctl", "tab_here_ctl"),
    ],
)
def test_slug(subject, expected):
    assert notes.slug(subject) == expected


def test_meeting_slug_strips_cancel_prefix():
    assert notes.slug("Canceled: Re: Sync", meeting=True) == "Sync"
    assert notes.slug("Canceled: Sync") == "Canceled_ Sync"


def test_filenames():
    assert notes.base_filename("email", email_fm()) == "2026-08-22 Budget Q3.md"
    assert notes.base_filename("meeting", meeting_fm()) == "2026-08-25 1300 Supplier sync.md"
    assert notes.base_filename("person", person_fm(name="Doe: Jane")) == "Doe_ Jane.md"
    assert notes.base_filename("person", person_fm(name="")) == "Jane.Doe.md"
    assert notes.base_filename("daily", {"date": "2026-08-22"}) == "2026-08-22.md"
    assert notes.base_filename("weekly", {"week": "2026-W34"}) == "2026-W34.md"
    with pytest.raises(notes.NoteError):
        notes.base_filename("weekly", {"week": "34"})


# ----------------------------------------------------------------- frontmatter


def test_frontmatter_round_trip():
    data = {
        "type": "email",
        "entry_id": "00AA",
        "internet_message_id": "<abc@example.com>",
        "from_link": "[[Wiki/People/Jane Doe]]",
        "subject": 'He said "hi": ok #1',
        "to": ["a@example.com", "b@example.com"],
        "cc": [],
        "received": "2026-08-22T09:14:00+02:00",
        "is_recurring": False,
        "mails_seen": 23,
        "empty": "",
        "none": None,
        "numeric_string": "0123",
        "location": "",
    }
    text = fmt.format_frontmatter(data)
    parsed, block, body = fmt.split_note(text + "\nbody\n")
    expected = dict(data)
    expected["none"] = ""
    assert parsed == expected
    assert body == "body\n"
    assert 'received: "2026-08-22T09:14:00+02:00"' in text
    assert 'entry_id: "00AA"' in text
    assert 'subject: "He said \\"hi\\": ok #1"' in text
    assert 'from_link: "[[Wiki/People/Jane Doe]]"' in text
    assert 'numeric_string: "0123"' in text
    assert "is_recurring: false" in text
    assert "cc: []" in text
    assert "  - a@example.com" in text


def test_frontmatter_parses_hand_written_forms():
    block = (
        "type: person\n"
        "aliases: [Doe, Jane, 'x@example.com']\n"
        "tags:\n"
        "  - one\n"
        "  - \"two: 2\"\n"
        "flag: true\n"
        "n: 7\n"
        "empty_list: []\n"
        "# a comment\n"
    )
    d = fmt.parse_frontmatter_block(block)
    assert d["aliases"] == ["Doe", "Jane", "x@example.com"]
    assert d["tags"] == ["one", "two: 2"]
    assert d["flag"] is True and d["n"] == 7 and d["empty_list"] == []


def test_replace_keys_only_touches_named_lines():
    block = "type: email\nstatus: todo\nto:\n  - a\n"
    out = fmt.replace_keys(block, {"status": "waiting"})
    assert out == "type: email\nstatus: waiting\nto:\n  - a\n"


# ------------------------------------------------------------------ write modes


def test_create_append_upsert(vault):
    res = store.write("email", email_fm(), "# Re: Budget Q3\n\n## Body\n\nhello", "create")
    assert res == {
        "path": "Soma/Emails/2026-08-22 Budget Q3.md",
        "action": "created",
        "identity": {"internet_message_id": "<abc@example.com>", "entry_id": "00AA"},
    }
    p = vault / res["path"]
    first = p.read_text(encoding="utf-8")
    assert first.startswith("---\ntype: email\n")
    assert 'entry_id: "00AA"' in first
    assert first.endswith("hello\n")

    with pytest.raises(store.VaultError):
        store.write("email", email_fm(), "x", "create")

    res2 = store.write("email", email_fm(status="waiting", subject="changed"), "- status: todo → waiting", "append")
    assert res2["action"] == "appended" and res2["path"] == res["path"]
    second = p.read_text(encoding="utf-8")
    assert "## Body\n\nhello\n\n## Update 20" in second
    assert "status: waiting" in second
    assert 'subject: "Re: Budget Q3"' in second  # frozen key untouched
    assert "---\n\n# Re: Budget Q3\n" in second  # blank line after the frontmatter kept
    assert "- status: todo → waiting\n" in second
    assert len(list((vault / "Soma" / "Emails").glob("*.md"))) == 1

    res3 = store.write("email", email_fm(), "again", "upsert")
    assert res3["action"] == "appended"
    res4 = store.write("email", email_fm(internet_message_id="<new@example.com>", entry_id="00AB"), "n", "upsert")
    assert res4["action"] == "created"
    assert res4["path"] == "Soma/Emails/2026-08-22 Budget Q3 (2).md"


def test_append_requires_existing(vault):
    with pytest.raises(store.VaultError):
        store.write("email", email_fm(), "x", "append")


def test_missing_required_key_is_refused(vault):
    fm = email_fm()
    del fm["received"]
    with pytest.raises(notes.NoteError):
        store.write("email", fm, "x", "create")
    with pytest.raises(store.VaultError):
        store.write("email", email_fm(), "x", "replace")


def test_duplicate_filename_suffix(vault):
    a = store.write("email", email_fm(), "a")
    b = store.write("email", email_fm(internet_message_id="<b@example.com>", entry_id="00AB"), "b")
    c = store.write("email", email_fm(internet_message_id="<c@example.com>", entry_id="00AC"), "c")
    assert a["path"].endswith("Budget Q3.md")
    assert b["path"].endswith("Budget Q3 (2).md")
    assert c["path"].endswith("Budget Q3 (3).md")


# -------------------------------------------------------------------- identity


def test_find_email_by_message_id_then_entry_id(vault):
    store.write("email", email_fm(), "a")
    assert store.find("email", "<abc@example.com>")["found"]
    assert store.find("email", {"internet_message_id": "", "entry_id": "00AA"})["found"]
    assert not store.find("email", {"internet_message_id": "<other>", "entry_id": "00AA"})["found"]
    assert not store.find("email", "nope")["found"]
    hit = store.find("email", "00AA")
    assert hit["path"] == "Soma/Emails/2026-08-22 Budget Q3.md"
    assert hit["frontmatter"]["subject"] == "Re: Budget Q3"


def test_find_meeting_by_occurrence_then_global_id(vault):
    store.write("meeting", meeting_fm(), "one")
    later = meeting_fm(
        occurrence_key="GID1|2026-09-01T13:00:00+02:00",
        start="2026-09-01T13:00:00+02:00",
        end="2026-09-01T14:00:00+02:00",
    )
    res = store.write("meeting", later, "two", "upsert")
    assert res["action"] == "created"  # a new occurrence is not the old note
    by_gid = store.find("meeting", {"global_id": "GID1"})
    assert by_gid["found"] and by_gid["path"].startswith("Soma/Meetings/2026-09-01 1300")
    assert len(by_gid["matches"]) == 2
    assert store.find("meeting", "GID1|2026-08-25T13:00:00+02:00")["path"].startswith(
        "Soma/Meetings/2026-08-25 1300"
    )


def test_person_identity_and_alias(vault):
    res = store.write("person", person_fm(), "# Jane Doe")
    assert res["path"] == "Soma/Wiki/People/Jane Doe.md"
    assert store.find("person", "jane.doe@EXAMPLE.com")["found"]
    assert store.find("person", "JDOE@example.com")["found"]  # alias
    assert not store.find("person", "someone@example.com")["found"]
    # second display name for the same address: same note, alias merged, last_contact moved
    res2 = store.write(
        "person",
        person_fm(name="Doe, Jane", aliases=["Doe, Jane"], last_contact="2026-08-23T10:00:00+02:00"),
        "seen again",
        "upsert",
    )
    assert res2["action"] == "appended" and res2["path"] == res["path"]
    fm = fmt.split_note((vault / res["path"]).read_text(encoding="utf-8"))[0]
    assert fm["aliases"] == ["jdoe@example.com", "Doe, Jane"]
    assert fm["last_contact"] == "2026-08-23T10:00:00+02:00"
    assert fm["name"] == "Jane Doe"
    assert len(list((vault / "Soma" / "Wiki" / "People").glob("*.md"))) == 1
    # vault_write("person") goes through the wiki: a draft page following the contract, no "## Update" heading
    text = (vault / res["path"]).read_text(encoding="utf-8")
    assert fm["status"] == "draft" and "## Update" not in text and "seen again" not in text
    assert f"# Jane Doe\n\nJane Doe ({person_fm()['email']}).\n\n## Facts\n\n## Topics\n\n## Open\n\n## Records\n\n## Related\n\n## History\n" in text
    # an old-style body line becomes a Records line
    store.write("person", person_fm(), "- 2026-08-25 — [[Meetings/2026-08-25 1300 Sync]] (held)", "append")
    assert "## Records\n\n- 2026-08-25 — [[Meetings/2026-08-25 1300 Sync]]\n" in (vault / res["path"]).read_text(encoding="utf-8")


def test_daily_and_weekly_identity(vault):
    d = {"type": "daily", "source": "outlook", "date": "2026-08-22", "folder": "inbox",
         "since": "2026-08-21T18:00:00+02:00", "inbox_checked": "2026-08-22T08:31:10+02:00",
         "mails_seen": 23, "status": "todo", "created_by": CB}
    assert store.write("daily", d, "# 2026-08-22")["path"] == "Soma/Daily/2026-08-22.md"
    r = store.write("daily", dict(d, inbox_checked="2026-08-22T15:40:00+02:00", mails_seen=99), "more", "upsert")
    assert r["action"] == "appended" and set(r["frontmatter_changed"]) == {"inbox_checked", "mails_seen"}
    assert store.find("daily", "2026-08-22")["found"]
    w = {"type": "weekly", "week": "2026-W34", "start": "2026-08-17", "end": "2026-08-23", "created_by": CB}
    assert store.write("weekly", w, "# Week 34")["path"] == "Soma/Weekly/2026-W34.md"
    assert store.find("weekly", "2026-W34")["found"]


# ------------------------------------------------------------------ path rules


@pytest.mark.parametrize(
    "bad",
    ["Notes/x.md", "../x.md", "Soma/../x.md", "C:/x.md", "/Soma/x.md", "", "Soma2/x.md"],
)
def test_refuses_paths_outside_soma(vault, bad):
    with pytest.raises(store.VaultError):
        store.resolve(vault, bad)
    with pytest.raises(store.VaultError):
        store.append_row(bad, "Open", ["a"])


def test_accepts_backslashes(vault):
    p = store.resolve(vault, "Soma\\Follow-ups.md")
    assert p == vault / "Soma" / "Follow-ups.md"


# ------------------------------------------------------------------ tables


def test_append_row_dedupe_and_move(vault):
    path = legacy_followups(vault)
    row = ["2026-08-21", "[[Wiki/People/Carol Ng]]", "Contract draft", "[[Emails/2026-08-21 Contract draft]]", "2026-08-22"]
    r1 = store.append_row(path, "Open", row, "00AC")
    assert r1["appended"] and r1["row"].endswith("2026-08-22 <!-- entry_id: 00AC --> |")
    r2 = store.append_row(path, "Open", row, "00AC")
    assert r2 == {"appended": False, "path": path, "reason": "duplicate", "line": r2["line"]}
    store.append_row(path, "Open", ["2026-08-22", "Bob", "Offsite", "", "2026-08-22"], "00AD")
    text = (vault / path).read_text(encoding="utf-8")
    open_part = text.split("## Open")[1].split("## Done")[0]
    assert open_part.count("<!-- entry_id:") == 2
    with pytest.raises(store.VaultError):
        store.append_row(path, "Open", ["too", "few"], "00AE")

    m = store.move_row(path, "Open", "Done", "00AC", set_last_cell="2026-08-23")
    assert m["moved"] and m["row"].endswith("| 2026-08-23 <!-- entry_id: 00AC --> |")
    text = (vault / path).read_text(encoding="utf-8")
    open_part, done_part = text.split("## Open")[1].split("## Done")
    assert "00AC" not in open_part and "00AD" in open_part
    assert "Contract draft" in done_part and "| Since | Who | What | Email | Closed |" in done_part
    assert store.move_row(path, "Open", "Done", "00AC")["moved"] is False
    assert store.move_row(path, "Nope", "Done", "00AD")["moved"] is False


def test_a_generated_file_takes_no_rows(vault):
    """Follow-ups.md is written from the wiki pages: rows go on the page instead."""
    path = "Soma/Follow-ups.md"
    fm = fmt.split_note((vault / "Soma" / "Follow-ups.md").read_text(encoding="utf-8"))[0]
    assert fm["generated"] is True and fm["source"] == "wiki"
    with pytest.raises(store.VaultError) as e1:
        store.append_row(path, "Open", ["2026-08-21", "Bob", "x", "", "2026-08-22"], "00AF")
    assert "written from the wiki pages" in str(e1.value) and "open op" in str(e1.value)
    with pytest.raises(store.VaultError):
        store.move_row(path, "Open", "Done", "00AF")


def test_append_row_creates_section_and_header(vault):
    store.write("email", email_fm(), "# Note\n\n## Body\n\ntext")
    path = "Soma/Emails/2026-08-22 Budget Q3.md"
    with pytest.raises(store.VaultError):
        store.append_row(path, "Related", ["a", "b"])
    r = store.append_row(path, "Related", ["a", "b"], "K1", header=["Left", "Right"], key_label="occurrence_key")
    assert r["appended"]
    text = (vault / path).read_text(encoding="utf-8")
    assert text.rstrip().endswith("## Related\n\n| Left | Right |\n| --- | --- |\n| a | b <!-- occurrence_key: K1 --> |")
    assert "## Body\n\ntext\n" in text
    # a second row lands under the first; a cell with a pipe is escaped
    store.append_row(path, "Related", ["c|d", "e"], "K2", key_label="occurrence_key")
    assert "| c\\|d | e <!-- occurrence_key: K2 --> |" in (vault / path).read_text(encoding="utf-8")
    assert store.read(path)["sections"] == ["Note", "Body", "Related"]


def test_meeting_row_with_pipe_in_occurrence_key_round_trips(vault):
    path = legacy_followups(vault)
    key = "GID1|2026-08-25T13:00:00+02:00 # Confirm Leipzig address"
    row = ["2026-08-25", "[[Wiki/People/Tom Lee]]", "Confirm Leipzig address", "[[Meetings/2026-08-25 1300 Supplier sync]]", "2026-08-25"]
    r1 = store.append_row(path, "Open", row, key, key_label="occurrence_key")
    assert r1["appended"]
    text = (vault / path).read_text(encoding="utf-8")
    line = next(l for l in text.split("\n") if "Leipzig" in l)
    # the pipe inside the hidden comment is escaped, so the row still has five cells
    assert "<!-- occurrence_key: GID1\\|2026-08-25T13:00:00+02:00 # Confirm Leipzig address -->" in line
    assert len(store._cells(line)) == 5
    assert store._cells(line)[-1].endswith("<!-- occurrence_key: " + key + " -->")
    assert store._comment_key(line) == key
    # the same key is a duplicate
    assert store.append_row(path, "Open", row, key, key_label="occurrence_key")["appended"] is False
    # move finds it by the unescaped key and keeps the cells intact
    m = store.move_row(path, "Open", "Done", key, set_last_cell="2026-08-26")
    assert m["moved"] and m["row"] == "| 2026-08-25 | [[Wiki/People/Tom Lee]] | Confirm Leipzig address | [[Meetings/2026-08-25 1300 Supplier sync]] | 2026-08-26 <!-- occurrence_key: GID1\\|2026-08-25T13:00:00+02:00 # Confirm Leipzig address --> |"
    open_part, done_part = (vault / path).read_text(encoding="utf-8").split("## Open")[1].split("## Done")
    assert "Leipzig" not in open_part and done_part.count("<!-- occurrence_key:") == 1
    assert store.move_row(path, "Open", "Done", key)["moved"] is False


def test_pipe_in_plain_cell_survives_move_without_double_escaping(vault):
    path = legacy_followups(vault)
    store.append_row(path, "Open", ["2026-08-21", "Bob", "a|b or c", "", "2026-08-22"], "00AF")
    m = store.move_row(path, "Open", "Done", "00AF", set_last_cell="2026-08-23")
    assert m["row"] == "| 2026-08-21 | Bob | a\\|b or c |  | 2026-08-23 <!-- entry_id: 00AF --> |"
    text = (vault / path).read_text(encoding="utf-8")
    assert "a\\\\|b" not in text and text.count("a\\|b or c") == 1


def test_append_row_into_update_section_dedupes_across_file(vault):
    d = {"type": "daily", "source": "outlook", "date": "2026-08-22", "folder": "inbox",
         "since": "x", "inbox_checked": "y", "mails_seen": 1, "status": "todo", "created_by": CB}
    hdr = ["#", "Label", "From", "Subject", "Received", "Why", "Note"]
    store.write("daily", d, "# 2026-08-22\n\n## Inbox\n\n| " + " | ".join(hdr) + " |\n| --- | --- | --- | --- | --- | --- | --- |")
    path = "Soma/Daily/2026-08-22.md"
    assert store.append_row(path, "Inbox", ["1", "act", "Jane", "Budget", "09:14", "why", ""], "00AA")["appended"]
    heading = store.write("daily", d, "second run", "append")["update_heading"]
    assert store.append_row(path, heading, ["2", "fyi", "Bob", "Hi", "10:00", "why", ""], "00AA", header=hdr)["appended"] is False
    assert store.append_row(path, heading, ["2", "fyi", "Bob", "Hi", "10:00", "why", ""], "00AB", header=hdr)["appended"]


# ------------------------------------------------------------------ read/list


def test_read(vault):
    r = store.read("Soma/Follow-ups.md")
    assert r["frontmatter"]["type"] == "followups"
    assert r["sections"] == ["Follow-ups", "Open", "Done"]
    assert r["body"].startswith("\n# Follow-ups") or r["body"].startswith("# Follow-ups")
    with pytest.raises(store.VaultError):
        store.read("Soma/Missing.md")


def test_list_ordering_and_since(vault):
    for i, rec in enumerate(["2026-08-20T10:00:00+02:00", "2026-08-22T09:14:00+02:00", "2026-08-21T23:30:00-05:00"]):
        store.write("email", email_fm(internet_message_id=f"<{i}@x>", entry_id=f"0{i}", received=rec, subject=f"m{i}"), "b")
    items = store.list_notes("email")
    # m2 is 04:30Z on the 22nd, m1 is 07:14Z on the 22nd: offsets are honoured
    assert [i["frontmatter"]["subject"] for i in items] == ["m1", "m2", "m0"]
    assert all(i["path"].startswith("Soma/Emails/") for i in items)
    assert [i["frontmatter"]["subject"] for i in store.list_notes("email", since="2026-08-21")] == ["m1", "m2"]
    assert len(store.list_notes("email", limit=1)) == 1
    assert store.list_notes("weekly") == []
    with pytest.raises(store.VaultError):
        store.list_notes("email", since="yesterday")


# --------------------------------------------------------------------- server


def test_server_tools():
    server = build_server()
    assert server.name == "vault"
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "vault_status", "vault_init", "vault_find", "vault_write", "vault_row", "vault_read",
        "vault_rules", "vault_inbox_prepare", "vault_write_daily", "vault_save",
        "vault_prep_context", "vault_weekly_facts",
        "vault_wiki_search", "vault_wiki_read", "vault_wiki_write", "vault_wiki_keep",
        "vault_collect", "vault_load_history", "vault_time_block", "vault_priorities_write",
    }
    # 34 tools folded into 20: search took match, write took ingest/create/apply,
    # keep took log/review/lint/merge/migrate, save took the three savers, collect
    # took changed_notes, time_block took its three, row took the two, find took list.
    assert len(tools) == 20


# What every tool costs the model before it has read a word: the same sum the
# host pays on each turn, name + description + inputSchema per tool.
VAULT_SCHEMA_CAP = 28_000
TEAMS_SCHEMA_CAP = 3_500


def _schema_chars(server) -> int:
    tools = asyncio.run(server.list_tools())
    return sum(
        len(json.dumps({"name": t.name, "description": t.description or "", "inputSchema": t.inputSchema}))
        for t in tools
    )


def test_tool_schemas_stay_under_their_caps():
    """Guard the size the tool list costs, so the prose cannot creep back.

    Result shapes and the per-parameter detail live in each server's
    INSTRUCTIONS string, which the host reads once, and the wiki's page
    contract lives in wiki_schema.md. Anything moved back into a description
    is paid for on every turn, so these two numbers are a ratchet: they may
    fall, and a change that raises one is the change to think again about.
    """
    from local_ms_teams.server import build_server as build_teams

    vault_chars = _schema_chars(build_server())
    teams_chars = _schema_chars(build_teams())
    assert vault_chars <= VAULT_SCHEMA_CAP, f"vault tool schemas grew to {vault_chars}"
    assert teams_chars <= TEAMS_SCHEMA_CAP, f"teams tool schemas grew to {teams_chars}"


def test_schema_trim_keeps_every_parameter():
    """Dropping pydantic's "title" metadata must not eat a parameter of that name."""
    from soma_vault.server import _drop_titles

    # what pydantic hands over for a tool that really does take a "title"
    schema = _drop_titles({
        "title": "vault_wiki_writeArguments",
        "type": "object",
        "properties": {
            "title": {"title": "Title", "type": "string", "description": "Noun phrase, 6 words or fewer."},
            "pages": {"title": "Pages", "type": "array", "items": {"title": "Item", "type": "object"}},
        },
        "required": ["title"],
    })
    assert schema["properties"]["title"] == {"type": "string", "description": "Noun phrase, 6 words or fewer."}
    assert schema["properties"]["pages"] == {"type": "array", "items": {"type": "object"}}
    assert "title" not in schema and schema["required"] == ["title"]
    for tool in asyncio.run(build_server().list_tools()):
        schema = tool.inputSchema
        assert "title" not in schema, tool.name
        for name, spec in schema.get("properties", {}).items():
            assert "title" not in spec, f"{tool.name}.{name}"


def test_no_tool_description_runs_long():
    """The eleven tools the plugin leans on may be fuller; the rest stay short."""
    fuller = {
        "vault_wiki_search", "vault_wiki_write", "vault_wiki_keep", "vault_wiki_read",
        "vault_save", "vault_write_daily", "vault_inbox_prepare",
        "vault_prep_context", "vault_status", "vault_find", "vault_write",
    }
    for tool in asyncio.run(build_server().list_tools()):
        cap = 900 if tool.name in fuller else 400
        assert len(tool.description or "") <= cap, f"{tool.name}: {len(tool.description or '')} chars"


def test_server_call_round_trip(vault):
    server = build_server()
    out = asyncio.run(server.call_tool("vault_status", {}))
    text = out[0].text if isinstance(out, list) else out[0][0].text
    assert json.loads(text)["soma_dir_exists"] is True
    out = asyncio.run(server.call_tool("vault_write", {"type": "email", "frontmatter": email_fm(), "body": "hi"}))
    text = out[0].text if isinstance(out, list) else out[0][0].text
    assert json.loads(text)["action"] == "created"
    with pytest.raises(Exception):
        asyncio.run(server.call_tool("vault_read", {"path": "Other/x.md"}))

    def call(name, args):
        out = asyncio.run(server.call_tool(name, args))
        return json.loads(out[0].text if isinstance(out, list) else out[0][0].text)

    # vault_find without identity is the old list; with one it is the old find
    assert [n["frontmatter"]["subject"] for n in call("vault_find", {"type": "email"})] == ["Re: Budget Q3"]
    assert call("vault_find", {"type": "email", "identity": "<abc@example.com>"})["found"] is True
    # vault_row does both halves of the old pair
    daily = {"type": "daily", "date": "2026-08-22", "folder": "inbox", "since": "2026-08-22T00:00:00+02:00",
             "inbox_checked": "2026-08-22T09:00:00+02:00", "mails_seen": 0, "status": "open", "created_by": "t"}
    path = call("vault_write", {"type": "daily", "frontmatter": daily, "body": "b"})["path"]
    assert call("vault_row", {"action": "append", "path": path, "section": "Open", "row": ["a", "b"],
                              "dedupe_key": "K1", "header": ["One", "Two"]})["appended"] is True
    call("vault_row", {"action": "append", "path": path, "section": "Done", "row": ["x", "y"],
                       "dedupe_key": "K0", "header": ["One", "Two"]})
    assert call("vault_row", {"action": "move", "path": path, "from_section": "Open", "to_section": "Done",
                              "dedupe_key": "K1", "set_last_cell": "2026-08-22"})["moved"] is True
    for bad in ({"action": "append", "path": path}, {"action": "move", "path": path}, {"action": "nope", "path": path}):
        with pytest.raises(Exception):
            asyncio.run(server.call_tool("vault_row", bad))
    # vault_save says which kind it is writing
    for bad in ({"kind": "email"}, {"kind": "chat"}, {"kind": "transcript"}, {"kind": "nope"}):
        with pytest.raises(Exception):
            asyncio.run(server.call_tool("vault_save", bad))


def test_the_backup_zip_is_made_once_even_before_any_wiki_write(vault):
    """A second setup on an older vault must not zip everything again."""
    from soma_vault import store, wiki
    wiki.create("topic", "Old page", created_by=CB)
    state = vault / "Soma" / "Wiki" / "_cache" / "state.json"
    if state.exists():
        state.unlink()
    first = store.init(created_by=CB)
    assert first["backup"]
    if state.exists():
        state.unlink()
    second = store.init(created_by=CB)
    assert second["backup"] is None
    assert len(list((vault / "Soma" / "_backup").glob("*.zip"))) == 1
