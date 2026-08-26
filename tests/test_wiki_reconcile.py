"""administrator_vault.wiki_reconcile: pages edited by hand in Obsidian read
back into the wiki — first run, each kind of edit, renames and moves, pages
written or deleted by hand, and what the tools say about it."""

from __future__ import annotations

import json
import time

import pytest

from administrator_vault import frontmatter as fmt
from administrator_vault import store, wiki, wiki_reconcile, wiki_search

CB = "administrator/0.4.0"
W = "Administrator/Wiki"


@pytest.fixture
def vault(tmp_path, monkeypatch):
    root = tmp_path / "Vault"
    root.mkdir()
    monkeypatch.setenv("ADMINISTRATOR_VAULT", str(root))
    monkeypatch.delenv("ADMINISTRATOR_VAULT_NAME", raising=False)
    store.init(created_by=CB)
    wiki_reconcile._STATE.clear()
    wiki_reconcile._MEMO.clear()
    wiki_search._LIVE.clear()
    yield root
    wiki_reconcile._STATE.clear()
    wiki_reconcile._MEMO.clear()
    wiki_search._LIVE.clear()


def text_of(vault, path):
    return (vault / path).read_text(encoding="utf-8")


def fm_of(vault, path):
    return fmt.split_note(text_of(vault, path))[0]


def hand_edit(vault, path, text):
    """What Obsidian does: the file on disk changes, nothing else."""
    (vault / path).write_text(text, encoding="utf-8")


def state(vault):
    return json.loads(text_of(vault, wiki_reconcile.STATE_PATH))["pages"]


def topic(vault, title="Q3 budget", **kw):
    args = dict(type="topic", title=title, aliases=["Budget Q3"], lead="Jane collects final Q3 numbers by 2026-08-29.",
                summary="Final Q3 numbers due 2026-08-29.")
    args.update(kw)
    res = wiki.create(**args)
    assert res["created"], res
    return res["path"]


def email(n=1, subject="Budget Q3", received="2026-08-22T09:14:00+02:00"):
    fm = {
        "type": "email", "source": "outlook", "internet_message_id": f"<m{n}@example.com>", "entry_id": f"00A{n}",
        "conversation_id": "C1", "subject": subject, "from": "jane.doe@example.com", "from_name": "Jane Doe",
        "from_link": "[[Wiki/People/Jane Doe]]", "to": [], "cc": [], "received": received, "status": "todo", "created_by": CB,
    }
    return store.write("email", fm, f"# {subject}\n\n## Summary\n\nJane asks for the numbers.\n")["path"]


def with_bullet(text, bullet):
    return text.replace("## Facts\n\n", f"## Facts\n\n{bullet}\n", 1)


# ------------------------------------------------------------------ the first run


def test_the_first_run_gives_every_page_an_id_and_leaves_the_rest_alone(vault):
    path = f"{W}/Topics/old-page.md"
    page = wiki.Page(
        path=path,
        fm={"type": "topic", "title": "Old page", "aliases": [], "summary": "", "status": "active", "created": "2026-08-01",
            "updated": "2026-08-01T09:00:00+02:00", "verified": "2026-08-01", "sources": 1, "open_items": 0, "flags": [],
            "created_by": "administrator/0.3.0"},
        title="Old page", lead="A page from before ids.")
    page.facts = [wiki.Fact("abcd", "The rate is 7 percent", "2026-08-01", ["<m1@example.com>"])]
    (vault / path).parent.mkdir(parents=True, exist_ok=True)
    (vault / path).write_text(wiki.format_page(page), encoding="utf-8")
    before = text_of(vault, path)

    out = wiki_reconcile.reconcile(vault)
    assert out["first_run"] is True and out["adopted"] == [] and out["scanned"] == 1
    fm = fm_of(vault, path)
    assert len(fm["id"]) == 26 and list(fm)[:2] == ["type", "id"] and fm["updated"] == "2026-08-01T09:00:00+02:00"
    assert text_of(vault, path).replace(f"id: {fm['id']}\n", "", 1) == before  # one line more, every other byte the same
    entry = state(vault)["Wiki/Topics/old-page"]
    assert entry["id"] == fm["id"] and entry["facts"]["abcd"][0] == "The rate is 7 percent" and entry["kind"] == "topic"
    assert "— updated" not in text_of(vault, path) and wiki.log(limit=500)["total"] == 0  # no History, no log line


