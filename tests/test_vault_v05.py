"""administrator_vault v0.5: rules, inbox prepare, write daily, save email,
prep context, weekly facts, transcript, and fields on find/list."""

from __future__ import annotations

import asyncio
import json

import pytest

from administrator_vault import frontmatter as fmt
from administrator_vault import store, workflows
from administrator_vault.server import build_server

CB = "administrator/0.0.5"
DAY = "2026-08-22"


@pytest.fixture
def vault(tmp_path, monkeypatch):
    root = tmp_path / "Vault"
    root.mkdir()
    monkeypatch.setenv("ADMINISTRATOR_VAULT", str(root))
    monkeypatch.delenv("ADMINISTRATOR_VAULT_NAME", raising=False)
    store.init(created_by=CB)
    return root


def item(n, **over):
    d = {
        "entry_id": f"00A{n}",
        "internet_message_id": f"<m{n}@example.com>",
        "from_address": f"person{n}@example.com",
        "from_name": f"Person {n}",
        "subject": f"Subject {n}",
        "received": f"2026-08-22T0{n}:10:00+02:00",
        "preview": "p" * 200,
    }
    d.update(over)
    return d


def person(vault, name="Jane Doe", email="jane.doe@example.com", **over):
    fm = {"type": "person", "source": "outlook", "name": name, "email": email, "aliases": [],
          "last_contact": "2026-08-20T09:00:00+02:00", "created_by": CB}
    fm.update(over)
    body = f"# {name}\n\n{email}\n\n## Emails\n\n- 2026-08-20 — [[Emails/2026-08-20 Old mail]] (done)\n- 2026-08-10 — [[Emails/2026-08-10 Older]] (fyi)\n"
    return store.write("person", fm, body)["path"]


# ------------------------------------------------------------------ rules


def test_init_creates_rules_and_never_overwrites(vault):
    p = vault / "Administrator" / "Rules.md"
    assert p.is_file()
    fm = fmt.split_note(p.read_text(encoding="utf-8"))[0]
    assert fm["type"] == "rules"
    assert store.status()["files"]["Rules.md"] is True
    p.write_text("---\ntype: rules\n---\n# mine\n", encoding="utf-8")
    res = store.init(overwrite=True, created_by=CB)
    assert "Administrator/Rules.md" in res["skipped"]
    assert "# mine" in p.read_text(encoding="utf-8")


def test_rules_get_and_match(vault):
    store.append_row("Administrator/Rules.md", "Labels", ["@newsletter.example", "from", "noise"])
    store.append_row("Administrator/Rules.md", "Labels", ["invoice*", "subject", "act"])
    store.append_row("Administrator/Rules.md", "Never save", ["spam.example", "domain"])
    p = vault / "Administrator" / "Rules.md"
    p.write_text(p.read_text(encoding="utf-8") + "- boss@example.com\n", encoding="utf-8")
    person(vault, "Fyi Person", "fyi@example.com", status="fyi")

    got = workflows.rules_get()
    assert got["labels"] == [
        {"match": "@newsletter.example", "field": "from", "label": "noise"},
        {"match": "invoice*", "field": "subject", "label": "act"},
    ]
    assert got["never_save"] == [{"match": "spam.example", "field": "domain"}]
    assert got["fyi_senders"] == ["boss@example.com"]

    items = [
        item(1, from_address="news@newsletter.example"),
        item(2, subject="Invoice 4471"),
        item(3, from_address="x@spam.example"),
        item(4, from_address="boss@example.com"),
        item(5, headers={"list_unsubscribe": "<mailto:u@x>"}),
        item(6, subject="Automatic reply: out"),
        item(7, message_class="IPM.Schedule.Meeting.Resp.Pos", subject="Accepted: Sync"),
        item(8, from_address="no-reply@shop.example"),
        item(9, from_address="fyi@example.com"),
        item(0, subject="plain"),
    ]
    res = {r["entry_id"]: r for r in workflows.rules_match(items)["results"]}
    assert res["00A1"]["label"] == "noise" and res["00A1"]["rule"].startswith("Labels:")
    assert res["00A2"]["label"] == "act"
    assert res["00A3"]["never_save"] is True and res["00A3"]["label"] is None
    assert res["00A4"]["label"] == "fyi" and res["00A4"]["rule"].startswith("Fyi senders")
    assert res["00A5"]["label"] == "fyi" and "List-Unsubscribe" in res["00A5"]["rule"]
    assert res["00A6"]["label"] == "noise"
    assert res["00A7"]["label"] == "noise"
    assert res["00A8"]["label"] == "fyi"
    assert res["00A9"]["label"] == "fyi" and "People/Fyi Person" in res["00A9"]["rule"]
    assert res["00A0"] == {"entry_id": "00A0", "label": None, "never_save": False, "rule": None}


