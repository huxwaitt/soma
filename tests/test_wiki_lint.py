"""administrator_vault.wiki_lint: the checks on a seeded vault, fix=true, merge with redirect."""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta

import pytest

from administrator_vault import frontmatter as fmt
from administrator_vault import store, wiki, wiki_lint, wiki_search, workflows
from administrator_vault.server import build_server

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


def fm_of(vault, path):
    return fmt.split_note(text_of(vault, path))[0]


def write_page(vault, path, fm, title, lead="x", facts=(), **sections):
    page = wiki.Page(path=path, fm=dict({"created": "2026-08-01", "created_by": CB, "aliases": [], "summary": "", "flags": [], "sources": 0, "open_items": 0, "verified": "2026-08-01", "updated": "2026-08-01T09:00:00+02:00", "title": title}, **fm), title=title, lead=lead)
    page.facts = [wiki.Fact(["abcd", "efgh", "ijkl", "mnop"][i], t, s, [src]) for i, (t, s, src) in enumerate(facts)]
    for name, lines in sections.items():
        page.sections[name] = list(lines)
    (vault / path).parent.mkdir(parents=True, exist_ok=True)
    (vault / path).write_text(wiki.format_page(page), encoding="utf-8")
    return path


def email(n=1, subject="Budget Q3", received="2026-08-22T09:14:00+02:00", body="## Summary\n\nS.\n\n## Action items\n\n- none\n", wiki_key=None):
    fm = {
        "type": "email", "source": "outlook", "internet_message_id": f"<m{n}@example.com>", "entry_id": f"00A{n}", "conversation_id": "C1",
        "subject": subject, "from": "jane.doe@example.com", "from_name": "Jane Doe", "from_link": "[[Wiki/People/Jane Doe]]", "to": [], "cc": [],
        "received": received, "status": "todo", "created_by": CB,
    }
    if wiki_key:
        fm["wiki"] = wiki_key
    return store.write("email", fm, f"# {subject}\n\n{body}")["path"]


def seed(vault):
    """One page (or record) per check."""
    T = f"{W}/Topics"
    # 2 dangling link in Related; 3 orphan (nothing links to it); 7 stale active topic; 15 unconfirmed old fact; 8 due in the past
    write_page(vault, f"{T}/stale-thing.md", {"type": "topic", "status": "active", "verified": "2020-01-10", "due": "2020-02-01"}, "Stale thing",
               facts=[("Old single-source fact", "2020-01-10", "<old@example.com>")], Related=["- [[Wiki/Topics/nope]]"])
    # 4 frontmatter: extra key, hand-edited sources; 5 sections: unknown + out of order (written raw)
    raw = write_page(vault, f"{T}/messy.md", {"type": "topic", "status": "active", "verified": "2026-08-20", "sources": 99, "foo": "bar"}, "Messy page")
    text = text_of(vault, raw).replace("## Milestones\n\n## People\n", "## People\n\n## Milestones\n").replace("## History\n", "## Random\n\nstuff\n\n## History\n")
    (vault / raw).write_text(text, encoding="utf-8")
    # 6 oversized person page
    write_page(vault, f"{W}/People/Big Person.md", {"type": "person", "name": "Big Person", "email": "big@example.com", "last_contact": "2026-08-20T09:00:00+02:00", "status": "active", "verified": "2026-08-20"}, "Big Person",
               History=[f"- 2026-08-01 — note {i} " + "y" * 300 for i in range(15)])
    # 9 open item whose record action is ticked; the record links back (not an orphan)
    rec = email(1, body="## Summary\n\nS.\n\n## Action items\n\n- [x] Send Q3 numbers to Jane\n", wiki_key=["[[Wiki/Topics/q3-budget]]"])
    write_page(vault, f"{T}/q3-budget.md", {"type": "topic", "status": "active", "verified": "2026-08-22", "aliases": ["Budget Q3"]}, "Q3 budget",
               Open=["- [ ] Send Q3 numbers to Jane — [[Emails/2026-08-22 Budget Q3]]"], Records=["- 2026-08-22 — [[Emails/2026-08-22 Budget Q3]] — S."])
    # 10 duplicate: same alias, and a second pair by email
    write_page(vault, f"{T}/budget-q3.md", {"type": "topic", "status": "active", "verified": "2026-08-21", "aliases": ["Budget Q3"]}, "Budget round Q3", Related=["- [[Wiki/Topics/q3-budget]]"])
    write_page(vault, f"{W}/People/Jane Doe.md", {"type": "person", "name": "Jane Doe", "email": "jane.doe@example.com", "last_contact": "2026-08-22T09:14:00+02:00", "status": "active", "verified": "2026-08-22"}, "Jane Doe", Related=["- [[Wiki/People/J Doe]]"])
    write_page(vault, f"{W}/People/J Doe.md", {"type": "person", "name": "J Doe", "email": "JANE.DOE@example.com", "last_contact": "2026-08-22T09:14:00+02:00", "status": "active", "verified": "2026-08-22"}, "J Doe", Related=["- [[Wiki/People/Jane Doe]]", "- [[Wiki/People/Big Person]]", "- [[Wiki/Topics/budget-q3]]", "- [[Wiki/Topics/messy]]"])
    # 11 un-ingested record (no wiki key)
    email(2, subject="Offsite venue", received="2026-08-21T09:00:00+02:00")
    # 12 candidate over threshold
    (vault / W / "_cache").mkdir(exist_ok=True)
    (vault / W / "_cache" / "candidates.json").write_text(json.dumps({"offsite venue": {"subject": "Offsite venue", "records": {"Emails/a": "2026-08-20", "Emails/b": "2026-08-21"}}}), encoding="utf-8")
    # 13 History over 40 lines
    write_page(vault, f"{T}/long-history.md", {"type": "topic", "status": "active", "verified": "2026-08-22"}, "Long history", History=[f"- 2026-08-01 — step {i} (user)" for i in range(45)], Related=["- [[Wiki/Topics/q3-budget]]"])
    # Log over 500 lines
    (vault / W / "Log.md").write_text("# Wiki log\n\n" + "\n".join(f"- [2026-01-01T00:00:{i % 60:02d}+00:00] apply | Wiki/Topics/x | user | add 1" for i in range(500)) + "\n", encoding="utf-8")
    # 1: the index does not know any of these pages yet
    return rec


