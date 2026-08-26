"""administrator_vault.wiki: page contract, fact ops and refusals, caps,
index / log / review generation, lock, record two-way link, candidates."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time

import pytest

from administrator_vault import frontmatter as fmt
from administrator_vault import store, wiki, workflows
from administrator_vault.server import build_server

CB = "administrator/0.4.1"
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
    assert re.search(r'## Open\n\n- \[ \] Send Q3 numbers to Jane — owner: me <!-- o:[a-z2-7]{4} since:\d{4}-\d{2}-\d{2} src:"user" -->\n', text)
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
    # the record's summary names a day ("by Friday"), so the model is told to propose a due date
    assert wiki.ingest(a, [])["candidate"] == {"subject": "Offsite venue", "records": ["Emails/2026-08-20 Offsite venue"], "days": 1, "over_threshold": False, "page": None, "suggest_due": True}
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
    assert fm["created_by"] == "administrator/0.4.1"
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
    assert ctx["wiki"][1]["lead"].startswith("Jane collects")
    assert ctx["wiki"][1]["open"][0].startswith("- [ ] Send numbers to Jane — owner: me <!-- o:")
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

    def write(args):
        """One page through vault_wiki_write: the page's own result."""
        return call("vault_wiki_write", args)["pages"][0]

    c = write({"pages": [{"new": {"type": "topic", "title": "Q3 budget", "lead": "Lead.", "summary": "S.",
                                 "facts": [{"text": "Deadline is 2026-08-29", "since": "2026-08-22"}]}}]})
    assert c["created"] and c["path"] == f"{W}/Topics/q3-budget.md"
    r = call("vault_wiki_read", {"path": "Wiki/Topics/q3-budget"})
    fid = r["facts"][0]["id"]
    rec = email(1)
    i = call("vault_wiki_write", {"record_path": rec, "pages": [{"path": c["path"], "ops": [{"op": "confirm", "id": fid}]}]})
    assert i["record"] and i["pages"][0]["applied"] == [{"op": "confirm", "id": fid}]
    a = write({"pages": [{"path": c["path"], "ops": [{"op": "contest", "id": fid, "text": "Deadline is 2026-08-30"}]}]})
    assert a["applied"][0]["result"] == "review"
    # the commitment ops through the tools
    o = write({"pages": [{"path": c["path"], "ops": [
        {"op": "open", "text": "Send the numbers", "owner": "Jane Doe", "due": "2026-08-29", "since": "2026-08-22", "src": "user"}]}]})
    oid = o["applied"][0]["id"]
    assert o["applied"][0]["owner"] == "Jane Doe"
    items = call("vault_wiki_search", {"query": "", "open_items": True, "owner": "others"})
    assert [(x["stem"], x["text"], x["owner"], x["due"]) for x in items] == [("Wiki/Topics/q3-budget", "Send the numbers", "Jane Doe", "2026-08-29")]
    assert call("vault_wiki_search", {"query": "", "open_items": True, "owner": "me"}) == []
    assert write({"pages": [{"path": c["path"], "ops": [{"op": "reschedule", "id": oid, "due": "2026-09-05", "src": "user"}]}]})["applied"][0]["due"] == "2026-09-05"
    assert write({"pages": [{"path": c["path"], "ops": [{"op": "done", "id": oid, "src": "user"}]}]})["applied"][0]["id"] == oid
    assert call("vault_wiki_search", {"query": "", "open_items": True}) == []
    assert call("vault_wiki_search", {"query": "budget q3 numbers", "pages": True})["pages"][0]["path"] == c["path"]
    assert call("vault_wiki_keep", {"action": "log", "page": "q3-budget"})["total"] == 6
    assert len(call("vault_wiki_keep", {"action": "review"})["open"]) == 1
    assert call("vault_wiki_keep", {"action": "review", "review_action": "resolve", "item": "1"})["page"] == "Wiki/Topics/q3-budget"
    # one write, several pages: an existing one and a new one, each with its own result
    multi = call("vault_wiki_write", {"pages": [
        {"path": c["path"], "ops": [{"op": "add", "text": "Forecast closes on 2026-09-02", "since": "2026-08-22"}]},
        {"new": {"type": "org", "title": "Acme Parts", "lead": "The supplier.", "summary": "Supplier."}},
    ]})
    assert multi["record"] is None and multi["candidate"] is None and len(multi["pages"]) == 2
    assert multi["pages"][0]["written"] is True and multi["pages"][1]["created"] is True
    with pytest.raises(Exception):
        asyncio.run(server.call_tool("vault_wiki_keep", {"action": "review", "review_action": "nope"}))
    with pytest.raises(Exception):
        asyncio.run(server.call_tool("vault_wiki_keep", {"action": "nope"}))
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


# ------------------------------------------------------------------ commitments


