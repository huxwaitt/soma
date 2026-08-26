"""administrator_vault.wiki_migrate: a 0.1.0 vault (People/ next to the records)
moves into Wiki/People/ with every link rewritten, a backup, and a dry run first."""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from administrator_vault import frontmatter as fmt
from administrator_vault import notes, store, wiki, wiki_migrate, workflows
from administrator_vault.server import build_server

OLD = "administrator/0.1.0"
CB = "administrator/0.4.1"
A = "Administrator"
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")


def person_note(name, email, company="", records=(), voice="", extra_text=""):
    fm = fmt.format_frontmatter({"type": "person", "source": "outlook", "name": name, "email": email, **({"company": company} if company else {}),
                                 "last_contact": "2026-08-20T09:00:00+02:00", "aliases": [f"{name.split()[1]}, {name.split()[0]}"], "created_by": OLD})
    body = f"# {name}\n\n{email}" + (f" · {company}" if company else "") + "\n\n## Emails\n\n"
    body += "\n".join(f"- {d} — [[Emails/{d} {s}]] ({st})" for d, s, st in records if s.startswith(("Mail", "Old"))) + "\n\n## Meetings\n\n"
    body += "\n".join(f"- {d} — [[Meetings/{d} 1300 {s}]] ({st})" for d, s, st in records if s.startswith("Sync")) + "\n"
    if voice:
        body += f"\n{voice}\n"
    if extra_text:
        body += f"\n{extra_text}\n"
    body += "\n## Update 2026-08-21T10:00:00+02:00\n\n- 2026-08-21 — [[Emails/2026-08-21 Mail 5]] (fyi)\n"
    return fm + "\n" + body


def legacy_followups(root):
    """Follow-ups.md as the older releases kept it: rows, no `generated` key."""
    cols = "| --- | --- | --- | --- | --- |"
    text = ["---", "type: followups", "source: outlook", f"created_by: {OLD}", "---", "",
            "# Follow-ups", "", "Things I am waiting on.", "", "## Open", "",
            "| " + " | ".join(notes.FOLLOWUPS_OPEN_HEADER) + " |", cols, "", "## Done", "",
            "| " + " | ".join(notes.FOLLOWUPS_DONE_HEADER) + " |", cols]
    (root / A / "Follow-ups.md").write_text("\n".join(text) + "\n", encoding="utf-8")