def test_lint_report_hits_every_check(vault):
    seed(vault)
    r = wiki_lint.lint(fix=False)
    c = r["checks"]
    assert r["pages"] == 8 and r["fix"] is False
    # 1 index <-> files
    assert "Wiki/Topics/stale-thing" in c["1"]["missing_lines"]
    # 2 dangling
    assert c["2"]["count"] == 1 and c["2"]["items"][0] == {"page": "Wiki/Topics/stale-thing", "target": "Wiki/Topics/nope", "where": "body"}
    # 3 orphans: stale-thing and long-history have no inbound link; q3-budget has the record's wiki key, Jane the from_link
    assert c["3"]["pages"] == ["Wiki/Topics/long-history", "Wiki/Topics/stale-thing"]
    # 4 frontmatter
    messy = next(i for i in c["4"]["items"] if i["page"] == "Wiki/Topics/messy")
    assert messy["extra"] == ["foo"] and messy["code_owned_edited"] == ["sources"] and messy["missing"] == []  # the id came from the hand-edit pass
    # 5 sections
    assert c["5"]["items"] == [{"page": "Wiki/Topics/messy", "unknown": ["Random"], "duplicate": [], "out_of_order": True}]
    # 6 oversized
    assert c["6"]["items"][0]["page"] == "Wiki/People/Big Person" and c["6"]["items"][0]["chars"] > 4000 and "smaller op set" in c["6"]["remedies"]
    # 7 stale
    assert [s["page"] for s in c["7"]["items"]] == ["Wiki/Topics/stale-thing"] and c["7"]["items"][0]["set_dormant"] is False
    # 8 due past
    assert c["8"]["items"] == [{"page": "Wiki/Topics/stale-thing", "due": "2020-02-01"}]
    # 9 open item done in the record
    assert c["9"]["items"] == [{"page": "Wiki/Topics/q3-budget", "id": None, "text": "Send Q3 numbers to Jane", "record": "Emails/2026-08-22 Budget Q3"}]
    # 10 duplicates: alias pair and email pair
    pairs = {(d["a"], d["b"]) for d in c["10"]["items"]}
    assert pairs == {("Wiki/Topics/budget-q3", "Wiki/Topics/q3-budget"), ("Wiki/People/J Doe", "Wiki/People/Jane Doe")}
    assert any('shared name "budget q3"' in l for l in r["review_added"]) and any('email "jane.doe@example.com"' in l for l in r["review_added"])
    # 11 un-ingested
    assert c["11"]["count"] == 1 and c["11"]["records"] == ["Administrator/Emails/2026-08-21 Offsite venue.md"]
    # 12 candidates
    assert [x["subject"] for x in c["12"]["items"]] == ["Offsite venue"]
    # 13 rotation
    assert c["13"]["history_over"] == ["Wiki/Topics/long-history"] and c["13"]["log_over"] is True
    # 14 ask the model: first run -> every page
    assert len(c["14"]["ask_model"]) == 8 and c["14"]["since"] is None
    # 15 unconfirmed
    assert c["15"]["count"] == 1 and c["15"]["pages"] == {"Wiki/Topics/stale-thing": [{"id": "abcd", "text": "Old single-source fact", "since": "2020-01-10"}]}
    # 16 consistency: the five one-way links in the seed, reported and not yet fixed
    assert c["16"]["count"] == 5 and {i["kind"] for i in c["16"]["items"]} == {"link"} and c["16"]["fixed"] is False
    assert {(i["page"], i["other"]) for i in c["16"]["items"]} == {
        ("Wiki/People/J Doe", "Wiki/People/Big Person"), ("Wiki/People/J Doe", "Wiki/Topics/budget-q3"),
        ("Wiki/People/J Doe", "Wiki/Topics/messy"), ("Wiki/Topics/budget-q3", "Wiki/Topics/q3-budget"),
        ("Wiki/Topics/long-history", "Wiki/Topics/q3-budget"),
    }
    # 17 close: the topic with a due date and nothing new since 2020; 18 thin: nothing yet, every page is young
    assert [i["page"] for i in c["17"]["items"]] == ["Wiki/Topics/stale-thing"] and c["18"]["count"] == 0
    assert any("no update in 90 days: close it?" in l for l in r["review_added"])
    # flags were written (both modes), index regenerated, cache + log line present
    assert set(r["flagged"]) == {"Wiki/Topics/stale-thing", "Wiki/Topics/long-history", "Wiki/People/Big Person", "Wiki/Topics/q3-budget", "Wiki/Topics/budget-q3", "Wiki/People/Jane Doe", "Wiki/People/J Doe"}
    assert fm_of(vault, f"{W}/Topics/stale-thing.md")["flags"] == ["orphan", "stale"]
    assert fm_of(vault, f"{W}/People/Big Person.md")["flags"] == ["oversized"]
    assert fm_of(vault, f"{W}/Topics/q3-budget.md")["flags"] == ["possible-duplicate"]
    assert "Wiki/Topics/messy" not in r["flagged"] and fm_of(vault, f"{W}/Topics/messy.md")["sources"] == 99  # report only without fix
    assert "- [[Wiki/Topics/stale-thing|Stale thing]]" in text_of(vault, f"{W}/Index.md")
    assert r["cache"] == f"{W}/_cache/lint-{r['date']}.json" and json.loads(text_of(vault, r["cache"]))["counts"] == r["counts"]
    line = wiki.log(page="Wiki")["lines"][-1]  # one line per run with every count on it
    assert "lint | Wiki | - | 8 pages, 7 flagged, 4 review lines, 7 written, " in line
    assert "consistency 5, close 1, thin 0" in line and "questions 0/0" in line and line.endswith("unanswered 0")
    assert fm_of(vault, f"{W}/Topics/stale-thing.md")["status"] == "active"
    # second run: flags unchanged, nothing rewritten, only pages touched since the last lint go to the model
    r2 = wiki_lint.lint(fix=False)
    assert r2["written"] == [] and r2["review_added"] == [] and r2["checks"]["14"]["ask_model"] == [] and r2["checks"]["14"]["since"] == r["finished"]
    assert r2["cache"] == r["cache"] and json.loads(text_of(vault, r2["cache"]))["finished"] == r2["finished"]
    wiki.apply(f"{W}/Topics/q3-budget.md", [{"op": "summary", "text": "Numbers due Friday."}])
    assert wiki_lint.lint()["checks"]["14"]["ask_model"] == ["Wiki/Topics/q3-budget"]


