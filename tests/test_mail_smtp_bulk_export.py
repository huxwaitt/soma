"""Tests for the fork additions: SMTP resolution, DASL filter building,
bulk ops, and export/save-as. All run against fake COM objects."""

import csv
import json
import sys
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="client modules import pywin32"
)


# ---------------------------------------------------------------- fakes --


class FakeAccessor:
    def __init__(self, props):
        self.props = props

    def GetProperty(self, tag):
        if tag not in self.props:
            raise RuntimeError("MAPI_E_NOT_FOUND")
        return self.props[tag]


class FakeExchangeUser:
    def __init__(self, smtp):
        self.PrimarySmtpAddress = smtp


class FakeSender:
    def __init__(self, exch):
        self._exch = exch

    def GetExchangeUser(self):
        return self._exch


class FakeItem:
    Class = 43

    def __init__(self, entry_id, subject="s", **kw):
        self.EntryID = entry_id
        self.Subject = subject
        self.UnRead = True
        self.FlagStatus = 0
        self.Categories = ""
        self.saved = False
        self.deleted = False
        self.saved_as = None
        for k, v in kw.items():
            setattr(self, k, v)

    def Save(self):
        self.saved = True

    def Delete(self):
        self.deleted = True

    def Move(self, target):
        target.moved.append(self)
        return SimpleNamespace(EntryID=self.EntryID + "-moved")

    def SaveAs(self, path, save_type):
        self.saved_as = (path, save_type)
        with open(path, "wb") as fh:
            fh.write(b"x")


class FakeFolder:
    def __init__(self, name="Inbox"):
        self.Name = name
        self.moved = []


class FakeNamespace:
    def __init__(self, items):
        self._items = {i.EntryID: i for i in items}

    def GetItemFromID(self, entry_id, store_id=None):
        try:
            return self._items[entry_id]
        except KeyError:
            import pythoncom

            raise pythoncom.com_error(-2147221233, "not found", None, None)


# ---------------------------------------------------------- sender_smtp --


def test_sender_smtp_passthrough_for_internet_mail():
    from outlook_mcp.client.mail import sender_smtp

    item = FakeItem("1", SenderEmailAddress="a@x.com", SenderEmailType="SMTP")
    assert sender_smtp(item) == "a@x.com"


def test_sender_smtp_resolves_ex_via_property_accessor():
    from outlook_mcp.client.mail import SMTP_PROPTAG, sender_smtp

    item = FakeItem(
        "1",
        SenderEmailAddress="/O=EXCHANGELABS/OU=X/CN=RECIPIENTS/CN=abc",
        SenderEmailType="EX",
        PropertyAccessor=FakeAccessor({SMTP_PROPTAG: "real@corp.com"}),
    )
    assert sender_smtp(item) == "real@corp.com"


def test_sender_smtp_falls_back_to_exchange_user():
    from outlook_mcp.client.mail import sender_smtp

    item = FakeItem(
        "1",
        SenderEmailAddress="/O=EX/CN=abc",
        SenderEmailType="EX",
        PropertyAccessor=FakeAccessor({}),
        Sender=FakeSender(FakeExchangeUser("primary@corp.com")),
    )
    assert sender_smtp(item) == "primary@corp.com"


def test_sender_smtp_returns_raw_when_unresolvable():
    from outlook_mcp.client.mail import sender_smtp

    item = FakeItem(
        "1",
        SenderEmailAddress="/O=EX/CN=abc",
        SenderEmailType="EX",
        PropertyAccessor=FakeAccessor({}),
        Sender=None,
    )
    assert sender_smtp(item) == "/O=EX/CN=abc"


def test_mail_summary_uses_resolved_smtp():
    from outlook_mcp.client.mail import SMTP_PROPTAG, _mail_summary

    item = FakeItem(
        "1",
        SenderEmailAddress="/O=EX/CN=abc",
        SenderEmailType="EX",
        SenderName="Bob",
        PropertyAccessor=FakeAccessor({SMTP_PROPTAG: "bob@corp.com"}),
        Attachments=None,
        Body="",
        ReceivedTime=None,
        To="",
        Importance=1,
    )
    assert _mail_summary(item)["from_address"] == "bob@corp.com"


# ----------------------------------------------------- build_mail_filter --


def test_build_filter_none_when_empty():
    from outlook_mcp.client.mail import build_mail_filter

    assert build_mail_filter() is None


def test_build_filter_combines_clauses_in_dasl():
    from outlook_mcp.client.mail import (
        DASL_READ,
        DASL_RECEIVED,
        SMTP_PROPTAG,
        build_mail_filter,
    )

    out = build_mail_filter(
        unread_only=True,
        since="2026-03-01T14:30:00",
        from_address="o'neil@x.com",
        has_attachments=True,
    )
    assert out.startswith("@SQL=")
    assert f'"{DASL_READ}" = 0' in out
    assert f"\"{DASL_RECEIVED}\" >= '03/01/2026 02:30 PM'" in out
    assert "hasattachment\" = 1" in out
    # quote escaped, SMTP proptag included so EX senders match
    assert "o''neil@x.com" in out
    assert SMTP_PROPTAG in out
    assert out.count(" AND ") == 3


def test_search_clause_scopes():
    from outlook_mcp.client.mail import DASL_BODY, DASL_SUBJECT, search_clause

    assert search_clause("x", "subject") == f"\"{DASL_SUBJECT}\" LIKE '%x%'"
    assert DASL_BODY in search_clause("x", "subject_body")
    assert "fromname" in search_clause("x", "from")


# ------------------------------------------------------------- bulk ops --


