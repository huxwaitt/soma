"""Document records: reading a file part by part, the record contract on every
kind, locators in fact sources, and the watched folders."""

from __future__ import annotations

import asyncio
import json
import zipfile
from datetime import datetime, timedelta

import pytest

from soma_vault import documents, notes, store, wiki, wiki_lint, workflows
from soma_vault.server import build_server
from soma_vault.store import VaultError

CB = "soma/0.4.2"
A = "Soma"


@pytest.fixture
def vault(tmp_path, monkeypatch):
    root = tmp_path / "Vault"
    root.mkdir()
    monkeypatch.setenv("SOMA_VAULT", str(root))
    store.init(created_by=CB)
    return root


def text_of(root, rel):
    return (root / rel).read_text(encoding="utf-8")


def fm_of(root, rel):
    return store.read(rel)["frontmatter"]


# ------------------------------------------------------------------ builders


WNS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
ANS = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
PNS = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
SNS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
RNS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
PKG = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'


def _par(text, style=""):
    pr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{pr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def docx(path, blocks):
    """blocks: [("heading"|"text", value)] plus ("table", [[cell, ...], ...])."""
    body = []
    for kind, value in blocks:
        if kind == "heading":
            body.append(_par(value, "Heading1"))
        elif kind == "text":
            body.append(_par(value))
        else:
            rows = "".join(
                "<w:tr>" + "".join(f"<w:tc>{_par(c)}</w:tc>" for c in row) + "</w:tr>" for row in value
            )
            body.append(f"<w:tbl>{rows}</w:tbl>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", f"<w:document {WNS}><w:body>{''.join(body)}</w:body></w:document>")
    return path


def pptx(path, slides):
    """slides: [(title, body, notes)]."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        for i, (title, text, note) in enumerate(slides, 1):
            z.writestr(
                f"ppt/slides/slide{i}.xml",
                f"<p:sld {PNS} {ANS}><p:cSld><p:spTree>"
                '<p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
                f"<p:txBody><a:p><a:r><a:t>{title}</a:t></a:r></a:p></p:txBody></p:sp>"
                "<p:sp><p:nvSpPr><p:nvPr/></p:nvSpPr>"
                f"<p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>"
                "</p:spTree></p:cSld></p:sld>",
            )
            if note:
                z.writestr(
                    f"ppt/notesSlides/notesSlide{i}.xml",
                    f"<p:notes {PNS} {ANS}><p:cSld><p:spTree><p:sp><p:txBody>"
                    f"<a:p><a:r><a:t>{note}</a:t></a:r></a:p></p:txBody></p:sp>"
                    "</p:spTree></p:cSld></p:notes>",
                )
    return path


def xlsx(path, sheets):
    """sheets: {name: [[cell, ...], ...]}; every cell is written as an inline string."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        names = list(sheets)
        z.writestr(
            "xl/workbook.xml",
            f"<workbook {SNS} {RNS}><sheets>"
            + "".join(f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, 1))
            + "</sheets></workbook>",
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            f"<Relationships {PKG}>"
            + "".join(f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(names) + 1))
            + "</Relationships>",
        )
        for i, name in enumerate(names, 1):
            rows = []
            for r, row in enumerate(sheets[name], 1):
                cells = "".join(
                    f'<c r="{chr(65 + c)}{r}" t="inlineStr"><is><t>{value}</t></is></c>'
                    for c, value in enumerate(row)
                    if str(value) != ""
                )
                rows.append(f'<row r="{r}">{cells}</row>')
            z.writestr(f"xl/worksheets/sheet{i}.xml", f"<worksheet {SNS}><sheetData>{''.join(rows)}</sheetData></worksheet>")
    return path


