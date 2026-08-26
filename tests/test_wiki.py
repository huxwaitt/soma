"""administrator_vault.wiki: page contract, fact ops and refusals, caps,
index / log / review generation, lock, record two-way link, candidates."""

from __future__ import annotations

import asyncio
import json
import os
import time

import pytest

from administrator_vault import frontmatter as fmt
from administrator_vault import store, wiki, workflows
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


def email(n=1, subject="Budget Q3", received="2026-08-22T09:14:00+02:00", summary="Jane asks for final numbers by Friday.", imid=None):
    fm = {
        "type": "email", "source": "outlook", "internet_message_id": imid or f"<m{n}@example.com>", "entry_id": f"00A{n}",
        "conversation_id": "C1", "subject": subject, "from": "jane.doe@example.com", "from_name": "Jane Doe",
        "from_link": "[[Wiki/People/Jane Doe]]", "to": [], "cc": [], "received": received, "status": "todo", "created_by": CB,
    }
    return store.write("email", fm, f"# {subject}\n\n## Summary\n\n{summary}\n\n## Body\n\ntext")["path"]


def meeting(start="2026-08-20T13:00:00+02:00", subject="Budget review with Jane"):
    key = f"0400ABC|{start}"
    fm = {
        "type": "meeting", "source": "outlook", "global_id": "0400ABC", "occurrence_key": key, "subject": subject, "start": start,
        "end": start.replace("13:00", "14:00"), "location": "Room 4", "organizer": "jane.doe@example.com", "organizer_link": "[[Wiki/People/Jane Doe]]",
        "attendees": ["jane.doe@example.com"], "attendee_links": ["[[Wiki/People/Jane Doe]]"], "is_recurring": False, "status": "held", "created_by": CB,
    }
    return store.write("meeting", fm, f"# {subject}\n\n## Summary\n\nAgreed the sheet layout.\n")["path"], key


def topic(vault, title="Q3 budget", **kw):
    args = dict(type="topic", title=title, aliases=["Budget Q3"], lead="Jane collects final Q3 numbers by 2026-08-29.", summary="Final Q3 numbers due 2026-08-29.")
    args.update(kw)
    res = wiki.create(**args)
    assert res["created"], res
    return res["path"]


# ------------------------------------------------------------------ page model


def test_parse_and_format_round_trip_keeps_notes_and_src_with_pipe():
    text = (
        "---\ntype: topic\ntitle: Q3 budget\naliases: []\nsummary: \"\"\nstatus: active\ncreated: \"2026-08-20\"\ncreated_by: x\n---\n\n"
        "# Q3 budget\n\nLead text.\n\n## Facts\n\n"
        '- Numbers go into Budget_Q3.xlsx <!-- f:c3mm since:2026-08-20 src:"0400ABC|2026-08-20T13:00:00+02:00","<a@b>" -->\n'
        "- A hand-written bullet\n\n## People\n\n- [[Wiki/People/Jane Doe]] — owns the forecast\n\n## Notes\n\nMy own text | with pipes\n\n## My heading\n\nmore\n"
    )
    page = wiki.parse_page(text, f"{W}/Topics/q3-budget.md")
    assert page.title == "Q3 budget" and page.lead == "Lead text."
    assert page.facts[0].id == "c3mm" and page.facts[0].src == ["0400ABC|2026-08-20T13:00:00+02:00", "<a@b>"]
    assert page.facts[1].src == ["user"] and len(page.facts[1].id) == 4
    assert page.notes == "My own text | with pipes\n\n## My heading\n\nmore"
    out = wiki.format_page(page)
    assert '<!-- f:c3mm since:2026-08-20 src:"0400ABC|2026-08-20T13:00:00+02:00","<a@b>" -->' in out
    assert out.index("## Facts") < out.index("## People") < out.index("## Open") < out.index("## Records") < out.index("## Related") < out.index("## History") < out.index("## Notes")
    assert out.endswith("## Notes\n\nMy own text | with pipes\n\n## My heading\n\nmore\n")
    again = wiki.parse_page(out)
    assert [f.src for f in again.facts] == [["0400ABC|2026-08-20T13:00:00+02:00", "<a@b>"], ["user"]]
    assert again.notes == page.notes


def test_per_type_sections():
    for t, names in (("person", ("Facts", "Topics", "Open", "Records")), ("org", ("Facts", "Contacts", "Topics")), ("howto", ("Steps", "Facts")), ("me", ("Facts", "Related", "History"))):
        page = wiki.Page(path="x", fm={"type": t}, title="T")
        out = wiki.format_page(page)
        heads = [l[3:] for l in out.split("\n") if l.startswith("## ")]
        assert heads == list(wiki.SECTIONS[t]), t
        assert all(n in heads for n in names)


# ------------------------------------------------------------------ create


def test_create_writes_contract_and_refuses_duplicates_and_code_owned(vault):
    path = topic(vault, facts=[{"text": "Deadline for the user's numbers is 2026-08-29", "since": "2026-08-22", "src": "<m1@example.com>"}])
    assert path == f"{W}/Topics/q3-budget.md"
    fm = fm_of(vault, path)
    assert fm["type"] == "topic" and fm["status"] == "active" and fm["created_by"] == CB
    assert fm["verified"] == "2026-08-22" and fm["sources"] == 1 and fm["open_items"] == 0 and fm["flags"] == []
    assert list(fm)[:6] == ["type", "id", "title", "aliases", "summary", "status"]
    assert len(fm["id"]) == 26 and set(fm["id"]) <= set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
    text = text_of(vault, path)
    assert "# Q3 budget\n\nJane collects final Q3 numbers by 2026-08-29.\n\n## Facts\n\n- Deadline for the user's numbers is 2026-08-29 <!-- f:" in text
    assert "- 2026-" in text and "— page created (user)" in text
    # duplicate title or alias -> the match, no file
    dup = wiki.create("topic", "Budget Q3")
    assert dup["created"] is False and dup["reason"] == "exists" and dup["path"] == path and "[[Wiki/Topics/q3-budget|Q3 budget]]" in dup["match"]
    assert wiki.create("topic", "Other", aliases=["q3 BUDGET"])["created"] is False
    assert len(list((vault / W / "Topics").glob("*.md"))) == 1
    with pytest.raises(store.VaultError):
        wiki.create("topic", "Another", extra={"verified": "2020-01-01"})
    with pytest.raises(store.VaultError):
        wiki.create("topic", "Budget 2026-09 plan")
    with pytest.raises(store.VaultError):
        wiki.create("nope", "x")
    # index and log updated
    idx = text_of(vault, f"{W}/Index.md")
    assert "## Topics (1)" in idx and "- [[Wiki/Topics/q3-budget|Q3 budget]] · active · 2026-08-22 — Final Q3 numbers due 2026-08-29." in idx
    assert "create | Wiki/Topics/q3-budget | user | topic, facts 1" in text_of(vault, f"{W}/Log.md")
    # person by email, me page, slugs
    p = wiki.create("person", "Jane Doe", extra={"email": "jane.doe@example.com"})["path"]
    assert p == f"{W}/People/Jane Doe.md" and fm_of(vault, p)["name"] == "Jane Doe"
    assert wiki.create("person", "J. Doe", extra={"email": "JANE.DOE@example.com"})["created"] is False
    assert wiki.create("me", "Me", lead="I run the team.")["path"] == f"{W}/Me.md"
    assert wiki.create("howto", "Submit an expense claim: Ünïcode")["path"] == f"{W}/Howto/submit-an-expense-claim-unicode.md"


