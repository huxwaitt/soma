"""Tests for get_conversation and the internet_message_id field.
All run against fake COM objects."""

import datetime as dt
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


class FakeConversation:
    """Tree given as {parent_entry_id: [child items]}; roots listed separately."""

    def __init__(self, roots, children):
        self._roots = roots
        self._children = children

    def GetRootItems(self):
        return list(self._roots)

    def GetChildren(self, node):
        return list(self._children.get(node.EntryID, []))


class FakeItem:
    Class = 43

    def __init__(self, entry_id, received, *, message_id=None, conversation=None, folder="Inbox", body="body text"):
        self.EntryID = entry_id
        self.Subject = f"Subj {entry_id}"
        self.SenderName = "Bob"
        self.SenderEmailAddress = "bob@x.com"
        self.SenderEmailType = "SMTP"
        self.To = "me@x.com"
        self.CC = ""
        self.BCC = ""
        self.Recipients = None
        self.ReceivedTime = received
        self.SentOn = received
        self.UnRead = False
        self.FlagStatus = 0
        self.Attachments = None
        self.Importance = 1
        self.Categories = ""
        self.Body = body
        self.ConversationID = "conv-1"
        self.Parent = SimpleNamespace(Name=folder)
        self.PropertyAccessor = FakeAccessor(
            {} if message_id is None else {
                "http://schemas.microsoft.com/mapi/proptag/0x1035001F": message_id
            }
        )
        self._conversation = conversation

    def GetConversation(self):
        return self._conversation


class FakeNamespace:
    def __init__(self, items):
        self._items = {i.EntryID: i for i in items}

    def GetItemFromID(self, entry_id, store_id=None):
        return self._items[entry_id]


def _t(hour):
    return dt.datetime(2026, 3, 1, hour, 0, 0)


# ------------------------------------------------------ get_conversation --


def test_no_conversation_returns_single_item():
    from outlook_mcp.client.mail import get_conversation

    item = FakeItem("a", _t(9), message_id="<a@x.com>")
    out = get_conversation(None, FakeNamespace([item]), entry_id="a")
    assert out["conversation_id"] == "conv-1"
    assert out["count"] == 1 and out["truncated"] is False
    assert out["items"][0]["entry_id"] == "a"
    assert out["items"][0]["internet_message_id"] == "<a@x.com>"
    assert out["items"][0]["folder"] == "Inbox"
    assert "body" not in out["items"][0]


def test_root_with_two_children_sorted_oldest_first_across_folders():
    from outlook_mcp.client.mail import get_conversation

    root = FakeItem("root", _t(9))
    reply1 = FakeItem("r1", _t(10), folder="Sent Items")
    reply2 = FakeItem("r2", _t(11))
    # Newest-first in the tree to prove we sort by ReceivedTime.
    conv = FakeConversation([root], {"root": [reply2, reply1]})
    for it in (root, reply1, reply2):
        it._conversation = conv

    out = get_conversation(None, FakeNamespace([root, reply1, reply2]), entry_id="r2", include_body=True, max_body_chars=4)
    assert out["count"] == 3
    assert [i["entry_id"] for i in out["items"]] == ["root", "r1", "r2"]
    assert out["items"][1]["folder"] == "Sent Items"
    assert out["items"][0]["body"] == "body" and out["items"][0]["body_truncated"] is True


def test_limit_truncates():
    from outlook_mcp.client.mail import get_conversation

    root = FakeItem("root", _t(9))
    kids = [FakeItem(f"k{i}", _t(10 + i)) for i in range(3)]
    conv = FakeConversation([root], {"root": kids})
    for it in [root, *kids]:
        it._conversation = conv

    out = get_conversation(None, FakeNamespace([root, *kids]), entry_id="root", limit=2)
    assert out["count"] == 2 and out["truncated"] is True
    assert [i["entry_id"] for i in out["items"]] == ["root", "k0"]


def test_non_mail_nodes_skipped_and_duplicates_collapsed():
    from outlook_mcp.client.mail import get_conversation

    root = FakeItem("root", _t(9))
    note = FakeItem("note", _t(10))
    note.Class = 26  # olAppointment
    conv = FakeConversation([root, root], {"root": [note]})
    root._conversation = conv

    out = get_conversation(None, FakeNamespace([root]), entry_id="root")
    assert [i["entry_id"] for i in out["items"]] == ["root"]


# -------------------------------------------------- internet_message_id --


def test_internet_message_id_in_all_shapes():
    from outlook_mcp.client.mail import EXPORT_COLUMNS, _mail_full, _mail_row, _mail_summary

    item = FakeItem("a", _t(9), message_id="<msg-1@x.com>")
    assert _mail_summary(item)["internet_message_id"] == "<msg-1@x.com>"
    assert _mail_row(item)["internet_message_id"] == "<msg-1@x.com>"
    assert _mail_full(item)["internet_message_id"] == "<msg-1@x.com>"
    assert "internet_message_id" in EXPORT_COLUMNS


def test_internet_message_id_empty_when_missing():
    from outlook_mcp.client.mail import _mail_full, _mail_row, _mail_summary

    item = FakeItem("a", _t(9))  # no property on the accessor
    assert _mail_summary(item)["internet_message_id"] == ""
    assert _mail_row(item)["internet_message_id"] == ""
    assert _mail_full(item)["internet_message_id"] == ""

    item.PropertyAccessor = None
    assert _mail_summary(item)["internet_message_id"] == ""