def test_open_lines_carry_owner_due_and_id_and_round_trip(vault):
    path = topic(vault)
    wiki.create("person", "Jane Doe", extra={"email": "jane.doe@example.com"})
    r = wiki.apply(path, [
        {"op": "open", "text": "Send Q3 numbers", "due": "2026-08-29", "since": "2026-08-22", "src": "<x1@example.com>"},
        {"op": "open", "text": "Sign the contract", "owner": "[[Wiki/People/Jane Doe]]", "since": "2026-08-21", "src": "<x2@example.com>"},
        {"op": "open", "text": "Book the room", "owner": "Tom Lee", "due": "2026-09-02", "since": "2026-08-20", "src": "<x3@example.com>"},
    ])
    assert r["refused"] == [] and [a["owner"] for a in r["applied"]] == ["me", "[[Wiki/People/Jane Doe]]", "Tom Lee"]
    ids = [a["id"] for a in r["applied"]]
    text = text_of(vault, path)
    assert f'- [ ] Send Q3 numbers — owner: me · due: 2026-08-29 <!-- o:{ids[0]} since:2026-08-22 src:"<x1@example.com>" -->' in text
    assert f'- [ ] Sign the contract — owner: [[Wiki/People/Jane Doe]] <!-- o:{ids[1]} since:2026-08-21 src:"<x2@example.com>" -->' in text
    assert f'- [ ] Book the room — owner: Tom Lee · due: 2026-09-02 <!-- o:{ids[2]} since:2026-08-20 src:"<x3@example.com>" -->' in text
    assert fm_of(vault, path)["open_items"] == 3
    # read back and written again unchanged
    page = wiki.parse_page(text, path)
    assert [(o.id, o.text, o.owner, o.due, o.since, o.src, o.record, o.done) for o in page.opens] == [
        (ids[0], "Send Q3 numbers", "me", "2026-08-29", "2026-08-22", ["<x1@example.com>"], "", False),
        (ids[1], "Sign the contract", "[[Wiki/People/Jane Doe]]", "", "2026-08-21", ["<x2@example.com>"], "", False),
        (ids[2], "Book the room", "Tom Lee", "2026-09-02", "2026-08-20", ["<x3@example.com>"], "", False),
    ]
    assert wiki.format_page(page) == text
    assert page.opens[0].as_dict()["id"] == ids[0] and set(page.opens[0].as_dict()) == {
        "id", "text", "owner", "due", "since", "src", "record", "done"}
    # an item from a record names the record
    rec = email(1)
    wiki.ingest(rec, [{"path": path, "ops": [{"op": "open", "text": "Ask Jane for the sheet"}]}])
    line = next(l for l in text_of(vault, path).split("\n") if "Ask Jane" in l)
    assert " — [[Emails/2026-08-22 Budget Q3]] <!-- o:" in line and "owner: me" in line


def test_open_refusals_and_duplicates(vault):
    path = topic(vault)
    wiki.apply(path, [{"op": "open", "text": "Send Q3 numbers", "src": "<m1@example.com>"}])
    r = wiki.apply(path, [
        {"op": "open", "text": "send  q3 NUMBERS.", "src": "<other@example.com>"},   # same text
        {"op": "open", "text": "Something else", "src": "<m1@example.com>"},         # same source
        {"op": "open", "text": "Bad owner", "owner": "Wiki/People/Nobody"},
        {"op": "open", "text": "Bad owner", "owner": "Tom · Lee"},
        {"op": "open", "text": "Bad date", "due": "soon"},
    ])
    assert [x["reason"] for x in r["refused"]] == ["duplicate", "duplicate", "no-such-page", "bad-owner", "bad-date"]
    # "user" is not a record: two things the user said are two items
    r = wiki.apply(path, [{"op": "open", "text": "Call the bank", "src": "user"}, {"op": "open", "text": "Call the office", "src": "user"}])
    assert r["refused"] == [] and len(r["applied"]) == 2


def test_an_open_item_only_goes_on_a_page_that_has_the_section(vault):
    """org and howto pages have no ## Open in the contract; an item there would
    sit under a heading lint calls unknown."""
    org = wiki.create("org", "Example GmbH", created_by=CB)["path"]
    how = wiki.create("howto", "Book a room", created_by=CB)["path"]
    for path in (org, how):
        r = wiki.apply(path, [{"op": "open", "text": "Send the contract", "src": "user"}])
        assert r["applied"] == [] and r["refused"][0]["reason"] == "wrong-type"
        assert "no Open section" in r["refused"][0]["detail"]
        assert "## Open" not in text_of(vault, path)