@pytest.fixture
def old_vault(tmp_path, monkeypatch):
    """3 people (one with a Voice block), 5 emails, 2 meetings, Follow-ups rows, a daily and a weekly note, all linking People/."""
    root = tmp_path / "Vault"
    root.mkdir()
    monkeypatch.setenv("ADMINISTRATOR_VAULT", str(root))
    monkeypatch.delenv("ADMINISTRATOR_VAULT_NAME", raising=False)
    store.init(created_by=OLD)
    for f in ("Wiki", ):
        pass
    people = root / A / "People"
    people.mkdir()
    recs = [("2026-08-20", "Mail 1", "todo"), ("2026-08-19", "Mail 2", "done"), ("2026-08-18", "Sync with Jane", "held")]
    (people / "Jane Doe.md").write_text(person_note("Jane Doe", "jane.doe@example.com", "Example GmbH", recs,
                                                    voice="Voice with this person:\n- short, first names, no greeting\n- she signs off with 'Best'"), encoding="utf-8")
    (people / "Bob Lee.md").write_text(person_note("Bob Lee", "bob.lee@example.com", "", [("2026-08-17", "Mail 3", "fyi"), ("2026-08-16", "Sync with Bob", "upcoming")], extra_text="Knows the Leipzig site well."), encoding="utf-8")
    (people / "Carol Ng.md").write_text(person_note("Carol Ng", "carol@partner.example", "Partner AG", [("2026-08-15", "Mail 4", "waiting")]), encoding="utf-8")
    # the People.base view of 0.1.0
    (root / A / "_views" / "People.base").write_text('filters:\n  and:\n    - file.inFolder("Administrator/People")\n    - note.type == "person"\nproperties:\n  note.company:\n    displayName: Company\nviews:\n  - type: table\n    name: People\n    order:\n      - file.name\n      - note.company\n', encoding="utf-8")
    (root / A / "_views" / "Wiki.base").unlink()
    for n, (day, subj, who, link) in enumerate([("2026-08-20", "Mail 1", "jane.doe@example.com", "Jane Doe"), ("2026-08-19", "Mail 2", "jane.doe@example.com", "Jane Doe"),
                                                  ("2026-08-17", "Mail 3", "bob.lee@example.com", "Bob Lee"), ("2026-08-15", "Mail 4", "carol@partner.example", "Carol Ng"),
                                                  ("2026-08-21", "Mail 5", "jane.doe@example.com", "Jane Doe")], 1):
        fm = {"type": "email", "source": "outlook", "internet_message_id": f"<m{n}@example.com>", "entry_id": f"00A{n}", "conversation_id": "C1", "subject": subj,
              "from": who, "from_name": link, "from_link": f"[[People/{link}]]", "to": ["me@example.com"], "cc": [], "received": f"{day}T09:00:00+02:00", "status": "todo", "created_by": OLD}
        store.write("email", fm, f"# {subj}\n\n**From:** [[People/{link}]] <{who}>\n\n## Summary\n\nAbout {subj}.\n\n## Action items\n\n- [ ] reply to [[People/{link}]]\n")
    for day, subj, org, att in [("2026-08-18", "Sync with Jane", "Jane Doe", ["Jane Doe", "Bob Lee"]), ("2026-08-16", "Sync with Bob", "Bob Lee", ["Bob Lee"])]:
        fm = {"type": "meeting", "source": "outlook", "global_id": f"G{day}", "occurrence_key": f"G{day}|{day}T13:00:00+02:00", "subject": subj, "start": f"{day}T13:00:00+02:00", "end": f"{day}T14:00:00+02:00",
              "location": "Teams", "organizer": org, "organizer_link": f"[[People/{org}]]", "attendees": att, "attendee_links": [f"[[People/{a}]]" for a in att], "is_recurring": False, "status": "held", "created_by": OLD}
        store.write("meeting", fm, f"# {subj}\n\n### People\n\n" + "\n".join(f"- [[People/{a}]]" for a in att) + "\n\n## Summary\n\nTalked.\n")
    legacy_followups(root)
    store.append_row(f"{A}/Follow-ups.md", "Open", ["2026-08-15", "[[People/Carol Ng]]", "Mail 4", "[[Emails/2026-08-15 Mail 4]]", "2026-08-16"], "00A4")
    store.append_row(f"{A}/Follow-ups.md", "Done", ["2026-08-10", "[[People/Bob Lee]]", "Old thing", "", "2026-08-12"], "00A9")
    store.write("daily", {"type": "daily", "source": "outlook", "date": "2026-08-20", "folder": "inbox", "since": "2026-08-19T18:00:00+02:00", "inbox_checked": "2026-08-20T08:30:00+02:00", "mails_seen": 1, "status": "todo", "created_by": OLD},
                "# 2026-08-20\n\n## To do\n\n- [ ] reply — Mail 1 ([[People/Jane Doe]]) — [[Emails/2026-08-20 Mail 1]]\n")
    store.write("weekly", {"type": "weekly", "week": "2026-W33", "start": "2026-08-10", "end": "2026-08-16", "created_by": OLD}, "# Week 33\n\n## People going quiet\n\n- [[People/Carol Ng]] — last contact 2026-08-15\n")
    return root


def all_links(root):
    out = []
    for p in (root / A).rglob("*.md"):
        r = p.relative_to(root).as_posix()
        if r.startswith(f"{A}/_backup/") or r in (f"{A}/Wiki/Wiki.md", f"{A}/Priorities.md", f"{A}/Wiki/Questions.md"):  # the schema copy and the priorities and questions templates hold example links
            continue
        for m in LINK_RE.finditer(p.read_text(encoding="utf-8")):
            out.append((r, m.group(1).strip()))
    return out


def resolves(root, target):
    t = target[len(A) + 1 :] if target.startswith(A + "/") else target
    return (root / A / (t + ".md")).is_file() or (root / A / t).is_file()


def old_links(root):
    return [(f, t) for f, t in all_links(root) if t.startswith("People/")]