def test_nothing_changed_costs_no_lock_and_no_line(vault):
    topic(vault)
    n = wiki.log(limit=500)["total"]
    wiki_reconcile._MEMO.clear()  # the memo would answer before the files are even read
    real = wiki._wiki_lock

    def refuse(root):
        raise AssertionError("the fast path took the write lock")

    wiki._wiki_lock = refuse
    try:
        out = wiki_reconcile.reconcile(vault)
    finally:
        wiki._wiki_lock = real
    assert out == {"adopted": [], "review": [], "busy": [], "first_run": False, "scanned": 1}
    assert wiki.log(limit=500)["total"] == n


# ------------------------------------------------------------------ edits inside a page


def test_bullets_changes_removals_and_ticks_are_taken_over(vault):
    path = topic(vault, facts=[{"text": "Deadline is 2026-08-29", "since": "2026-08-22", "src": "<m1@example.com>"},
                               {"text": "The sheet is Budget_Q3.xlsx", "since": "2026-08-22", "src": "<m1@example.com>"}])
    wiki.apply(path, [{"op": "open", "text": "Send the numbers to Jane"}])
    ids = [f["id"] for f in wiki.read(path)["facts"]]
    lines = []
    for line in text_of(vault, path).split("\n"):
        if line.startswith("- The sheet is Budget_Q3.xlsx"):
            continue  # deleted by hand
        if line.startswith("- Deadline is 2026-08-29 <!--"):
            line = line.replace("- Deadline is 2026-08-29", "- Deadline is 2026-08-30", 1)
        lines.append(line)
    hand_edit(vault, path, with_bullet("\n".join(lines), "- Jane presents the numbers herself").replace(
        "- [ ] Send the numbers to Jane", "- [x] Send the numbers to Jane"))

    assert wiki.read(path)["hand_edits"] == 1  # a read only says how many; it takes nothing over
    out = wiki_reconcile.reconcile(vault)  # what the next writing call does
    assert out["adopted"] == [{"page": "Wiki/Topics/q3-budget",
                               "changes": "1 new fact, 1 fact changed, 1 fact removed, 1 open item ticked"}]
    facts = {f["text"]: f for f in wiki.read(path)["facts"]}
    assert facts["Jane presents the numbers herself"]["src"] == ["user"]
    assert facts["Jane presents the numbers herself"]["since"] == wiki._today()
    assert facts["Deadline is 2026-08-30"]["src"] == ["user", "<m1@example.com>"] and len(facts) == 2
    body = text_of(vault, path)
    assert f'updated f:{ids[0]} "Deadline is 2026-08-29" → "Deadline is 2026-08-30" — edited by hand (user)' in body
    assert '— retired "The sheet is Budget_Q3.xlsx" — removed by hand (user)' in body
    assert '— done "Send the numbers to Jane"' in body and "- [x]" not in body and fm_of(vault, path)["open_items"] == 0
    assert wiki.log(page="q3-budget")["lines"][-1].endswith(
        "adopt | Wiki/Topics/q3-budget | user | 1 new fact, 1 fact changed, 1 fact removed, 1 open item ticked")
    entry = state(vault)["Wiki/Topics/q3-budget"]
    assert entry["hash"] == wiki_reconcile._hash(text_of(vault, path)) and len(entry["facts"]) == 2


