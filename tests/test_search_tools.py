"""Batch-4 search tools: search_attachments, advanced_search,
extract_attachment_text, reply/forward save_only. All against fakes."""

import asyncio
import datetime as dt
import json
import sys
import zipfile
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="client modules import pywin32"
)

HIDDEN_TAG = "http://schemas.microsoft.com/mapi/proptag/0x7FFE000B"


# ---------------------------------------------------------------- fakes --


class FakeAccessor:
    def __init__(self, props):
        self.props = props

    def GetProperty(self, tag):
        if tag not in self.props:
            raise RuntimeError("MAPI_E_NOT_FOUND")
        return self.props[tag]


class FakeAttachment:
    def __init__(self, filename, size=100, hidden=None, content=b""):
        self.FileName = filename
        self.Size = size
        self.PropertyAccessor = FakeAccessor({} if hidden is None else {HIDDEN_TAG: hidden})
        self._content = content
        self.saved_to = None

    def SaveAsFile(self, path):
        self.saved_to = path
        with open(path, "wb") as fh:
            fh.write(self._content)


class FakeAttachments(list):
    @property
    def Count(self):
        return len(self)


class FakeItem:
    Class = 43

    def __init__(self, entry_id, received, attachments=(), folder="Inbox"):
        self.EntryID = entry_id
        self.Subject = f"Subj {entry_id}"
        self.SenderName = "Bob"
        self.SenderEmailAddress = "bob@example.com"
        self.SenderEmailType = "SMTP"
        self.To = "hux@example.com"
        self.ReceivedTime = received
        self.UnRead = False
        self.FlagStatus = 0
        self.Attachments = FakeAttachments(attachments)
        self.Importance = 1
        self.Body = "body"
        self.Parent = SimpleNamespace(Name=folder)
        self.PropertyAccessor = FakeAccessor({})


class FakeItems(list):
    def __init__(self, items):
        super().__init__(items)
        self.restricted_with = None

    def Sort(self, key, descending):
        self.sort(key=lambda i: i.ReceivedTime, reverse=descending)

    def Restrict(self, dasl):
        self.restricted_with = dasl
        if "hasattachment\" = 1" in dasl:
            return FakeItems([i for i in self if len(i.Attachments)])
        return self


class FakeFolder:
    def __init__(self, name, items=(), subfolders=(), path=None):
        self.Name = name
        self.Items = FakeItems(list(items))
        self.Folders = list(subfolders)
        self.FolderPath = path or f"\\\\Mailbox\\{name}"


class FakeStore:
    def __init__(self, name, root):
        self.DisplayName = name
        self._root = root

    def GetRootFolder(self):
        return self._root


class FakeNamespace:
    def __init__(self, inbox, stores=(), items=()):
        self._inbox = inbox
        self.Stores = list(stores)
        self._items = {i.EntryID: i for i in items}

    def GetDefaultFolder(self, which):
        return self._inbox

    def GetItemFromID(self, entry_id, store_id=None):
        return self._items[entry_id]


def _t(day, hour=9):
    return dt.datetime(2026, 8, day, hour, 0, 0)


# ---------------------------------------------------- search_attachments --


def test_attachment_name_matcher_words_and_glob():
    from outlook_mcp.client.mail import attachment_name_matcher

    words = attachment_name_matcher("Budget q3")
    assert words("Q3_budget_final.xlsx")
    assert not words("budget.xlsx")
    glob = attachment_name_matcher("*.PDF")
    assert glob("invoice.pdf") and not glob("invoice.pdf.zip")
    assert attachment_name_matcher("budget*.xlsx")("Budget_Q3.xlsx")


def test_search_attachments_walks_subfolders_skips_inline_and_sorts():
    from outlook_mcp.client.mail import search_attachments

    a = FakeItem("a", _t(20), [FakeAttachment("Budget_Q3.xlsx", 180), FakeAttachment("image001.png", hidden=True)])
    b = FakeItem("b", _t(22), [FakeAttachment("notes.txt")])
    c = FakeItem("c", _t(21), [FakeAttachment("budget draft.XLSX", 90)], folder="Projects")
    d = FakeItem("d", _t(23), [], folder="Projects")
    sub = FakeFolder("Projects", [c, d])
    inbox = FakeFolder("Inbox", [a, b], [sub])
    ns = FakeNamespace(inbox)

    out = search_attachments(None, ns, query="budget", folder="inbox")
    assert out["folder"] == "Inbox" and out["folders_searched"] == 2
    assert out["count"] == 2 and out["truncated"] is False
    assert [i["entry_id"] for i in out["items"]] == ["c", "a"]  # newest first across folders
    assert out["items"][0]["folder"] == "Projects"
    assert out["items"][1]["matches"] == [{"index": 1, "filename": "Budget_Q3.xlsx", "size_bytes": 180}]
    assert inbox.Items.restricted_with is not None and "hasattachment" in inbox.Items.restricted_with

    # inline image is never a match, even with a glob
    assert search_attachments(None, ns, query="*.png")["count"] == 0
    # no sub-folders, since pushed into the filter, limit honoured
    out = search_attachments(None, ns, query="*", include_subfolders=False, since="2026-08-01", limit=1)
    assert out["folders_searched"] == 1 and out["count"] == 1 and out["truncated"] is True
    assert "datereceived" in inbox.Items.restricted_with


