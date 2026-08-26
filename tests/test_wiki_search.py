"""administrator_vault.wiki_search: the tokeniser, the four candidate lists,
the priors, the cache, brief(), open items, the query log, and wiki.match()
re-implemented on the engine."""

from __future__ import annotations

import asyncio
import gzip
import json

import pytest

from administrator_vault import store, wiki
from administrator_vault import wiki_search as ws
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
    ws._LIVE.clear()
    yield root
    ws._LIVE.clear()


def write_page(root, path, fm, title, lead="", facts=(), notes="", **sections):
    base = {"type": "topic", "id": wiki.new_page_id(), "aliases": [], "summary": "", "status": "active", "created": "2026-08-01",
            "updated": "2026-08-01T09:00:00+02:00", "verified": "2026-08-20", "sources": 1, "open_items": 0, "flags": [], "created_by": CB, "title": title}
    page = wiki.Page(path=path, fm=dict(base, **fm), title=title, lead=lead, notes=notes)
    page.facts = [wiki.Fact(fid, text, since, list(src)) for fid, text, since, src in facts]
    for name, lines in sections.items():
        page.sections[name] = list(lines)
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(wiki.format_page(page), encoding="utf-8")
    return path


def seed(root):
    """Four pages: two topics, a person, an org."""
    write_page(
        root, f"{W}/Topics/quarterly-numbers.md", {"aliases": ["Q3 budget"], "summary": "The quarterly numbers."},
        "Quarterly numbers", lead="Jane collects the numbers each quarter.",
        facts=[("abcd", "Deadline is 2026-08-29", "2026-08-22", ["<m1@example.com>"]),
               ("efgh", "The sheet lives in Budget_Q3.xlsx", "2026-08-20", ["0400ABC|2026-08-20T13:00:00+02:00", "user"])],
        notes="zebra ostrich, kept in the notes only",
        Open=["- [ ] Send the numbers to Jane", "- [x] Ask for the template"],
        Related=["- [[Wiki/People/Jane Doe]]"],
        Records=["- 2026-08-22 — [[Emails/2026-08-22 Budget Q3]] — Jane asks for the final numbers."],
    )
    write_page(
        root, f"{W}/Topics/budget-rules.md", {"summary": "How budgets are approved."}, "Budget rules",
        lead="How the budget is planned each year.",
        facts=[("ijkl", "Budget approval needs two signatures", "2026-05-01", ["user"])],
    )
    write_page(
        root, f"{W}/People/Jane Doe.md",
        {"type": "person", "name": "Jane Doe", "email": "jane.doe@example.com", "aliases": ["Doe, Jane"], "summary": "Finance lead."},
        "Jane Doe", lead="Jane Doe (jane.doe@example.com) — Example GmbH.",
        facts=[("mnop", "Jane signed the offer on 2026-08-01", "2026-08-01", ["<m2@example.com>"])],
    )
    write_page(
        root, f"{W}/Orgs/example-gmbh.md", {"type": "org", "domains": ["example.com"], "summary": "The customer."},
        "Example GmbH", lead="The customer since 2024.",
    )
    return root


# ------------------------------------------------------------------ tokeniser


def test_tokenize_stems_lightly_and_leaves_numbers_alone():
    assert ws.tokenize("The Q3 budget numbers are due 2026-08-29") == ["q3", "budget", "number", "due", "2026", "08", "29"]
    assert ws.tokenize("Meetings discussed policies") == ["meeting", "discuss", "policy"]
    assert ws.tokenize("access process") == ["access", "process"]  # never strips 'ss'
    assert ws.tokenize("a in of on") == []  # the stop list
    assert ws.tokenize("<m1@example.com>") == ["m1", "example", "com"]


def test_literals_and_regex():
    assert ws.literals('the "net 45" term for <m1@example.com> f:abcd on 2026-08-29') == [
        "net 45", "<m1@example.com>", "f:abcd", "2026-08-29"]
    assert ws.literals("plain words only") == []
    assert ws.regex_of("/net \\d+/").pattern == "net \\d+"
    assert ws.regex_of("re:net.4") is not None
    assert ws.regex_of("Re: the budget") is None  # a subject prefix is not a regex


# ------------------------------------------------------------------ ranking