# ------------------------------------------------------------------ inbox prepare + write daily


def test_inbox_prepare_and_write_daily_twice(vault):
    store.append_row("Administrator/Rules.md", "Never save", ["spam.example", "domain"])
    items = [
        item(1),
        item(2, from_address="news@x.example", headers={"list_unsubscribe": "y"}),
        item(3, from_address="x@spam.example"),
        item(4, received="2026-08-21T17:55:00+02:00"),
    ]
    prep = workflows.inbox_prepare(items, DAY)
    assert prep["already_seen"] == [] and prep["never_save"] == ["00A3"]
    assert prep["labelled_by_rule"] == 1
    by = {i["entry_id"]: i for i in prep["to_label"]}
    assert set(by) == {"00A1", "00A2", "00A4"}
    assert by["00A2"]["label"] == "fyi" and "preview" not in by["00A2"]
    assert by["00A1"]["label"] is None and len(by["00A1"]["preview"]) <= 120
    assert (vault / prep["cache"]).is_file()

    events = [
        {"occurrence_key": "G1|2026-08-22T09:30:00+02:00", "subject": "Stand-up", "start": "2026-08-22T09:30:00+02:00",
         "end": "2026-08-22T10:00:00+02:00", "location": "Teams", "organizer": "Bob Lee"},
        {"occurrence_key": "G2|2026-08-22T13:00:00+02:00", "subject": "Budget review", "start": "2026-08-22T13:00:00+02:00",
         "end": "2026-08-22T14:00:00+02:00", "location": "Room 4", "organizer": "Jane Doe"},
        {"occurrence_key": "G3|2026-08-22T13:30:00+02:00", "subject": "Dentist", "start": "2026-08-22T13:30:00+02:00",
         "end": "2026-08-22T14:30:00+02:00", "location": "", "organizer": "me"},
        {"occurrence_key": "G4|2026-08-22T00:00:00+02:00", "subject": "Holiday", "start": "2026-08-22T00:00:00+02:00",
         "end": "2026-08-23T00:00:00+02:00", "all_day": True, "organizer": ""},
    ]
    labels = [
        {"entry_id": "00A1", "label": "act", "reason": "Asks for numbers by Friday"},
        {"entry_id": "00A4", "label": "waiting", "reason": "Will send the draft | next week"},
    ]
    res = workflows.write_daily(DAY, labels, None, events, ["Bring the contract"], since="2026-08-21T18:02:00+02:00",
                                inbox_checked="2026-08-22T08:31:10+02:00", tokens_used=1234)
    assert res["action"] == "created" and res["path"] == "Administrator/Daily/2026-08-22.md"
    assert res["rows_written"] == 3 and res["followups_added"] == 1 and res["calendar_rows"] == 4
    text = (vault / res["path"]).read_text(encoding="utf-8")
    fm = fmt.split_note(text)[0]
    assert fm["mails_seen"] == 3 and fm["tokens_used"] == 1234 and fm["since"] == "2026-08-21T18:02:00+02:00"
    lines = text.split("\n")
    rows = [c for l in lines if l.startswith("| ") and l[2].isdigit() and len(c := store._cells(l)) == 7]
    assert [r[1] for r in rows] == ["act", "waiting", "fyi"]
    assert rows[0][4] == "01:10" and rows[1][4] == "2026-08-21 17:55"
    assert rows[1][5] == "Will send the draft | next week"
    assert rows[0][6] == "<!-- entry_id: 00A1 -->"
    assert "- [ ] act — Subject 1 (Person 1)" in text
    assert "- Person 4 — Subject 4 (since 2026-08-21) → also in [[Follow-ups]]" in text
    assert "| all day | all day | Holiday |" in text
    assert "| 09:30 | 10:00 | Stand-up | Teams | Bob Lee <!-- occurrence_key: G1\\|2026-08-22T09:30:00+02:00 --> |" in text
    assert "- Bring the contract" in text
    assert "- Clash: Budget review (13:00–14:00) overlaps Dentist (13:30–14:30)" in text
    assert "- No prep note: Stand-up" in text and "No prep note: Holiday" not in text
    fu = (vault / "Administrator" / "Follow-ups.md").read_text(encoding="utf-8")
    assert "| 2026-08-21 | Person 4 | Subject 4 |  | 2026-08-22 <!-- entry_id: 00A4 --> |" in fu

    # second run the same day: one new mail, the rest already seen
    prep2 = workflows.inbox_prepare(items + [item(5)], DAY)
    assert sorted(prep2["already_seen"]) == ["00A1", "00A2", "00A4"]
    assert [i["entry_id"] for i in prep2["to_label"]] == ["00A5"]
    res2 = workflows.write_daily(DAY, [{"entry_id": "00A5", "label": "reply", "reason": "asks"}], None, events,
                                 since="2026-08-22T08:31:10+02:00", inbox_checked="2026-08-22T15:40:00+02:00")
    assert res2["action"] == "appended" and res2["rows_written"] == 1 and res2["calendar_rows"] == 0
    text2 = (vault / res["path"]).read_text(encoding="utf-8")
    assert text2.count("<!-- entry_id: 00A1 -->") == 1
    assert "### Inbox (since 2026-08-22T08:31:10+02:00)" in text2
    assert "| 4 | reply | Person 5 |" in text2
    assert text2.count("## Calendar") == 1 and text2.count("Clash:") == 1
    assert fmt.split_note(text2)[0]["inbox_checked"] == "2026-08-22T15:40:00+02:00"
    assert fmt.split_note(text2)[0]["mails_seen"] == 3

    # third run with the same items again: nothing new, nothing written
    res3 = workflows.write_daily(DAY, [], items, events, since="x")
    assert res3["action"] == "unchanged" and res3["duplicates_skipped"] == 3
    assert (vault / res["path"]).read_text(encoding="utf-8") == text2