def test_read_answers_with_the_open_and_milestone_lines(vault):
    path = topic(vault)
    wiki.apply(path, [{"op": "open", "text": "Send Q3 numbers", "due": "2026-08-29", "src": "user"},
                      {"op": "milestone", "text": "Draft ready", "due": "2026-08-26", "src": "user"}])
    out = wiki.read(path, sections=["lead", "facts", "open", "milestones"])
    oid = wiki.commitments(vault, page="Wiki/Topics/q3-budget")[0]["id"]
    assert f"<!-- o:{oid} " in out["sections"]["Open"] and "Send Q3 numbers" in out["sections"]["Open"]
    assert "Draft ready" in out["sections"]["Milestones"] and "<!-- m:" in out["sections"]["Milestones"]


def test_done_and_reschedule(vault):
    path = topic(vault)
    r = wiki.apply(path, [{"op": "open", "text": "Send Q3 numbers", "due": "2026-08-29", "since": "2026-08-22", "src": "<m1@example.com>"}])
    oid = r["applied"][0]["id"]
    r2 = wiki.apply(path, [{"op": "reschedule", "id": oid, "due": "2026-09-05", "src": "user"}])
    assert r2["refused"] == [] and r2["applied"][0]["due"] == "2026-09-05"
    text = text_of(vault, path)
    assert 'rescheduled "Send Q3 numbers" 2026-08-29 → 2026-09-05 (user)' in text and "due: 2026-09-05" in text
    assert wiki.apply(path, [{"op": "done", "id": "zzzz", "src": "user"}])["refused"][0]["reason"] == "unknown-id"
    r3 = wiki.apply(path, [{"op": "done", "id": oid, "src": "user"}])
    assert r3["applied"][0] == {"op": "done", "id": oid, "text": "Send Q3 numbers"}
    text = text_of(vault, path)
    assert "- [ ] Send Q3 numbers" not in text and fm_of(vault, path)["open_items"] == 0
    assert '— done "Send Q3 numbers" — owner: me · since 2026-08-22 (user)' in text


def test_old_open_lines_are_upgraded_on_the_next_write(vault):
    path = topic(vault)
    p = vault / path
    p.write_text(text_of(vault, path).replace("## Open\n", "## Open\n\n- [ ] Send the numbers — [[Emails/2026-08-22 Budget Q3]]\n- plain words nobody ticked\n"), encoding="utf-8")
    wiki.apply(path, [])
    line = next(l for l in text_of(vault, path).split("\n") if l.startswith("- [ ] Send"))
    assert re.match(r'^- \[ \] Send the numbers — owner: me — \[\[Emails/2026-08-22 Budget Q3\]\] <!-- o:[a-z2-7]{4} since:\d{4}-\d{2}-\d{2} src:"user" -->$', line)
    assert "- plain words nobody ticked" in text_of(vault, path)  # nothing is lost
    assert fm_of(vault, path)["open_items"] == 1


def test_milestones_are_kept_like_open_items_and_tick_to_history(vault):
    path = topic(vault)
    p = vault / path
    p.write_text(text_of(vault, path).replace("## Milestones\n", "## Milestones\n\n- [ ] Draft ready — due: 2026-09-01\n"), encoding="utf-8")
    wiki.apply(path, [])
    line = next(l for l in text_of(vault, path).split("\n") if l.startswith("- [ ] Draft ready"))
    assert re.match(r'^- \[ \] Draft ready — due: 2026-09-01 <!-- m:[a-z2-7]{4} since:\d{4}-\d{2}-\d{2} src:"user" -->$', line)
    assert fm_of(vault, path)["open_items"] == 0  # milestones are not open items
    p.write_text(text_of(vault, path).replace("- [ ] Draft ready", "- [x] Draft ready"), encoding="utf-8")
    wiki.apply(path, [])
    text = text_of(vault, path)
    assert "- [x] Draft ready" not in text and '— milestone reached "Draft ready" (user)' in text


def test_commitments_filters(vault):
    tp = topic(vault)
    jane = wiki.create("person", "Jane Doe", extra={"email": "jane.doe@example.com"})["path"]
    wiki.apply(tp, [
        {"op": "open", "text": "Send Q3 numbers", "due": "2026-08-29", "since": "2026-08-22", "src": "a"},
        {"op": "open", "text": "Sign the contract", "owner": "[[Wiki/People/Jane Doe]]", "since": "2026-08-20", "src": "b"},
    ])
    wiki.apply(jane, [{"op": "open", "text": "Tell Jane the date", "due": "2026-09-10", "since": "2026-08-21", "src": "c"}])
    all_of_them = wiki.commitments(vault)
    assert [(c["stem"], c["text"]) for c in all_of_them] == [
        ("Wiki/Topics/q3-budget", "Sign the contract"),
        ("Wiki/People/Jane Doe", "Tell Jane the date"),
        ("Wiki/Topics/q3-budget", "Send Q3 numbers"),
    ]  # oldest since first
    assert set(all_of_them[0]) == {"page", "stem", "type", "title", "owner_name", "id", "text", "owner", "due", "since", "src", "record", "done"}
    assert all_of_them[0]["page"] == f"{W}/Topics/q3-budget.md" and all_of_them[0]["owner_name"] == "Jane Doe"
    assert [c["text"] for c in wiki.commitments(vault, owner="me")] == ["Tell Jane the date", "Send Q3 numbers"]
    assert [c["text"] for c in wiki.commitments(vault, owner="others")] == ["Sign the contract"]
    assert [c["text"] for c in wiki.commitments(vault, due_before="2026-08-29")] == []
    assert [c["text"] for c in wiki.commitments(vault, due_before="2026-08-30")] == ["Send Q3 numbers"]
    assert [c["text"] for c in wiki.commitments(vault, page="Wiki/People/Jane Doe")] == ["Tell Jane the date"]
    assert len(wiki.commitments(vault, limit=1)) == 1
    with pytest.raises(store.VaultError):
        wiki.commitments(vault, owner="somebody")
    # done items are left out unless asked for
    oid = next(c["id"] for c in all_of_them if c["text"] == "Sign the contract")
    wiki.apply(tp, [{"op": "done", "id": oid, "src": "user"}])
    assert [c["text"] for c in wiki.commitments(vault, owner="others")] == []


