"""The bulk flag on listed and searched mail, against fake COM objects.

Bulk = nobody typed it for this reader: a mailing list, a machine's notice,
a meeting response, a receipt, an out-of-office reply.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="client modules import pywin32"
)

HEADER_TAG = "http://schemas.microsoft.com/mapi/proptag/0x007D001F"


class FakeAccessor:
    """Counts every read, so a test can say how often the headers were asked for."""

    def __init__(self, props, fail=False):
        self.props = props
        self.fail = fail
        self.reads = {}

    def GetProperty(self, tag):
        self.reads[tag] = self.reads.get(tag, 0) + 1
        if self.fail or tag not in self.props:
            raise RuntimeError("MAPI_E_NOT_FOUND")
        return self.props[tag]


class FakeItem:
    Class = 43

    def __init__(self, entry_id="1", headers=None, fail=False, **kw):
        self.EntryID = entry_id
        self.Subject = "Subject"
        self.SenderName = "Bob Lee"
        self.SenderEmailAddress = "bob@example.com"
        self.SenderEmailType = "SMTP"
        self.To = "Hux"
        self.ReceivedTime = None
        self.UnRead = False
        self.FlagStatus = 0
        self.Attachments = None
        self.Importance = 1
        self.Body = "body"
        self.MessageClass = "IPM.Note"
        for k, v in kw.items():
            setattr(self, k, v)
        props = {} if headers is None else {HEADER_TAG: headers}
        self.PropertyAccessor = FakeAccessor(props, fail=fail)

    @property
    def header_reads(self):
        return self.PropertyAccessor.reads.get(HEADER_TAG, 0)


class FakeItems(list):
    def Sort(self, key, descending=False):
        pass

    def Restrict(self, dasl):
        return self


class FakeFolder:
    def __init__(self, name="Inbox", items=()):
        self.Name = name
        self.Items = FakeItems(items)


class FakeNamespace:
    def __init__(self, folder):
        self._folder = folder

    def GetDefaultFolder(self, which):
        return self._folder


def flags(item):
    from outlook_mcp.client.mail import bulk_flags

    return bulk_flags(item)


# ------------------------------------------------------------- headers --


def test_list_unsubscribe_header_is_bulk():
    bulk, why = flags(FakeItem(headers="From: a@b.c\r\nList-Unsubscribe: <mailto:u@b.c>\r\n"))
    assert bulk is True and why == "List-Unsubscribe header"


@pytest.mark.parametrize("value", ["bulk", "list", "junk", "Bulk"])
def test_precedence_values_are_bulk(value):
    bulk, why = flags(FakeItem(headers=f"Precedence: {value}\r\n"))
    assert bulk is True and why == f"Precedence: {value.lower()}"


def test_precedence_first_class_is_not_bulk():
    assert flags(FakeItem(headers="Precedence: first-class\r\n")) == (False, "")


def test_auto_submitted_other_than_no_is_bulk():
    bulk, why = flags(FakeItem(headers="Auto-Submitted: auto-generated\r\n"))
    assert bulk is True and why == "Auto-Submitted: auto-generated"


def test_auto_submitted_no_is_not_bulk():
    assert flags(FakeItem(headers="Auto-Submitted: no\r\n")) == (False, "")


def test_auto_response_suppress_is_bulk():
    bulk, why = flags(FakeItem(headers="X-Auto-Response-Suppress: OOF, AutoReply\r\n"))
    assert bulk is True and why == "X-Auto-Response-Suppress header"


def test_folded_header_line_is_not_read_as_a_header():
    # "Precedence: bulk" here is the continuation of Subject, not a header.
    item = FakeItem(headers="Subject: what to do\r\n\tPrecedence: bulk\r\n")
    assert flags(item) == (False, "")


def test_headers_win_over_the_other_signals():
    item = FakeItem(headers="Precedence: bulk\r\n", SenderEmailAddress="news@shop.example")
    assert flags(item)[1] == "Precedence: bulk"


# -------------------------------------------------------------- sender --


@pytest.mark.parametrize(
    "address",
    [
        "no-reply@shop.example",
        "noreply@shop.example",
        "donotreply@shop.example",
        "do-not-reply@shop.example",
        "newsletter@shop.example",
        "news-digest@shop.example",
        "marketing.mail@shop.example",
        "notifications@shop.example",
        "mailer-daemon@shop.example",
        "bounce+123@shop.example",
        "alerts@shop.example",
        "daily-digest@shop.example",
    ],
)
def test_sender_local_parts_that_mean_a_machine(address):
    bulk, why = flags(FakeItem(SenderEmailAddress=address))
    assert bulk is True and why == f"sender address {address}"


@pytest.mark.parametrize(
    "address", ["jane.andrews@corp.example", "info@corp.example", "newsroom@corp.example"]
)
def test_a_word_inside_a_longer_local_part_is_not_a_signal(address):
    assert flags(FakeItem(SenderEmailAddress=address)) == (False, "")


@pytest.mark.parametrize("name", ["Acme Newsletter", "Shop (no reply)"])
def test_display_names_that_mean_a_machine(name):
    bulk, why = flags(FakeItem(SenderName=name))
    assert bulk is True and why == f"sender name {name}"


# ------------------------------------------------------- message class --


@pytest.mark.parametrize(
    "message_class,why",
    [
        ("IPM.Schedule.Meeting.Resp.Pos", "meeting response"),
        ("IPM.Schedule.Meeting.Resp.Neg", "meeting response"),
        ("REPORT.IPM.Note.IPNRN", "read receipt"),
        ("REPORT.IPM.Note.IPNNRN", "read receipt"),
        ("IPM.Note.Rules.Oof.Template.Microsoft", "out-of-office reply"),
    ],
)
def test_message_classes_that_mean_a_machine(message_class, why):
    assert flags(FakeItem(MessageClass=message_class)) == (True, why)


def test_a_plain_mail_is_not_bulk():
    assert flags(FakeItem()) == (False, "")


def test_a_failing_property_accessor_is_not_bulk():
    item = FakeItem(headers="List-Unsubscribe: <mailto:u@b.c>", fail=True)
    assert flags(item) == (False, "")
    assert item.header_reads == 1, "the failure is not retried"


def test_no_property_accessor_at_all_is_not_bulk():
    from outlook_mcp.client.mail import bulk_flags

    item = FakeItem()
    del item.PropertyAccessor
    assert bulk_flags(item) == (False, "")


# ------------------------------------------------------- list / search --


def test_listed_mails_carry_bulk_and_the_headers_are_read_once():
    from outlook_mcp.client.mail import list_mails

    news = FakeItem("a", headers="List-Unsubscribe: <mailto:u@b.c>\r\n")
    plain = FakeItem("b")
    out = list_mails(None, FakeNamespace(FakeFolder("Inbox", [news, plain])), preview_chars=0)
    assert [(i["entry_id"], i["bulk"], i["bulk_why"]) for i in out["items"]] == [
        ("a", True, "List-Unsubscribe header"),
        ("b", False, ""),
    ]
    assert news.header_reads == 1 and plain.header_reads == 1


def test_the_headers_are_left_alone_when_bulk_was_not_asked_for():
    from outlook_mcp.client.mail import list_mails

    news = FakeItem("a", headers="List-Unsubscribe: <mailto:u@b.c>\r\n")
    out = list_mails(
        None,
        FakeNamespace(FakeFolder("Inbox", [news])),
        fields=["subject", "from_address"],
        preview_chars=0,
    )
    assert "bulk" not in out["items"][0]
    assert news.header_reads == 0


def test_asking_for_bulk_alone_leaves_the_reason_behind():
    """Why every caller names both keys: fields filters bulk_why like any other,
    and vault_rules(action="match") has nothing to name in its drop reason."""
    from outlook_mcp.client.mail import list_mails

    folder = FakeNamespace(FakeFolder("Inbox", [FakeItem("a", headers="Precedence: bulk\r\n")]))
    thin = list_mails(None, folder, fields=["subject", "bulk"], preview_chars=0)
    assert thin["items"][0]["bulk"] is True and "bulk_why" not in thin["items"][0]
    full = list_mails(None, folder, fields=["subject", "bulk", "bulk_why"], preview_chars=0)
    assert full["items"][0]["bulk_why"] == "Precedence: bulk"


def test_the_load_history_window_is_listed_with_both_keys():
    """The call vault_load_history hands the model runs vault_rules on its
    answer, so the fields it names carry the flag and the reason."""
    from soma_vault.history import MAIL_FIELDS

    assert "bulk" in MAIL_FIELDS and "bulk_why" in MAIL_FIELDS


def test_bulk_in_fields_asks_for_it_and_nothing_else():
    from outlook_mcp.client.mail import list_mails

    news = FakeItem("a", headers="Precedence: bulk\r\n")
    out = list_mails(
        None,
        FakeNamespace(FakeFolder("Inbox", [news])),
        fields=["subject", "bulk", "bulk_why"],
        preview_chars=0,
    )
    assert out["items"][0] == {
        "entry_id": "a",
        "subject": "Subject",
        "bulk": True,
        "bulk_why": "Precedence: bulk",
    }
    assert news.header_reads == 1


def test_searched_mails_carry_bulk_too():
    from outlook_mcp.client.mail import search_mails

    news = FakeItem("a", Subject="Weekly digest", headers="Precedence: list\r\n")
    out = search_mails(
        None, FakeNamespace(FakeFolder("Inbox", [news])), query="digest", preview_chars=0
    )
    assert out["items"][0]["bulk"] is True and out["items"][0]["bulk_why"] == "Precedence: list"
    assert news.header_reads == 1