def test_alias_hit_beats_word_overlap(vault):
    seed(vault)
    hits = ws.search("Q3 budget")
    assert hits[0]["page"] == "Wiki/Topics/quarterly-numbers"
    assert "Wiki/Topics/budget-rules" in [h["page"] for h in hits]
    assert [h["page"] for h in hits].index("Wiki/Topics/budget-rules") > 0


def test_ids_and_dates_are_always_found(vault):
    seed(vault)
    by_src = ws.search("<m1@example.com>")
    assert any(h["fact_id"] == "abcd" and "exact" in h["why"] for h in by_src)
    by_id = ws.search("f:mnop")
    assert [(h["page"], h["fact_id"]) for h in by_id] == [("Wiki/People/Jane Doe", "mnop")]
    by_date = ws.search("2026-08-29")
    assert by_date[0]["fact_id"] == "abcd" and "exact" in by_date[0]["why"]
    by_regex = ws.search("/signed|signature/")
    assert {h["fact_id"] for h in by_regex} == {"ijkl", "mnop"}


def test_a_misspelled_name_still_finds_the_person(vault):
    seed(vault)
    hits = ws.search("Jane Do")
    assert hits[0]["page"] == "Wiki/People/Jane Doe" and "name" in hits[0]["why"]
    assert ws.search("Exampel GmbH")[0]["page"] == "Wiki/Orgs/example-gmbh"


def test_superseded_text_is_hidden_by_default_and_ranked_below(vault):
    seed(vault)
    wiki.apply(f"{W}/Topics/quarterly-numbers.md", [{"op": "supersede", "id": "abcd", "text": "Deadline is 2026-09-05", "since": "2026-08-25"}])
    assert not [h for h in ws.search("deadline") if h["superseded"]]
    both = ws.search("deadline", include_superseded=True)
    old = [i for i, h in enumerate(both) if h["superseded"]]
    new = [i for i, h in enumerate(both) if h["text"] == "Deadline is 2026-09-05"]
    assert old and new and new[0] < old[0]
    assert both[old[0]]["text"] == "Deadline is 2026-08-29" and both[old[0]]["fact_id"] is None


def test_kinds_and_since_filters(vault):
    seed(vault)
    assert {h["kind"] for h in ws.search("jane", kinds=["person"])} == {"person"}
    assert {h["kind"] for h in ws.search("budget numbers", kinds=["topic", "org"])} <= {"topic", "org"}
    late = ws.search("budget signatures numbers", since="2026-08-01")
    assert late and all(h["since"] >= "2026-08-01" for h in late)
    assert "ijkl" not in {h["fact_id"] for h in late}  # since 2026-05-01


def test_notes_are_never_indexed(vault):
    seed(vault)
    assert ws.search("zebra ostrich") == []
    assert ws.search("/ostrich/") == []


def test_at_most_three_facts_per_page_and_deterministic_order(vault):
    write_page(
        vault, f"{W}/Topics/many.md", {}, "Many facts", lead="Facts about the budget.",
        facts=[(fid, f"Budget note {n} of the year", "2026-08-1%d" % n, ["user"]) for n, fid in enumerate("aaaa bbbb cccc dddd eeee".split(), start=1)],
    )
    first = ws.search("budget note")
    assert len([h for h in first if h["fact_id"]]) == 3
    assert [(h["page"], h["fact_id"], h["score"]) for h in ws.search("budget note")] == [(h["page"], h["fact_id"], h["score"]) for h in first]
    ws._LIVE.clear()
    (vault / ws.SEARCH_CACHE).unlink()
    rebuilt = ws.search("budget note")
    assert [(h["page"], h["fact_id"], h["score"]) for h in rebuilt] == [(h["page"], h["fact_id"], h["score"]) for h in first]


def test_priors_demote_a_closed_page(vault):
    write_page(vault, f"{W}/Topics/live.md", {"verified": "2026-08-20"}, "Venue live", lead="The venue for the offsite.",
               facts=[("aaaa", "The offsite venue is the old mill", "2026-08-20", ["<a@b>", "user"])])
    write_page(vault, f"{W}/Topics/gone.md", {"status": "closed", "verified": "2024-01-05"}, "Venue gone", lead="The venue for the offsite.",
               facts=[("bbbb", "The offsite venue is the old mill", "2024-01-05", ["user"])])
    hits = ws.search("offsite venue")
    assert hits[0]["page"] == "Wiki/Topics/live"
    assert [h["page"] for h in hits].index("Wiki/Topics/gone") > 0


