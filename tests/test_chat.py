"""administrator_vault.workflows.save_chat: one record per chat per day, re-run dedupe,
several days split, person match by name / alias without creating pages."""

from __future__ import annotations

import asyncio
import json

import pytest

from administrator_vault import frontmatter as fmt
from administrator_vault import notes, store, wiki, workflows
from administrator_vault.server import build_server

CB = "administrator/0.3.0"
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


def fm_of(vault, path):
    return fmt.split_note(text_of(vault, path))[0]


def chat(**over):
    c = {
        "id": "19:abc@thread.v2", "title": "Q3 budget", "type": "group",
        "members": [{"name": "Jane Doe", "mri": "8:orgid:1"}, {"name": "Hux", "mri": "8:orgid:2"}],
        "account": "acme",
    }
    c.update(over)
    return c


def msg(n, time, sender="Jane Doe", text="hello", is_self=False):
    return {"id": f"m{n}", "time": time, "sender": sender, "is_self": is_self, "text": text}


def people_files(vault):
    return sorted(p.name for p in (vault / W / "People").glob("*.md"))


def test_save_chat_writes_the_day_record_and_dedupes_on_rerun(vault):
    res = workflows.save_chat(
        chat(),
        [msg(2, "2026-08-21T10:05:00+02:00", text="Numbers  by\nFriday?"), msg(1, "2026-08-21T09:14:00+02:00", "Hux", "Morning", True)],
        ["Hux"],
        created_by=CB,
    )
    assert res["path"] == "Administrator/Teams/2026-08-21 Q3 budget.md" and res["action"] == "created"
    assert res["added"] == 2 and res["skipped_duplicates"] == 0 and res["messages"] == 2 and res["date"] == "2026-08-21"
    assert res["record_id"] == "19:abc@thread.v2|2026-08-21"
    fm = fm_of(vault, res["path"])
    assert fm["type"] == "chat" and fm["source"] == "teams" and fm["chat_id"] == "19:abc@thread.v2" and fm["chat_title"] == "Q3 budget"
    assert fm["date"] == "2026-08-21" and fm["account"] == "acme" and fm["members"] == ["Jane Doe", "Hux"]
    assert fm["record_id"] == "19:abc@thread.v2|2026-08-21" and fm["messages"] == 2
    assert fm["first"] == "2026-08-21T09:14:00+02:00" and fm["last"] == "2026-08-21T10:05:00+02:00" and fm["created_by"] == CB
    for key in notes.schema("chat")["required"]:
        assert key in fm, key
    text = text_of(vault, res["path"])
    assert (
        "# Q3 budget — 2026-08-21\n\n**Members:** Jane Doe, Hux\n\n## Messages\n\n"
        "- 09:14 **Hux**: Morning <!-- id: m1 -->\n- 10:05 **Jane Doe**: Numbers by Friday? <!-- id: m2 -->"
    ) in text
    # nobody has a page and nobody gets one
    assert res["people"] == [] and res["unknown_people"] == ["Jane Doe"] and people_files(vault) == []
    assert "wiki" not in fm

    # the same messages again plus one new: only the new one is appended
    res2 = workflows.save_chat(chat(), [msg(2, "2026-08-21T10:05:00+02:00"), msg(3, "2026-08-21T11:00:00+02:00", text="Yes, tomorrow.")], ["Hux"], created_by=CB)
    assert res2["path"] == res["path"] and res2["action"] == "appended"
    assert res2["added"] == 1 and res2["skipped_duplicates"] == 1 and res2["messages"] == 3
    text = text_of(vault, res["path"])
    assert "\n## Update " in text and "### Messages\n\n- 11:00 **Jane Doe**: Yes, tomorrow. <!-- id: m3 -->" in text
    assert text.count("<!-- id: m2 -->") == 1 and text.count("# Q3 budget — 2026-08-21") == 1
    fm = fm_of(vault, res["path"])
    assert fm["messages"] == 3 and fm["last"] == "2026-08-21T11:00:00+02:00" and fm["first"] == "2026-08-21T09:14:00+02:00"

    # nothing new: unchanged, no Update section added
    before = text_of(vault, res["path"])
    res3 = workflows.save_chat(chat(), [msg(3, "2026-08-21T11:00:00+02:00")], ["Hux"], created_by=CB)
    assert res3["action"] == "unchanged" and res3["added"] == 0 and res3["skipped_duplicates"] == 1 and res3["messages"] == 3
    assert text_of(vault, res["path"]) == before

    # found by identity, listed newest first, one file only
    assert store.find("chat", "19:abc@thread.v2|2026-08-21")["path"] == res["path"]
    assert store.find("chat", {"chat_id": "19:abc@thread.v2", "date": "2026-08-21"})["found"]
    assert [n["path"] for n in store.list_notes("chat")] == [res["path"]]