def test_dry_run_reports_the_plan_and_writes_nothing(old_vault):
    root = old_vault
    before = {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in (root / A).rglob("*.md")}
    assert store.status()["old_people_dir"] is True
    plan = wiki_migrate.migrate(dry_run=True)
    assert plan["needed"] and plan["dry_run"] is True
    assert [p["from"] for p in plan["people"]] == [f"{A}/People/Bob Lee.md", f"{A}/People/Carol Ng.md", f"{A}/People/Jane Doe.md"]
    jane = plan["people"][2]
    assert jane["to"] == f"{A}/Wiki/People/Jane Doe.md" and jane["records"] == 4 and jane["voice"] is True and jane["exists"] is False and jane["newest_record"] == "2026-08-21"
    assert plan["people"][0]["voice"] is False and plan["people"][0]["notes_lines"] == 1
    assert plan["links"]["files"] == 10 and plan["links"]["count"] == len(old_links(root)) == 35
    assert {v["path"] for v in plan["views"]} == {f"{A}/_views/People.base", f"{A}/_views/Wiki.base"}
    assert plan["left"] == [] and "_backup/<stamp>/People/" in plan["backup"]
    assert plan["parts"] == {"people": True, "followups": True, "views": True}
    fu = plan["followups"]
    assert fu["count"] == 2 and "_backup/<stamp>/Follow-ups.md" in fu["backup"]
    assert fu["open"] == [{"who": "[[Wiki/People/Carol Ng]]", "text": "Mail 4", "since": "2026-08-15", "closed": "",
                           "page": "Wiki/People/Carol Ng", "record": "Emails/2026-08-15 Mail 4", "src": "00A4"}]
    assert fu["done"] == [{"who": "[[Wiki/People/Bob Lee]]", "text": "Old thing", "since": "2026-08-10", "closed": "2026-08-12",
                           "page": "Wiki/People/Bob Lee", "record": "", "src": "00A9"}]
    after = {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in (root / A).rglob("*.md")}
    assert after == before
    assert not (root / A / "_backup").exists() and not (root / A / "Wiki" / ".lock").exists()


def test_the_follow_ups_rows_move_onto_the_pages(old_vault):
    root = old_vault
    store.append_row(f"{A}/Follow-ups.md", "Open", ["2026-08-14", "Someone Unknown", "Send the map", "", "2026-08-16"], "00B7")
    res = wiki_migrate.migrate(dry_run=False, created_by=CB)
    assert res["followups_moved"] == {"open": 2, "done": 1}
    # the linked person keeps the item, with the row's date, source and record
    carol = wiki.commitments(root, page="Wiki/People/Carol Ng")
    assert [(c["text"], c["owner"], c["since"], c["src"], c["record"]) for c in carol] == [
        ("Mail 4", "[[Wiki/People/Carol Ng]]", "2026-08-15", ["00A4"], "Emails/2026-08-15 Mail 4")]
    # an unknown name lands on Me.md, with the name in the text
    me = wiki.commitments(root, page="Wiki/Me")
    assert [(c["text"], c["owner"]) for c in me] == [("Someone Unknown: Send the map", "Someone Unknown")]
    # the Done row is a History line on Bob's page
    bob = (root / A / "Wiki" / "People" / "Bob Lee.md").read_text(encoding="utf-8")
    assert '- 2026-08-12 — done "Old thing" — owner: [[Wiki/People/Bob Lee]] · since 2026-08-10 (user)' in bob
    # the file itself is now written from the pages, and a second run has nothing to do
    fu = (root / A / "Follow-ups.md").read_text(encoding="utf-8")
    assert fmt.split_note(fu)[0]["generated"] is True
    assert "| 2026-08-15 | [[Wiki/People/Carol Ng]] | Mail 4 | [[Emails/2026-08-15 Mail 4]] |" in fu
    assert "| 2026-08-10 | [[Wiki/People/Bob Lee]] | Old thing |  | 2026-08-12 |" in fu
    again = wiki_migrate.migrate(dry_run=True)
    assert again["parts"]["followups"] is False and again["followups"]["count"] == 0
    backup = next((root / A / "_backup").iterdir())
    assert "00A4" in (backup / "Follow-ups.md").read_text(encoding="utf-8")


def test_a_row_naming_an_org_lands_on_me(old_vault):
    """An org page has no Open section in the contract, so the row goes to Me.md
    with the name in the text rather than onto a page that cannot hold it."""
    root = old_vault
    wiki.create("org", "Partner AG", created_by=CB)
    store.append_row(f"{A}/Follow-ups.md", "Open", ["2026-08-14", "Partner AG", "Send the price list", "", "2026-08-16"], "00B8")
    row = next(o for o in wiki_migrate.migrate(dry_run=True)["followups"]["open"] if o["src"] == "00B8")
    assert row["page"] == "Wiki/Me" and row["text"] == "Partner AG: Send the price list"
    store.append_row(f"{A}/Follow-ups.md", "Open", ["2026-08-15", "[[Wiki/Orgs/partner-ag]]", "Send the invoice", "", "2026-08-16"], "00B9")
    row2 = next(o for o in wiki_migrate.migrate(dry_run=True)["followups"]["open"] if o["src"] == "00B9")
    assert row2["text"] == "Partner AG: Send the invoice"  # the page's title, not its slug
    wiki_migrate.migrate(dry_run=False, created_by=CB)
    assert sorted(c["text"] for c in wiki.commitments(root, page="Wiki/Me")) == ["Partner AG: Send the invoice", "Partner AG: Send the price list"]
    assert "## Open" not in (root / A / "Wiki" / "Orgs" / "partner-ag.md").read_text(encoding="utf-8")