def test_lint_fix_applies_the_safe_fixes(vault):
    seed(vault)
    r = wiki_lint.lint(fix=True)
    c = r["checks"]
    # 2: dangling link in a code-owned section became plain text
    assert "- Wiki/Topics/nope" in text_of(vault, f"{W}/Topics/stale-thing.md") and "[[Wiki/Topics/nope]]" not in text_of(vault, f"{W}/Topics/stale-thing.md")
    # 4: code-owned keys recomputed, the missing id written, the extra key is only reported
    fm = fm_of(vault, f"{W}/Topics/messy.md")
    assert fm["sources"] == 0 and fm["foo"] == "bar" and len(fm["id"]) == 26
    ids = {fm_of(vault, p)["id"] for p in (f"{W}/Topics/messy.md", f"{W}/Topics/q3-budget.md", f"{W}/People/Jane Doe.md")}
    assert len(ids) == 3
    # 5: section order fixed, unknown section kept and reported
    text = text_of(vault, f"{W}/Topics/messy.md")
    assert text.index("## Facts") < text.index("## People") and "## Random" in text and c["5"]["items"][0]["unknown"] == ["Random"]
    # 7: a stale topic with a due date is left for check 17 to ask about (it stays active); one without a due is set dormant
    assert fm_of(vault, f"{W}/Topics/stale-thing.md")["status"] == "active" and c["7"]["items"][0]["set_dormant"] is False
    assert c["17"]["count"] == 1 and c["17"]["items"][0]["page"] == "Wiki/Topics/stale-thing"
    # 9: the open item moved to History
    text = text_of(vault, f"{W}/Topics/q3-budget.md")
    assert "- [ ] Send Q3" not in text and '— done "Send Q3 numbers to Jane" — owner: me · since ' in text
    assert fm_of(vault, f"{W}/Topics/q3-budget.md")["open_items"] == 0
    # 13: History rotated, Log rotated
    hist = text_of(vault, f"{W}/Topics/long-history.md").split("## History\n\n")[1].split("\n## Notes")[0].strip().split("\n")
    assert len(hist) == 40 and hist[0].startswith("- older history: [[Wiki/_history/Topics/long-history]]")
    assert (vault / W / "_history" / "Log-2026.md").is_file() and wiki.log(limit=500)["total"] < 10
    # 1: index regenerated with every page
    assert c["1"]["fixed"] is True and text_of(vault, f"{W}/Index.md").count("- [[Wiki/") == 8
    # Review: duplicates + stale lines. Check 7 parked the stale topic as dormant,
    # so check 17 does not ask "close it?" about it in the same run.
    rv = wiki.review("list")
    assert len(rv["open"]) == 4 and any("merge [[Wiki/Topics/q3-budget]] into [[Wiki/Topics/budget-q3]]?" in o["text"] for o in rv["open"])  # duplicate, stale, close-it, and the person merge
    assert sum("no update in 90 days" in o["text"] for o in rv["open"]) == 1 and c["17"]["count"] == 1  # asked once, not parked by check 7
    # 16: the one-way links got their other side, and a second run finds none
    assert "- [[Wiki/Topics/budget-q3]]" in text_of(vault, f"{W}/Topics/q3-budget.md")
    assert "- [[Wiki/People/J Doe]]" in text_of(vault, f"{W}/Topics/messy.md").split("## People")[1]
    assert wiki_lint.lint(fix=True)["checks"]["16"]["count"] == 0