# ------------------------------------------------------------------ ops via apply


def test_every_fact_op(vault):
    path = topic(vault)
    r = wiki.apply(path, [{"op": "add", "text": "Forecast closes 2026-09-02", "since": "2026-08-22", "src": "<m1@example.com>"}])
    fid = r["applied"][0]["id"]
    assert r["written"] and r["refused"] == [] and len(fid) == 4
    # duplicate text (case / whitespace) -> confirm
    r = wiki.apply(path, [{"op": "add", "text": "forecast  closes 2026-09-02.", "since": "2026-08-23", "src": "<m2@example.com>"}])
    assert r["applied"][0]["result"] == "confirm" and r["applied"][0]["id"] == fid
    facts = wiki.read(path)["facts"]
    assert facts == [{"id": fid, "text": "Forecast closes 2026-09-02", "since": "2026-08-22", "src": ["<m2@example.com>", "<m1@example.com>"]}]
    assert fm_of(vault, path)["verified"] == wiki._today() and fm_of(vault, path)["sources"] == 2  # confirm stamps verified with today
    # update keeps id and since, extends src (capped at 3, newest first)
    r = wiki.apply(path, [{"op": "update", "id": fid, "text": "Forecast closes 2026-09-02 at noon", "src": "<m3@example.com>"}])
    f = wiki.read(path)["facts"][0]
    assert f["id"] == fid and f["since"] == "2026-08-22" and f["src"] == ["<m3@example.com>", "<m2@example.com>", "<m1@example.com>"]
    wiki.apply(path, [{"op": "confirm", "id": fid, "src": "<m4@example.com>"}])
    assert wiki.read(path)["facts"][0]["src"] == ["<m4@example.com>", "<m3@example.com>", "<m2@example.com>"]
    assert 'updated f:' + fid + ' "Forecast closes 2026-09-02" → "Forecast closes 2026-09-02 at noon" (user)' in text_of(vault, path)
    # supersede: new id, old text in History
    r = wiki.apply(path, [{"op": "supersede", "id": fid, "text": "Forecast closes 2026-09-05", "since": "2026-08-25", "src": "<m5@example.com>"}])
    new_id = r["applied"][0]["id"]
    assert new_id != fid and r["applied"][0]["replaced"] == fid
    facts = wiki.read(path)["facts"]
    assert [f["id"] for f in facts] == [new_id] and facts[0]["since"] == "2026-08-25"
    assert 'superseded "Forecast closes 2026-09-02 at noon" → "Forecast closes 2026-09-05" (user)' in text_of(vault, path)
    # retire
    r = wiki.apply(path, [{"op": "retire", "id": new_id, "src": "<m6@example.com>", "reason": "forecast cancelled"}])
    assert r["applied"] == [{"op": "retire", "id": new_id}] and wiki.read(path)["facts"] == []
    assert 'retired "Forecast closes 2026-09-05" — forecast cancelled (user)' in text_of(vault, path)
    # contest: flag + Review, facts unchanged
    fid2 = wiki.apply(path, [{"op": "add", "text": "Sheet tab is Sales", "since": "2026-08-22", "src": "<m1@example.com>"}])["applied"][0]["id"]
    r = wiki.apply(path, [{"op": "contest", "id": fid2, "text": "Sheet tab is Marketing", "src": "<m7@example.com>"}])
    assert r["applied"][0]["result"] == "review" and fm_of(vault, path)["flags"] == ["contradiction"]
    assert wiki.read(path)["facts"][0]["text"] == "Sheet tab is Sales"
    rv = wiki.review("list")
    assert len(rv["open"]) == 1 and rv["open"][0]["text"] == f'- [ ] [[Wiki/Topics/q3-budget]] — f:{fid2} "Sheet tab is Sales" vs "Sheet tab is Marketing" ("<m1@example.com>" / user)'


def test_fact_refusals(vault):
    path = topic(vault)
    fid = wiki.apply(path, [{"op": "add", "text": "Deadline is 2026-08-29", "since": "2026-08-22", "src": "<m1@example.com>"}])["applied"][0]["id"]
    ops = [
        {"op": "supersede", "id": fid, "text": "Deadline is 2026-08-27", "since": "2026-08-20", "src": "<old@example.com>"},
        {"op": "update", "id": "zzzz", "text": "x", "src": "s"},
        {"op": "add", "text": " ".join(["word"] * 26), "since": "2026-08-22", "src": "s"},
        {"op": "add", "text": "has <!-- a comment -->", "since": "2026-08-22", "src": "s"},
        {"op": "add", "text": "bad date", "since": "yesterday", "src": "s"},
        {"op": "add", "text": "bad src", "since": "2026-08-22", "src": "a-->b"},
        {"op": "retire", "id": fid, "src": "s", "reason": ""},
        {"op": "frobnicate"},
        "not an object",
    ]
    r = wiki.apply(path, ops)
    reasons = [x["reason"] for x in r["refused"]]
    assert reasons == ["older-than-current", "unknown-id", "fact-too-long", "bad-text", "bad-date", "bad-src", "missing-text", "unknown-op", "not-an-object"]
    assert r["refused"][0]["current_since"] == "2026-08-22" and r["refused"][1]["known"] == [fid]
    assert r["applied"] == [] and r["written"] is True  # nothing applied, but the page write itself went through
    assert wiki.read(path)["facts"][0]["text"] == "Deadline is 2026-08-29"
    open_items = [o["text"] for o in wiki.review("list")["open"]]
    assert open_items == [f'- [ ] [[Wiki/Topics/q3-budget]] — f:{fid} "Deadline is 2026-08-29" (since 2026-08-22) vs older "Deadline is 2026-08-27" (since 2026-08-20) (user)']
    # same-day supersede is allowed
    assert wiki.apply(path, [{"op": "supersede", "id": fid, "text": "Deadline is 2026-08-30", "since": "2026-08-22", "src": "s"}])["refused"] == []
    # facts cap: 25 bullets
    for i in range(24):
        assert wiki.apply(path, [{"op": "add", "text": f"Fact number {i}", "since": "2026-08-22", "src": "s"}])["refused"] == []
    r = wiki.apply(path, [{"op": "add", "text": "One too many", "since": "2026-08-22", "src": "s"}])
    assert r["refused"][0]["reason"] == "facts-cap" and r["refused"][0]["facts"] == 25