# ------------------------------------------------------ advanced_search --


class FakeResults(list):
    @property
    def Count(self):
        return len(self)


class FakeSearch:
    """Results grow by one per poll until ``final`` is reached."""

    def __init__(self, final):
        self._final = list(final)
        self.Results = FakeResults()
        self.stopped = False

    def grow(self):
        if len(self.Results) < len(self._final):
            self.Results.append(self._final[len(self.Results)])

    def Stop(self):
        self.stopped = True


class FakeApp:
    def __init__(self, search):
        self.search = search
        self.calls = []

    def AdvancedSearch(self, scope, dasl, sub, tag):
        self.calls.append((scope, dasl, sub, tag))
        return self.search


def test_advanced_search_filter_and_scope():
    from outlook_mcp.client.mail import advanced_search_filter, advanced_search_scope

    f = advanced_search_filter("delivery sep'tember", since="2026-08-01T00:00:00")
    assert f.startswith("@SQL=(")
    assert "\"urn:schemas:httpmail:subject\" ci_phrasematch 'delivery'" in f
    assert "\"urn:schemas:httpmail:textdescription\" ci_phrasematch 'sep''tember'" in f
    assert "\"urn:schemas:httpmail:datereceived\" >= '08/01/2026 12:00 AM'" in f
    with pytest.raises(Exception):
        advanced_search_filter("   ")

    ns = FakeNamespace(
        FakeFolder("Inbox", path="\\\\Mailbox - Hux\\Inbox"),
        stores=[FakeStore("Mailbox - Hux", FakeFolder("root", path="\\\\Mailbox - Hux")), FakeStore("Archive", FakeFolder("r", path="\\\\Archive"))],
    )
    assert advanced_search_scope(ns, "all") == "'\\\\Mailbox - Hux','\\\\Archive'"
    assert advanced_search_scope(ns, "inbox") == "'\\\\Mailbox - Hux\\Inbox'"


def test_wait_for_search_stable_and_timeout():
    from outlook_mcp.client.mail import wait_for_search

    clock = {"t": 0.0}
    pumps = []

    def tick(sec):
        clock["t"] += sec

    search = FakeSearch([1, 2, 3])

    def pump():
        pumps.append(clock["t"])
        search.grow()

    timed_out = wait_for_search(search, timeout_sec=20, clock=lambda: clock["t"], sleep=tick, pump=pump)
    assert timed_out is False and search.Results.Count == 3 and pumps
    # stable for 1s after the last growth, never near the timeout
    assert 1.0 <= clock["t"] < 5

    # zero results: waits min_wait_sec, not the whole timeout
    clock["t"] = 0.0
    empty = FakeSearch([])
    assert wait_for_search(empty, timeout_sec=20, clock=lambda: clock["t"], sleep=tick, pump=lambda: None) is False
    assert 3.0 <= clock["t"] < 5

    # a count that never settles hits the timeout
    clock["t"] = 0.0
    forever = FakeSearch(range(1000))
    assert wait_for_search(forever, timeout_sec=2, clock=lambda: clock["t"], sleep=tick, pump=forever.grow) is True
    assert clock["t"] >= 2