def test_a_heading_the_contract_does_not_know_moves_under_notes(vault):
    path = topic(vault)
    hand_edit(vault, path, text_of(vault, path).replace("## Notes\n", "## Scratch\n\n- my own list\n- and one more\n\n## Notes\n"))

    out = wiki_reconcile.reconcile(vault)
    assert out["adopted"][0]["changes"] == "moved Scratch under Notes"
    body = text_of(vault, path)
    assert "## Scratch" not in body.split("## Notes")[0]
    assert f"### Scratch (moved {wiki._today()})\n- my own list\n- and one more" in wiki.read(path, ["notes"])["notes"]


def test_a_new_title_becomes_an_alias_and_a_new_lead_is_kept(vault):
    path = topic(vault)
    hand_edit(vault, path, text_of(vault, path).replace("# Q3 budget\n\nJane collects", "# Q3 numbers\n\nJane and Bob collect"))

    out = wiki_reconcile.reconcile(vault)
    assert out["adopted"][0]["changes"] == 'title changed from "Q3 budget", new lead'
    fm = fm_of(vault, path)
    assert fm["title"] == "Q3 numbers" and fm["aliases"] == ["Budget Q3", "Q3 budget"]
    assert wiki.read(path)["lead"].startswith("Jane and Bob collect")
    assert "- [[Wiki/Topics/q3-budget|Q3 numbers]]" in text_of(vault, f"{W}/Index.md")


def test_a_shortened_history_comes_back_from_the_previous_copy_and_asks(vault):
    path = topic(vault, facts=[{"text": "Deadline is 2026-08-29", "since": "2026-08-22", "src": "<m1@example.com>"}])
    fid = wiki.read(path)["facts"][0]["id"]
    wiki.apply(path, [{"op": "update", "id": fid, "text": "Deadline is 2026-08-31"}])
    assert len(wiki.read(path, ["history"])["sections"]["History"].split("\n")) == 2
    hand_edit(vault, path, "\n".join(l for l in text_of(vault, path).split("\n") if not l.startswith("- 2026-")))

    out = wiki_reconcile.reconcile(vault)
    assert out["adopted"][0]["changes"] == "History put back"
    assert "— page created (user)" in text_of(vault, path)
    line = next(l for l in out["review"] if "History" in l)
    assert line.startswith("- [ ] [[Wiki/Topics/q3-budget]] — the History section was shortened by hand")
    assert 'Say "drop it" to keep the short one.' in line
    assert any("shortened by hand" in item["text"] for item in wiki.review("list")["open"])


def test_the_id_and_the_created_date_are_put_back(vault):
    path = topic(vault)
    fm = fm_of(vault, path)
    hand_edit(vault, path, text_of(vault, path)
              .replace(f"id: {fm['id']}", "id: SOMETHINGELSE")
              .replace(f'created: "{fm["created"]}"', 'created: "2001-01-01"')
              .replace("sources: 0", "sources: 42"))

    out = wiki_reconcile.reconcile(vault)
    assert out["adopted"][0]["changes"] == "id and created put back"
    back = fm_of(vault, path)
    assert back["id"] == fm["id"] and back["created"] == fm["created"] and back["sources"] == 0


# ------------------------------------------------------------------ renamed, moved, written, deleted


