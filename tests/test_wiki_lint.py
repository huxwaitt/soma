"""administrator_vault.wiki_lint: the fifteen checks on a seeded vault, fix=true, merge with redirect."""

from __future__ import annotations

import asyncio
import json

import pytest

from administrator_vault import frontmatter as fmt
from administrator_vault import store, wiki, wiki_lint, workflows
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
    text = text_of(vault, raw).replace("## Facts\n\n## People\n", "## People\n\n## Facts\n").replace("## History\n", "## Random\n\nstuff\n\n## History\n")
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
    assert messy["extra"] == ["foo"] and messy["code_owned_edited"] == ["sources"] and messy["missing"] == []
    # 5 sections
    assert c["5"]["items"] == [{"page": "Wiki/Topics/messy", "unknown": ["Random"], "duplicate": [], "out_of_order": True}]
    # 6 oversized
    assert c["6"]["items"][0]["page"] == "Wiki/People/Big Person" and c["6"]["items"][0]["chars"] > 4000 and "smaller op set" in c["6"]["remedies"]
    # 7 stale
    assert [s["page"] for s in c["7"]["items"]] == ["Wiki/Topics/stale-thing"] and c["7"]["items"][0]["set_dormant"] is False
    # 8 due past
    assert c["8"]["items"] == [{"page": "Wiki/Topics/stale-thing", "due": "2020-02-01"}]
    # 9 open item done in the record
    assert c["9"]["items"] == [{"page": "Wiki/Topics/q3-budget", "text": "Send Q3 numbers to Jane", "record": "Emails/2026-08-22 Budget Q3"}]
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
    # flags were written (both modes), index regenerated, cache + log line present
    assert set(r["flagged"]) == {"Wiki/Topics/stale-thing", "Wiki/Topics/long-history", "Wiki/People/Big Person", "Wiki/Topics/q3-budget", "Wiki/Topics/budget-q3", "Wiki/People/Jane Doe", "Wiki/People/J Doe"}
    assert fm_of(vault, f"{W}/Topics/stale-thing.md")["flags"] == ["orphan", "stale"]
    assert fm_of(vault, f"{W}/People/Big Person.md")["flags"] == ["oversized"]
    assert fm_of(vault, f"{W}/Topics/q3-budget.md")["flags"] == ["possible-duplicate"]
    assert "Wiki/Topics/messy" not in r["flagged"] and fm_of(vault, f"{W}/Topics/messy.md")["sources"] == 99  # report only without fix
    assert "- [[Wiki/Topics/stale-thing|Stale thing]]" in text_of(vault, f"{W}/Index.md")
    assert r["cache"] == f"{W}/_cache/lint-{r['date']}.json" and json.loads(text_of(vault, r["cache"]))["counts"] == r["counts"]
    assert wiki.log(page="Wiki")["lines"][-1].endswith("lint | Wiki | - | 8 pages, 7 flagged, 3 review lines, 7 written")
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
    # 4: code-owned keys recomputed, the extra key is only reported
    fm = fm_of(vault, f"{W}/Topics/messy.md")
    assert fm["sources"] == 0 and fm["foo"] == "bar"
    # 5: section order fixed, unknown section kept and reported
    text = text_of(vault, f"{W}/Topics/messy.md")
    assert text.index("## Facts") < text.index("## People") and "## Random" in text and c["5"]["items"][0]["unknown"] == ["Random"]
    # 7: stale topic set to dormant and logged; stale people are not
    assert fm_of(vault, f"{W}/Topics/stale-thing.md")["status"] == "dormant" and c["7"]["items"][0]["set_dormant"] is True
    assert any("stale" in l and "dormant" in l for l in wiki.log(page="stale-thing")["lines"])
    # 9: the open item moved to History
    text = text_of(vault, f"{W}/Topics/q3-budget.md")
    assert "- [ ] Send Q3" not in text and '— done "Send Q3 numbers to Jane — [[Emails/2026-08-22 Budget Q3]]"' in text and fm_of(vault, f"{W}/Topics/q3-budget.md")["open_items"] == 0
    # 13: History rotated, Log rotated
    hist = text_of(vault, f"{W}/Topics/long-history.md").split("## History\n\n")[1].split("\n## Notes")[0].strip().split("\n")
    assert len(hist) == 40 and hist[0].startswith("- older history: [[Wiki/_history/Topics/long-history]]")
    assert (vault / W / "_history" / "Log-2026.md").is_file() and wiki.log(limit=500)["total"] < 10
    # 1: index regenerated with every page
    assert c["1"]["fixed"] is True and text_of(vault, f"{W}/Index.md").count("- [[Wiki/") == 8
    # Review: duplicates + stale lines
    rv = wiki.review("list")
    assert len(rv["open"]) == 3 and any("merge [[Wiki/Topics/q3-budget]] into [[Wiki/Topics/budget-q3]]?" in o["text"] for o in rv["open"])


def test_weekly_facts_has_wiki_counts(vault):
    seed(vault)
    wiki_lint.lint()
    w = workflows.weekly_facts("2026-W34", today="2026-08-22")["wiki"]
    assert w == {"review_open": 3, "stale": 1, "uningested": 1, "candidates": 1}


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
    assert r["fix"] is True and set(r["checks"]) == {str(i) for i in range(1, 16)}
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
