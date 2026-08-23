"""administrator_vault: init, slug rules, write modes, identity, tables, listing."""

from __future__ import annotations

import asyncio
import json

import pytest

from administrator_vault import frontmatter as fmt
from administrator_vault import notes, store
from administrator_vault.server import build_server

CB = "administrator/0.0.4"


@pytest.fixture
def vault(tmp_path, monkeypatch):
    root = tmp_path / "Vault"
    root.mkdir()
    monkeypatch.setenv("ADMINISTRATOR_VAULT", str(root))
    monkeypatch.delenv("ADMINISTRATOR_VAULT_NAME", raising=False)
    store.init(created_by=CB)
    return root


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
        "from_link": "[[People/Jane Doe]]",
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
        "organizer_link": "[[People/Jane Doe]]",
        "attendees": ["jane.doe@example.com"],
        "attendee_links": ["[[People/Jane Doe]]"],
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
    monkeypatch.delenv("ADMINISTRATOR_VAULT", raising=False)
    s = store.status()
    assert s["exists"] is False and s["administrator_dir_exists"] is False
    assert set(s["folders"]) == set(notes.FOLDERS)


def test_init_creates_everything(vault):
    s = store.status()
    assert s["administrator_dir_exists"]
    assert all(s["folders"].values()), s["folders"]
    assert all(s["files"].values()), s["files"]
    assert s["vault_name"] == "Vault"
    views = {p.name for p in (vault / "Administrator" / "_views").glob("*.base")}
    assert views == {"People.base", "Follow-ups.base", "Meetings.base", "Emails.base"}
    fu = (vault / "Administrator" / "Follow-ups.md").read_text(encoding="utf-8")
    assert "type: followups" in fu
    assert "## Open" in fu and "## Done" in fu
    assert "| Since | Who | What | Email | Last checked |" in fu
    pref = fmt.split_note((vault / "Administrator" / "Preferences.md").read_text(encoding="utf-8"))[0]
    assert pref["work_start"] == "09:00" and pref["buffer_minutes"] == 15
    assert pref["preferred_days"] == ["Tue", "Wed", "Thu"]
    # second run: nothing created, everything skipped
    again = store.init(created_by=CB)
    assert again["created"] == []
    assert "Administrator/Follow-ups.md" in again["skipped"]


def test_init_overwrite_keeps_followups(vault):
    fu = vault / "Administrator" / "Follow-ups.md"
    fu.write_text("---\ntype: followups\n---\n# mine\n", encoding="utf-8")
    res = store.init(work_start="08:00", overwrite=True, created_by=CB)
    assert "Administrator/Preferences.md" in res["created"]
    assert "Administrator/Follow-ups.md" in res["skipped"]
    assert "# mine" in fu.read_text(encoding="utf-8")


def test_vault_root_must_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMINISTRATOR_VAULT", str(tmp_path / "nope"))
    with pytest.raises(store.VaultError):
        store.vault_root()
    monkeypatch.setenv("ADMINISTRATOR_VAULT", "relative/path")
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
        "from_link": "[[People/Jane Doe]]",
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
    assert 'from_link: "[[People/Jane Doe]]"' in text
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
        "path": "Administrator/Emails/2026-08-22 Budget Q3.md",
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
    assert len(list((vault / "Administrator" / "Emails").glob("*.md"))) == 1

    res3 = store.write("email", email_fm(), "again", "upsert")
    assert res3["action"] == "appended"
    res4 = store.write("email", email_fm(internet_message_id="<new@example.com>", entry_id="00AB"), "n", "upsert")
    assert res4["action"] == "created"
    assert res4["path"] == "Administrator/Emails/2026-08-22 Budget Q3 (2).md"


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
    assert hit["path"] == "Administrator/Emails/2026-08-22 Budget Q3.md"
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
    assert by_gid["found"] and by_gid["path"].startswith("Administrator/Meetings/2026-09-01 1300")
    assert len(by_gid["matches"]) == 2
    assert store.find("meeting", "GID1|2026-08-25T13:00:00+02:00")["path"].startswith(
        "Administrator/Meetings/2026-08-25 1300"
    )


def test_person_identity_and_alias(vault):
    res = store.write("person", person_fm(), "# Jane Doe")
    assert res["path"] == "Administrator/People/Jane Doe.md"
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
    assert len(list((vault / "Administrator" / "People").glob("*.md"))) == 1


def test_daily_and_weekly_identity(vault):
    d = {"type": "daily", "source": "outlook", "date": "2026-08-22", "folder": "inbox",
         "since": "2026-08-21T18:00:00+02:00", "inbox_checked": "2026-08-22T08:31:10+02:00",
         "mails_seen": 23, "status": "todo", "created_by": CB}
    assert store.write("daily", d, "# 2026-08-22")["path"] == "Administrator/Daily/2026-08-22.md"
    r = store.write("daily", dict(d, inbox_checked="2026-08-22T15:40:00+02:00", mails_seen=99), "more", "upsert")
    assert r["action"] == "appended" and set(r["frontmatter_changed"]) == {"inbox_checked", "mails_seen"}
    assert store.find("daily", "2026-08-22")["found"]
    w = {"type": "weekly", "week": "2026-W34", "start": "2026-08-17", "end": "2026-08-23", "created_by": CB}
    assert store.write("weekly", w, "# Week 34")["path"] == "Administrator/Weekly/2026-W34.md"
    assert store.find("weekly", "2026-W34")["found"]