def test_user_pin_protects_facts_from_record_sources(vault):
    path = topic(vault)
    fid = wiki.apply(path, [{"op": "add", "text": "Budget owner is the user", "since": "2026-08-22"}])["applied"][0]["id"]
    assert wiki.read(path)["facts"][0]["src"] == ["user"]
    rec = email(1)
    r = wiki.ingest(rec, [{"path": path, "ops": [
        {"op": "supersede", "id": fid, "text": "Budget owner is Jane", "since": "2026-08-22"},
        {"op": "retire", "id": fid, "reason": "gone"},
        {"op": "update", "id": fid, "text": "Budget owner is the user, since 2025"},
        {"op": "confirm", "id": fid},
    ]}])
    res = r["pages"][0]
    assert [x["reason"] for x in res["refused"]] == ["user-pin", "user-pin", "user-pin"]
    assert res["applied"] == [{"op": "confirm", "id": fid}]
    assert wiki.read(path)["facts"][0] == {"id": fid, "text": "Budget owner is the user", "since": "2026-08-22", "src": ["<m1@example.com>", "user"]}
    assert len(wiki.review("list")["open"]) == 3
    # the user may still change it
    assert wiki.apply(path, [{"op": "supersede", "id": fid, "text": "Budget owner is Jane", "since": "2026-08-22"}])["refused"] == []


def test_page_ops(vault):
    path = topic(vault, lead="")
    assert fm_of(vault, path)["status"] == "draft"
    jane = wiki.create("person", "Jane Doe", extra={"email": "jane.doe@example.com"})["path"]
    org = wiki.create("org", "Example GmbH", extra={"domains": ["example.com"]})["path"]
    howto = wiki.create("howto", "Submit expense claim")["path"]
    r = wiki.apply(path, [
        {"op": "lead", "text": "Jane collects the numbers. The user owes the sales figures."},
        {"op": "summary", "text": "Numbers due 2026-08-29."},
        {"op": "title", "text": "Q3 budget round"},
        {"op": "alias", "text": "Q3 forecast"},
        {"op": "alias", "text": "q3 FORECAST"},
        {"op": "role", "page": "[[Wiki/People/Jane Doe]]", "role": "owns the forecast"},
        {"op": "related", "page": "Wiki/Orgs/example-gmbh"},
        {"op": "open", "text": "Send Q3 numbers to Jane"},
        {"op": "due", "value": "2026-08-29"},
        {"op": "owner", "value": "[[Wiki/People/Jane Doe]]"},
        {"op": "org", "value": "Wiki/Orgs/example-gmbh"},
        {"op": "status", "value": "dormant"},
    ])
    assert r["refused"] == [], r["refused"]
    fm = fm_of(vault, path)
    assert fm["status"] == "dormant" and fm["summary"] == "Numbers due 2026-08-29." and fm["title"] == "Q3 budget round"
    assert fm["aliases"] == ["Budget Q3", "Q3 budget", "Q3 forecast"] and fm["due"] == "2026-08-29"
    assert fm["owner"] == "[[Wiki/People/Jane Doe]]" and fm["org"] == "[[Wiki/Orgs/example-gmbh]]" and fm["open_items"] == 1
    text = text_of(vault, path)
    assert "# Q3 budget round\n\nJane collects the numbers. The user owes the sales figures.\n" in text
    assert "## People\n\n- [[Wiki/People/Jane Doe]] — owns the forecast\n" in text
    assert "## Open\n\n- [ ] Send Q3 numbers to Jane\n" in text
    assert "## Related\n\n- [[Wiki/Orgs/example-gmbh]]\n" in text
    # symmetric: the person lists the topic with the role, the org links back
    assert "## Topics\n\n- [[Wiki/Topics/q3-budget]] — owns the forecast\n" in text_of(vault, jane)
    assert "## Related\n\n- [[Wiki/Topics/q3-budget]]\n" in text_of(vault, org)
    # index shows the new title and the filename is unchanged; a topic with a due is a project
    idx = text_of(vault, f"{W}/Index.md")
    assert "## Projects (1)" in idx and idx.index("## Projects") < idx.index("## People")
    assert "- [[Wiki/Topics/q3-budget|Q3 budget round]] · Jane Doe · 2026-08-29 · dormant — Numbers due 2026-08-29." in idx
    # refusals of page ops
    r = wiki.apply(path, [
        {"op": "lead", "text": " ".join(["w"] * 81)},
        {"op": "lead", "text": "## heading"},
        {"op": "summary", "text": "x" * 161},
        {"op": "title", "text": "one two three four five six seven"},
        {"op": "status", "value": "done"},
        {"op": "role", "page": "Wiki/People/Nobody", "role": "x"},
        {"op": "role", "page": jane, "role": "one two three four five"},
        {"op": "related", "page": path},
        {"op": "open", "text": "Send Q3 numbers to Jane"},
        {"op": "steps", "text": "1. x"},
        {"op": "due", "value": "soon"},
        {"op": "owner", "value": ""},
    ])
    assert [x["reason"] for x in r["refused"]] == [
        "lead-too-long", "bad-text", "summary-too-long", "title-too-long", "bad-status", "no-such-page", "role-too-long",
        "self-link", "duplicate", "wrong-type", "bad-date", "missing-text",
    ]
    # steps on a howto; due on a person is refused
    r = wiki.apply(howto, [{"op": "steps", "text": "1. Open the portal\n2. Upload the receipt\n3. Submit"}, {"op": "due", "value": "2026-09-01"}])
    assert [x["reason"] for x in r["refused"]] == ["wrong-type"]
    assert "## Steps\n\n1. Open the portal\n2. Upload the receipt\n3. Submit\n\n## Facts" in text_of(vault, howto)
    # ticked open items move to History on the next write
    p = vault / path
    p.write_text(text_of(vault, path).replace("- [ ] Send Q3 numbers to Jane", "- [x] Send Q3 numbers to Jane"), encoding="utf-8")
    wiki.apply(path, [])
    text = text_of(vault, path)
    assert "- [x]" not in text and '— done "Send Q3 numbers to Jane"' in text and fm_of(vault, path)["open_items"] == 0
    # a link inside a fact becomes a Related link on both pages
    wiki.apply(path, [{"op": "add", "text": "Steps are in [[Wiki/Howto/submit-expense-claim]]", "since": "2026-08-22"}])
    assert "- [[Wiki/Howto/submit-expense-claim]]" in text_of(vault, path) and "- [[Wiki/Topics/q3-budget]]" in text_of(vault, howto)