def test_save_chat_splits_messages_over_several_days(vault):
    res = workflows.save_chat(chat(), [msg(2, "2026-08-21T09:00:00+02:00"), msg(1, "2026-08-20T17:00:00+02:00", text="Late one")], ["Hux"], created_by=CB)
    assert isinstance(res, list) and [r["date"] for r in res] == ["2026-08-20", "2026-08-21"]
    assert [r["path"] for r in res] == ["Administrator/Teams/2026-08-20 Q3 budget.md", "Administrator/Teams/2026-08-21 Q3 budget.md"]
    assert all(r["action"] == "created" and r["added"] == 1 for r in res)
    assert "<!-- id: m1 -->" in text_of(vault, res[0]["path"]) and "<!-- id: m2 -->" not in text_of(vault, res[0]["path"])
    assert fm_of(vault, res[1]["path"])["record_id"] == "19:abc@thread.v2|2026-08-21"
    # a 1:1 chat without a title falls back to the id; a message without a time is skipped and counted
    res = workflows.save_chat(chat(id="19:x_y", title=""), [msg(5, "2026-08-21T09:00:00+02:00"), {"id": "m6", "sender": "Jane Doe", "text": "no time"}], created_by=CB)
    assert res["path"] == "Administrator/Teams/2026-08-21 19_x_y.md" and res["skipped_no_time"] == 1 and res["added"] == 1


def test_save_chat_matches_people_by_name_or_alias_and_never_creates_pages(vault):
    jane = wiki.create("person", "Jane Doe", aliases=["Doe, Jane"], lead="Jane Doe (jane.doe@example.com).", extra={"email": "jane.doe@example.com"})["path"]
    bob = wiki.create("person", "Bob Miller", lead="Bob Miller (bob@example.com).", extra={"email": "bob@example.com"})["path"]
    res = workflows.save_chat(
        chat(),
        [
            msg(1, "2026-08-21T09:14:00+02:00", "Doe, Jane", "Numbers by Friday?"),
            msg(2, "2026-08-21T09:20:00+02:00", "Hux", "Sure", True),
            msg(3, "2026-08-21T09:30:00+02:00", "bob miller", "I can help"),
            msg(4, "2026-08-21T09:40:00+02:00", "Doe, Jane", "Thanks"),
            msg(5, "2026-08-21T09:45:00+02:00", "Nobody Known", "hi"),
        ],
        ["Hux"],
        created_by=CB,
    )
    assert res["people"] == [{"name": "Doe, Jane", "page": jane}, {"name": "bob miller", "page": bob}]
    assert res["unknown_people"] == ["Nobody Known"]
    assert people_files(vault) == sorted(p.rsplit("/", 1)[-1] for p in (jane, bob))  # no page for Nobody Known
    jfm = fm_of(vault, jane)
    assert jfm["last_contact"] == "2026-08-21T09:40:00+02:00" and jfm["email"] == "jane.doe@example.com"
    assert "- 2026-08-21 — [[Teams/2026-08-21 Q3 budget]] — Q3 budget: Numbers by Friday?" in text_of(vault, jane)
    assert "- 2026-08-21 — [[Teams/2026-08-21 Q3 budget]] — Q3 budget: I can help" in text_of(vault, bob)
    assert text_of(vault, jane).count("[[Teams/2026-08-21 Q3 budget]]") == 1  # one Records line for two messages
    stems = [p[len("Administrator/") : -3] for p in (jane, bob)]
    assert fm_of(vault, res["path"])["wiki"] == [f"[[{s}]]" for s in stems]
    # a later message from Jane the same day: one more line in the record, no second Records line, last_contact forward
    res2 = workflows.save_chat(chat(), [msg(6, "2026-08-21T15:00:00+02:00", "Jane Doe", "Sent.")], ["Hux"], created_by=CB)
    assert res2["action"] == "appended" and res2["people"] == [{"name": "Jane Doe", "page": jane}]
    assert text_of(vault, jane).count("[[Teams/2026-08-21 Q3 budget]]") == 1
    assert fm_of(vault, jane)["last_contact"] == "2026-08-21T15:00:00+02:00"
    assert workflows.weekly_facts("2026-W34", today="2026-08-22")["quiet_people"] == []


def test_save_chat_refuses_bad_input(vault):
    with pytest.raises(notes.NoteError):
        workflows.save_chat({}, [msg(1, "2026-08-21T09:14:00+02:00")])
    with pytest.raises(notes.NoteError):
        workflows.save_chat(chat(), [])
    with pytest.raises(notes.NoteError):
        workflows.save_chat(chat(), [{"id": "m1", "sender": "Jane Doe", "text": "no time"}])


def test_server_save_chat_round_trip(vault):
    server = build_server()
    out = asyncio.run(server.call_tool("vault_save_chat", {"chat": chat(), "messages": [msg(1, "2026-08-21T09:14:00+02:00")], "self_names": ["Hux"]}))
    text = out[0].text if isinstance(out, list) else out[0][0].text
    res = json.loads(text)
    assert res["action"] == "created" and res["path"] == "Administrator/Teams/2026-08-21 Q3 budget.md" and res["unknown_people"] == ["Jane Doe"]
    assert fm_of(vault, res["path"])["created_by"] == "administrator/0.3.0"