def test_fix_takes_a_dead_link_out_of_an_open_item(vault):
    """An open item names a record that was deleted: fix turns the link into
    plain text, the way it does in every other code-owned section."""
    path = wiki.create("topic", "Q3 budget", lead="Jane collects the numbers.")["path"]
    wiki.apply(path, [{"op": "open", "text": "chase [[Emails/gone]]", "src": "user"},
                      {"op": "milestone", "text": "sheet in [[Emails/gone]]", "src": "user"}])
    r = wiki_lint.lint(fix=True)
    assert r["checks"]["2"]["items"] == [{"page": "Wiki/Topics/q3-budget", "target": "Emails/gone", "where": "body"}]
    text = text_of(vault, path)
    assert "[[Emails/gone]]" not in text and "- [ ] chase Emails/gone" in text and "<!-- o:" in text
    assert "- [ ] sheet in Emails/gone" in text and "<!-- m:" in text
    assert wiki_lint.lint(fix=True)["checks"]["2"]["count"] == 0  # and it stays fixed


def test_weekly_facts_has_wiki_counts(vault):
    seed(vault)
    wiki_lint.lint()
    w = workflows.weekly_facts("2026-W34", today="2026-08-22")["wiki"]
    assert w == {"review_open": 4, "stale": 1, "uningested": 1, "candidates": 1, "questions": "0/0", "unanswered": 0}


def test_merge_with_redirect(vault):
    keep = wiki.create("topic", "Q3 budget", aliases=["Budget Q3"], lead="Jane collects the numbers.", summary="Numbers due.",
                       facts=[{"text": "Deadline is 2026-08-29", "since": "2026-08-22", "src": "<a@example.com>"}])["path"]
    drop = wiki.create("topic", "Budget round Q3", lead="Same thing, other name.",
                       facts=[{"text": "deadline is 2026-08-29", "since": "2026-08-20", "src": "<b@example.com>"}, {"text": "Sheet tab is Sales", "since": "2026-08-21", "src": "<c@example.com>"}])["path"]
    jane = wiki.create("person", "Jane Doe", extra={"email": "jane.doe@example.com"})["path"]
    wiki.apply(drop, [{"op": "role", "page": jane, "role": "owns it"}, {"op": "open", "text": "Send the sheet"}])
    rec = email(1)
    wiki.ingest(rec, [{"path": drop, "ops": []}])
    wiki.apply(drop, [{"op": "alias", "text": "Budget Q3"}])  # now the two share an alias: lint proposes the merge
    wiki_lint.lint()
    assert any("merge [[Wiki/Topics/q3-budget]] into [[Wiki/Topics/budget-round-q3]]?" in o["text"] for o in wiki.review("list")["open"])
    assert "possible-duplicate" in fm_of(vault, keep)["flags"]
    r = wiki_lint.merge("Wiki/Topics/q3-budget", "[[Wiki/Topics/budget-round-q3]]")
    assert r["keep"] == keep and r["drop"] == drop and r["redirect"] == "[[Wiki/Topics/q3-budget]]"
    assert len(r["facts_added"]) == 1 and len(r["facts_confirmed"]) == 1 and r["facts_refused"] == [] and r["review_closed"] == 1
    assert "possible-duplicate" not in fm_of(vault, keep)["flags"]  # the merge answered the question
    facts = wiki.read(keep)["facts"]
    assert [f["text"] for f in facts] == ["Deadline is 2026-08-29", "Sheet tab is Sales"]
    assert facts[0]["src"] == ["<b@example.com>", "<a@example.com>"] and facts[1]["src"] == ["<c@example.com>"] and facts[1]["since"] == "2026-08-21"
    text = text_of(vault, keep)
    fm = fm_of(vault, keep)
    assert "Budget round Q3" in fm["aliases"] and "budget-round-q3" in fm["aliases"]
    assert "- [[Wiki/People/Jane Doe]] — owns it" in text and "- [ ] Send the sheet" in text and "[[Emails/2026-08-22 Budget Q3]]" in text
    assert "merged [[Wiki/Topics/budget-round-q3]] into this page: facts added 1, confirmed 1 ([[Wiki/Topics/budget-round-q3]])" in text
    # the dropped page is a redirect: 3 lines of body, type redirect, skipped by the index and by match, followed by read
    red = text_of(vault, drop)
    rfm = fmt.split_note(red)[0]
    assert rfm["type"] == "redirect" and rfm["redirect"] == "[[Wiki/Topics/q3-budget]]" and rfm["title"] == "Budget round Q3"
    assert red.split("---\n")[-1].strip().split("\n\n") == ["# Budget round Q3", "Merged into [[Wiki/Topics/q3-budget]] on " + wiki._today() + "."]
    idx = text_of(vault, f"{W}/Index.md")
    assert "budget-round-q3" not in idx and fmt.split_note(idx)[0]["pages"] == 2
    assert all(p["path"] != drop for p in wiki.match("Budget round Q3")["pages"])
    rd = wiki.read(drop)
    assert rd["path"] == keep and rd["redirected_from"] == "Wiki/Topics/budget-round-q3"
    # the person page's link followed the merge; the old page text is kept under _history
    assert "- [[Wiki/Topics/q3-budget]] — owns it" in text_of(vault, jane) and "budget-round-q3" not in text_of(vault, jane)
    assert "Page text before the merge" in text_of(vault, f"{W}/_history/Topics/budget-round-q3.md")
    assert wiki.review("list")["open"] == []
    assert "merge | Wiki/Topics/q3-budget | [[Wiki/Topics/budget-round-q3]] | facts added 1, confirmed 1, refused 0, relinked 1" in wiki.log()["lines"][-1]
    # lint after the merge: no dangling link, the redirect is not a page
    r = wiki_lint.lint()
    assert r["checks"]["2"]["count"] == 0 and r["pages"] == 2
    with pytest.raises(store.VaultError):
        wiki_lint.merge(keep, keep)
    with pytest.raises(store.VaultError):
        wiki_lint.merge(keep, drop)  # a redirect cannot be merged again