# ------------------------------------------------------------------ ingest


def test_ingest_records_history_two_way_link_and_candidates(vault):
    path = topic(vault)
    rec = email(1)
    r = wiki.ingest(rec, [{"path": path, "ops": [
        {"op": "add", "text": "Deadline for the user's numbers is 2026-08-29"},
        {"op": "add", "text": "Forecast closes 2026-09-02", "since": "2026-08-21"},
    ]}], created_by=CB)
    assert r["record"] == "[[Emails/2026-08-22 Budget Q3]]"
    res = r["pages"][0]
    assert res["written"] and len(res["applied"]) == 2 and res["record_added"] is True
    facts = wiki.read(path)["facts"]
    assert facts[0]["since"] == "2026-08-22" and facts[0]["src"] == ["<m1@example.com>"] and facts[1]["since"] == "2026-08-21"
    text = text_of(vault, path)
    assert "## Records\n\n- 2026-08-22 — [[Emails/2026-08-22 Budget Q3]] — Jane asks for final numbers by Friday.\n" in text
    assert fm_of(vault, path)["sources"] == 1  # the fact src and the Records line are the same mail
    # the record points back
    efm = fm_of(vault, rec)
    assert efm["wiki"] == ["[[Wiki/Topics/q3-budget]]"]
    assert "## Body\n\ntext" in text_of(vault, rec)  # body untouched
    # log line
    log = wiki.log()
    assert log["lines"][-1].endswith("ingest | Wiki/Topics/q3-budget | [[Emails/2026-08-22 Budget Q3]] | add 2")
    assert wiki.log(page="q3-budget")["total"] == 2 and wiki.log(page="nope")["total"] == 0
    assert wiki.log(since="2099-01-01")["lines"] == []
    # noop on a new record: Records line + History seen; same record again: nothing
    mpath, key = meeting()
    r = wiki.ingest(mpath, [{"path": path, "ops": []}])
    assert r["pages"][0]["record_added"] is True and r["pages"][0]["history_added"] == 1
    text = text_of(vault, path)
    assert "- 2026-08-22 — [[Emails/2026-08-22 Budget Q3]]" in text and "- 2026-08-20 — [[Meetings/2026-08-20 1300 Budget review with Jane]] — Agreed the sheet layout." in text
    assert text.index("[[Emails/2026-08-22") < text.index("[[Meetings/2026-08-20")  # newest first
    assert "— seen ([[Meetings/2026-08-20 1300 Budget review with Jane]])" in text
    r = wiki.ingest(mpath, [{"path": path, "ops": []}])
    assert r["pages"][0]["record_added"] is False and r["pages"][0]["history_added"] == 0
    assert fm_of(vault, mpath)["wiki"] == ["[[Wiki/Topics/q3-budget]]"]
    # a meeting src carries a pipe and survives
    r = wiki.ingest(mpath, [{"path": path, "ops": [{"op": "add", "text": "Numbers go into the shared sheet"}]}])
    f = next(f for f in wiki.read(path)["facts"] if f["text"] == "Numbers go into the shared sheet")
    assert f["src"] == [key] and f["since"] == "2026-08-20"
    assert f'src:"{key}"' in text_of(vault, path)
    # new page in the same call, ops applied, duplicate title refused
    r = wiki.ingest(rec, [{"new": {"type": "org", "title": "Example GmbH", "domains": ["example.com"]}, "ops": [{"op": "add", "text": "Payment terms are net 45"}]},
                          {"new": {"type": "topic", "title": "Budget Q3"}, "ops": []}])
    assert r["pages"][0]["created"] and r["pages"][0]["path"] == f"{W}/Orgs/example-gmbh.md" and len(r["pages"][0]["applied"]) == 1
    assert r["pages"][1]["created"] is False and r["pages"][1]["reason"] == "exists"
    assert fm_of(vault, rec)["wiki"] == ["[[Wiki/Topics/q3-budget]]", "[[Wiki/Orgs/example-gmbh]]"]
    with pytest.raises(store.VaultError):
        wiki.ingest("Administrator/Follow-ups.md", [])
    with pytest.raises(store.VaultError):
        wiki.ingest(rec, [{"new": {"type": "topic", "title": "X", "sources": 9}}])


def test_candidates_threshold(vault):
    a = email(1, subject="Re: Offsite venue", received="2026-08-20T10:00:00+02:00")
    assert wiki.ingest(a, [])["candidate"] == {"subject": "Offsite venue", "records": ["Emails/2026-08-20 Offsite venue"], "days": 1, "over_threshold": False, "page": None}
    assert wiki.match("Offsite venue")["candidates"] == []
    b = email(2, subject="AW: Offsite venue", received="2026-08-20T15:00:00+02:00")
    assert wiki.ingest(b, [])["candidate"]["over_threshold"] is False  # two records, one day
    c = email(3, subject="Offsite venue", received="2026-08-21T09:00:00+02:00")
    cand = wiki.ingest(c, [])["candidate"]
    assert cand["over_threshold"] is True and cand["days"] == 2 and len(cand["records"]) == 3
    m = wiki.match("anything")
    assert [c["subject"] for c in m["candidates"]] == ["Offsite venue"]
    data = json.loads(text_of(vault, f"{W}/_cache/candidates.json"))
    assert set(data["offsite venue"]["records"]) == {"Emails/2026-08-20 Offsite venue", "Emails/2026-08-20 Offsite venue (2)", "Emails/2026-08-21 Offsite venue"}
    # once the page exists the candidate is gone
    wiki.create("topic", "Offsite venue")
    assert wiki.match("anything")["candidates"] == []