def test_a_renamed_page_takes_its_links_with_it(vault):
    path = topic(vault)
    other = wiki.create("topic", "Offsite venue", lead="Where the team meets in October.")["path"]
    wiki.apply(other, [{"op": "related", "page": "Wiki/Topics/q3-budget"}])
    rec = email()
    wiki.ingest(rec, [{"path": path, "ops": [{"op": "add", "text": "Numbers due Friday", "since": "2026-08-22"}]}], created_by=CB)
    assert fm_of(vault, rec)["wiki"] == ["[[Wiki/Topics/q3-budget]]"]
    (vault / path).rename(vault / W / "Topics" / "budget-2026.md")

    res = wiki.apply(other, [])
    new = f"{W}/Topics/budget-2026.md"
    assert res["adopted"][0]["page"] == "Wiki/Topics/budget-2026"
    assert res["adopted"][0]["changes"].startswith("moved from Wiki/Topics/q3-budget, 3 links rewritten")
    assert not (vault / path).exists() and fm_of(vault, new)["title"] == "Q3 budget"
    assert "- [[Wiki/Topics/budget-2026]]" in text_of(vault, other)
    assert fm_of(vault, rec)["wiki"] == ["[[Wiki/Topics/budget-2026]]"]
    assert "- [[Wiki/Topics/budget-2026|Q3 budget]]" in text_of(vault, f"{W}/Index.md")
    assert "Wiki/Topics/q3-budget" not in state(vault) and state(vault)["Wiki/Topics/budget-2026"]["path"] == new
    assert wiki.read(new)["facts"][0]["text"] == "Numbers due Friday"


def test_a_page_moved_to_another_folder_changes_its_kind(vault):
    path = topic(vault, title="Example GmbH", aliases=[], lead="The customer since 2024.")
    (vault / path).rename(vault / W / "Orgs" / "example-gmbh.md")

    out = wiki_reconcile.reconcile(vault)
    new = f"{W}/Orgs/example-gmbh.md"
    assert "now an org page" in out["adopted"][0]["changes"]
    assert fm_of(vault, new)["type"] == "org"
    heads = [l[3:] for l in text_of(vault, new).split("\n") if l.startswith("## ")]
    assert heads == list(wiki.SECTIONS["org"])
    assert "## Orgs (1)" in text_of(vault, f"{W}/Index.md") and "## Topics" not in text_of(vault, f"{W}/Index.md")


def test_a_page_written_by_hand_gets_the_contract(vault):
    wiki_reconcile.reconcile(vault)  # the vault has had its first pass; this is a page the user wrote after it
    p = vault / W / "Topics" / "new-thing.md"
    p.write_text("# New thing\n\nWhat we do about the new thing.\n\n## Facts\n\n- It starts in October\n"
                 "- Bob owns it\n- The budget is 5000 EUR\n", encoding="utf-8")

    out = wiki_reconcile.reconcile(vault)
    path = f"{W}/Topics/new-thing.md"
    assert out["adopted"][0]["changes"] == "new page written by hand, 3 new facts"
    fm = fm_of(vault, path)
    assert fm["type"] == "topic" and fm["title"] == "New thing" and fm["status"] == "active" and fm["created_by"] == "user"
    assert len(fm["id"]) == 26 and fm["created"] == wiki._today()
    facts = wiki.read(path)["facts"]
    assert [f["text"] for f in facts] == ["It starts in October", "Bob owns it", "The budget is 5000 EUR"]
    assert all(f["src"] == ["user"] and f["since"] == wiki._today() for f in facts)
    assert "- [[Wiki/Topics/new-thing|New thing]]" in text_of(vault, f"{W}/Index.md")


def test_a_page_written_by_hand_with_a_name_that_exists_is_asked_about(vault):
    topic(vault)
    p = vault / W / "Topics" / "budget-q3-notes.md"
    p.write_text("# Budget Q3\n\nMy own page about the same thing.\n", encoding="utf-8")
    before = p.read_text(encoding="utf-8")

    out = wiki_reconcile.reconcile(vault)
    assert out["adopted"] == []
    assert out["review"] == ["- [ ] [[Wiki/Topics/budget-q3-notes]] — a page written by hand has the same name as "
                             "[[Wiki/Topics/q3-budget]]; merge them or rename one?"]
    assert p.read_text(encoding="utf-8") == before  # nothing written, nothing lost
    assert wiki_reconcile.reconcile(vault)["review"] == []  # asked once
    assert len([i for i in wiki.review("list")["open"] if "merge them or rename one?" in i["text"]]) == 1