def test_advanced_search_collects_sorts_filters():
    from outlook_mcp.client.mail import advanced_search

    old = FakeItem("old", _t(1))
    new = FakeItem("new", _t(22), folder="Sent Items")
    mid = FakeItem("mid", _t(10))
    appt = FakeItem("appt", _t(23))
    appt.Class = 26
    search = FakeSearch([old, appt, new, mid])
    search.Results.extend(search._final)
    app = FakeApp(search)
    ns = FakeNamespace(FakeFolder("Inbox"), stores=[FakeStore("M", FakeFolder("r", path="\\\\M"))])

    out = advanced_search(app, ns, query="offsite", since="2026-08-05", limit=1, timeout_sec=5, _wait=lambda s, **kw: False)
    scope, dasl, sub, tag = app.calls[0]
    assert scope == "'\\\\M'" and sub is True and tag.startswith("outlook_mcp_")
    assert out["filter"] == dasl and out["scope"] == "all"
    assert out["timed_out"] is False and out["total_found"] == 2 and out["count"] == 1
    assert out["items"][0]["entry_id"] == "new" and out["items"][0]["folder"] == "Sent Items"
    assert search.stopped

    out = advanced_search(app, ns, query="offsite", _wait=lambda s, **kw: True)
    assert out["timed_out"] is True and [i["entry_id"] for i in out["items"]] == ["new", "mid", "old"]


# ----------------------------------------------- extract_attachment_text --


def _zip(path, members):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path.read_bytes()


DOCX_XML = (
    '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:body><w:p><w:r><w:t>Hello</w:t></w:r><w:r><w:tab/><w:t>world</w:t></w:r></w:p>"
    "<w:p><w:r><w:t>Second para</w:t></w:r></w:p><w:p/></w:body></w:document>"
)
SLIDE_XML = (
    '<?xml version="1.0"?><p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>'
    "<p:sp><p:txBody><a:p><a:r><a:t>Slide {n} title</a:t></a:r></a:p></p:txBody></p:sp>"
    "</p:spTree></p:cSld></p:sld>"
)
def _mini_pdf():
    """A one-page PDF with a valid xref table and the text 'Hello PDF'."""
    stream = b"BT /F1 12 Tf 20 100 Td (Hello PDF) Tj ET"
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<</Size {len(objects) + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


MINI_PDF = _mini_pdf()


def test_extract_docx_pptx_text(tmp_path):
    from outlook_mcp.client.attachments import extract_text_from_file

    docx = _zip(tmp_path / "a.docx", {"word/document.xml": DOCX_XML, "[Content_Types].xml": "<x/>"})
    (tmp_path / "b.docx").write_bytes(docx)
    assert extract_text_from_file(str(tmp_path / "b.docx"), "docx") == "Hello\tworld\nSecond para"

    _zip(tmp_path / "c.pptx", {
        "ppt/slides/slide10.xml": SLIDE_XML.format(n=10),
        "ppt/slides/slide2.xml": SLIDE_XML.format(n=2),
        "ppt/slideLayouts/slideLayout1.xml": SLIDE_XML.format(n=99),
    })
    assert extract_text_from_file(str(tmp_path / "c.pptx"), "pptx") == "Slide 2 title\n\nSlide 10 title"

    (tmp_path / "t.csv").write_bytes("a,b\r\nc,\xff\n".encode("utf-8", "surrogateescape") if False else b"a,b\r\nc,\xff\n")
    assert extract_text_from_file(str(tmp_path / "t.csv"), "text") == "a,b\nc,�\n"

    (tmp_path / "bad.docx").write_bytes(b"not a zip")
    with pytest.raises(Exception, match="not a valid Office file"):
        extract_text_from_file(str(tmp_path / "bad.docx"), "docx")


def test_extract_xlsx_and_pdf_need_extras(tmp_path):
    from outlook_mcp.client.attachments import extract_text_from_file

    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["Name", "Qty"])
    ws.append(["Bolt", 12])
    ws.append([None, None])
    wb.create_sheet("Empty")
    wb.save(tmp_path / "d.xlsx")
    assert extract_text_from_file(str(tmp_path / "d.xlsx"), "xlsx") == "# Data\nName\tQty\nBolt\t12\n\n# Empty"

    pytest.importorskip("pypdf")
    (tmp_path / "e.pdf").write_bytes(MINI_PDF)
    assert "Hello PDF" in extract_text_from_file(str(tmp_path / "e.pdf"), "pdf")


def test_extract_pdf_missing_dependency_names_extra(tmp_path, monkeypatch):
    import builtins

    from outlook_mcp.client.attachments import extract_text_from_file

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pypdf":
            raise ImportError("no pypdf")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    (tmp_path / "e.pdf").write_bytes(MINI_PDF)
    with pytest.raises(Exception, match="'search' extra"):
        extract_text_from_file(str(tmp_path / "e.pdf"), "pdf")