def test_write_daily_links_existing_email_note_and_needs_items(vault):
    with pytest.raises(store.VaultError):
        workflows.write_daily("2026-08-23", [])
    mail_fm = {"type": "email", "source": "outlook", "internet_message_id": "<m1@example.com>", "entry_id": "00A1",
               "conversation_id": "C", "subject": "Subject 1", "from": "person1@example.com", "from_name": "Person 1",
               "from_link": "", "to": [], "cc": [], "received": "2026-08-22T01:10:00+02:00", "status": "todo", "created_by": CB}
    store.write("email", mail_fm, "x")
    res = workflows.write_daily(DAY, [{"entry_id": "00A1", "label": "act", "reason": "r"}], [item(1), item(2)], since="s")
    assert res["unlabelled"] == ["00A2"] and res["rows_written"] == 1
    text = (vault / res["path"]).read_text(encoding="utf-8")
    assert "| [[Emails/2026-08-22 Subject 1]] <!-- entry_id: 00A1 --> |" in text
    assert "- [ ] act — Subject 1 (Person 1) — [[Emails/2026-08-22 Subject 1]]" in text
    assert "## Calendar" not in text and "## Watch out" not in text


# ------------------------------------------------------------------ save email


def mail_json(**over):
    d = {
        "entry_id": "00AA",
        "internet_message_id": "<7f3a9c@example.com>",
        "conversation_id": "CAE1",
        "subject": "Re: Budget Q3",
        "from": "Jane Doe",
        "from_address": "jane.doe@example.com",
        "to": "Hux Waitt",
        "cc": "",
        "recipients": [
            {"name": "Hux Waitt", "address": "hux@example.com", "type": "to"},
            {"name": "Carol Ng", "address": "carol@example.com", "type": "cc"},
        ],
        "received": "2026-08-22T09:14:00+02:00",
        "attachments": [{"index": 1, "filename": "Budget_Q3.xlsx", "size_bytes": 184320}, {"index": 2, "filename": "image001.png", "size_bytes": 4000}],
        "body": "Hi,\n\ncould you send the numbers?\n\nThanks\nJane\n\n> older quoted text",
        "body_trimmed": "Hi,\n\ncould you send the numbers?\n\nThanks\nJane",
    }
    d.update(over)
    return d