def test_migrate_moves_people_and_rewrites_every_link(old_vault):
    root = old_vault
    (root / A / "People" / "notes.txt").write_text("mine", encoding="utf-8")  # a stray file: reported, left, folder kept
    n_old = len(old_links(root))
    res = wiki_migrate.migrate(dry_run=False, created_by=CB)
    assert res["dry_run"] is False and len(res["moved"]) == 3 and res["skipped"] == [] and res["links_rewritten"] == n_old == 35
    assert res["left"] == [f"{A}/People/notes.txt"] and res["old_folder_removed"] is False and res["old_folder_left"] == [f"{A}/People/notes.txt"]
    # every link resolves, none points at the old folder
    assert old_links(root) == []
    links = all_links(root)
    assert len(links) > 30
    bad = [(f, t) for f, t in links if not resolves(root, t)]
    assert bad == []
    # frontmatter keys were rewritten too
    e = fmt.split_note((root / A / "Emails" / "2026-08-20 Mail 1.md").read_text(encoding="utf-8"))[0]
    assert e["from_link"] == "[[Wiki/People/Jane Doe]]"
    m = fmt.split_note((root / A / "Meetings" / "2026-08-18 1300 Sync with Jane.md").read_text(encoding="utf-8"))[0]
    assert m["organizer_link"] == "[[Wiki/People/Jane Doe]]" and m["attendee_links"] == ["[[Wiki/People/Jane Doe]]", "[[Wiki/People/Bob Lee]]"]
    fu = (root / A / "Follow-ups.md").read_text(encoding="utf-8")
    assert "[[Wiki/People/Carol Ng]]" in fu and "[[Wiki/People/Bob Lee]]" in fu
    assert "[[Wiki/People/Jane Doe]]" in (root / A / "Daily" / "2026-08-20.md").read_text(encoding="utf-8")
    assert "[[Wiki/People/Carol Ng]]" in (root / A / "Weekly" / "2026-W33.md").read_text(encoding="utf-8")
    # the person pages follow the contract
    jane_text = (root / A / "Wiki" / "People" / "Jane Doe.md").read_text(encoding="utf-8")
    jfm = fmt.split_note(jane_text)[0]
    assert jfm["type"] == "person" and jfm["name"] == "Jane Doe" and jfm["title"] == "Jane Doe" and jfm["email"] == "jane.doe@example.com"
    assert jfm["org"] == "Example GmbH" and "company" not in jfm and "source" not in jfm
    assert jfm["aliases"] == ["Doe, Jane"] and jfm["last_contact"] == "2026-08-20T09:00:00+02:00" and jfm["status"] == "draft"
    assert jfm["created_by"] == CB and jfm["verified"] == "2026-08-21" and jfm["created"] == "2026-08-18" and jfm["sources"] == 4 and jfm["flags"] == []
    assert list(jfm)[:5] == ["type", "id", "title", "name", "email"] and len(jfm["id"]) == 26
    body = jane_text.split("---\n", 2)[2].lstrip("\n")
    assert body.startswith("# Jane Doe\n\nJane Doe (jane.doe@example.com) — Example GmbH.\n\n## Facts\n\n## Topics\n\n## Open\n\n## Records\n\n")
    recs = [l for l in body.split("\n") if l.startswith("- 2026-")]
    assert recs[:4] == ["- 2026-08-21 — [[Emails/2026-08-21 Mail 5]]", "- 2026-08-20 — [[Emails/2026-08-20 Mail 1]]", "- 2026-08-19 — [[Emails/2026-08-19 Mail 2]]", "- 2026-08-18 — [[Meetings/2026-08-18 1300 Sync with Jane]]"]
    assert "## History\n\n- " in body and "— migrated from People/Jane Doe (user)" in body
    assert body.rstrip().endswith("## Notes\n\nVoice with this person:\n- short, first names, no greeting\n- she signs off with 'Best'")
    bob = (root / A / "Wiki" / "People" / "Bob Lee.md").read_text(encoding="utf-8")
    assert bob.rstrip().endswith("## Notes\n\nKnows the Leipzig site well.") and "org:" not in fmt.split_note(bob)[1]
    carol = (root / A / "Wiki" / "People" / "Carol Ng.md").read_text(encoding="utf-8")
    assert carol.rstrip().endswith("## Notes") and "(waiting)" not in carol
    # the wiki reads them, the index lists them, the old workflows still find them
    page = wiki.read("Wiki/People/Jane Doe", ["lead", "notes"])
    assert page["notes"].startswith("Voice with this person:")
    idx = (root / A / "Wiki" / "Index.md").read_text(encoding="utf-8")
    assert "## People (3)" in idx and idx.count("- [[Wiki/People/") == 3 and "- [[Wiki/People/Jane Doe]] · Example GmbH · 2026-08-21" in idx
    assert store.find("person", "jane.doe@example.com")["path"] == f"{A}/Wiki/People/Jane Doe.md"
    assert workflows.prep_context("G|2026-08-25T13:00:00+02:00", "", ["jane.doe@example.com"])["people"][0]["company"] == "Example GmbH"
    # backup, views, log
    backups = list((root / A / "_backup").iterdir())
    assert len(backups) == 1 and re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}$", backups[0].name)
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}$", backups[0].name)
    assert res["backup"] == f"{A}/_backup/{backups[0].name}/People"
    assert sorted(p.name for p in (backups[0] / "People").iterdir()) == ["Bob Lee.md", "Carol Ng.md", "Jane Doe.md", "notes.txt"]
    assert "Voice with this person:" in (backups[0] / "People" / "Jane Doe.md").read_text(encoding="utf-8")
    pb = (root / A / "_views" / "People.base").read_text(encoding="utf-8")
    assert 'file.inFolder("Administrator/Wiki/People")' in pb and "note.company" not in pb and pb == (store.VIEWS_DIR / "People.base").read_text(encoding="utf-8")
    assert (root / A / "_views" / "Wiki.base").read_text(encoding="utf-8") == (store.VIEWS_DIR / "Wiki.base").read_text(encoding="utf-8")
    log = wiki.log()["lines"]
    assert log[0].endswith("migrate | Wiki/People | - | 3 people, 35 links")
    assert any(l.endswith("migrate | Follow-ups | - | 1 open, 1 done") for l in log)
    # second run: nothing left to move except the stray file
    again = wiki_migrate.migrate(dry_run=False)
    assert again["people"] == [] and again["links"]["count"] == 0 and again["old_folder_removed"] is False
    (root / A / "People" / "notes.txt").unlink()
    assert wiki_migrate.migrate(dry_run=False)["old_folder_removed"] is True and not (root / A / "People").exists()
    assert wiki_migrate.migrate()["needed"] is False and store.status()["old_people_dir"] is False