def test_a_deleted_page_is_only_ever_asked_about(vault):
    path = topic(vault)
    other = wiki.create("topic", "Offsite venue", lead="Where the team meets in October.")["path"]
    wiki.apply(other, [{"op": "related", "page": "Wiki/Topics/q3-budget"}])
    (vault / path).unlink()

    out = wiki_reconcile.reconcile(vault)
    assert out["adopted"] == [] and len(out["review"]) == 1
    line = out["review"][0]
    assert line.startswith("- [ ] [[Wiki/Topics/q3-budget]] — the page was deleted by hand; put it back from the copy under")
    assert "drop the 2 links that still point at it?" in line
    assert "- [[Wiki/Topics/q3-budget]]" in text_of(vault, other)  # links are left alone until the user says
    assert wiki_reconcile.reconcile(vault)["review"] == [] and wiki.review("list")["done"] == 0
    assert len([i for i in wiki.review("list")["open"] if "deleted by hand" in i["text"]]) == 1


def test_a_sync_conflict_copy_is_left_alone(vault):
    path = topic(vault)
    copy = vault / W / "Topics" / "q3-budget (1).md"
    copy.write_text(text_of(vault, path), encoding="utf-8")

    out = wiki_reconcile.reconcile(vault)
    assert out["adopted"] == [] and out["review"] == [
        "- [ ] [[Wiki/Topics/q3-budget (1)]] — this file looks like a copy of [[Wiki/Topics/q3-budget]] left by a sync; it was not read."]
    assert copy.read_text(encoding="utf-8") == text_of(vault, path)
    assert "q3-budget (1)" not in text_of(vault, f"{W}/Index.md")


def test_a_read_while_another_process_writes_still_answers(vault):
    path = topic(vault)
    hand_edit(vault, path, with_bullet(text_of(vault, path), "- Bob keeps the ledger of pledges"))
    (vault / W / ".lock").write_text(f"99999 {time.time():.0f} another process\n", encoding="utf-8")

    out = wiki.read(path)  # a read takes no lock at all: it counts and answers
    assert "adopted" not in out and out["hand_edits"] == 1 and out["title"] == "Q3 budget"
    (vault / W / ".lock").unlink()
    assert wiki.apply(path, [])["adopted"] == [{"page": "Wiki/Topics/q3-budget", "changes": "1 new fact"}]


def test_a_file_still_being_written_waits_for_the_next_pass(vault, monkeypatch):
    path = topic(vault)
    hand_edit(vault, path, with_bullet(text_of(vault, path), "- Bob keeps the ledger of pledges"))
    real = wiki_search._page_files
    # the file changes again between the scan and the write: it is left alone
    monkeypatch.setattr(wiki_search, "_page_files", lambda root: [(p, f, size + 1, mt) for p, f, size, mt in real(root)])

    out = wiki_reconcile.reconcile(vault)
    assert out["busy"] == ["Wiki/Topics/q3-budget"] and out["adopted"] == []
    assert "- Bob keeps the ledger of pledges\n" in text_of(vault, path)  # nothing was written: the bullet has no id yet
    monkeypatch.setattr(wiki_search, "_page_files", real)
    assert wiki_reconcile.reconcile(vault)["adopted"] == [{"page": "Wiki/Topics/q3-budget", "changes": "1 new fact"}]


def test_a_busy_file_is_read_back_even_when_it_then_lies_still(vault, monkeypatch):
    """The file settles at the size and time the folders show right after the
    pass, so nothing more changes: it still has to be read on the next call."""
    path = topic(vault)
    hand_edit(vault, path, with_bullet(text_of(vault, path), "- Bob keeps the ledger of pledges"))
    real = wiki_search._page_files
    calls = {"n": 0}

    def stale_once(root):  # only the scan that opens the pass is behind the file
        rows = real(root)
        calls["n"] += 1
        return [(p, f, size - 1, mt) for p, f, size, mt in rows] if calls["n"] == 1 else rows

    monkeypatch.setattr(wiki_search, "_page_files", stale_once)
    assert wiki_reconcile.reconcile(vault)["busy"] == ["Wiki/Topics/q3-budget"]
    monkeypatch.setattr(wiki_search, "_page_files", real)
    assert wiki_reconcile.reconcile(vault)["adopted"] == [{"page": "Wiki/Topics/q3-budget", "changes": "1 new fact"}]