def test_save_email_creates_note_and_person(vault):
    att_dir = vault / "Administrator" / "Attachments" / "2026-08-22 Budget Q3"
    att_dir.mkdir(parents=True)
    res = workflows.save_email(
        mail_json(), "Jane asks for the Q3 numbers by Friday.", ["Send Q3 numbers to Jane by 2026-08-29 — owner: me"],
        attachments_saved=[str(att_dir / "Budget_Q3.xlsx")], msg_file=str(att_dir / "Budget Q3.msg"),
    )
    assert res["path"] == "Administrator/Emails/2026-08-22 Budget Q3.md" and res["action"] == "created"
    assert res["status"] == "todo" and res["person_path"] == "Administrator/Wiki/People/Jane Doe.md" and res["person_action"] == "created"
    assert res["followup_added"] is False
    text = (vault / res["path"]).read_text(encoding="utf-8")
    fm = fmt.split_note(text)[0]
    assert fm["from_link"] == "[[Wiki/People/Jane Doe]]" and fm["to"] == ["hux@example.com"] and fm["cc"] == ["carol@example.com"]
    assert fm["has_attachments"] is True
    assert fm["attachments"] == ["[[Administrator/Attachments/2026-08-22 Budget Q3/Budget_Q3.xlsx|Budget_Q3.xlsx]]"]
    assert fm["msg_file"] == "[[Administrator/Attachments/2026-08-22 Budget Q3/Budget Q3.msg|Budget Q3.msg]]"
    assert "**From:** [[Wiki/People/Jane Doe]] <jane.doe@example.com>" in text
    assert "**To:** Hux Waitt <hux@example.com>" in text and "**Cc:** Carol Ng <carol@example.com>" in text
    assert "**Received:** 2026-08-22 09:14" in text
    assert "## Summary\n\nJane asks for the Q3 numbers by Friday.\n" in text
    assert "- [ ] Send Q3 numbers to Jane by 2026-08-29 — owner: me" in text
    assert "## Body\n\nHi,\n\ncould you send the numbers?\n\nThanks\nJane\n" in text and "older quoted" not in text
    assert "- [[Administrator/Attachments/2026-08-22 Budget Q3/Budget Q3.msg|Budget Q3.msg]] (original message)" in text
    assert "- [[Administrator/Attachments/2026-08-22 Budget Q3/Budget_Q3.xlsx|Budget_Q3.xlsx]] (180 KB)" in text
    assert "- image001.png (4 KB, not exported)" in text
    ptext = (vault / res["person_path"]).read_text(encoding="utf-8")
    pfm = fmt.split_note(ptext)[0]
    assert pfm["last_contact"] == "2026-08-22T09:14:00+02:00" and pfm["aliases"] == []
    assert pfm["type"] == "person" and pfm["status"] == "draft" and pfm["email"] == "jane.doe@example.com"
    assert "# Jane Doe\n\nJane Doe (jane.doe@example.com).\n\n## Facts\n" in ptext
    assert "## Records\n\n- 2026-08-22 — [[Emails/2026-08-22 Budget Q3]] — Jane asks for the Q3 numbers by Friday." in ptext
    assert fmt.split_note((vault / res["path"]).read_text(encoding="utf-8"))[0]["wiki"] == ["[[Wiki/People/Jane Doe]]"]

    # same mail again: an Update on the note, a new line on the person, no second file
    res2 = workflows.save_email(mail_json(from_="x"), "Again.", [])
    assert res2["action"] == "appended" and res2["person_action"] == "appended"
    text = (vault / res["path"]).read_text(encoding="utf-8")
    assert text.count("## Body") == 1 and "### Summary\n\nAgain." in text
    assert len(list((vault / "Administrator" / "Emails").glob("*.md"))) == 1
    assert len(list((vault / "Administrator" / "Wiki" / "People").glob("*.md"))) == 1
    ptext = (vault / res["person_path"]).read_text(encoding="utf-8")
    assert ptext.count("[[Emails/2026-08-22 Budget Q3]]") == 1  # Records line not doubled