def test_extract_attachment_text_end_to_end(tmp_path, monkeypatch):
    import os

    from outlook_mcp.client import attachments as mod

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    att = FakeAttachment("Notes.TXT", content=("x" * 30).encode())
    item = FakeItem("a", _t(1), [FakeAttachment("pic.png"), att])
    ns = FakeNamespace(FakeFolder("Inbox"), items=[item])

    out = mod.extract_attachment_text(None, ns, entry_id="a", index=2, max_chars=10)
    assert out == {"entry_id": "a", "index": 2, "filename": "Notes.TXT", "kind": "text", "chars": 30, "truncated": True, "text": "x" * 10}
    assert att.saved_to.startswith(os.path.join(str(tmp_path), "outlook-mcp", "tmp"))
    assert att.saved_to.endswith(".txt")
    assert not os.path.exists(att.saved_to) and not os.path.exists(os.path.dirname(att.saved_to))

    with pytest.raises(Exception, match="supported types"):
        mod.extract_attachment_text(None, ns, entry_id="a", index=1)
    with pytest.raises(Exception, match="out of range"):
        mod.extract_attachment_text(None, ns, entry_id="a", index=3)


# ---------------------------------------------------------- save_only --


class FakeDraft:
    def __init__(self, entry_id, subject):
        self.EntryID = entry_id
        self.Subject = subject
        self.Body = "quoted"
        self.HTMLBody = ""
        self.To = ""
        self.CC = ""
        self.Attachments = SimpleNamespace(Add=lambda p: None)
        self.saved = False
        self.sent = False

    def Save(self):
        self.saved = True

    def Send(self):
        self.sent = True


class FakeOriginal:
    def __init__(self):
        self.reply = FakeDraft("draft-1", "RE: Offsite")
        self.fwd = FakeDraft("draft-2", "FW: Offsite")

    def Reply(self):
        return self.reply

    def ReplyAll(self):
        return self.reply

    def Forward(self):
        return self.fwd


def test_reply_and_forward_save_only():
    from outlook_mcp.client.mail import forward_mail, reply_mail

    orig = FakeOriginal()
    orig.EntryID = "o"
    ns = FakeNamespace(FakeFolder("Inbox"), items=[orig])

    out = reply_mail(None, ns, entry_id="o", body="Thanks", reply_all=True, save_only=True)
    assert out == {"status": "saved", "reply_all": True, "in_reply_to": "o", "entry_id": "draft-1", "subject": "RE: Offsite"}
    assert orig.reply.saved and not orig.reply.sent and orig.reply.Body.startswith("Thanks\n\nquoted")

    out = forward_mail(None, ns, entry_id="o", to=["sam@example.com"], body="FYI", save_only=True)
    assert out == {"status": "saved", "forwarded": "o", "to": ["sam@example.com"], "entry_id": "draft-2", "subject": "FW: Offsite"}
    assert orig.fwd.saved and not orig.fwd.sent and orig.fwd.To == "sam@example.com"

    assert reply_mail(None, ns, entry_id="o", body="x")["status"] == "sent" and orig.reply.sent
    assert forward_mail(None, ns, entry_id="o", to=["a@example.com"])["status"] == "sent" and orig.fwd.sent


# ------------------------------------------------------- registration --


class FakeBridge:
    def __init__(self, namespace, app=None):
        self._ns = namespace
        self._app = app

    async def call(self, func, *args, **kwargs):
        return func(self._app, self._ns, *args, **kwargs)


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, name=None, **_kw):
        def deco(fn):
            self.tools[name or fn.__name__] = fn
            return fn

        return deco


def test_tool_wrappers_return_json():
    from outlook_mcp.tools import mail as mail_tools

    a = FakeItem("a", _t(20), [FakeAttachment("Budget.xlsx")])
    ns = FakeNamespace(FakeFolder("Inbox", [a]), items=[a])
    mcp = FakeMCP()
    mail_tools.register(mcp, FakeBridge(ns))
    for name in ("outlook_search_attachments", "outlook_advanced_search", "outlook_extract_attachment_text"):
        assert name in mcp.tools
    res = json.loads(asyncio.run(mcp.tools["outlook_search_attachments"](query="budget")))
    assert res["count"] == 1 and res["items"][0]["matches"][0]["filename"] == "Budget.xlsx"


def test_server_has_46_outlook_tools():
    from outlook_mcp.server import build_server

    mcp, _bridge = build_server()
    names = {t.name for t in asyncio.run(mcp.list_tools()) if t.name.startswith("outlook_")}
    assert {"outlook_search_attachments", "outlook_advanced_search", "outlook_extract_attachment_text"} <= names
    assert len(names) == 46