def test_follow_ups_is_written_from_the_pages(vault):
    fu = "Administrator/Follow-ups.md"
    head = fm_of(vault, fu)
    assert head["type"] == "followups" and head["source"] == "wiki" and head["generated"] is True
    jane = wiki.create("person", "Jane Doe", extra={"email": "jane.doe@example.com"})["path"]
    rec = email(1)
    wiki.ingest(rec, [{"path": jane, "ops": [
        {"op": "open", "text": "Send the signed contract", "owner": "[[Wiki/People/Jane Doe]]", "since": "2026-08-22"},
        {"op": "open", "text": "Book the room"},
    ]}])
    text = text_of(vault, fu)
    assert "Generated from the Open items of the wiki pages" in text
    assert "| Since | Who | What | Email | Last checked |" in text and "| Since | Who | What | Email | Closed |" in text
    open_part, done_part = text.split("## Open")[1].split("## Done")
    row = next(l for l in open_part.split("\n") if "Send the signed" in l)
    cells = store._cells(row)
    assert cells[:4] == ["2026-08-22", "[[Wiki/People/Jane Doe]]", "Send the signed contract", "[[Emails/2026-08-22 Budget Q3]]"]
    assert re.match(r"^\d{4}-\d{2}-\d{2} <!-- o: [a-z2-7]{4} @ Wiki/People/Jane Doe -->$", cells[4])
    assert "Book the room" not in open_part  # owner me
    assert fm_of(vault, fu)["open"] == 1
    # ticking it moves it to Done
    oid = wiki.commitments(vault, owner="others")[0]["id"]
    wiki.apply(jane, [{"op": "done", "id": oid, "src": "user"}])
    text = text_of(vault, fu)
    open_part, done_part = text.split("## Open")[1].split("## Done")
    assert "Send the signed contract" not in open_part
    done = store._cells(next(l for l in done_part.split("\n") if "Send the signed" in l))
    assert done[:3] == ["2026-08-22", "[[Wiki/People/Jane Doe]]", "Send the signed contract"] and done[4] == wiki._today()
    assert fm_of(vault, fu)["open"] == 0


# ------------------------------------------------------------------ decisions and project fields


def jane(vault):
    return wiki.create("person", "Jane Doe", extra={"email": "jane.doe@example.com"})["path"]


def decision(vault, title="Ship on the new stack", **kw):
    args = dict(
        type="decision", title=title, lead="We go with the new stack for the rebuild.", summary="New stack for the rebuild.",
        facts=[{"text": "The rebuild runs on the new stack", "since": "2026-08-22", "src": "<m1@example.com>"}],
        extra={"decided": "2026-08-22", "by": ["[[Wiki/People/Jane Doe]]"]},
    )
    args.update(kw)
    res = wiki.create(**args)
    assert res["created"], res
    return res["path"]


def test_decision_page_is_created_flagged_and_listed_in_review(vault):
    jane(vault)
    path = decision(vault)
    assert path == f"{W}/Decisions/ship-on-the-new-stack.md"
    fm = fm_of(vault, path)
    assert fm["type"] == "decision" and fm["status"] == "current" and fm["decided"] == "2026-08-22"
    assert fm["by"] == ["[[Wiki/People/Jane Doe]]"] and fm["flags"] == ["unconfirmed-decision"]
    assert list(fm).index("decided") > list(fm).index("status") and list(fm).index("by") > list(fm).index("decided")
    heads = [l[3:] for l in text_of(vault, path).split("\n") if l.startswith("## ")]
    assert heads == list(wiki.SECTIONS["decision"]) and "Milestones" not in heads
    line = '- [ ] [[Wiki/Decisions/ship-on-the-new-stack]] — unconfirmed decision: "The rebuild runs on the new stack" — confirm or drop (user)'
    assert any(o["text"] == line for o in wiki.review("list")["open"])
    assert wiki.CAPS["decision"] == (60, 3000)
    # the people who decided are linked both ways, so the page is not an orphan
    assert "- [[Wiki/People/Jane Doe]] — decided" in text_of(vault, path)
    assert "[[Wiki/Decisions/ship-on-the-new-stack]]" in text_of(vault, f"{W}/People/Jane Doe.md")