def test_save_email_updates_person_and_follow_ups(vault):
    person(vault, "Jane Doe", "jane.doe@example.com")
    res = workflows.save_email(mail_json(**{"from": "Doe, Jane"}), "s", [], status="waiting")
    assert res["person_action"] == "appended" and res["followup_added"] is True
    pfm = fmt.split_note((vault / res["person_path"]).read_text(encoding="utf-8"))[0]
    assert pfm["aliases"] == ["Doe, Jane"] and pfm["last_contact"] == "2026-08-22T09:14:00+02:00"
    fu = (vault / "Administrator" / "Follow-ups.md").read_text(encoding="utf-8")
    assert "| 2026-08-22 | [[Wiki/People/Jane Doe]] | Budget Q3 | [[Emails/2026-08-22 Budget Q3]] |" in fu and "<!-- entry_id: 00AA -->" in fu
    # from the user: no person note for self, waiting row points at the recipient
    res2 = workflows.save_email(
        mail_json(entry_id="00AB", internet_message_id="<own@example.com>", from_address="hux@example.com", **{"from": "Hux Waitt"}),
        "I asked Hux's colleague for the numbers.", ["Get numbers — owner: Hux Waitt"], self_addresses=["HUX@example.com"],
    )
    assert res2["status"] == "waiting" and res2["person_path"] is None
    fu = (vault / "Administrator" / "Follow-ups.md").read_text(encoding="utf-8")
    assert "| 2026-08-22 | Hux Waitt | Budget Q3 | [[Emails/2026-08-22 Budget Q3 (2)]] |" in fu
    fm = fmt.split_note((vault / res2["path"]).read_text(encoding="utf-8"))[0]
    assert fm["from_link"] == ""
    with pytest.raises(Exception):
        workflows.save_email({"subject": "x"}, "s")


# ------------------------------------------------------------------ prep context


def meeting_fm(key="GID1|2026-08-25T13:00:00+02:00", start="2026-08-25T13:00:00+02:00", **over):
    fm = {"type": "meeting", "source": "outlook", "global_id": "GID1", "occurrence_key": key, "subject": "Supplier sync",
          "start": start, "end": start.replace("13:00", "14:00"), "location": "Room 4", "organizer": "jane.doe@example.com",
          "organizer_link": "[[Wiki/People/Jane Doe]]", "attendees": ["jane.doe@example.com", "tom.lee@example.com"],
          "attendee_links": ["[[Wiki/People/Jane Doe]]", "[[Wiki/People/Tom Lee]]"], "is_recurring": True, "status": "upcoming", "created_by": CB}
    fm.update(over)
    return fm