# ------------------------------------------------------------------ the tools


def test_a_read_only_counts_the_hand_edits_and_the_next_write_takes_them_over(vault):
    """No read rewrites a page: each one says how many files differ, and the
    writing call after it is what adopts them."""
    path = topic(vault)
    hand_edit(vault, path, with_bullet(text_of(vault, path), "- Bob keeps the ledger of pledges"))
    before = text_of(vault, path)

    reads = [wiki.read(path), wiki.log(), wiki.review("list"), wiki.match("ledger"),
             wiki_search.search_tool("ledger", brief=True)]
    for out in reads:
        assert out["hand_edits"] == 1 and "adopted" not in out
    assert text_of(vault, path) == before  # not one of them wrote
    assert state(vault)["Wiki/Topics/q3-budget"]["facts"] == {}

    assert wiki.apply(path, [])["adopted"] == [{"page": "Wiki/Topics/q3-budget", "changes": "1 new fact"}]
    assert wiki.read(path).get("hand_edits") is None and wiki.log().get("hand_edits") is None
    assert [f[0] for f in state(vault)["Wiki/Topics/q3-budget"]["facts"].values()] == ["Bob keeps the ledger of pledges"]


def test_the_search_answers_with_the_text_written_by_hand(vault):
    path = topic(vault)
    hand_edit(vault, path, with_bullet(text_of(vault, path), "- Bob keeps the ledger of pledges"))

    out = wiki_search.search_tool("who keeps the ledger")
    assert out["hand_edits"] == 1 and "adopted" not in out  # the search wrote nothing
    assert out["hits"][0]["text"] == "Bob keeps the ledger of pledges"
    assert state(vault)["Wiki/Topics/q3-budget"]["facts"] == {}  # the file holds it, the state does not yet
    assert wiki.apply(path, [])["adopted"] == [{"page": "Wiki/Topics/q3-budget", "changes": "1 new fact"}]
    assert wiki.read(path)["facts"][0]["src"] == ["user"]
    again = wiki_search.search_tool("who keeps the ledger")
    assert again[0]["text"] == "Bob keeps the ledger of pledges"  # nothing left to take over: the plain list
    entry = state(vault)["Wiki/Topics/q3-budget"]
    assert entry["hash"] == wiki_reconcile._hash(text_of(vault, path))
    assert [f[0] for f in entry["facts"].values()] == ["Bob keeps the ledger of pledges"]


def test_lint_reports_the_hand_edits_under_check_zero(vault):
    from administrator_vault import wiki_lint

    path = topic(vault)
    hand_edit(vault, path, with_bullet(text_of(vault, path), "- The venue is booked for October"))
    report = wiki_lint.lint(items=True)
    assert report["checks"]["0"] == {"name": "hand-edits", "adopted": [{"page": "Wiki/Topics/q3-budget", "changes": "1 new fact"}],
                                     "review": [], "first_run": False, "scanned": 1}
    assert report["counts"]["hand_edits"] == 1 and report["adopted"] == report["checks"]["0"]["adopted"]
    assert wiki.read(path)["facts"][0]["text"] == "The venue is booked for October"