def test_migrate_removes_the_old_folder_and_keeps_a_clashing_page(old_vault):
    root = old_vault
    wiki.create("person", "Bob Lee", lead="Bob runs the site.", extra={"email": "bob.lee@example.com"})
    res = wiki_migrate.migrate(dry_run=False)
    assert len(res["moved"]) == 2 and res["skipped"][0]["from"] == f"{A}/People/Bob Lee.md" and res["old_folder_removed"] is False
    assert res["old_folder_left"] == [f"{A}/People/Bob Lee.md"]
    assert fmt.split_note((root / A / "Wiki" / "People" / "Bob Lee.md").read_text(encoding="utf-8"))[0]["status"] == "active"
    (root / A / "People" / "Bob Lee.md").unlink()
    assert wiki_migrate.migrate(dry_run=False)["old_folder_removed"] is True
    assert [(f, t) for f, t in all_links(root) if not resolves(root, t)] == []


def test_server_migrate_tool(old_vault):
    server = build_server()
    out = asyncio.run(server.call_tool("vault_wiki_keep", {"action": "migrate"}))
    plan = json.loads(out[0].text if isinstance(out, list) else out[0][0].text)
    assert plan["dry_run"] is True and len(plan["people"]) == 3
    assert (old_vault / A / "People" / "Jane Doe.md").is_file()
    out = asyncio.run(server.call_tool("vault_wiki_keep", {"action": "migrate", "dry_run": False}))
    res = json.loads(out[0].text if isinstance(out, list) else out[0][0].text)
    assert res["old_folder_removed"] is True and len(res["moved"]) == 3