def test_prep_context(vault):
    person(vault)
    store.write("meeting", meeting_fm("GID1|2026-08-18T13:00:00+02:00", "2026-08-18T13:00:00+02:00", status="held"),
                "# Supplier sync\n\n## Action items\n\n- [ ] Send forecast — owner: me\n- [x] done thing\n\n## Update x\n\n### Action items\n\n- [ ] Confirm address — owner: Tom Lee\n\n### Closed\n\n- [ ] not this one\n")
    store.write("meeting", meeting_fm("GID1|2026-08-11T13:00:00+02:00", "2026-08-11T13:00:00+02:00", status="held"), "older")
    store.append_row("Administrator/Follow-ups.md", "Open", ["2026-08-21", "[[Wiki/People/Jane Doe]]", "Contract draft", "", "2026-08-22"], "00AC")
    store.append_row("Administrator/Follow-ups.md", "Open", ["2026-08-21", "Tom Lee", "Schedule", "", "2026-08-22"], "00AD")
    store.append_row("Administrator/Follow-ups.md", "Open", ["2026-08-21", "Someone Else", "x", "", "2026-08-22"], "00AE")

    ctx = workflows.prep_context("GID1|2026-08-25T13:00:00+02:00", "", ["jane.doe@example.com", {"name": "Tom Lee", "address": "tom.lee@example.com"}])
    assert ctx["existing_note"] is None
    assert ctx["previous_occurrence"]["path"].startswith("Administrator/Meetings/2026-08-18 1300")
    assert ctx["previous_occurrence"]["open_actions"] == ["- [ ] Send forecast — owner: me", "- [ ] Confirm address — owner: Tom Lee"]
    jane, tom = ctx["people"]
    assert jane["path"] == "Administrator/Wiki/People/Jane Doe.md" and jane["last_contact"] == "2026-08-20T09:00:00+02:00"
    # the old-style body became Records lines on the wiki page (status tails dropped)
    assert jane["last_emails"] == ["- 2026-08-20 — [[Emails/2026-08-20 Old mail]]", "- 2026-08-10 — [[Emails/2026-08-10 Older]]"]
    assert tom["path"] is None and tom["name"] == "Tom Lee"
    assert len(ctx["followups_open"]) == 2 and all("Someone Else" not in r for r in ctx["followups_open"])
    # wiki[]: the attendee's person page (draft, identity lead), no topic without a subject match
    assert [w["path"] for w in ctx["wiki"]] == ["Administrator/Wiki/People/Jane Doe.md"]
    assert ctx["wiki"][0]["type"] == "person" and ctx["wiki"][0]["lead"] == "Jane Doe (jane.doe@example.com)." and ctx["wiki"][0]["facts"] == []

    store.write("meeting", meeting_fm(), "this one")
    ctx2 = workflows.prep_context("GID1|2026-08-25T13:00:00+02:00")
    assert ctx2["existing_note"].startswith("Administrator/Meetings/2026-08-25 1300") and ctx2["existing_status"] == "upcoming"
    assert ctx2["previous_occurrence"]["path"].startswith("Administrator/Meetings/2026-08-18 1300")


# ------------------------------------------------------------------ weekly facts