# ------------------------------------------------------------------ the cache


def test_only_the_changed_file_is_read_again(vault):
    seed(vault)
    ws.search("budget")
    assert (vault / ws.SEARCH_CACHE).is_file()
    ix = ws.Index.load(vault)
    assert ix.reused is True and ix.reparsed == [] and ix.hashed == []
    wiki.apply(f"{W}/Topics/budget-rules.md", [{"op": "add", "text": "Budgets are frozen in December", "since": "2026-08-24"}])
    ix = ws.Index.load(vault)
    assert ix.reparsed == [f"{W}/Topics/budget-rules.md"] and ix.hashed == ix.reparsed and ix.rebuilt is False
    assert "frozen" in {t for d in ix.docs for t in d["tf"].get("fact", {})}
    # a hand edit in the editor is picked up the same way
    p = vault / W / "People" / "Jane Doe.md"
    p.write_text(p.read_text(encoding="utf-8").replace("Finance lead.", "Finance lead and keeper of the ledger."), encoding="utf-8")
    ix = ws.Index.load(vault)
    assert ix.reparsed == [f"{W}/People/Jane Doe.md"]
    assert ws.search("who keeps the ledger")[0]["page"] == "Wiki/People/Jane Doe"


def test_a_touched_file_is_hashed_but_not_read_again(vault):
    seed(vault)
    ws.search("budget")
    p = vault / W / "Orgs" / "example-gmbh.md"
    p.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")  # same text, new stat
    ws._LIVE.clear()
    ix = ws.Index.load(vault)
    assert f"{W}/Orgs/example-gmbh.md" in ix.hashed and ix.reparsed == []


def test_a_new_schema_rebuilds_the_cache(vault, monkeypatch):
    seed(vault)
    ws.search("budget")
    with gzip.open(vault / ws.SEARCH_CACHE, "rt", encoding="utf-8") as fh:
        assert json.load(fh)["schema"] == ws.SCHEMA_VERSION
    ws._LIVE.clear()
    monkeypatch.setattr(ws, "SCHEMA_VERSION", ws.SCHEMA_VERSION + 1)
    ix = ws.Index.load(vault)
    assert ix.rebuilt is True and len(ix.reparsed) == 4
    ws._LIVE.clear()
    (vault / ws.SEARCH_CACHE).write_bytes(b"not gzip at all")
    assert ws.Index.load(vault).rebuilt is True  # a broken cache is only a cache
    assert ws.search("budget")


# ------------------------------------------------------------------ brief and open items


def test_brief_stitches_the_top_pages_and_keeps_the_cap(vault):
    seed(vault)
    wiki.apply(f"{W}/People/Jane Doe.md", [{"op": "add", "text": "Jane agreed the layout on 2026-08-18", "since": "2026-08-18", "src": "<m3@example.com>"}])
    out = ws.brief("what is the deadline for the quarterly numbers")
    assert out["chars"] == len(out["text"]) and out["chars"] <= 1500
    assert out["text"].startswith("[[Wiki/Topics/quarterly-numbers|Quarterly numbers]] · topic · active · ")
    assert "Jane collects the numbers each quarter." in out["text"]
    assert "- Deadline is 2026-08-29 (f:abcd, 2026-08-22)" in out["text"]
    assert "- [ ] Send the numbers to Jane" in out["text"] and "- [x]" not in out["text"]
    ids = [(f["page"], f["id"]) for f in out["facts"]]
    assert len(ids) == len(set(ids)) and ("Wiki/Topics/quarterly-numbers", "abcd") in ids
    assert [p["page"] for p in out["pages"]][0] == "Wiki/Topics/quarterly-numbers"
    assert all(p["page"] in out["text"] for p in out["pages"])
    small = ws.brief("what is the deadline for the quarterly numbers", max_chars=200)
    assert small["chars"] <= 200 and small["pages"] and len(small["facts"]) <= len(out["facts"])