def test_server_lint_and_merge_tools(vault):
    server = build_server()

    def call(name, args):
        out = asyncio.run(server.call_tool(name, args))
        return json.loads(out[0].text if isinstance(out, list) else out[0][0].text)

    seed(vault)
    r = call("vault_wiki_lint", {"fix": True})
    assert r["fix"] is True and set(r["checks"]) == {str(i) for i in range(0, 22)}  # 0 = the hand-edit pass
    m = call("vault_wiki_merge", {"keep": "Wiki/Topics/q3-budget", "drop": "Wiki/Topics/budget-q3"})
    assert m["redirect"] == "[[Wiki/Topics/q3-budget]]"
    assert fm_of(vault, f"{W}/Topics/budget-q3.md")["type"] == "redirect"


def test_uningested_includes_chat_records(vault):
    chat = {"id": "19:abc@thread.v2", "title": "Q3 budget", "type": "group", "members": [{"name": "Jane Doe"}], "account": "acme"}
    rec = workflows.save_chat(chat, [{"id": "m1", "time": "2026-08-21T09:14:00+02:00", "sender": "Jane Doe", "is_self": False, "text": "Hi"}], ["Hux"], created_by=CB)["path"]
    assert wiki_lint._record_day(fm_of(vault, rec)) == "2026-08-21"
    assert wiki_lint.uningested_records(vault) == (1, [rec])
    assert wiki_lint.lint()["checks"]["11"]["records"] == [rec]
    page = wiki.create("topic", "Q3 budget", lead="Numbers.", summary="Numbers.")["path"]
    wiki.ingest(rec, [{"path": page, "ops": []}], created_by=CB)
    assert wiki_lint.uningested_records(vault) == (0, [])


def test_the_copy_of_a_deleted_page_does_not_hide_the_links_to_it(vault):
    """_cache/prev/ holds each page's text from before the last write. Those
    copies are working files, not notes: a link to a page the user deleted is
    still a dangling link."""
    path = wiki.create("topic", "Q3 budget", lead="Numbers.", summary="Numbers.")["path"]
    other = wiki.create("topic", "Offsite venue", lead="October.", summary="Where.")["path"]
    wiki.apply(other, [{"op": "related", "page": "Wiki/Topics/q3-budget"}])
    (vault / path).unlink()

    assert (vault / f"{W}/_cache/prev/Topics/q3-budget.md.prev").is_file()
    c = wiki_lint.lint()["checks"]["2"]
    assert c["count"] == 1 and c["items"][0]["target"] == "Wiki/Topics/q3-budget"


def test_check_19_asks_about_the_users_own_items_past_their_due_date(vault):
    path = wiki.create("topic", "Q3 budget", lead="Numbers.", summary="Numbers.")["path"]
    jane = wiki.create("person", "Jane Doe", extra={"email": "jane.doe@example.com"})["path"]
    today = date.today().isoformat()
    late = (date.today() - timedelta(days=3)).isoformat()
    soon = (date.today() + timedelta(days=3)).isoformat()
    wiki.apply(path, [
        {"op": "open", "text": "Send the numbers", "due": late, "src": "a"},
        {"op": "open", "text": "Book the room", "due": soon, "src": "b"},
        {"op": "open", "text": "Read the draft", "due": today, "src": "c"},
    ])
    wiki.apply(jane, [{"op": "open", "text": "Jane signs", "owner": "[[Wiki/People/Jane Doe]]", "due": late, "src": "d"}])
    c = wiki_lint.lint()["checks"]["19"]
    assert c["name"] == "overdue" and c["count"] == 1
    assert c["items"][0]["page"] == "Wiki/Topics/q3-budget" and c["items"][0]["text"] == "Send the numbers" and c["items"][0]["due"] == late
    assert wiki_lint.lint()["counts"]["overdue"] == 1
    line = f'- [ ] [[Wiki/Topics/q3-budget]] — overdue: "Send the numbers" due {late} — done, reschedule, or drop'
    assert any(o["text"] == line for o in wiki.review("list")["open"])


def questions_file(vault, *lines):
    p = vault / "Administrator" / "Wiki" / "Questions.md"
    p.write_text("---\ntype: wiki-questions\nsource: administrator\n---\n# Questions\n\nMine.\n\n## Questions\n\n"
                 + "".join(l + "\n" for l in lines), encoding="utf-8")
    return p