def test_the_newest_history_line_comes_back_from_the_state_file(vault):
    # the prev copy is the text from before the last write, so it can never hold the line that write added;
    # the state file does
    path = topic(vault, facts=[{"text": "Deadline is 2026-08-29", "since": "2026-08-22", "src": "<m1@example.com>"}])
    fid = wiki.read(path)["facts"][0]["id"]
    wiki.apply(path, [{"op": "update", "id": fid, "text": "Deadline is 2026-08-31"}])
    lines = text_of(vault, path).split("\n")
    newest = [l for l in lines if l.startswith("- 2026-") and "updated" in l][0]
    hand_edit(vault, path, "\n".join(l for l in lines if l != newest))

    out = wiki_reconcile.reconcile(vault)
    assert out["adopted"][0]["changes"] == "History put back"
    assert newest in text_of(vault, path)
    assert any("shortened by hand" in l for l in out["review"])


def test_a_history_loss_that_cannot_be_put_back_is_still_asked_about(vault):
    path = topic(vault, facts=[{"text": "Deadline is 2026-08-29", "since": "2026-08-22", "src": "<m1@example.com>"}])
    fid = wiki.read(path)["facts"][0]["id"]
    wiki.apply(path, [{"op": "update", "id": fid, "text": "Deadline is 2026-08-31"}])
    state = json.loads(text_of(vault, f"{W}/_cache/state.json"))
    state["pages"]["Wiki/Topics/q3-budget"]["history"] = []  # a state file from before the lines were kept
    (vault / W / "_cache" / "state.json").write_text(json.dumps(state), encoding="utf-8")
    for f in (vault / W / "_cache" / "prev").glob("**/*.prev"):
        f.unlink()
    hand_edit(vault, path, "\n".join(l for l in text_of(vault, path).split("\n") if not l.startswith("- 2026-")))

    out = wiki_reconcile.reconcile(vault)
    assert out["adopted"][0]["changes"] == "2 History lines lost"
    line = next(l for l in out["review"] if "History" in l)
    assert "2 History line(s) were removed by hand and no copy holds them" in line


def test_bullets_under_a_bare_title_become_facts(vault):
    wiki_reconcile.reconcile(vault)
    p = vault / W / "Topics" / "new-thing.md"
    p.write_text("# New thing\n\n- It starts in October\n- Bob owns it\n", encoding="utf-8")

    out = wiki_reconcile.reconcile(vault)
    path = f"{W}/Topics/new-thing.md"
    assert out["adopted"][0]["changes"] == "new page written by hand, 2 new facts"
    facts = wiki.read(path)["facts"]
    assert [f["text"] for f in facts] == ["It starts in October", "Bob owns it"]
    assert all(f["src"] == ["user"] for f in facts)
    assert fm_of(vault, path)["status"] == "draft" and wiki.read(path)["lead"] == ""


def test_an_open_item_typed_by_hand_gets_an_id_an_owner_and_a_date(vault):
    """A commitment written in Obsidian is adopted like a bullet: without an id
    nothing could tick or reschedule it later."""
    path = topic(vault)
    person = wiki.create("person", "Jane Doe", extra={"email": "jane@example.com"}, created_by=CB)["path"]
    hand_edit(vault, path, text_of(vault, path).replace(
        "## Open\n", f"## Open\n\n- [ ] call Jane — owner: me\n- [ ] Jane sends the sheet — owner: [[{wiki._stem(person)}]]\n"))

    assert wiki.read(path)["hand_edits"] == 1
    out = wiki_reconcile.reconcile(vault)
    assert out["adopted"] == [{"page": "Wiki/Topics/q3-budget", "changes": "2 new open items"}]
    items = wiki.commitments(vault, page="Wiki/Topics/q3-budget")
    assert [i["text"] for i in items] == ["call Jane", "Jane sends the sheet"]
    for item in items:
        assert item["id"] and item["since"] == wiki._today() and item["src"] == ["user"]
    assert items[0]["owner"] == "me" and items[1]["owner_name"] == "Jane Doe"
    assert fm_of(vault, path)["open_items"] == 2
    wiki_reconcile._MEMO.clear()
    assert wiki.read(path).get("hand_edits") is None  # taken over: nothing left to report