def test_bulk_move_reports_partial_failure():
    from outlook_mcp.client import mail as m

    a, b = FakeItem("a"), FakeItem("b")
    ns = FakeNamespace([a, b])
    target = FakeFolder("Archive")
    m.resolve_folder = lambda namespace, spec: target  # monkeypatch module ref
    try:
        out = m.bulk_move_mails(None, ns, entry_ids=["a", "missing", "b"], target_folder="Archive")
    finally:
        from outlook_mcp.client.folders import resolve_folder

        m.resolve_folder = resolve_folder
    assert out["status"] == "partial"
    assert out["succeeded"] == 2 and out["failed"] == 1
    assert out["failures"][0]["entry_id"] == "missing"
    assert [r["new_entry_id"] for r in out["results"]] == ["a-moved", "b-moved"]
    assert target.moved == [a, b]


def test_bulk_stop_on_error_halts():
    from outlook_mcp.client.mail import bulk_delete_mails

    a, b = FakeItem("a"), FakeItem("b")
    ns = FakeNamespace([a, b])
    out = bulk_delete_mails(None, ns, entry_ids=["a", "missing", "b"], stop_on_error=True)
    assert out["succeeded"] == 1 and out["failed"] == 1
    assert a.deleted and not b.deleted


def test_bulk_mark_sets_all_fields():
    from outlook_mcp.client.mail import bulk_mark_mails

    a = FakeItem("a")
    out = bulk_mark_mails(
        None, FakeNamespace([a]), entry_ids=["a"], read=True, flagged=True, categories=["Red", "Blue"]
    )
    assert out["status"] == "ok"
    assert a.UnRead is False and a.FlagStatus == 2 and a.Categories == "Red, Blue" and a.saved


def test_bulk_mark_requires_a_change():
    from outlook_mcp.client.mail import bulk_mark_mails
    from outlook_mcp.errors import OutlookError

    with pytest.raises(OutlookError):
        bulk_mark_mails(None, FakeNamespace([]), entry_ids=["a"])


def test_bulk_reraises_disconnect():
    from outlook_mcp.client.mail import bulk_delete_mails

    class Dying(FakeNamespace):
        def GetItemFromID(self, entry_id, store_id=None):
            import pythoncom

            raise pythoncom.com_error(-2147023174, "RPC server unavailable", None, None)

    with pytest.raises(Exception) as exc:
        bulk_delete_mails(None, Dying([]), entry_ids=["a"])
    assert "RPC" in str(exc.value)


# --------------------------------------------------------------- export --


def _rich_item(entry_id, smtp):
    return FakeItem(
        entry_id,
        subject=f"Subj {entry_id}",
        SenderName="Bob",
        SenderEmailAddress=smtp,
        SenderEmailType="SMTP",
        To="me@x.com",
        CC="",
        ReceivedTime=None,
        SentOn=None,
        Attachments=None,
        Importance=1,
        ConversationID="c1",
        Body="hello, world",
    )


def test_export_by_entry_ids_csv(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTLOOK_MCP_ALLOW_ANY_PATH", "1")
    from outlook_mcp.client.mail import export_mails

    ns = FakeNamespace([_rich_item("a", "a@x.com"), _rich_item("b", "b@x.com")])
    out_file = tmp_path / "out" / "mails.csv"
    out = export_mails(
        None, ns, output_path=str(out_file), entry_ids=["a", "b", "nope"], include_body=True, max_body_chars=5
    )
    assert out["count"] == 2 and out["failures"][0]["entry_id"] == "nope"
    with open(out_file, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["from_address"] for r in rows] == ["a@x.com", "b@x.com"]
    assert rows[0]["body"] == "hello"
    assert "conversation_id" in rows[0]


def test_export_json_and_suffix_check(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTLOOK_MCP_ALLOW_ANY_PATH", "1")
    from outlook_mcp.client.mail import export_mails
    from outlook_mcp.errors import OutlookError

    ns = FakeNamespace([_rich_item("a", "a@x.com")])
    out_file = tmp_path / "m.json"
    export_mails(None, ns, output_path=str(out_file), entry_ids=["a"], fmt="json")
    assert json.loads(out_file.read_text(encoding="utf-8"))[0]["subject"] == "Subj a"

    with pytest.raises(OutlookError):
        export_mails(None, ns, output_path=str(tmp_path / "m.xlsx"), entry_ids=["a"])


def test_save_mail_as_uniquifies_and_sanitizes(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTLOOK_MCP_ALLOW_ANY_PATH", "1")
    from outlook_mcp.client.mail import save_mail_as
    from outlook_mcp.constants import OL_SAVE_MSG_UNICODE

    item = FakeItem("a", subject='Re: Q3 <budget> / "final"?')
    ns = FakeNamespace([item])
    first = save_mail_as(None, ns, entry_id="a", output_dir=str(tmp_path))
    second = save_mail_as(None, ns, entry_id="a", output_dir=str(tmp_path))
    assert first["path"].endswith('Re_ Q3 _budget_ _ _final__.msg')
    assert second["path"].endswith(" (1).msg")
    assert item.saved_as[1] == OL_SAVE_MSG_UNICODE


def test_save_mail_as_rejects_path_in_filename(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTLOOK_MCP_ALLOW_ANY_PATH", "1")
    from outlook_mcp.client.mail import save_mail_as
    from outlook_mcp.errors import OutlookError

    ns = FakeNamespace([FakeItem("a")])
    with pytest.raises(OutlookError):
        save_mail_as(None, ns, entry_id="a", output_dir=str(tmp_path), filename="..\\evil.msg")
    with pytest.raises(OutlookError):
        save_mail_as(None, ns, entry_id="a", output_dir=str(tmp_path), fmt="eml")