def test_check_20_asks_the_wiki_the_users_own_questions(vault):
    path = wiki.create("topic", "Q3 budget", aliases=["Budget Q3"], lead="Jane collects the numbers.", summary="Numbers due.",
                       facts=[{"text": "Deadline is 2026-08-29", "since": "2026-08-22", "src": "<a@example.com>"}])["path"]
    fid = wiki.read(path)["facts"][0]["id"]
    wiki.create("topic", "Expense policy", lead="Receipts within 30 days.", summary="Receipts.")
    questions_file(
        vault,
        f"- When is the Q3 budget due? → [[Wiki/Topics/q3-budget]] f:{fid}",  # the fact itself must come back
        "- Which receipts count? → [[Wiki/Topics/expense-policy]]",
        "- What is the gate code for the car park? → [[Wiki/Topics/expense-policy]]",  # nothing answers this
        "- Anything at all? → [[Wiki/Topics/never-written]]",  # no such page yet: not counted
        "a line that is not a question",
    )
    r = wiki_lint.lint()
    c = r["checks"]["20"]
    assert c["name"] == "questions" and c["asked"] == 3 and c["found"] == 2
    assert [m["question"] for m in c["misses"]] == ["What is the gate code for the car park?"]
    assert c["misses"][0]["expected"] == "Wiki/Topics/expense-policy" and c["misses"][0]["top"] == []
    assert c["unknown"] == [{"question": "Anything at all?", "expected": "Wiki/Topics/never-written"}]
    assert r["counts"]["questions"] == "2/3"
    assert "questions 2/3" in wiki.log(page="Wiki")["lines"][-1]
    # asking them is not the same as being asked them: they do not land in queries.log
    assert wiki_search.read_query_log(vault) == []
    # the named fact has to be the one found, not just its page
    questions_file(vault, "- When is the Q3 budget due? → [[Wiki/Topics/q3-budget]] f:zzzz")
    c = wiki_lint.lint()["checks"]["20"]
    assert c["asked"] == 1 and c["found"] == 0 and c["misses"][0]["expected"] == "Wiki/Topics/q3-budget f:zzzz"
    assert f"Wiki/Topics/q3-budget f:{fid}" in c["misses"][0]["top"]


def test_check_21_asks_about_the_questions_the_wiki_could_not_answer(vault):
    wiki.create("topic", "Q3 budget", lead="Jane collects the numbers.", summary="Numbers due.")
    day = date.today().isoformat()
    old = (date.today() - timedelta(days=60)).isoformat()
    rows = [
        (f"{day}T09:00:00+02:00", "Where is the offsite?", 0, "-"),
        (f"{day}T10:00:00+02:00", "where is the offsite", 0, "-"),  # the same question twice
        (f"{day}T11:00:00+02:00", "who owns the budget", 1, "Wiki/Topics/q3-budget"),  # answered
        (f"{day}T12:00:00+02:00", "what is the gate code", 0, "-"),  # asked once
        (f"{old}T09:00:00+02:00", "how do I book a room", 0, "-"),  # too long ago
        (f"{old}T10:00:00+02:00", "how do I book a room", 0, "-"),
    ]
    log = vault / wiki_search.QUERY_LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("\n".join("\t".join([w, q, str(h), t]) for w, q, h, t in rows) + "\n", encoding="utf-8")
    r = wiki_lint.lint()
    c = r["checks"]["21"]
    assert c["name"] == "unanswered" and c["count"] == 1 and c["days"] == 30
    assert c["items"] == [{"query": "where is the offsite", "times": 2, "last": day}]
    assert r["counts"]["unanswered"] == 1 and "unanswered 1" in wiki.log(page="Wiki")["lines"][-1]
    line = '- [ ] no page answers "where is the offsite" — create one?'
    assert line in r["review_added"] and any(o["text"] == line for o in wiki.review("list")["open"])
    # a second run does not ask twice
    assert wiki_lint.lint()["review_added"] == []
    assert workflows.weekly_facts("2026-W34", today="2026-08-22")["wiki"]["unanswered"] == 1