def test_open_items_of_a_page_and_of_the_matching_pages(vault):
    seed(vault)
    one = ws.open_items(page="Wiki/Topics/quarterly-numbers")
    assert one == [{"page": "Wiki/Topics/quarterly-numbers", "title": "Quarterly numbers",
                    "text": "Send the numbers to Jane", "record": "", "line": "- [ ] Send the numbers to Jane"}]
    assert ws.open_items("quarterly numbers deadline") == one
    assert ws.open_items() == one
    assert ws.open_items(page="Wiki/Orgs/example-gmbh") == []


# ------------------------------------------------------------------ the query log


def test_every_query_is_logged_and_the_log_is_trimmed(vault):
    seed(vault)
    ws.search("budget rules")
    ws.brief("who is jane")
    rows = ws.read_query_log(vault)
    assert [r[1] for r in rows] == ["budget rules", "who is jane"]
    assert rows[0][2] > 0 and rows[0][3].startswith("Wiki/")
    assert ws.search("nothing at all about anything")[-0:] == []
    assert ws.read_query_log(vault)[-1][2:] == (0, "-")
    p = vault / ws.QUERY_LOG
    p.write_text("\n".join(f"2026-08-24T09:00:00+02:00\told {i}\t1\tWiki/Topics/x" for i in range(2001)) + "\n", encoding="utf-8")
    ws.search("budget")
    rows = ws.read_query_log(vault)
    assert len(rows) == ws.QUERY_LOG_KEEP and rows[-1][1] == "budget"


def test_unanswered_is_empty_for_now(vault):
    assert ws.unanswered(vault) == []


# ------------------------------------------------------------------ match on the engine


def test_match_keeps_its_scores_why_and_order(vault):
    seed(vault)
    m = wiki.match("Re: Q3 budget - final numbers", ["jane.doe@example.com"], ["example.com"])
    assert [(p["path"], p["score"], p["why"]) for p in m["pages"]] == [
        (f"{W}/Topics/quarterly-numbers.md", 4, ["alias"]),
        (f"{W}/People/Jane Doe.md", 3, ["address"]),
        (f"{W}/Orgs/example-gmbh.md", 1, ["domain"]),
    ]
    words = wiki.match("how are budgets planned for the year")
    assert [(p["path"], p["score"], p["why"]) for p in words["pages"]] == [(f"{W}/Topics/budget-rules.md", 2, ["words"])]
    assert wiki.match("nothing here")["pages"] == []
    assert wiki.match("Jane Doe")["pages"][0]["path"] == f"{W}/People/Jane Doe.md"


def test_prep_pages_takes_its_topics_from_the_engine(vault):
    seed(vault)
    out = wiki.prep_pages(vault, [f"{W}/People/Jane Doe.md"], "Q3 budget review")
    assert [p["path"] for p in out] == [f"{W}/People/Jane Doe.md", f"{W}/Topics/quarterly-numbers.md"]
    assert out[1]["open"][0] == "- [ ] Send the numbers to Jane" and out[1]["facts"][0]["id"] == "abcd"


# ------------------------------------------------------------------ the tool


def test_server_search_tool_round_trip(vault):
    seed(vault)
    server = build_server()

    def call(name, args):
        out = asyncio.run(server.call_tool(name, args))
        return json.loads(out[0].text if isinstance(out, list) else out[0][0].text)

    hits = call("vault_wiki_search", {"query": "when are the quarterly numbers due"})
    assert hits[0]["page"] == "Wiki/Topics/quarterly-numbers"
    assert set(hits[0]) == {"page", "kind", "title", "fact_id", "text", "since", "src", "score", "why", "superseded", "streams", "confirmed"}
    one = call("vault_wiki_search", {"query": "numbers", "page": "Wiki/People/Jane Doe"})
    assert {h["page"] for h in one} == {"Wiki/People/Jane Doe"}
    brief = call("vault_wiki_search", {"query": "quarterly numbers", "brief": True, "max_chars": 400})
    assert set(brief) == {"text", "pages", "facts", "chars"} and brief["chars"] <= 400
    items = call("vault_wiki_search", {"query": "", "open_items": True})
    assert items == [{"page": "Wiki/Topics/quarterly-numbers", "title": "Quarterly numbers",
                      "text": "Send the numbers to Jane", "record": "", "line": "- [ ] Send the numbers to Jane"}]
    assert call("vault_wiki_search", {"query": "budget", "kinds": ["person"], "limit": 3})[0]["kind"] == "person"