def test_records_capped_at_15_newest(vault):
    path = topic(vault)
    for i in range(17):
        rec = email(i, subject=f"Mail {i}", received=f"2026-07-{i + 1:02d}T09:00:00+02:00", imid=f"<r{i}@example.com>")
        wiki.ingest(rec, [{"path": path, "ops": []}])
    lines = [l for l in text_of(vault, path).split("\n") if l.startswith("- 2026-07-")]
    assert len(lines) == 15 and lines[0].startswith("- 2026-07-17") and lines[-1].startswith("- 2026-07-03")
    assert fm_of(vault, path)["sources"] == 15


# ------------------------------------------------------------------ caps, history rotation


def test_cap_refuses_write_with_measured_sizes(vault):
    path = wiki.create("person", "Big Person", extra={"email": "big@example.com"})["path"]
    ops = [{"op": "add", "text": f"Fact {i} " + "x" * 150, "since": "2026-08-22"} for i in range(24)]
    r = wiki.apply(path, ops)
    assert r["written"] is False and r["applied"] == []
    first = r["refused"][0]
    assert first["reason"] == "cap" and first["max_chars"] == 4000 and first["chars"] > 4000 and first["max_lines"] == 80
    assert "smaller op set" in first["detail"]
    assert wiki.read(path)["facts"] == []  # nothing written
    # a smaller set goes through; a topic allows 120 lines / 6000 chars
    assert wiki.apply(path, ops[:3])["written"] is True
    t = topic(vault)
    r = wiki.apply(t, [{"op": "add", "text": f"Fact {i} " + "x" * 150, "since": "2026-08-22"} for i in range(25)])
    assert r["written"] is True and r["sizes"]["chars"] > 4000 and r["sizes"]["max_chars"] == 6000
    with pytest.raises(store.VaultError):
        wiki.create("org", "Huge", facts=[{"text": f"Fact {i} " + "y" * 150, "since": "2026-08-22"} for i in range(25)])


def test_history_rotation(vault):
    path = topic(vault)
    fid = wiki.apply(path, [{"op": "add", "text": "Deadline is 2026-08-01", "since": "2026-08-01"}])["applied"][0]["id"]
    for i in range(2, 45):
        fid = wiki.apply(path, [{"op": "supersede", "id": fid, "text": f"Deadline is 2026-08-{i:02d}", "since": "2026-08-01"}])["applied"][0]["id"]
    text = text_of(vault, path)
    hist = text.split("## History\n\n")[1].split("\n## Notes")[0].strip().split("\n")
    assert len(hist) == 40 and hist[0] == "- older history: [[Wiki/_history/Topics/q3-budget]]"
    assert hist[-1].endswith('→ "Deadline is 2026-08-44" (user)') and "page created" not in text
    old = text_of(vault, f"{W}/_history/Topics/q3-budget.md")
    assert "page created (user)" in old and '"Deadline is 2026-08-01" → "Deadline is 2026-08-02"' in old
    assert len(wiki.read(path)["facts"]) == 1
    # the pointer line stays single after more writes
    wiki.apply(path, [{"op": "supersede", "id": fid, "text": "Deadline is 2026-09-01", "since": "2026-08-01"}])
    assert text_of(vault, path).count("- older history:") == 1


# ------------------------------------------------------------------ index, match, read


def test_index_sorting_people_line_and_split(vault):
    wiki.create("topic", "Closed thing", lead="x", summary="done")
    wiki.apply(f"{W}/Topics/closed-thing.md", [{"op": "status", "value": "closed"}])
    wiki.create("topic", "Old active", lead="x", facts=[{"text": "a", "since": "2026-01-05"}])
    wiki.create("topic", "New active", lead="x", facts=[{"text": "b", "since": "2026-08-01"}])
    wiki.create("person", "Jane Doe", summary="Finance lead.", extra={"email": "jane@example.com", "org": "[[Wiki/Orgs/example-gmbh]]"})
    idx = text_of(vault, f"{W}/Index.md")
    fm = fmt.split_note(idx)[0]
    assert fm["type"] == "wiki-index" and fm["pages"] == 4
    body = idx.split("# Wiki index\n\n")[1]
    assert body.index("## Topics (3)") < body.index("## People (1)")
    topics = [l for l in body.split("\n") if l.startswith("- [[Wiki/Topics/")]
    assert [l.split("|")[1].split("]]")[0] for l in topics] == ["New active", "Old active", "Closed thing"]
    assert "- [[Wiki/People/Jane Doe]] · example-gmbh · " in body and body.rstrip().endswith("— Finance lead.")
    # a hand edit is overwritten on the next write
    (vault / W / "Index.md").write_text("garbage", encoding="utf-8")
    wiki.apply(f"{W}/Topics/old-active.md", [])
    assert "## Topics (3)" in text_of(vault, f"{W}/Index.md")
    # over 200 lines: per-type indexes plus a short root index
    for i in range(200):  # written directly: 200 create calls would rescan the folder each time
        page = wiki.Page(path=f"{W}/Topics/topic-number-{i}.md", fm={"type": "topic", "status": "active", "created": "2026-08-01", "created_by": CB}, title=f"Topic number {i}", lead="x")
        (vault / page.path).write_text(wiki.format_page(page), encoding="utf-8")
    wiki.apply(f"{W}/Topics/old-active.md", [])
    idx = text_of(vault, f"{W}/Index.md")
    assert idx.count("\n") < 12 and "- [[Wiki/Topics/Index|Topics]] — 203 pages" in idx and "- [[Wiki/People/Index|People]] — 1 pages" in idx
    sub = text_of(vault, f"{W}/Topics/Index.md")
    assert sub.count("- [[Wiki/Topics/") == 203 and fmt.split_note(sub)[0]["type"] == "wiki-index"
    assert store.list_notes("person") and all("Index" not in p["path"] for p in store.list_notes("person"))