def test_decision_create_needs_a_date_and_people_who_have_a_page(vault):
    jane(vault)
    for extra in (
        {"by": ["[[Wiki/People/Jane Doe]]"]},                                  # no decided
        {"decided": "soon", "by": ["[[Wiki/People/Jane Doe]]"]},               # not a date
        {"decided": "2026-08-22"},                                             # no by
        {"decided": "2026-08-22", "by": ["[[Wiki/People/Nobody]]"]},           # no such page
    ):
        with pytest.raises(store.VaultError):
            wiki.create("decision", "Ship on the new stack", extra=extra)
    assert not list((vault / W / "Decisions").glob("*.md"))


def test_a_decision_is_added_to_never_rewritten(vault):
    jane(vault)
    path = decision(vault)
    fid = wiki.read(path)["facts"][0]["id"]
    refused = wiki.apply(path, [
        {"op": "add", "text": "Something else", "src": "user"},
        {"op": "update", "id": fid, "text": "Other wording", "src": "user"},
        {"op": "supersede", "id": fid, "text": "Other stack", "since": "2026-08-25", "src": "user"},
        {"op": "retire", "id": fid, "reason": "wrong", "src": "user"},
        {"op": "contest", "id": fid, "text": "Not so", "src": "user"},
        {"op": "due", "value": "2026-09-01"},
        {"op": "outcome", "text": "Shipped"},
        {"op": "milestone", "text": "Kick-off", "src": "user"},
        {"op": "risk", "text": "The licence", "src": "user"},
        {"op": "link", "url": "https://example.com"},
        {"op": "steps", "text": "1. do it"},
        {"op": "status", "value": "superseded"},
    ])["refused"]
    assert [x["reason"] for x in refused] == ["append-only"] * 12
    assert "new decision" in refused[0]["detail"]
    assert wiki.read(path)["facts"] == [{"id": fid, "text": "The rebuild runs on the new stack", "since": "2026-08-22", "src": ["<m1@example.com>"]}]
    ok = wiki.apply(path, [
        {"op": "summary", "text": "The rebuild runs on the new stack."},
        {"op": "lead", "text": "We go with the new stack, decided in the August review."},
        {"op": "alias", "text": "Stack choice"},
        {"op": "reversal", "text": "A licence problem with the new stack would reopen it."},
        {"op": "confirm", "id": fid, "src": "<m2@example.com>"},
        {"op": "open", "text": "Tell the team", "src": "user"},
        {"op": "related", "page": "Wiki/People/Jane Doe"},
    ])
    assert ok["refused"] == [] and len(ok["applied"]) == 7
    fm = fm_of(vault, path)
    assert fm["reversal"] == "A licence problem with the new stack would reopen it." and fm["status"] == "current"
    assert wiki.apply(path, [{"op": "reversal", "text": "x" * 161}])["refused"][0]["reason"] == "reversal-too-long"


def test_a_decision_holds_at_most_eight_facts(vault):
    jane(vault)
    facts = [{"text": f"Consequence number {i}", "since": "2026-08-22", "src": "<m1@example.com>"} for i in range(9)]
    res = wiki.create("decision", "Ship on the new stack", facts=facts, extra={"decided": "2026-08-22", "by": ["[[Wiki/People/Jane Doe]]"]})
    assert len(res["applied"]) == 8 and res["refused"][0]["reason"] == "facts-cap" and res["refused"][0]["max_facts"] == 8


def test_superseded_by_sets_the_status_and_links_both_ways(vault):
    jane(vault)
    old = decision(vault)
    new = decision(vault, title="Ship on the old stack", extra={"decided": "2026-09-01", "by": ["[[Wiki/People/Jane Doe]]"]})
    r = wiki.apply(old, [{"op": "superseded_by", "page": new, "src": "user"}])
    assert r["refused"] == [] and r["applied"][0] == {"op": "superseded_by", "page": "Wiki/Decisions/ship-on-the-old-stack"}
    fm = fm_of(vault, old)
    assert fm["status"] == "superseded" and fm["superseded_by"] == "[[Wiki/Decisions/ship-on-the-old-stack]]"
    assert "— superseded by [[Wiki/Decisions/ship-on-the-old-stack]] (user)" in text_of(vault, old)
    assert "- [[Wiki/Decisions/ship-on-the-old-stack]]" in text_of(vault, old)
    assert "- [[Wiki/Decisions/ship-on-the-new-stack]]" in text_of(vault, new)
    tp = topic(vault)
    assert wiki.apply(new, [{"op": "superseded_by", "page": tp, "src": "user"}])["refused"][0]["reason"] == "wrong-type"
    assert wiki.apply(tp, [{"op": "superseded_by", "page": new, "src": "user"}])["refused"][0]["reason"] == "wrong-type"