def test_weekly_facts(vault):
    d = {"type": "daily", "source": "outlook", "date": "2026-08-19", "folder": "inbox", "since": "s", "inbox_checked": "c",
         "mails_seen": 3, "status": "todo", "created_by": CB}
    body = (
        "# 2026-08-19\n\n## Inbox (since s)\n\n| # | Label | From | Subject | Received | Why | Note |\n| --- | --- | --- | --- | --- | --- | --- |\n"
        "| 1 | act | Jane Doe | Budget Q3 | 09:14 | why | [[Emails/2026-08-19 Budget Q3]] <!-- entry_id: 00A1 --> |\n"
        "| 2 | reply | Bob Lee | Offsite | 08:40 | why | <!-- entry_id: 00A2 --> |\n"
        "| 3 | act | Sam | Done thing | 08:00 | why | <!-- entry_id: 00A3 --> |\n"
        "| 4 | fyi | IT | Maint | 07:00 | why | <!-- entry_id: 00A4 --> |\n\n"
        "## To do\n\n- [ ] act — Budget Q3 (Jane Doe)\n- [x] act — Done thing (Sam)\n"
    )
    store.write("daily", d, body)
    store.write("daily", dict(d, date="2026-08-24"), "next week")
    efm = {"type": "email", "source": "outlook", "internet_message_id": "", "entry_id": "00A2", "conversation_id": "C", "subject": "Offsite",
           "from": "bob@example.com", "from_name": "Bob Lee", "from_link": "", "to": [], "cc": [], "received": "2026-08-19T08:40:00+02:00",
           "status": "done", "created_by": CB}
    store.write("email", efm, "x")
    store.append_row("Administrator/Follow-ups.md", "Open", ["2026-08-16", "[[Wiki/People/Tom Lee]]", "Delivery", "", "2026-08-22"], "00B1")
    store.write("meeting", meeting_fm("GID1|2026-08-18T13:00:00+02:00", "2026-08-18T13:00:00+02:00", status="held"), "# m\n\n## Action items\n\n- [ ] Confirm address — owner: Tom Lee\n")
    store.write("meeting", meeting_fm("GID1|2026-08-20T13:00:00+02:00", "2026-08-20T13:00:00+02:00"), "upcoming in the past")
    person(vault, "Carol Ng", "carol@example.com", last_contact="2026-07-10T10:00:00+02:00")
    person(vault, "Fresh", "fresh@example.com", last_contact="2026-08-20T10:00:00+02:00")
    person(vault, "Stub", "stub@example.com", last_contact="")

    facts = workflows.weekly_facts("2026-W34", today="2026-08-22")
    assert facts["start"] == "2026-08-17" and facts["end"] == "2026-08-23"
    assert [(r["subject"], r["label"]) for r in facts["open_from_inbox"]] == [("Budget Q3", "act")]
    assert facts["open_from_inbox"][0]["note"] == "[[Emails/2026-08-19 Budget Q3]]" and facts["open_from_inbox"][0]["entry_id"] == "00A1"
    assert facts["waiting"] == [{"since": "2026-08-16", "who": "[[Wiki/People/Tom Lee]]", "what": "Delivery", "email": "", "age_days": 6}]
    assert len(facts["meetings_held"]) == 1 and facts["meetings_held"][0]["unchecked_actions"] == ["- [ ] Confirm address — owner: Tom Lee"]
    assert [m["date"] for m in facts["no_notes"]] == ["2026-08-20"]
    assert [(q["name"], q["days"]) for q in facts["quiet_people"]] == [("Carol Ng", 44)]
    with pytest.raises(store.VaultError):
        workflows.weekly_facts("34")


# ------------------------------------------------------------------ transcript


TRANSCRIPT = """PART 1 of 1
[13:02] Jane Doe: Let's start with the contract.
[13:03] Hux Waitt: Yes. I'll sign version 3 tomorrow.
wrapped line without a name
[13:04] JANE DOE: Good, so we agreed on net 45.
[13:05] Tom Lee: One thing from my side.
12. Priya: I'll send the packaging spec draft next week.
END OF TRANSCRIPT
Speakers:
Jane Doe
Hux Waitt
Tom Lee
Priya
"""