def test_match_and_read(vault):
    t = topic(vault, aliases=["Budget Q3", "Q3 forecast"], facts=[{"text": "Deadline is 2026-08-29", "since": "2026-08-22", "src": "<m1@example.com>"}])
    wiki.create("person", "Jane Doe", aliases=["Doe, Jane"], summary="Finance lead.", extra={"email": "jane.doe@example.com"})
    wiki.create("org", "Example GmbH", extra={"domains": ["example.com"]})
    wiki.create("topic", "Office move", lead="x")
    m = wiki.match("Re: Budget Q3 - final numbers", ["jane.doe@example.com"])
    paths = [p["path"] for p in m["pages"]]
    assert paths[:2] == [t, f"{W}/People/Jane Doe.md"] and paths[2] == f"{W}/Orgs/example-gmbh.md"
    assert m["pages"][0]["why"] == ["alias"] and m["pages"][1]["why"] == ["address"] and m["pages"][2]["why"] == ["domain"]
    assert f"{W}/Topics/office-move.md" not in paths
    assert [p["path"] for p in wiki.match("the q3 budget forecast numbers")["pages"]] == [t]  # word overlap
    assert wiki.match("nothing here", limit=1)["pages"] == []
    assert len(wiki.match("Budget Q3", domains=["example.com"], limit=1)["pages"]) == 1
    r = wiki.read("[[Wiki/Topics/q3-budget]]", ["lead", "facts", "history", "notes"])
    assert r["path"] == t and r["lead"].startswith("Jane collects") and r["facts"][0]["text"] == "Deadline is 2026-08-29"
    assert "page created" in r["sections"]["History"] and r["notes"] == ""
    small = wiki.read(t, ["lead", "facts"], max_chars=300)
    assert small.get("facts") == [] or "facts_truncated" in small or len(json.dumps(small)) <= 300
    with pytest.raises(store.VaultError):
        wiki.read("Administrator/Follow-ups.md")
    with pytest.raises(store.VaultError):
        wiki.read("Wiki/Topics/nope")


# ------------------------------------------------------------------ review, lock, init


def test_review_resolve_with_ops(vault):
    path = topic(vault)
    fid = wiki.apply(path, [{"op": "add", "text": "Sheet tab is Sales", "since": "2026-08-22", "src": "<m1@example.com>"}])["applied"][0]["id"]
    wiki.apply(path, [{"op": "contest", "id": fid, "text": "Sheet tab is Marketing", "src": "<m2@example.com>"}])
    assert fm_of(vault, path)["flags"] == ["contradiction"]
    rv = wiki.review("resolve", "1", [{"op": "supersede", "id": fid, "text": "Sheet tab is Marketing", "since": "2026-08-22"}])
    assert rv["page"] == "Wiki/Topics/q3-budget" and rv["applied"]["refused"] == []
    assert wiki.read(path)["facts"][0]["text"] == "Sheet tab is Marketing" and fm_of(vault, path)["flags"] == []
    text = text_of(vault, f"{W}/Review.md")
    assert "## Open\n\n\n## Done\n\n- [x] [[Wiki/Topics/q3-budget]]" in text.replace("\n\n## Done", "\n\n\n## Done", 1) or "- [x] [[Wiki/Topics/q3-budget]]" in text.split("## Done")[1]
    assert "## Open" in text and wiki.review("list") == {"path": f"{W}/Review.md", "open": [], "done": 1}
    with pytest.raises(store.VaultError):
        wiki.review("resolve", "1")
    with pytest.raises(store.VaultError):
        wiki.review("nope")


def test_lock_takeover_and_refusal(vault):
    path = topic(vault)
    lock = vault / W / ".lock"
    lock.write_text(f"99999 {time.time() - 120:.0f} old\n", encoding="utf-8")
    assert wiki.apply(path, [])["written"] is True
    assert not lock.exists()
    lock.write_text(f"99999 {time.time():.0f} fresh\n", encoding="utf-8")
    with pytest.raises(store.VaultError, match="another process"):
        wiki.apply(path, [])
    lock.write_text(f"{os.getpid()} {time.time():.0f} mine\n", encoding="utf-8")  # our own pid: re-entered after a crash
    assert wiki.apply(path, [])["written"] is True
    assert not (vault / path).with_name((vault / path).name + ".tmp").exists()


def test_init_is_safe_to_rerun_and_keeps_wiki_files(vault):
    (vault / W / "Wiki.md").write_text("# my notes", encoding="utf-8")
    (vault / W / "Log.md").write_text("# Wiki log\n\n- [2026-01-01T00:00:00+00:00] x | y | z | w\n", encoding="utf-8")
    res = store.init(created_by=CB, overwrite=True)
    assert not any(p.startswith(W) for p in res["created"])
    assert text_of(vault, f"{W}/Wiki.md") == "# my notes" and wiki.log()["total"] == 1


def test_log_rotation(vault):
    p = vault / W / "Log.md"
    p.write_text("# Wiki log\n\n" + "\n".join(f"- [2026-01-01T00:00:{i % 60:02d}+00:00] apply | Wiki/Topics/x | user | add 1" for i in range(500)) + "\n", encoding="utf-8")
    topic(vault)
    lines = wiki.log(limit=500)["lines"]
    assert len(lines) == 2 and "rotate | Wiki/Log | [[Wiki/_history/Log-2026]] | 500 lines moved" in lines[0] and "create | Wiki/Topics/q3-budget" in lines[1]
    assert text_of(vault, f"{W}/_history/Log-2026.md").count("\n- [") == 500


# ------------------------------------------------------------------ save_email + server