def test_dropped_is_the_only_status_and_only_from_the_user(vault):
    jane(vault)
    path = decision(vault)
    rec = email(1)
    res = wiki.ingest(rec, [{"path": path, "ops": [{"op": "status", "value": "dropped"}]}])
    assert res["pages"][0]["refused"][0]["reason"] == "append-only"
    r = wiki.apply(path, [{"op": "status", "value": "dropped"}])
    assert r["refused"] == [] and fm_of(vault, path)["status"] == "dropped"
    assert wiki.apply(path, [{"op": "status", "value": "closed"}])["refused"][0]["reason"] == "append-only"


def test_a_decision_is_confirmed_by_resolving_the_review_line_or_by_ticking_it(vault):
    jane(vault)
    path = decision(vault)
    fid = wiki.read(path)["facts"][0]["id"]
    wiki.review("resolve", "ship-on-the-new-stack", [{"op": "confirm", "id": fid, "src": "user"}])
    assert fm_of(vault, path)["flags"] == []
    other = decision(vault, title="Move the office", extra={"decided": "2026-08-24", "by": ["[[Wiki/People/Jane Doe]]"]})
    assert fm_of(vault, other)["flags"] == ["unconfirmed-decision"]
    p = vault / wiki.REVIEW_PATH
    p.write_text(p.read_text(encoding="utf-8").replace("- [ ] [[Wiki/Decisions/move-the-office]]", "- [x] [[Wiki/Decisions/move-the-office]]"), encoding="utf-8")
    out = wiki.ingest(email(2), [])
    assert out["confirmed_decisions"] == ["Wiki/Decisions/move-the-office"]
    assert fm_of(vault, other)["flags"] == [] and "— decision confirmed (user)" in text_of(vault, other)
    assert not any("move-the-office" in o["text"] for o in wiki.review("list")["open"])
    assert "— confirmed " in text_of(vault, wiki.REVIEW_PATH).split("## Done")[1]


def test_decisions_and_people_link_through_topics_and_people(vault):
    assert wiki._section_for("decision", "person") == "People"
    assert wiki._section_for("person", "decision") == "Topics"
    assert wiki._section_for("org", "decision") == "Topics"
    person = jane(vault)
    path = decision(vault)
    r = wiki.apply(path, [{"op": "role", "page": "Wiki/People/Jane Doe", "role": "decided it", "src": "user"}])
    assert r["applied"][0] == {"op": "role", "page": "Wiki/People/Jane Doe", "section": "People"}
    assert "- [[Wiki/People/Jane Doe]] — decided it" in text_of(vault, path)
    topics = text_of(vault, person).split("## Topics")[1].split("## ")[0]
    assert "- [[Wiki/Decisions/ship-on-the-new-stack]] — decided it" in topics


def test_a_decision_is_never_merged(vault):
    from administrator_vault import wiki_lint

    jane(vault)
    path = decision(vault)
    other = decision(vault, title="Move the office", extra={"decided": "2026-08-24", "by": ["[[Wiki/People/Jane Doe]]"]})
    with pytest.raises(store.VaultError):
        wiki_lint.merge(path, other)
    with pytest.raises(store.VaultError):
        wiki_lint.merge(topic(vault), other)


def test_index_lists_projects_then_decisions_then_topics(vault):
    jane(vault)
    decision(vault)
    project = topic(vault, title="Acme contract", aliases=[], summary="Renewal.")
    wiki.apply(project, [{"op": "due", "value": "2026-09-01"}, {"op": "owner", "value": "[[Wiki/People/Jane Doe]]"}])
    topic(vault, title="Reading list", aliases=[], summary="Things to read.")
    body = text_of(vault, f"{W}/Index.md").split("# Wiki index\n\n")[1]
    assert body.index("## Projects (1)") < body.index("## Decisions (1)") < body.index("## Topics (1)") < body.index("## People (1)")
    assert "- [[Wiki/Decisions/ship-on-the-new-stack|Ship on the new stack]] · current · 2026-08-22 — New stack for the rebuild." in body


