"""administrator_vault.priorities: the candidates for a ranked suggestion and
the write that replaces only the numbered list of Priorities.md."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date

import pytest

from administrator_vault import frontmatter as fmt
from administrator_vault import priorities, store, timeblock, wiki
from administrator_vault.server import build_server
from administrator_vault.store import VaultError

CB = "administrator/0.3.0"
PATH = "Administrator/Priorities.md"
TODAY = "2026-08-24"
STAMP_RE = re.compile(r"<!-- suggested by administrator, confirmed \d{4}-\d{2}-\d{2} -->")


@pytest.fixture
def vault(tmp_path, monkeypatch):
    root = tmp_path / "Vault"
    root.mkdir()
    monkeypatch.setenv("ADMINISTRATOR_VAULT", str(root))
    monkeypatch.delenv("ADMINISTRATOR_VAULT_NAME", raising=False)
    store.init(created_by=CB)
    return root


def text_of(vault, path=PATH):
    return (vault / path).read_text(encoding="utf-8")


def section(text, heading):
    body = fmt.split_note(text)[2]
    m = re.search(rf"^## {heading}\n(.*?)(?=^## |\Z)", body, re.S | re.M)
    return m.group(1) if m else None


# ------------------------------------------------------------------ candidates


def test_candidates_topics_followups_weekly_and_current(vault):
    wiki.create("topic", "Acme contract", lead="The supplier contract.", summary="Renewal by September.", extra={"due": "2026-09-01"})
    hiring = wiki.create("topic", "Hiring a PM", lead="x")["path"]
    wiki.apply(hiring, [{"op": "open", "text": "Post the ad", "src": "user"}])
    closed = wiki.create("topic", "Old thing", lead="x", extra={"due": "2026-08-30"})["path"]
    wiki.apply(closed, [{"op": "status", "value": "closed"}])
    wiki.create("person", "Jane Doe", extra={"email": "jane@example.com"})
    store.append_row("Administrator/Follow-ups.md", "Open", ["2026-08-18", "[[Wiki/People/Jane Doe]]", "Contract draft", "", "2026-08-22"], "00AC")
    store.append_row("Administrator/Follow-ups.md", "Open", ["2026-08-10", "Tom Lee", "Delivery date", "", "2026-08-22"], "00AD")
    d = {"type": "daily", "source": "outlook", "date": "2026-08-19", "folder": "inbox", "since": "s", "inbox_checked": "c", "mails_seen": 2, "status": "todo", "created_by": CB}
    store.write("daily", d, (
        "# 2026-08-19\n\n## Inbox (since s)\n\n| # | Label | From | Subject | Received | Why | Note |\n| --- | --- | --- | --- | --- | --- | --- |\n"
        "| 1 | act | Jane Doe | Budget Q3 | 09:14 | why | <!-- entry_id: 00A1 --> |\n"
        "| 2 | fyi | IT | Maint | 07:00 | why | <!-- entry_id: 00A4 --> |\n"
    ))
    store.write("weekly", {"type": "weekly", "week": "2026-W34", "start": "2026-08-17", "end": "2026-08-23", "created_by": CB}, "# W34")

    c = priorities.candidates(TODAY)
    assert c["path"] == PATH
    assert [(t["title"], t["due"], t["open_items"], t["status"]) for t in c["topics"]] == [("Acme contract", "2026-09-01", 0, "active"), ("Hiring a PM", None, 1, "active")]
    assert c["topics"][0]["page"] == "[[Wiki/Topics/acme-contract]]" and c["topics"][0]["summary"] == "Renewal by September." and re.match(r"^\d{4}-\d{2}-\d{2}$", c["topics"][0]["verified"])
    assert c["followups"] == [
        {"since": "2026-08-10", "who": "Tom Lee", "what": "Delivery date", "age_days": 14},
        {"since": "2026-08-18", "who": "[[Wiki/People/Jane Doe]]", "what": "Contract draft", "age_days": 6},
    ]
    assert c["weekly_open"] == [{"subject": "Budget Q3", "label": "act", "date": "2026-08-19"}]
    assert c["current"] == []  # the placeholder line does not count
    assert "1. (your first priority" in text_of(vault)  # read only

    # an empty vault: nothing to suggest from, no weekly note
    (vault / PATH).unlink()
    for p in (vault / "Administrator" / "Weekly").glob("*.md"):
        p.unlink()
    e = priorities.candidates(TODAY)
    assert e["weekly_open"] == [] and e["current"] == []


# ------------------------------------------------------------------ write


def test_write_replaces_the_placeholder_and_keeps_the_rest(vault):
    p = vault / PATH
    p.write_text(text_of(vault) + "\n## Notes\n\nMy own words stay here.\n", encoding="utf-8")
    before = text_of(vault)
    res = priorities.write(["[[Wiki/Topics/acme-contract]]", "Hiring a PM", "3. Offsite"], today=TODAY)
    assert res == {"path": PATH, "action": "written", "lines": ["[[Wiki/Topics/acme-contract]]", "Hiring a PM", "Offsite"], "previous": []}
    after = text_of(vault)
    assert section(after, "Priorities") == "\n1. [[Wiki/Topics/acme-contract]]\n2. Hiring a PM\n3. Offsite\n<!-- suggested by administrator, confirmed 2026-08-24 -->\n\n"
    assert "1. (your first priority" not in after
    # everything outside the numbered list is byte for byte the same
    head, _sep, _rest = before.partition("## Priorities\n")
    assert after.startswith(head + "## Priorities\n")
    assert section(after, "Notes") == section(before, "Notes") == "\nMy own words stay here.\n"
    assert fmt.split_note(after)[0] == fmt.split_note(before)[0]
    assert not (vault / "Administrator" / "Priorities.md.tmp").exists()
    # the planner reads the new list
    assert [(x["rank"], x["name"], x["page"]) for x in timeblock.read_priorities(vault, date(2026, 8, 24))] == [(1, "acme-contract", "[[Wiki/Topics/acme-contract]]"), (2, "Hiring a PM", None), (3, "Offsite", None)]


def test_second_write_replaces_the_list_and_keeps_user_text(vault):
    priorities.write(["Acme contract", "Hiring a PM"], note="from the week's follow-ups", today=TODAY)
    p = vault / PATH
    text = text_of(vault)
    assert "<!-- from the week's follow-ups -->" in text
    # the user adds a line of their own inside the section
    text = text.replace("<!-- from the week's follow-ups -->\n", "<!-- from the week's follow-ups -->\n\nThe offsite waits until October.\n")
    p.write_text(text, encoding="utf-8")
    res = priorities.write(["Offsite", "Acme contract"], today="2026-08-31")
    assert res["previous"] == ["Acme contract", "Hiring a PM"] and res["lines"] == ["Offsite", "Acme contract"]
    after = text_of(vault)
    assert section(after, "Priorities") == "\n1. Offsite\n2. Acme contract\n<!-- suggested by administrator, confirmed 2026-08-31 -->\n\nThe offsite waits until October.\n"
    assert after.count("suggested by administrator") == 1 and "follow-ups" not in after and "Hiring a PM" not in after
    assert [x["name"] for x in timeblock.read_priorities(vault, date(2026, 8, 31))] == ["Offsite", "Acme contract"]
    assert priorities.candidates("2026-08-31")["current"] == ["Offsite", "Acme contract"]


def test_write_creates_a_missing_file_and_a_missing_heading(vault):
    p = vault / PATH
    p.unlink()
    res = priorities.write(["Only one"], today=TODAY)
    assert res["previous"] == [] and p.is_file()
    text = text_of(vault)
    assert fmt.split_note(text)[0]["type"] == "priorities" and fmt.split_note(text)[0]["created_by"] == CB
    assert section(text, "Priorities") == "\n1. Only one\n<!-- suggested by administrator, confirmed 2026-08-24 -->\n"
    # no '## Priorities' heading at all: the section is added at the end
    p.write_text("---\ntype: priorities\n---\n\n# Priorities\n\nJust my words.\n", encoding="utf-8")
    priorities.write(["A", "B"], today=TODAY)
    text = text_of(vault)
    assert text.startswith("---\ntype: priorities\n---\n\n# Priorities\n\nJust my words.\n\n## Priorities\n\n1. A\n2. B\n<!-- suggested")
    assert [x["name"] for x in timeblock.read_priorities(vault, date(2026, 8, 24))] == ["A", "B"]


def test_write_refuses_bad_input(vault):
    before = text_of(vault)
    for bad in ([], None, [""], ["   "], ["a"] * 8, ["x" * 121], ["# heading"], ["done <!-- c -->"], "Acme"):
        with pytest.raises(VaultError):
            priorities.write(bad, today=TODAY)
    with pytest.raises(VaultError):
        priorities.write(["a"], note="ends the comment --> early", today=TODAY)
    with pytest.raises(VaultError):
        priorities.priorities_write("delete")
    assert text_of(vault) == before


def test_server_priorities_round_trip(vault):
    server = build_server()

    def call(name, args):
        out = asyncio.run(server.call_tool(name, args))
        return json.loads(out[0].text if isinstance(out, list) else out[0][0].text)

    c = call("vault_priorities_write", {"action": "candidates"})
    assert c["topics"] == [] and c["followups"] == [] and c["current"] == []
    w = call("vault_priorities_write", {"action": "write", "lines": ["Acme contract", "Offsite"], "note": "confirmed in chat"})
    assert w["action"] == "written" and w["lines"] == ["Acme contract", "Offsite"] and w["previous"] == []
    text = text_of(vault)
    assert STAMP_RE.search(text) and "<!-- confirmed in chat -->" in text
    assert call("vault_priorities_write", {"action": "candidates"})["current"] == ["Acme contract", "Offsite"]
    with pytest.raises(Exception):
        call("vault_priorities_write", {"action": "write", "lines": []})