def test_check_4_knows_the_keys_and_statuses_of_each_type(vault):
    old = (date.today() - timedelta(days=400)).isoformat()
    write_page(vault, f"{W}/Decisions/new-stack.md", {"type": "decision", "status": "current", "verified": old, "decided": "2026-08-22", "by": ["[[Wiki/People/Jane Doe]]"], "reversal": "A licence problem."}, "New stack")
    write_page(vault, f"{W}/Decisions/half-a-decision.md", {"type": "decision", "status": "active", "verified": "2026-08-22"}, "Half a decision")
    write_page(vault, f"{W}/Topics/at-risk-topic.md", {"type": "topic", "status": "at-risk", "verified": "2026-08-22"}, "At risk topic")
    write_page(vault, f"{W}/Topics/wrong-status.md", {"type": "topic", "status": "current", "verified": "2026-08-22"}, "Wrong status")
    c = wiki_lint.lint()["checks"]
    items = {i["page"]: i for i in c["4"]["items"]}
    assert "Wiki/Decisions/new-stack" not in items and "Wiki/Topics/at-risk-topic" not in items
    assert items["Wiki/Decisions/half-a-decision"]["missing"] == ["decided", "by"]
    assert items["Wiki/Decisions/half-a-decision"]["mistyped"] == ["status"]
    assert items["Wiki/Topics/wrong-status"]["mistyped"] == ["status"]
    # 7 stale: a decision is what was decided, so it never goes stale; the topics do
    assert [s["page"] for s in c["7"]["items"]] == []
    write_page(vault, f"{W}/Topics/old-topic.md", {"type": "topic", "status": "blocked", "verified": old}, "Old topic")
    c2 = wiki_lint.lint(fix=True)["checks"]
    assert [s["page"] for s in c2["7"]["items"]] == ["Wiki/Topics/old-topic"]
    assert fm_of(vault, f"{W}/Topics/old-topic.md")["status"] == "dormant"
    assert fm_of(vault, f"{W}/Decisions/new-stack.md")["status"] == "current"
    assert "stale" not in fm_of(vault, f"{W}/Decisions/new-stack.md")["flags"]
    # 4 with fix: a status the type does not know is put right (a decision with a lead is current)
    assert fm_of(vault, f"{W}/Decisions/half-a-decision.md")["status"] == "current"


def test_check_8_reads_a_due_date_on_a_blocked_topic_too(vault):
    late = (date.today() - timedelta(days=2)).isoformat()
    write_page(vault, f"{W}/Topics/blocked-thing.md", {"type": "topic", "status": "blocked", "verified": "2026-08-22", "due": late}, "Blocked thing")
    assert wiki_lint.lint()["checks"]["8"]["items"] == [{"page": "Wiki/Topics/blocked-thing", "due": late}]


def test_lint_settles_a_decision_the_user_ticked_in_review(vault):
    wiki.create("person", "Jane Doe", extra={"email": "jane.doe@example.com"})
    path = wiki.create("decision", "New stack", lead="We go with the new stack.", summary="New stack.",
                       facts=[{"text": "The rebuild runs on the new stack", "since": "2026-08-22", "src": "user"}],
                       extra={"decided": "2026-08-22", "by": ["[[Wiki/People/Jane Doe]]"]})["path"]
    assert fm_of(vault, path)["flags"] == ["unconfirmed-decision"]
    p = vault / wiki.REVIEW_PATH
    p.write_text(p.read_text(encoding="utf-8").replace("- [ ] [[Wiki/Decisions/new-stack]]", "- [x] [[Wiki/Decisions/new-stack]]"), encoding="utf-8")
    r = wiki_lint.lint()
    assert r["confirmed_decisions"] == ["Wiki/Decisions/new-stack"]
    assert "unconfirmed-decision" not in fm_of(vault, path)["flags"]
    assert not any("new-stack" in o["text"] for o in wiki.review("list")["open"])


# ------------------------------------------------------------------ 16 consistency, 17 close, 18 thin


def _ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


def seed_consistency(vault):
    """One page per case check 16 knows."""
    now = date.today().isoformat()
    write_page(vault, f"{W}/Orgs/acme.md", {"type": "org", "status": "active", "verified": now}, "Acme")
    write_page(vault, f"{W}/People/Jane Doe.md", {"type": "person", "name": "Jane Doe", "email": "jane.doe@example.com",
               "last_contact": "2026-08-22T09:14:00+02:00", "status": "active", "verified": now, "org": "[[Wiki/Orgs/acme]]"}, "Jane Doe")
    write_page(vault, f"{W}/Topics/q3-budget.md", {"type": "topic", "status": "active", "verified": now, "owner": "Jane Doe", "due": "2026-08-29"},
               "Q3 budget", facts=[("Numbers are due 2026-09-05", now, "<m1@example.com>")])
    write_page(vault, f"{W}/Topics/offsite.md", {"type": "topic", "status": "active", "verified": now, "owner": "Nobody Here"}, "Offsite")
    write_page(vault, f"{W}/Topics/rebuild.md", {"type": "topic", "status": "active", "verified": now}, "Rebuild", Related=["- [[Wiki/Topics/offsite]]"])


def test_check_16_reports_what_two_pages_say_about_each_other(vault):
    seed_consistency(vault)
    c = wiki_lint.lint()["checks"]["16"]
    assert c["name"] == "consistency" and c["count"] == 5 and c["fixed"] is False
    kinds = {(i["kind"], i["page"]): i for i in c["items"]}
    # 1 the org page does not list the person whose org key names it
    assert kinds[("org-contacts", "Wiki/People/Jane Doe")]["other"] == "Wiki/Orgs/acme"
    assert kinds[("org-contacts", "Wiki/People/Jane Doe")]["section"] == "Contacts"
    # 2 one-way link between two topics
    assert kinds[("link", "Wiki/Topics/rebuild")]["other"] == "Wiki/Topics/offsite"
    # 3 an owner that is a plain name a person page carries
    assert kinds[("owner", "Wiki/Topics/q3-budget")]["other"] == "Wiki/People/Jane Doe"
    # 4 an owner no person page carries
    assert kinds[("owner", "Wiki/Topics/offsite")]["other"] is None
    # 5 the due date against a fact naming another day
    due = kinds[("due", "Wiki/Topics/q3-budget")]
    assert due["due"] == "2026-08-29" and due["text"] == "Numbers are due 2026-09-05"