def xlsx_shared(path, sheets):
    """The same workbook the other way round: shared strings, and part names
    written from the root of the file ("/xl/worksheets/sheet2.xml")."""
    names = list(sheets)
    strings = []
    for rows in sheets.values():
        for row in rows:
            for value in row:
                if str(value) and str(value) not in strings:
                    strings.append(str(value))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(
            "xl/workbook.xml",
            f"<workbook {SNS} {RNS}><sheets>"
            + "".join(f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, 1))
            + "</sheets></workbook>",
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            f"<Relationships {PKG}>"
            + "".join(f'<Relationship Id="rId{i}" Target="/xl/worksheets/sheet{i}.xml"/>' for i in range(1, len(names) + 1))
            + "</Relationships>",
        )
        z.writestr("xl/sharedStrings.xml", f"<sst {SNS}>" + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
        for i, name in enumerate(names, 1):
            rows = []
            for r, row in enumerate(sheets[name], 1):
                cells = "".join(
                    f'<c r="{chr(65 + c)}{r}" t="s"><v>{strings.index(str(value))}</v></c>'
                    for c, value in enumerate(row)
                    if str(value) != ""
                )
                rows.append(f'<row r="{r}">{cells}</row>')
            z.writestr(f"xl/worksheets/sheet{i}.xml", f"<worksheet {SNS}><sheetData>{''.join(rows)}</sheetData></worksheet>")
    return path


def mail_json(**over):
    mail = {
        "entry_id": "00AA",
        "internet_message_id": "<7f3a9c@example.com>",
        "conversation_id": "CONV1",
        "subject": "Q3 numbers",
        "from": "Jane Doe",
        "from_address": "jane.doe@example.com",
        "recipients": [{"name": "Hux", "address": "hux@example.com", "type": "to"}],
        "received": "2026-08-22T09:14:00+02:00",
        "body": "Numbers attached.",
        "attachments": [],
    }
    mail.update(over)
    return mail


# ---------------------------------------------------------------- extraction


def test_docx_reads_headings_paragraphs_and_tables_in_order(vault):
    p = docx(vault / "notes.docx", [
        ("text", "Before any heading."),
        ("heading", "Pricing"),
        ("text", "Net 45 agreed."),
        ("table", [["Item", "Cost"], ["Setup", "500"]]),
        ("heading", "Next steps"),
        ("text", "Sign by Friday."),
    ])
    out = documents.extract(p)
    assert out["format"] == "docx" and out["parts"] == 3 and out["empty"] is False
    assert [s["locator"] for s in out["sections"]] == ["p1", "p2", "p3"]
    assert [s["heading"] for s in out["sections"]] == ["part 1", "Pricing", "Next steps"]
    assert out["sections"][0]["text"] == "Before any heading."
    assert out["sections"][1]["text"] == "Net 45 agreed.\n\nItem | Cost\nSetup | 500"
    assert out["chars"] == sum(s["chars"] for s in out["sections"])


def test_pptx_reads_slide_titles_text_and_notes(vault):
    p = pptx(vault / "deck.pptx", [("Agenda", "Why we are here", ""), ("Pricing", "Net 45 agreed", "Say it plainly")])
    out = documents.extract(p)
    assert out["format"] == "pptx" and out["parts"] == 2
    assert [(s["locator"], s["heading"]) for s in out["sections"]] == [("s1", "Agenda"), ("s2", "Pricing")]
    assert out["sections"][1]["text"] == "Net 45 agreed\n\nNotes: Say it plainly"


def test_xlsx_reads_each_sheet_as_rows_with_the_first_cell_address(vault):
    p = xlsx(vault / "book.xlsx", {"Sales": [["Name", "Q3"], ["Jane", "42"]], "Notes": [["", "later"]]})
    out = documents.extract(p)
    assert out["format"] == "xlsx" and out["parts"] == 2
    assert [s["locator"] for s in out["sections"]] == ["Sales", "Notes"]
    assert out["sections"][0]["text"] == "A1: Name | Q3\nA2: Jane | 42"
    assert out["sections"][1]["text"] == "B1: later"  # the address is the first cell that holds something


def test_shared_strings_and_root_named_sheets_are_read(vault):
    p = xlsx_shared(vault / "book.xlsx", {"Sales EU": [["Nom", "Chiffre"], ["Jérôme", "42"]], "Ventes": [["Café"]]})
    out = documents.extract(p)
    assert [s["locator"] for s in out["sections"]] == ["Sales EU", "Ventes"]
    assert out["sections"][0]["text"] == "A1: Nom | Chiffre\nA2: Jérôme | 42"
    assert out["sections"][1]["text"] == "A1: Café"


def test_a_sheet_whose_name_holds_a_space_can_be_read_back(vault):
    p = xlsx_shared(vault / "book.xlsx", {"Sales EU": [["Nom", "Chiffre"]]})
    res = workflows.save_document(str(p), "One sheet.", created_by=CB)
    got = store.read(res["path"], "Sales EU")["section"]
    assert got["locator"] == "Sales EU" and got["text"] == "A1: Nom | Chiffre"


def test_text_markdown_and_csv_are_read_as_they_are(vault):
    (vault / "plain.txt").write_text("just words", encoding="utf-8")
    (vault / "page.md").write_text("# Title\n\nbody", encoding="utf-8")
    (vault / "rows.csv").write_text("Name,Q3\nJane,42\n\n", encoding="utf-8")
    assert documents.extract(vault / "plain.txt")["sections"] == [
        {"locator": "p1", "heading": "plain", "text": "just words", "chars": 10}
    ]
    assert documents.extract(vault / "page.md")["sections"][0]["text"] == "# Title\n\nbody"
    assert documents.extract(vault / "rows.csv")["sections"][0]["text"] == "Name | Q3\nJane | 42"


def test_an_empty_file_answers_empty(vault):
    (vault / "nothing.txt").write_text("", encoding="utf-8")
    out = documents.extract(vault / "nothing.txt")
    assert out["empty"] is True and out["chars"] == 0


def test_a_format_it_cannot_read_is_refused(vault):
    (vault / "picture.png").write_bytes(b"\x89PNG")
    with pytest.raises(VaultError, match="cannot read .png"):
        documents.extract(vault / "picture.png")
    with pytest.raises(VaultError):
        documents.extract(vault / "missing.txt")


def test_a_pdf_without_pypdf_names_the_extra(vault, monkeypatch):
    import builtins

    real = builtins.__import__

    def no_pypdf(name, *args, **kw):
        if name == "pypdf":
            raise ImportError("no pypdf")
        return real(name, *args, **kw)

    (vault / "paper.pdf").write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(builtins, "__import__", no_pypdf)
    with pytest.raises(VaultError, match="search"):
        documents.extract(vault / "paper.pdf")


def test_a_broken_office_file_is_refused_not_a_crash(vault):
    (vault / "broken.docx").write_bytes(b"not a zip")
    with pytest.raises(VaultError, match="could not be read"):
        documents.extract(vault / "broken.docx")


def test_pdf_pages_become_p_sections(vault):
    pypdf = pytest.importorskip("pypdf", reason="pypdf comes with the search extra")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    p = vault / "scan.pdf"
    with p.open("wb") as f:
        writer.write(f)
    out = documents.extract(p)
    assert out["format"] == "pdf" and out["parts"] == 2
    assert [s["locator"] for s in out["sections"]] == ["p1", "p2"]
    # blank pages carry no text layer, which is what a scan looks like
    assert out["empty"] is True


# ------------------------------------------------------------------- records


def test_save_document_writes_the_record_and_answers_its_parts(vault):
    p = pptx(vault / "Q3 deck.pptx", [("Agenda", "Why we are here", ""), ("Pricing", "Net 45 agreed", "")])
    res = workflows.save_document(str(p), "The Q3 deck: pricing agreed.", ["Confirm net 45 with Jane"], created_by=CB)
    assert res["action"] == "created" and res["path"].startswith(f"{A}/Documents/")
    assert res["path"].endswith(" Q3 deck.md") and res["format"] == "pptx"
    assert res["parts"] == 2 and res["empty"] is False and res["text_file"] is None
    assert res["sections"] == [
        {"locator": "s1", "heading": "Agenda", "chars": 15},
        {"locator": "s2", "heading": "Pricing", "chars": 13},
    ]
    fm = fm_of(vault, res["path"])
    assert fm["record_id"] == res["record_id"] and len(fm["hash"]) == 16 and fm["hash"] == res["record_id"]
    assert fm["format"] == "pptx" and fm["parts"] == 2 and fm["chars"] == 28
    assert fm["from_email"] == "" and fm["text_file"] == "" and fm["path"] == str(p).replace("\\", "/")
    text = text_of(vault, res["path"])
    assert "# Q3 deck\n" in text and "**Read:** pptx, 2 parts, 28 characters" in text
    assert "## Summary\n\nThe Q3 deck: pricing agreed." in text
    assert "- [ ] Confirm net 45 with Jane" in text
    assert "## Content\n\n### s1 — Agenda\n\nWhy we are here\n\n### s2 — Pricing\n\nNet 45 agreed" in text
    assert "## Files\n\n- `" in text


def test_the_same_file_again_is_unchanged_and_a_new_version_appends_an_update(vault):
    p = pptx(vault / "deck.pptx", [("Agenda", "Why we are here", "")])
    first = workflows.save_document(str(p), "One slide.", created_by=CB)
    before = text_of(vault, first["path"])

    again = workflows.save_document(str(p), "One slide.", created_by=CB)
    assert again["action"] == "unchanged" and again["path"] == first["path"]
    assert again["record_id"] == first["record_id"] and text_of(vault, first["path"]) == before

    pptx(p, [("Agenda", "Why we are here", ""), ("Pricing", "Net 60 now", "")])
    changed = workflows.save_document(str(p), "Two slides now.", created_by=CB)
    assert changed["action"] == "appended" and changed["path"] == first["path"] and changed["parts"] == 2
    # the id a fact may already cite does not move; the file's hash does
    assert changed["record_id"] == first["record_id"]
    fm = fm_of(vault, first["path"])
    assert fm["record_id"] == first["record_id"] and fm["hash"] != first["record_id"]
    assert fm["parts"] == 2 and fm["chars"] == 25
    text = text_of(vault, first["path"])
    assert "\n## Update " in text and "### s2 — Pricing\n\nNet 60 now" in text
    assert len(list((vault / A / "Documents").glob("*.md"))) == 1
    # the newest part with that locator is what a read answers
    assert store.read(first["path"], "s1")["section"]["text"] == "Why we are here"
    assert store.read(first["path"], "s2")["section"]["text"] == "Net 60 now"


def test_text_over_the_cap_goes_to_a_file_and_the_record_keeps_the_first_characters(vault):
    p = vault / "long.md"
    p.write_text("A" * (workflows.DOCUMENT_CHARS + 100), encoding="utf-8")
    res = workflows.save_document(str(p), "Very long.", created_by=CB)
    assert res["chars"] == workflows.DOCUMENT_CHARS + 100
    assert res["text_file"] == f"{A}/Attachments/long/text.md"
    kept = text_of(vault, res["text_file"])
    assert kept.startswith("### p1 — long\n\nAAA") and len(kept) > workflows.DOCUMENT_CHARS
    text = text_of(vault, res["path"])
    assert "A" * workflows.DOCUMENT_SECTION_CHARS in text
    assert "A" * (workflows.DOCUMENT_SECTION_CHARS + 1) not in text
    assert "… (full text: [[Attachments/long/text]])" in text
    assert fm_of(vault, res["path"])["text_file"] == "[[Attachments/long/text]]"


def test_a_document_from_a_mail_links_both_ways(vault):
    em = workflows.save_email(mail_json(), "Jane sent the numbers.", [], created_by=CB)
    p = vault / "numbers.csv"
    p.write_text("Name,Q3\nJane,42\n", encoding="utf-8")
    doc = workflows.save_document(str(p), "The Q3 sheet.", from_email=em["path"], created_by=CB)
    # the mail's date, not the file's
    assert doc["path"] == f"{A}/Documents/2026-08-22 numbers.md"
    assert fm_of(vault, doc["path"])["from_email"] == "[[Emails/2026-08-22 Q3 numbers]]"
    assert "- [[Emails/2026-08-22 Q3 numbers]] — arrived as an attachment" in text_of(vault, doc["path"])
    mail_text = text_of(vault, em["path"])
    assert "\n## Update " in mail_text
    assert "### Files\n\n- [[Documents/2026-08-22 numbers]] — numbers.csv, read into the vault" in mail_text
    assert doc["from_email"] == "[[Emails/2026-08-22 Q3 numbers]]" and doc["linked"] is True
    # a second save of the same file does not double either line
    again = workflows.save_document(str(p), "The Q3 sheet.", from_email="[[Emails/2026-08-22 Q3 numbers]]", created_by=CB)
    assert again["action"] == "unchanged" and again["linked"] is False
    assert text_of(vault, em["path"]).count("[[Documents/2026-08-22 numbers]]") == 1
    assert text_of(vault, doc["path"]).count("— arrived as an attachment") == 1
    with pytest.raises(VaultError, match="No such record"):
        workflows.save_document(str(p), "x", from_email=f"{A}/Emails/nope.md", created_by=CB)


def test_the_same_file_under_a_new_path_is_still_linked_to_its_mail(vault):
    """An attachment exported from a mail may be a copy of a file already read."""
    p = vault / "terms.md"
    p.write_text("Net 45 agreed.", encoding="utf-8")
    first = workflows.save_document(str(p), "The terms.", created_by=CB)
    em = workflows.save_email(mail_json(), "Jane sent the terms.", [], created_by=CB)
    copy = vault / A / "Attachments" / "terms.md"
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text("Net 45 agreed.", encoding="utf-8")
    same = workflows.save_document(str(copy), "The terms.", from_email=em["path"], created_by=CB)
    assert same["action"] == "unchanged" and same["path"] == first["path"] and same["linked"] is True
    assert fm_of(vault, first["path"])["from_email"] == "[[Emails/2026-08-22 Q3 numbers]]"
    assert "- [[Emails/2026-08-22 Q3 numbers]] — arrived as an attachment" in text_of(vault, first["path"])
    assert "[[Documents/" in text_of(vault, em["path"])


def test_an_empty_pdf_says_so_in_the_record(vault):
    p = vault / "scan.txt"
    p.write_text("", encoding="utf-8")
    res = workflows.save_document(str(p), "A scan.", created_by=CB)
    assert res["empty"] is True and res["parts"] == 1
    assert "## Content\n\nNo text could be read (scanned?)." in text_of(vault, res["path"])


def test_a_file_it_cannot_read_and_a_missing_file_are_refused(vault):
    (vault / "picture.png").write_bytes(b"\x89PNG")
    with pytest.raises(VaultError, match="cannot read"):
        workflows.save_document(str(vault / "picture.png"), "x", created_by=CB)
    with pytest.raises(VaultError, match="No such file"):
        workflows.save_document(str(vault / "gone.txt"), "x", created_by=CB)


# ------------------------------------------------------- reading one part


def test_vault_read_answers_one_part_by_locator_or_heading(vault):
    p = pptx(vault / "deck.pptx", [("Agenda", "Why we are here", ""), ("Pricing", "Net 45 agreed", "")])
    res = workflows.save_document(str(p), "A deck.", created_by=CB)
    got = store.read(res["path"], "s2")
    assert got["section"] == {"locator": "s2", "heading": "Pricing", "text": "Net 45 agreed", "chars": 13}
    assert "body" not in got and "s2 — Pricing" in got["sections"]
    assert store.read(res["path"], "Pricing")["section"]["locator"] == "s2"
    assert store.read(res["path"], "s2 — Pricing")["section"]["locator"] == "s2"
    assert store.read(res["path"], "Summary")["section"]["text"] == "A deck."
    with pytest.raises(VaultError, match="No section"):
        store.read(res["path"], "s9")


# --------------------------------------------------------- record contract


def test_every_record_kind_carries_the_core_keys_in_one_order(vault):
    core = ["type"] + list(notes.CORE_KEYS)

    em = workflows.save_email(mail_json(), "Jane sent the numbers.", [], created_by=CB)
    chat = workflows.save_chat(
        {"id": "19:abc@thread.v2", "title": "Q3 budget", "type": "group", "members": ["Jane Doe"], "account": "acme"},
        [{"id": "m1", "time": "2026-08-21T09:14:00+02:00", "sender": "Jane Doe", "text": "Morning"}],
        created_by=CB,
    )
    daily = workflows.write_daily("2026-08-22", [], items=[], since="2026-08-22T00:00:00+02:00", created_by=CB)
    p = vault / "notes.txt"
    p.write_text("some words", encoding="utf-8")
    doc = workflows.save_document(str(p), "Some words.", created_by=CB)
    meeting = store.write("meeting", {
        "type": "meeting", "source": "outlook", "global_id": "G1", "occurrence_key": "G1|2026-08-20T13:00:00+02:00",
        "subject": "Budget review", "start": "2026-08-20T13:00:00+02:00", "end": "2026-08-20T14:00:00+02:00",
        "location": "Teams", "organizer": "jane.doe@example.com", "organizer_link": "[[Wiki/People/Jane Doe]]",
        "attendees": ["hux@example.com"], "attendee_links": ["[[Wiki/People/Hux]]"], "is_recurring": False,
        "status": "held", "created_by": CB,
    }, "# Budget review\n\n## Summary\n\nAgreed.")
    weekly = store.write("weekly", {
        "type": "weekly", "week": "2026-W34", "start": "2026-08-17", "end": "2026-08-23", "created_by": CB,
    }, "# 2026-W34")

    expect = {
        em["path"]: ("outlook", "<7f3a9c@example.com>", "Q3 numbers", "2026-08-22", ["[[Wiki/People/Jane Doe]]"]),
        chat["path"]: ("teams", "19:abc@thread.v2|2026-08-21", "Q3 budget", "2026-08-21", []),
        daily["path"]: ("outlook", "2026-08-22", "2026-08-22", "2026-08-22", []),
        doc["path"]: ("file", doc["record_id"], "notes", datetime.now().date().isoformat(), []),
        meeting["path"]: ("outlook", "G1|2026-08-20T13:00:00+02:00", "Budget review", "2026-08-20",
                          ["[[Wiki/People/Jane Doe]]", "[[Wiki/People/Hux]]"]),
        weekly["path"]: ("soma", "2026-W34", "2026-W34", "2026-08-17", []),
    }
    for path, (source, record_id, title, day, people) in expect.items():
        fm = fm_of(vault, path)
        assert list(fm)[: len(core)] == core, path
        assert (fm["source"], fm["record_id"], fm["title"], fm["date"], fm["people"]) == (source, record_id, title, day, people), path
        # nothing was read into the wiki yet, apart from the sender page a mail or chat writes
        sender = [] if path not in (em["path"], chat["path"]) else ["[[Wiki/People/Jane Doe]]"]
        assert fm["wiki"] == sender, path
        assert fm["ingested"] == "" and fm["created_by"] == CB, path
        for key in notes.schema(fm["type"])["required"]:
            assert key in fm, (path, key)


def test_a_thread_becomes_numbered_mail_sections(vault):
    thread = [
        {"received": "2026-08-21T16:02:00+02:00", "from": "hux@example.com", "body_trimmed": "Here they are."},
        {"received": "2026-08-20T09:00:00+02:00", "from": "jane.doe@example.com", "body_trimmed": "Can you send them?"},
    ]
    res = workflows.save_email(mail_json(), "Two mails.", [], thread=thread, created_by=CB)
    text = text_of(vault, res["path"])
    assert "## Content\n\n### m1 — 2026-08-20 09:00 jane.doe@example.com\n\nCan you send them?" in text
    assert "### m2 — 2026-08-21 16:02 hux@example.com\n\nHere they are." in text
    assert store.read(res["path"], "m2")["section"]["text"] == "Here they are."


def test_a_thread_written_into_the_body_is_numbered_too(vault):
    body = "### 2026-08-20 09:00 — jane.doe@example.com\n\nCan you send them?\n\n### 2026-08-21 16:02 — hux@example.com\n\nHere they are."
    res = workflows.save_email(mail_json(body=body), "Two mails.", [], created_by=CB)
    text = text_of(vault, res["path"])
    assert "### m1 — 2026-08-20 09:00 jane.doe@example.com" in text
    assert "### m2 — 2026-08-21 16:02 hux@example.com" in text


def test_an_append_never_blanks_a_key_a_record_already_holds(vault):
    em = workflows.save_email(mail_json(), "First.", [], created_by=CB)
    wiki.create("topic", "Q3 numbers", created_by=CB)
    wiki.ingest(em["path"], [{"path": "Wiki/Topics/q3-numbers", "ops": []}], created_by=CB)
    before = fm_of(vault, em["path"])
    assert before["wiki"] == ["[[Wiki/People/Jane Doe]]", "[[Wiki/Topics/q3-numbers]]"]
    assert before["ingested"] == wiki._today()
    workflows.save_email(mail_json(), "Again.", [], created_by=CB)
    after = fm_of(vault, em["path"])
    assert after["wiki"] == before["wiki"] and after["ingested"] == before["ingested"]


def test_a_single_heading_in_a_mail_body_is_not_a_thread(vault):
    body = "### Note\n\nThe one thing to know."
    res = workflows.save_email(mail_json(body=body), "One mail.", [], created_by=CB)
    assert "## Content\n\n### Note\n\nThe one thing to know." in text_of(vault, res["path"])


# -------------------------------------------------------------- locators


def test_a_fact_citing_a_part_counts_as_one_source_with_the_records_line(vault):
    p = pptx(vault / "deck.pptx", [("Agenda", "Why", ""), ("Pricing", "Net 45 agreed", ""), ("Risks", "Late", "")])
    doc = workflows.save_document(str(p), "A deck about pricing.", created_by=CB)
    out = wiki.ingest(doc["path"], [{
        "new": {"type": "topic", "title": "Supplier contract"},
        "ops": [
            {"op": "add", "text": "Net 45 payment terms agreed", "src": f"{doc['record_id']}#s2"},
            {"op": "add", "text": "Delivery may be late", "src": f"{doc['record_id']}#s3"},
        ],
    }], created_by=CB)
    page_path = out["pages"][0]["path"]
    text = text_of(vault, page_path)
    assert f'src:"{doc["record_id"]}#s2"' in text and f'src:"{doc["record_id"]}#s3"' in text
    assert "- [[Documents/" not in text  # the Records line carries the date first
    assert f"— [[Documents/{doc['path'].split('/')[-1][:-3]}]]" in text
    # one document, two facts and a Records line: one source
    assert fm_of(vault, page_path)["sources"] == 1
    page = wiki.parse_page(text, page_path)
    assert wiki.count_sources(vault, page) == 1
    assert wiki.src_record(f"{doc['record_id']}#s2") == doc["record_id"]
    assert wiki.src_record("user") == "user"
    # the record was marked as read into the wiki
    fm = fm_of(vault, doc["path"])
    assert fm["wiki"] == ["[[Wiki/Topics/supplier-contract]]"] and fm["ingested"] == out["ingested"]
    # and lint agrees with the count
    assert wiki_lint.lint(created_by=CB)["checks"]["4"]["count"] == 0


def test_the_search_reads_a_document_source_as_its_own_kind(vault):
    from soma_vault import wiki_search

    assert wiki_search._stream_of("a1b2c3d4e5f60718#s2") == "file"
    assert wiki_search._stream_of("<7f3a9c@example.com>#m2") == "mail"
    assert wiki_search._stream_of("19:abc@thread.v2|2026-08-21") == "chat"
    assert wiki_search._stream_of("user") == "user"


# ------------------------------------------------------- watched folders


def _preferences_with(root, key, values):
    p = root / A / "Preferences.md"
    text = p.read_text(encoding="utf-8")
    lines = "\n".join(f'  - "{v}"' for v in values)
    p.write_text(text.replace(f"{key}: []", f"{key}:\n{lines}"), encoding="utf-8")


def test_changed_lists_the_files_of_the_document_folders_without_reading_them(vault, tmp_path):
    outside = tmp_path / "Contracts"
    outside.mkdir()
    (outside / "supplier.docx").write_bytes(b"PK")  # never opened, so a stub is enough
    (outside / "picture.png").write_bytes(b"\x89PNG")
    inside = vault / "Papers"
    inside.mkdir()
    (inside / "terms.md").write_text("terms", encoding="utf-8")
    _preferences_with(vault, "document_folders", [str(outside).replace("\\", "/"), "Papers"])
    assert store.read_preferences()["preferences"]["document_folders"] == [
        str(outside).replace("\\", "/"), "Papers",
    ]

    since = (datetime.now().astimezone() - timedelta(hours=1)).isoformat(timespec="seconds")
    out = workflows.changed_notes(since, folders=[])
    got = {d["path"].split("/")[-1]: d for d in out["documents"]}
    assert set(got) == {"supplier.docx", "terms.md"}
    assert got["supplier.docx"]["kind"] == "document" and got["supplier.docx"]["format"] == "docx"
    assert got["supplier.docx"]["size"] == 2 and got["supplier.docx"]["path"] == (outside / "supplier.docx").as_posix()
    assert got["terms.md"]["path"] == "Papers/terms.md" and got["terms.md"]["format"] == "markdown"
    assert out["documents_total"] == 2 and len(out["document_folders"]) == 2

    later = (datetime.now().astimezone() + timedelta(hours=1)).isoformat(timespec="seconds")
    assert workflows.changed_notes(later, folders=[])["documents"] == []


def test_a_watched_folder_that_is_not_there_is_reported_not_an_error(vault):
    _preferences_with(vault, "document_folders", ["Nowhere"])
    since = (datetime.now().astimezone() - timedelta(hours=1)).isoformat(timespec="seconds")
    out = workflows.changed_notes(since, folders=[])
    assert out["documents"] == [] and "Nowhere" in out["missing"]
    _preferences_with(vault, "collect_folders", [".."])  # only to be sure the guards still bite
    with pytest.raises(VaultError):
        workflows.changed_notes(since)


def test_a_watched_folder_that_climbs_out_of_the_vault_is_refused(vault):
    since = (datetime.now().astimezone() - timedelta(hours=1)).isoformat(timespec="seconds")
    _preferences_with(vault, "document_folders", ["../elsewhere"])
    with pytest.raises(VaultError, match=r"\.\."):
        workflows.changed_notes(since, folders=[])


# ------------------------------------------------------------ the tool layer


def call(server, name, args):
    out = asyncio.run(server.call_tool(name, args))
    return json.loads(out[0].text if isinstance(out, list) else out[0][0].text)


def test_the_document_round_trip_through_the_tools(vault):
    server = build_server()
    p = pptx(vault / "deck.pptx", [("Agenda", "Why we are here", ""), ("Pricing", "Net 45 agreed", "")])
    res = call(server, "vault_save", {"kind": "document", "path": str(p), "summary": "A deck.",
                                      "action_items": [], "created_by": CB})
    assert res["action"] == "created" and res["parts"] == 2
    got = call(server, "vault_read", {"path": res["path"], "section": "s2"})
    assert got["section"]["text"] == "Net 45 agreed"
    assert "body" in call(server, "vault_read", {"path": res["path"]})
    found = call(server, "vault_find", {"type": "document", "identity": res["record_id"]})
    assert found["found"] is True and found["path"] == res["path"]
    assert [n["path"] for n in call(server, "vault_find", {"type": "document"})] == [res["path"]]
    with pytest.raises(Exception):
        asyncio.run(server.call_tool("vault_save", {"kind": "document"}))
    tools = asyncio.run(server.list_tools())
    assert len(tools) == 20 and "vault_save_document" not in {t.name for t in tools}


def test_two_parts_of_one_document_are_one_source_on_a_fact(vault):
    p = pptx(vault / "deck.pptx", [("Agenda", "Why", ""), ("Pricing", "Net 45 agreed", ""), ("Risks", "Late", "")])
    doc = workflows.save_document(str(p), "A deck.", created_by=CB)
    rid = doc["record_id"]
    wiki.create("topic", "Supplier contract", created_by=CB)
    wiki.ingest(doc["path"], [{"path": "Wiki/Topics/supplier-contract",
                              "ops": [{"op": "add", "text": "Net 45 payment terms agreed", "src": f"{rid}#s2"}]}],
                created_by=CB)
    fid = wiki.read("Wiki/Topics/supplier-contract")["facts"][0]["id"]
    out = wiki.ingest(doc["path"], [{"path": "Wiki/Topics/supplier-contract",
                                     "ops": [{"op": "confirm", "id": fid, "src": f"{rid}#s3"}]}], created_by=CB)
    page = wiki.read("Wiki/Topics/supplier-contract")
    fact = page["facts"][0]
    # the same document again replaces its own src: one record, one source
    assert fact["src"] == [f"{rid}#s3"]
    assert out["pages"][0]["written"] is True
    assert wiki_lint.lint(created_by=CB)["checks"]["4"]["count"] == 0


def test_one_record_adds_one_open_item_however_many_parts_it_cites(vault):
    p = pptx(vault / "deck.pptx", [("Agenda", "Why", ""), ("Pricing", "Net 45 agreed", "")])
    doc = workflows.save_document(str(p), "A deck.", created_by=CB)
    rid = doc["record_id"]
    wiki.create("topic", "Supplier contract", created_by=CB)
    out = wiki.ingest(doc["path"], [{"path": "Wiki/Topics/supplier-contract", "ops": [
        {"op": "open", "text": "Jane sends the signed contract", "owner": "Jane Doe",
         "due": "2026-09-01", "src": f"{rid}#s1"},
        {"op": "open", "text": "Jane sends the countersigned copy", "owner": "Jane Doe",
         "due": "2026-09-02", "src": f"{rid}#s2"},
    ]}], created_by=CB)
    refused = [r["reason"] for r in out["pages"][0]["refused"]]
    assert refused == ["duplicate"]  # the second part of the same record is the same record


def test_a_sheet_name_holding_a_dash_reads_back(vault):
    from soma_vault import store
    assert store._split_heading("Sales — EU — Sales — EU") == ("Sales — EU", "Sales — EU")
    assert store._split_heading("s2 — Roadmap — the plan") == ("s2", "Roadmap — the plan")
    assert store._split_heading("Just a heading") == ("", "Just a heading")