def test_attach_transcript_callout_and_link(vault):
    mpath = store.write("meeting", meeting_fm(), "# Supplier sync\n\n## Notes\n\n_(none yet)_")["path"]
    folder = vault / "Administrator" / "Attachments" / "2026-08-25 1300 Supplier sync"
    folder.mkdir(parents=True)
    (folder / "transcript.md").write_text(TRANSCRIPT, encoding="utf-8")
    res = workflows.attach_transcript(mpath, "Administrator/Attachments/2026-08-25 1300 Supplier sync/transcript.md")
    assert res["turns"] == 5 and res["speakers"] == ["Jane Doe", "Hux Waitt", "Tom Lee", "Priya"] and res["linked"] is False
    assert res["speaker_links"] == ["[[Wiki/People/Jane Doe]]", "Hux Waitt", "[[Wiki/People/Tom Lee]]", "Priya"]
    text = (vault / mpath).read_text(encoding="utf-8")
    assert "_(none yet)_\n\n## Update " in text
    assert "### Transcript\n\n**Speakers:** [[Wiki/People/Jane Doe]], Hux Waitt, [[Wiki/People/Tom Lee]], Priya\n\n> [!note]- Transcript (5 turns, 4 speakers)\n> [13:02] Jane Doe:" in text
    assert "> wrapped line without a name\n" in text and "PART 1" not in text and "END OF TRANSCRIPT" not in text and "\nSpeakers:\n" not in text

    big = "\n".join(f"[13:{i % 60:02d}] Jane Doe: line {i}" for i in range(401))
    (folder / "big.md").write_text(big, encoding="utf-8")
    res2 = workflows.attach_transcript(mpath, "Administrator/Attachments/2026-08-25 1300 Supplier sync/big.md")
    assert res2["linked"] is True and res2["turns"] == 401 and res2["speakers"] == ["Jane Doe"]
    text = (vault / mpath).read_text(encoding="utf-8")
    assert "Full text: [[Administrator/Attachments/2026-08-25 1300 Supplier sync/big|big.md]] (401 turns, 1 speakers, 401 lines)" in text
    assert "line 400" not in text

    with pytest.raises(store.VaultError):
        workflows.attach_transcript(mpath, "Administrator/Follow-ups.md")
    with pytest.raises(store.VaultError):
        workflows.attach_transcript("Administrator/Follow-ups.md", "Administrator/Attachments/2026-08-25 1300 Supplier sync/big.md")


# ------------------------------------------------------------------ fields


def test_find_and_list_fields(vault):
    person(vault)
    hit = store.find("person", "jane.doe@example.com", fields=["name", "last_contact", "nope"])
    assert hit["frontmatter"] == {"name": "Jane Doe", "last_contact": "2026-08-20T09:00:00+02:00"}
    assert store.list_notes("person", fields=["email"]) == [{"path": "Administrator/Wiki/People/Jane Doe.md", "frontmatter": {"email": "jane.doe@example.com"}}]
    assert "aliases" in store.find("person", "jane.doe@example.com")["frontmatter"]


# ------------------------------------------------------------------ server


def test_server_round_trip_v05(vault):
    server = build_server()

    def call(name, args):
        out = asyncio.run(server.call_tool(name, args))
        return json.loads(out[0].text if isinstance(out, list) else out[0][0].text)

    assert call("vault_rules", {})["labels"] == []
    r = call("vault_rules", {"action": "match", "items": [item(8, from_address="noreply@x.example")]})
    assert r["results"][0]["label"] == "fyi"
    prep = call("vault_inbox_prepare", {"items": [item(1)], "date": DAY})
    assert prep["to_label"][0]["entry_id"] == "00A1"
    w = call("vault_write_daily", {"date": DAY, "labels": [{"entry_id": "00A1", "label": "fyi", "reason": "r"}], "since": "s"})
    assert w["action"] == "created"
    assert call("vault_find", {"type": "daily", "identity": DAY, "fields": ["date"]})["frontmatter"] == {"date": DAY}
    assert call("vault_weekly_facts", {"week": "2026-W34", "today": DAY})["open_from_inbox"] == []
    with pytest.raises(Exception):
        asyncio.run(server.call_tool("vault_rules", {"action": "nope"}))