# ------------------------------------------------------------------ path rules


@pytest.mark.parametrize(
    "bad",
    ["Notes/x.md", "../x.md", "Administrator/../x.md", "C:/x.md", "/Administrator/x.md", "", "Administrator2/x.md"],
)
def test_refuses_paths_outside_administrator(vault, bad):
    with pytest.raises(store.VaultError):
        store.resolve(vault, bad)
    with pytest.raises(store.VaultError):
        store.append_row(bad, "Open", ["a"])


def test_accepts_backslashes(vault):
    p = store.resolve(vault, "Administrator\\Follow-ups.md")
    assert p == vault / "Administrator" / "Follow-ups.md"


# ------------------------------------------------------------------ tables


def test_append_row_dedupe_and_move(vault):
    path = "Administrator/Follow-ups.md"
    row = ["2026-08-21", "[[People/Carol Ng]]", "Contract draft", "[[Emails/2026-08-21 Contract draft]]", "2026-08-22"]
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


def test_append_row_creates_section_and_header(vault):
    store.write("email", email_fm(), "# Note\n\n## Body\n\ntext")
    path = "Administrator/Emails/2026-08-22 Budget Q3.md"
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
    path = "Administrator/Follow-ups.md"
    key = "GID1|2026-08-25T13:00:00+02:00 # Confirm Leipzig address"
    row = ["2026-08-25", "[[People/Tom Lee]]", "Confirm Leipzig address", "[[Meetings/2026-08-25 1300 Supplier sync]]", "2026-08-25"]
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
    assert m["moved"] and m["row"] == "| 2026-08-25 | [[People/Tom Lee]] | Confirm Leipzig address | [[Meetings/2026-08-25 1300 Supplier sync]] | 2026-08-26 <!-- occurrence_key: GID1\\|2026-08-25T13:00:00+02:00 # Confirm Leipzig address --> |"
    open_part, done_part = (vault / path).read_text(encoding="utf-8").split("## Open")[1].split("## Done")
    assert "Leipzig" not in open_part and done_part.count("<!-- occurrence_key:") == 1
    assert store.move_row(path, "Open", "Done", key)["moved"] is False


def test_pipe_in_plain_cell_survives_move_without_double_escaping(vault):
    path = "Administrator/Follow-ups.md"
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
    path = "Administrator/Daily/2026-08-22.md"
    assert store.append_row(path, "Inbox", ["1", "act", "Jane", "Budget", "09:14", "why", ""], "00AA")["appended"]
    heading = store.write("daily", d, "second run", "append")["update_heading"]
    assert store.append_row(path, heading, ["2", "fyi", "Bob", "Hi", "10:00", "why", ""], "00AA", header=hdr)["appended"] is False
    assert store.append_row(path, heading, ["2", "fyi", "Bob", "Hi", "10:00", "why", ""], "00AB", header=hdr)["appended"]


# ------------------------------------------------------------------ read/list


def test_read(vault):
    r = store.read("Administrator/Follow-ups.md")
    assert r["frontmatter"]["type"] == "followups"
    assert r["sections"] == ["Follow-ups", "Open", "Done"]
    assert r["body"].startswith("\n# Follow-ups") or r["body"].startswith("# Follow-ups")
    with pytest.raises(store.VaultError):
        store.read("Administrator/Missing.md")


def test_list_ordering_and_since(vault):
    for i, rec in enumerate(["2026-08-20T10:00:00+02:00", "2026-08-22T09:14:00+02:00", "2026-08-21T23:30:00-05:00"]):
        store.write("email", email_fm(internet_message_id=f"<{i}@x>", entry_id=f"0{i}", received=rec, subject=f"m{i}"), "b")
    items = store.list_notes("email")
    # m2 is 04:30Z on the 22nd, m1 is 07:14Z on the 22nd: offsets are honoured
    assert [i["frontmatter"]["subject"] for i in items] == ["m1", "m2", "m0"]
    assert all(i["path"].startswith("Administrator/Emails/") for i in items)
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
        "vault_status", "vault_init", "vault_find", "vault_write",
        "vault_append_row", "vault_move_row", "vault_read", "vault_list",
        "vault_rules", "vault_inbox_prepare", "vault_write_daily", "vault_save_email",
        "vault_prep_context", "vault_weekly_facts", "vault_attach_transcript",
    }
    assert len(tools) == 15


def test_server_call_round_trip(vault):
    server = build_server()
    out = asyncio.run(server.call_tool("vault_status", {}))
    text = out[0].text if isinstance(out, list) else out[0][0].text
    assert json.loads(text)["administrator_dir_exists"] is True
    out = asyncio.run(server.call_tool("vault_write", {"type": "email", "frontmatter": email_fm(), "body": "hi"}))
    text = out[0].text if isinstance(out, list) else out[0][0].text
    assert json.loads(text)["action"] == "created"
    with pytest.raises(Exception):
        asyncio.run(server.call_tool("vault_read", {"path": "Other/x.md"}))