def test_check_16_fixes_the_links_and_quotes_the_rest_in_review(vault):
    seed_consistency(vault)
    r = wiki_lint.lint(fix=True)
    assert r["counts"]["consistency"] == 5
    # the person is on the org's Contacts, the topic has its other side back
    assert "- [[Wiki/People/Jane Doe]]" in text_of(vault, f"{W}/Orgs/acme.md").split("## Contacts")[1]
    assert "- [[Wiki/Topics/rebuild]]" in text_of(vault, f"{W}/Topics/offsite.md").split("## Related")[1]
    # the plain-name owner became a link; the one nobody carries was left alone
    assert fm_of(vault, f"{W}/Topics/q3-budget.md")["owner"] == "[[Wiki/People/Jane Doe]]"
    assert fm_of(vault, f"{W}/Topics/offsite.md")["owner"] == "Nobody Here"
    lines = [o["text"] for o in wiki.review("list")["open"]]
    assert '- [ ] [[Wiki/Topics/offsite]] — owner: "Nobody Here" but no person page carries that name; link the person page or drop the key' in lines
    assert '- [ ] [[Wiki/Topics/q3-budget]] — due: 2026-08-29 but f:abcd says "Numbers are due 2026-09-05"; which day holds?' in lines
    # what was fixed stays fixed; what needs the user stays reported
    assert wiki_lint.lint(fix=True)["checks"]["16"]["count"] == 2


def test_checks_17_and_18_ask_about_a_project_that_stopped_and_a_page_with_one_record(vault):
    old, now = _ago(100), date.today().isoformat()
    # 17: a topic with a due date and nothing new for three months
    write_page(vault, f"{W}/Topics/rebuild.md", {"type": "topic", "status": "active", "verified": old, "created": old, "due": "2026-12-01"}, "Rebuild",
               facts=[("Two records back this", old, "<m1@example.com>"), ("And a second one", old, "<m2@example.com>")])
    # not 17: the same page once it is closed or parked as dormant (check 7 asked
    # that question already and the status is the answer); and one with no due date
    write_page(vault, f"{W}/Topics/offsite.md", {"type": "topic", "status": "closed", "verified": old, "created": old, "due": "2026-12-01"}, "Offsite",
               facts=[("Two records back this", old, "<m1@example.com>"), ("And a second one", old, "<m2@example.com>")])
    write_page(vault, f"{W}/Topics/parked.md", {"type": "topic", "status": "dormant", "verified": old, "created": old, "due": "2026-12-01"}, "Parked",
               facts=[("Two records back this", old, "<m1@example.com>"), ("And a second one", old, "<m2@example.com>")])
    write_page(vault, f"{W}/Topics/no-due.md", {"type": "topic", "status": "active", "verified": old, "created": old}, "No due",
               facts=[("Two records back this", old, "<m1@example.com>"), ("And a second one", old, "<m2@example.com>")])
    # 18: a topic and an org still standing on one record after two months
    write_page(vault, f"{W}/Topics/thin-topic.md", {"type": "topic", "status": "active", "verified": now, "created": _ago(70)}, "Thin topic",
               facts=[("One record only", now, "<m3@example.com>")])
    write_page(vault, f"{W}/Orgs/acme.md", {"type": "org", "status": "active", "verified": now, "created": _ago(70)}, "Acme")
    # not 18: a thin org already closed — there is nothing left to retire
    write_page(vault, f"{W}/Orgs/gone.md", {"type": "org", "status": "closed", "verified": now, "created": _ago(70)}, "Gone")
    # not 18: a person and a decision, however thin and however old
    write_page(vault, f"{W}/People/Jane Doe.md", {"type": "person", "name": "Jane Doe", "email": "jane.doe@example.com",
               "last_contact": "2026-08-22T09:14:00+02:00", "status": "active", "verified": now, "created": _ago(70)}, "Jane Doe")
    write_page(vault, f"{W}/Decisions/new-stack.md", {"type": "decision", "status": "current", "verified": now, "created": _ago(70),
               "decided": "2026-06-01", "by": ["[[Wiki/People/Jane Doe]]"]}, "New stack")
    r = wiki_lint.lint()
    c = r["checks"]
    assert c["17"]["name"] == "close" and [i["page"] for i in c["17"]["items"]] == ["Wiki/Topics/rebuild"]
    assert c["17"]["items"][0]["due"] == "2026-12-01" and c["17"]["items"][0]["days"] == 100
    assert c["18"]["name"] == "thin" and [i["page"] for i in c["18"]["items"]] == ["Wiki/Orgs/acme", "Wiki/Topics/thin-topic"]
    assert {i["sources"] for i in c["18"]["items"]} == {0, 1}
    lines = [o["text"] for o in wiki.review("list")["open"]]
    assert "- [ ] [[Wiki/Topics/rebuild]] — no update in 90 days: close it?" in lines
    assert "- [ ] [[Wiki/Orgs/acme]] — one record after 60 days: merge or retire?" in lines
    assert "- [ ] [[Wiki/Topics/thin-topic]] — one record after 60 days: merge or retire?" in lines
    assert r["counts"]["close"] == 1 and r["counts"]["thin"] == 2
    assert "close 1, thin 2" in wiki.log(page="Wiki")["lines"][-1]  # the Log line carries every count