def test_topic_project_ops_and_their_caps(vault):
    path = topic(vault)
    email(1)
    r = wiki.apply(path, [
        {"op": "outcome", "text": "The forecast closes with the sales numbers in."},
        {"op": "milestone", "text": "Draft ready", "due": "2026-09-01", "src": "user"},
        {"op": "risk", "text": "The sales numbers may be late", "src": "user"},
        {"op": "link", "url": "https://example.com/sheet", "label": "The sheet"},
        {"op": "link", "page": "Emails/2026-08-22 Budget Q3", "label": "Jane's mail"},
    ])
    assert r["refused"] == [] and r["applied"][1]["due"] == "2026-09-01"
    fm = fm_of(vault, path)
    assert fm["outcome"] == "The forecast closes with the sales numbers in."
    assert fm["risks"] == ["The sales numbers may be late"]
    assert fm["links"] == ["[The sheet](https://example.com/sheet)", "[[Emails/2026-08-22 Budget Q3|Jane's mail]]"]
    text = text_of(vault, path)
    assert "- [ ] Draft ready — due: 2026-09-01 <!-- m:" in text
    assert '— risk added "The sales numbers may be late" (user)' in text
    again = wiki.apply(path, [
        {"op": "milestone", "text": "draft READY", "src": "user"},
        {"op": "risk", "text": "The sales numbers may be late.", "src": "user"},
        {"op": "link", "url": "https://example.com/sheet", "label": "The sheet"},
        {"op": "outcome", "text": "x" * 161},
        {"op": "risk", "text": "y" * 81, "src": "user"},
        {"op": "link", "page": "Emails/nothing here", "label": "Gone"},
    ])
    assert [x["reason"] for x in again["refused"]] == ["duplicate", "duplicate", "duplicate", "outcome-too-long", "risk-too-long", "no-such-page"]
    more = wiki.apply(path, [{"op": "risk", "text": f"Risk number {i}", "src": "user"} for i in range(9)])
    assert [x["reason"] for x in more["refused"]] == ["risks-cap"] * 2 and len(fm_of(vault, path)["risks"]) == 8
    more = wiki.apply(path, [{"op": "link", "url": f"https://example.com/{i}"} for i in range(10)])
    assert [x["reason"] for x in more["refused"]] == ["links-cap"] * 2 and len(fm_of(vault, path)["links"]) == 10


def test_the_project_ops_are_only_for_topics(vault):
    person = jane(vault)
    r = wiki.apply(person, [
        {"op": "outcome", "text": "Done"},
        {"op": "milestone", "text": "Kick-off", "src": "user"},
        {"op": "risk", "text": "Late", "src": "user"},
        {"op": "link", "url": "https://example.com"},
    ])
    assert [x["reason"] for x in r["refused"]] == ["wrong-type"] * 4
    assert wiki.apply(topic(vault), [{"op": "reversal", "text": "x"}])["refused"][0]["reason"] == "wrong-type"


def test_prep_pages_takes_decisions_with_the_topics(vault):
    jane(vault)
    decision(vault, title="Budget tool choice", summary="We use the sheet.")
    project = topic(vault, title="Budget round", aliases=[], summary="The round.")
    wiki.apply(project, [{"op": "due", "value": "2026-09-01"}])
    rows = wiki.prep_pages(vault, [], "Budget tool choice", topics_max=3)
    stems = [wiki._stem(r["path"]) for r in rows]
    assert "Wiki/Decisions/budget-tool-choice" in stems
    assert rows[0]["type"] in ("topic", "decision")


def test_a_decision_can_come_from_an_ingest_with_its_facts(vault):
    jane(vault)
    rec = email(1, subject="Rebuild stack", summary="We agreed to go with the new stack.")
    out = wiki.ingest(rec, [{
        "new": {"type": "decision", "title": "New stack", "lead": "We go with the new stack.", "summary": "New stack.",
                "decided": "2026-08-22", "by": ["[[Wiki/People/Jane Doe]]"]},
        "ops": [{"op": "add", "text": "The rebuild runs on the new stack"},
                {"op": "open", "text": "Tell the team", "owner": "[[Wiki/People/Jane Doe]]"}],
    }])
    page = out["pages"][0]
    assert page["written"] is True and [a["op"] for a in page["applied"]] == ["add", "open"]
    fm = fm_of(vault, page["path"])
    assert fm["status"] == "current" and fm["flags"] == ["unconfirmed-decision"] and fm["decided"] == "2026-08-22"
    # the Review line quotes the first fact, which arrived with the ops
    line = '- [ ] [[Wiki/Decisions/new-stack]] — unconfirmed decision: "The rebuild runs on the new stack" — confirm or drop ([[Emails/2026-08-22 Rebuild stack]])'
    assert any(o["text"] == line for o in wiki.review("list")["open"])
    # a later record may not rewrite it
    r2 = wiki.ingest(email(2), [{"path": page["path"], "ops": [{"op": "add", "text": "Something else"}]}])
    assert r2["pages"][0]["refused"][0]["reason"] == "append-only"


# ------------------------------------------------------------------ conflicts at ingest