def test_save_email_person_page_follows_contract(vault):
    mail = {
        "entry_id": "00AA", "internet_message_id": "<7f3a9c@example.com>", "conversation_id": "CAE1", "subject": "Re: Budget Q3",
        "from": "Jane Doe", "from_address": "jane.doe@example.com", "recipients": [{"name": "Hux", "address": "hux@example.com", "type": "to"}],
        "received": "2026-08-22T09:14:00+02:00", "attachments": [], "body": "Hi",
    }
    res = workflows.save_email(mail, "Jane asks for the Q3 numbers by Friday.", [], company="Example GmbH")
    assert res["person_path"] == f"{W}/People/Jane Doe.md" and res["person_action"] == "created"
    text = text_of(vault, res["person_path"])
    fm = fmt.split_note(text)[0]
    assert fm["status"] == "draft" and fm["org"] == "Example GmbH" and fm["email"] == "jane.doe@example.com" and fm["last_contact"] == "2026-08-22T09:14:00+02:00"
    assert all(k in fm for k in ("name", "aliases", "created", "updated", "verified", "sources", "open_items", "flags", "created_by"))
    assert fm["created_by"] == "administrator/0.4.0"
    assert "# Jane Doe\n\nJane Doe (jane.doe@example.com) — Example GmbH.\n\n## Facts\n\n## Topics\n\n## Open\n\n## Records\n\n- 2026-08-22 — [[Emails/2026-08-22 Budget Q3]] — Jane asks for the Q3 numbers by Friday.\n\n## Related\n\n## History\n\n- " in text
    assert fm_of(vault, res["path"])["from_link"] == "[[Wiki/People/Jane Doe]]" and fm_of(vault, res["path"])["wiki"] == ["[[Wiki/People/Jane Doe]]"]
    assert "- [[Wiki/People/Jane Doe]] · Example GmbH · " in text_of(vault, f"{W}/Index.md")
    # the wiki then matches the sender and prep_context sees the page
    assert wiki.match("Budget", ["jane.doe@example.com"])["pages"][0]["path"] == res["person_path"]
    ctx = workflows.prep_context("G|2026-08-25T13:00:00+02:00", "", ["jane.doe@example.com"])
    assert ctx["people"][0]["path"] == res["person_path"] and ctx["people"][0]["company"] == "Example GmbH"
    assert ctx["people"][0]["last_emails"] == ["- 2026-08-22 — [[Emails/2026-08-22 Budget Q3]] — Jane asks for the Q3 numbers by Friday."]
    # wiki[]: the person page, plus the topic matched on the subject (lead, open items, facts with ids)
    tp = topic(vault, facts=[{"text": "Deadline is 2026-08-29", "since": "2026-08-22", "src": "<x@example.com>"}])
    wiki.apply(tp, [{"op": "open", "text": "Send numbers to Jane"}])
    ctx = workflows.prep_context("G|2026-08-25T13:00:00+02:00", "", ["jane.doe@example.com"], subject="Budget review Q3")
    assert [w["path"] for w in ctx["wiki"]] == [res["person_path"], tp]
    assert ctx["wiki"][1]["lead"].startswith("Jane collects") and ctx["wiki"][1]["open"] == ["- [ ] Send numbers to Jane"]
    assert ctx["wiki"][1]["facts"][0]["text"] == "Deadline is 2026-08-29" and len(ctx["wiki"][1]["facts"][0]["id"]) == 4
    # second mail: alias merged, last_contact forward, second Records line, index line updated
    mail2 = dict(mail, entry_id="00AB", internet_message_id="<n@example.com>", subject="Offsite", received="2026-08-23T10:00:00+02:00")
    mail2["from"] = "Doe, Jane"
    res2 = workflows.save_email(mail2, "Venue question.", [])
    assert res2["person_action"] == "appended"
    fm = fm_of(vault, res["person_path"])
    assert fm["aliases"] == ["Doe, Jane"] and fm["last_contact"] == "2026-08-23T10:00:00+02:00" and fm["status"] == "draft"
    assert text_of(vault, res["person_path"]).count("[[Emails/") == 2
    assert workflows.weekly_facts("2026-W34", today="2026-08-22")["quiet_people"] == []


def test_server_wiki_tools_round_trip(vault):
    server = build_server()

    def call(name, args):
        out = asyncio.run(server.call_tool(name, args))
        return json.loads(out[0].text if isinstance(out, list) else out[0][0].text)

    c = call("vault_wiki_create", {"type": "topic", "title": "Q3 budget", "lead": "Lead.", "summary": "S.", "facts": [{"text": "Deadline is 2026-08-29", "since": "2026-08-22"}]})
    assert c["created"] and c["path"] == f"{W}/Topics/q3-budget.md"
    r = call("vault_wiki_read", {"path": "Wiki/Topics/q3-budget"})
    fid = r["facts"][0]["id"]
    rec = email(1)
    i = call("vault_wiki_ingest", {"record_path": rec, "pages": [{"path": c["path"], "ops": [{"op": "confirm", "id": fid}]}]})
    assert i["pages"][0]["applied"] == [{"op": "confirm", "id": fid}]
    a = call("vault_wiki_apply", {"path": c["path"], "ops": [{"op": "contest", "id": fid, "text": "Deadline is 2026-08-30"}]})
    assert a["applied"][0]["result"] == "review"
    assert call("vault_wiki_match", {"text": "budget q3 numbers"})["pages"][0]["path"] == c["path"]
    assert call("vault_wiki_log", {"page": "q3-budget"})["total"] == 3
    assert len(call("vault_wiki_review", {})["open"]) == 1
    assert call("vault_wiki_review", {"action": "resolve", "item": "1"})["page"] == "Wiki/Topics/q3-budget"
    with pytest.raises(Exception):
        asyncio.run(server.call_tool("vault_wiki_review", {"action": "nope"}))
    with pytest.raises(Exception):
        asyncio.run(server.call_tool("vault_wiki_read", {"path": "Administrator/Follow-ups.md"}))


# ------------------------------------------------------------------ verified / sources


def test_verified_is_the_newest_source_date_not_today(vault):
    rec = email(1, received="2026-08-21T09:00:00+02:00")
    r = wiki.ingest(rec, [{"new": {"type": "topic", "title": "Q3 budget", "lead": "Jane collects numbers.", "summary": "Numbers."}, "ops": []}])
    path = r["pages"][0]["path"]
    assert fm_of(vault, path)["verified"] == "2026-08-21"  # record date, no facts yet
    r2 = wiki.ingest(rec, [{"path": path, "ops": [{"op": "add", "text": "Deadline is 2026-08-27", "since": "2026-08-21"}]}])
    fid = r2["pages"][0]["applied"][0]["id"]
    assert fm_of(vault, path)["verified"] == "2026-08-21"
    mpath, _key = meeting(start="2026-08-22T13:00:00+02:00")
    wiki.ingest(mpath, [{"path": path, "ops": [{"op": "supersede", "id": fid, "text": "Deadline is 2026-08-29", "since": "2026-08-22"}]}])
    fm = fm_of(vault, path)
    assert fm["verified"] == "2026-08-22" and fm["verified"] != wiki._today()


def test_sources_counts_each_record_once(vault):
    rec = email(1)
    r = wiki.ingest(rec, [{"new": {"type": "topic", "title": "Q3 budget", "lead": "x", "summary": "y"},
                           "ops": [{"op": "add", "text": "Deadline is 2026-08-29"}, {"op": "add", "text": "Sheet tab is Sales"}]}])
    path = r["pages"][0]["path"]
    assert fm_of(vault, path)["sources"] == 1  # one mail: two facts + one Records line
    mpath, _key = meeting()
    wiki.ingest(mpath, [{"path": path, "ops": [{"op": "confirm", "id": r["pages"][0]["applied"][0]["id"]}]}])
    assert fm_of(vault, path)["sources"] == 2
    wiki.apply(path, [{"op": "add", "text": "The user reports to Jane"}])  # src user never counts
    assert fm_of(vault, path)["sources"] == 2


def chat_record(day="2026-08-21"):
    chat = {"id": "19:abc@thread.v2", "title": "Q3 budget", "type": "group", "members": [{"name": "Jane Doe"}, {"name": "Hux"}], "account": "acme"}
    msgs = [
        {"id": "m1", "time": f"{day}T09:14:00+02:00", "sender": "Jane Doe", "is_self": False, "text": "Numbers by Friday?"},
        {"id": "m2", "time": f"{day}T09:20:00+02:00", "sender": "Hux", "is_self": True, "text": "Yes."},
    ]
    return workflows.save_chat(chat, msgs, ["Hux"], created_by=CB)["path"]


def test_record_info_and_ingest_on_a_chat_record(vault):
    rec = chat_record()
    info = wiki._record_info(vault, rec)
    assert info["type"] == "chat" and info["date"] == "2026-08-21" and info["src"] == "19:abc@thread.v2|2026-08-21"
    assert info["subject"] == "Q3 budget" and info["summary"] == "Jane Doe: Numbers by Friday?" and info["link"] == "[[Teams/2026-08-21 Q3 budget]]"
    path = topic(vault)
    r = wiki.ingest(rec, [{"path": path, "ops": [{"op": "add", "text": "Jane wants the numbers by Friday"}]}], created_by=CB)
    assert r["record"] == "[[Teams/2026-08-21 Q3 budget]]" and r["pages"][0]["record_added"] is True
    f = wiki.read(path)["facts"][0]
    assert f["src"] == ["19:abc@thread.v2|2026-08-21"] and f["since"] == "2026-08-21"
    assert "- 2026-08-21 — [[Teams/2026-08-21 Q3 budget]] — Jane Doe: Numbers by Friday?" in text_of(vault, path)
    assert fm_of(vault, rec)["wiki"] == ["[[Wiki/Topics/q3-budget]]"]
    assert fm_of(vault, path)["sources"] == 1  # the fact src and the Records line are the same chat day


# ------------------------------------------------------------------ reliable writes


def test_a_write_that_comes_back_wrong_is_put_back(vault, monkeypatch):
    path = topic(vault, facts=[{"text": "Deadline is 2026-08-29", "since": "2026-08-22", "src": "<m1@example.com>"}])
    before = text_of(vault, path)
    real = wiki.format_page

    def drops_a_fact(page):
        return "\n".join(l for l in real(page).split("\n") if not l.startswith("- Deadline is 2026-08-29 <!--"))

    monkeypatch.setattr(wiki, "format_page", drops_a_fact)
    r = wiki.apply(path, [{"op": "add", "text": "Sheet tab is Sales", "since": "2026-08-22"}])
    assert r["written"] is False and r["applied"] == []
    assert [(x["op"], x["reason"]) for x in r["refused"]] == [("add", "verify-failed")]
    assert any(p.startswith("facts") for p in r["refused"][0]["problems"])
    # the page is the page it was, and the copy under _cache/prev is the text from before the write
    assert text_of(vault, path) == before
    assert text_of(vault, f"{W}/_cache/prev/Topics/q3-budget.md.prev") == before
    assert wiki.read(path)["facts"][0]["text"] == "Deadline is 2026-08-29"
    line = wiki.review("list")["open"][0]["text"]
    assert "[[Wiki/Topics/q3-budget]] — write check failed (facts" in line and "previous text restored (apply, user)" in line
    assert "restore | Wiki/Topics/q3-budget | user | write check failed: facts" in wiki.log()["lines"][-1]


def test_a_hand_edited_index_is_repaired_and_a_normal_write_says_nothing(vault):
    topic(vault)
    other = wiki.create("topic", "Offsite venue", lead="Where the team meets in October.")["path"]
    # a normal write on another page: one log line, nothing else
    n = wiki.log(limit=500)["total"]
    wiki.apply(other, [{"op": "add", "text": "Venue is booked", "since": "2026-08-22"}])
    added = wiki.log(limit=500)["lines"][n:]
    assert len(added) == 1 and " apply | Wiki/Topics/offsite-venue | user | add 1" in added[0]
    # someone edits Index.md by hand: the next write puts it right and says so once
    idx = vault / W / "Index.md"
    hand = text_of(vault, f"{W}/Index.md").replace("[[Wiki/Topics/q3-budget|Q3 budget]]", "[[Wiki/Topics/q3-budget|Something else]]")
    assert "Something else" in hand
    idx.write_text(hand, encoding="utf-8")
    n = wiki.log(limit=500)["total"]
    wiki.apply(other, [])
    added = wiki.log(limit=500)["lines"][n:]
    assert any("index-repaired | Wiki/Index | - | 1 lines: Wiki/Topics/q3-budget" in l for l in added)
    idx_text = text_of(vault, f"{W}/Index.md")
    assert "[[Wiki/Topics/q3-budget|Q3 budget]]" in idx_text and "Something else" not in idx_text


def test_page_ids_are_sortable_unique_and_stay(vault):
    made = []
    for _ in range(3):
        made.append(wiki.new_page_id())
        time.sleep(0.002)
    assert made == sorted(made) and len(set(made)) == 3 and all(len(i) == 26 for i in made)
    path = topic(vault)
    first = fm_of(vault, path)["id"]
    wiki.apply(path, [{"op": "add", "text": "Sheet tab is Sales", "since": "2026-08-22"}])
    wiki.apply(path, [{"op": "summary", "text": "Numbers due Friday."}])
    assert fm_of(vault, path)["id"] == first
    person = wiki.create("person", "Jane Doe", extra={"email": "jane.doe@example.com"})["path"]
    assert fm_of(vault, person)["id"] != first and len(fm_of(vault, person)["id"]) == 26


def test_projects_group_lists_topics_with_a_due_soonest_first(vault):
    wiki.create("topic", "Office move", lead="The move to the new floor.")
    soon = wiki.create("topic", "Acme contract", lead="The supplier contract.", summary="Renewal.")["path"]
    wiki.create("topic", "Reading list", lead="Things to read.")
    wiki.apply(f"{W}/Topics/office-move.md", [{"op": "due", "value": "2026-12-01"}])
    wiki.apply(soon, [{"op": "due", "value": "2026-09-01"}, {"op": "owner", "value": "Jane Doe"}])
    body = text_of(vault, f"{W}/Index.md").split("# Wiki index\n\n")[1]
    assert body.index("## Projects (2)") < body.index("## Topics (1)")
    lines = [l for l in body.split("\n") if l.startswith("- [[Wiki/Topics/")]
    assert lines[0] == "- [[Wiki/Topics/acme-contract|Acme contract]] · Jane Doe · 2026-09-01 · active — Renewal."
    assert lines[1] == "- [[Wiki/Topics/office-move|Office move]] · — · 2026-12-01 · active"
    assert lines[2].startswith("- [[Wiki/Topics/reading-list|Reading list]] · active · ")