def test_add_is_refused_when_a_fact_holds_another_date_for_the_same_thing(vault):
    path = topic(vault)
    fid = wiki.apply(path, [{"op": "add", "text": "Final numbers are due 2026-08-29", "since": "2026-08-22"}])["applied"][0]["id"]
    r = wiki.apply(path, [{"op": "add", "text": "Final numbers are due 2026-09-05", "since": "2026-08-25"}])
    ref = r["refused"][0]
    assert ref["reason"] == "conflicts-with" and ref["id"] == fid
    assert ref["current"] == "Final numbers are due 2026-08-29" and ref["since"] == "2026-08-22"
    assert "supersede" in ref["detail"] and "contest" in ref["detail"]
    assert [f["text"] for f in wiki.read(path)["facts"]] == ["Final numbers are due 2026-08-29"]
    # the way out the refusal names: supersede when the new day is the newer one
    r2 = wiki.apply(path, [{"op": "supersede", "id": fid, "text": "Final numbers are due 2026-09-05", "since": "2026-08-25"}])
    assert r2["written"] is True and r2["refused"] == []
    assert [f["text"] for f in wiki.read(path)["facts"]] == ["Final numbers are due 2026-09-05"]
    # and contest when it is the older or the unsure one
    r3 = wiki.apply(path, [{"op": "contest", "id": r2["applied"][0]["id"], "text": "Final numbers are due 2026-08-29"}])
    assert r3["applied"][0]["result"] == "review"


def test_add_is_refused_when_a_fact_holds_another_amount_for_the_same_thing(vault):
    path = wiki.create("org", "Acme", lead="Acme prints the reports.")["path"]
    wiki.apply(path, [{"op": "add", "text": "Payment terms are net 30 days", "since": "2026-08-22"}])
    r = wiki.apply(path, [{"op": "add", "text": "Payment terms are net 45 days", "since": "2026-08-25"}])
    assert r["refused"][0]["reason"] == "conflicts-with" and r["refused"][0]["current"] == "Payment terms are net 30 days"
    # the same amount said again is no disagreement
    assert wiki.apply(path, [{"op": "add", "text": "Invoices are paid net 30 days by the finance desk", "since": "2026-08-25"}])["written"] is True
    # neither is a fact that names no amount at all
    assert wiki.apply(path, [{"op": "add", "text": "Acme prints the annual report", "since": "2026-08-25"}])["written"] is True


def test_a_price_and_a_percentage_are_amounts_however_they_are_written(vault):
    path = wiki.create("org", "Acme", lead="Acme prints the reports.")["path"]
    wiki.apply(path, [{"op": "add", "text": "The licence costs 4500 EUR a year", "since": "2026-08-22"}])
    # the name, the sign after and the sign before are one and the same amount
    assert wiki.apply(path, [{"op": "add", "text": "The licence costs 4500€ a year", "since": "2026-08-25"}])["written"] is True
    r = wiki.apply(path, [{"op": "add", "text": "The licence costs €9000 a year", "since": "2026-08-25"}])
    assert r["refused"][0]["reason"] == "conflicts-with" and r["refused"][0]["current"] == "The licence costs 4500 EUR a year"
    # a percentage at the end of a fact is an amount as well
    wiki.apply(path, [{"op": "add", "text": "The volume discount is 20%", "since": "2026-08-22"}])
    r2 = wiki.apply(path, [{"op": "add", "text": "The volume discount is 15%", "since": "2026-08-25"}])
    assert r2["refused"][0]["reason"] == "conflicts-with" and r2["refused"][0]["current"] == "The volume discount is 20%"


def test_small_bare_numbers_are_not_values_and_do_not_conflict(vault):
    path = topic(vault)
    ops = [{"op": "add", "text": f"Fact {i} " + "x" * 20, "since": "2026-08-22"} for i in (10, 11)]
    r = wiki.apply(path, ops)
    assert r["written"] is True and r["refused"] == [] and len(wiki.read(path)["facts"]) == 2
    # two facts that share only one word are two subjects, not one disagreement
    r2 = wiki.apply(path, [{"op": "add", "text": "Deadline 2026-08-29", "since": "2026-08-22"},
                           {"op": "add", "text": "Offsite 2026-09-30", "since": "2026-08-22"}])
    assert r2["written"] is True and r2["refused"] == []


def test_a_decision_page_is_never_checked_for_conflicts(vault):
    jane(vault)
    res = wiki.create("decision", "Ship on the new stack", lead="We go with the new stack.", summary="New stack.",
                      facts=[{"text": "Cutover happens on 2026-09-01", "since": "2026-08-22", "src": "<m1@example.com>"},
                             {"text": "Cutover happens on 2026-10-01", "since": "2026-08-22", "src": "<m1@example.com>"}],
                      extra={"decided": "2026-08-22", "by": ["[[Wiki/People/Jane Doe]]"]})
    assert res["created"] is True and res["refused"] == [] and len(wiki.read(res["path"])["facts"]) == 2
    # a later add is refused for being a decision, not for disagreeing
    r = wiki.apply(res["path"], [{"op": "add", "text": "Cutover happens on 2026-11-01", "since": "2026-08-25"}])
    assert r["refused"][0]["reason"] == "append-only"
