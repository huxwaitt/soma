"""Tests for outlook_mcp.utils.trim.trim_quoted and its wiring into
outlook_get_mail / outlook_get_conversation (fake COM, fake bridge)."""

import asyncio
import datetime as dt
import json
import sys
from types import SimpleNamespace

import pytest

from outlook_mcp.utils.trim import trim_quoted

# ------------------------------------------------------------- samples --

OUTLOOK_DESKTOP = """Hi Anna,

yes, Thursday 10:00 works for me. I'll book the room.

Best,
Bob

-----Original Message-----
From: Anna Schmidt <anna@example.com>
Sent: Monday, March 2, 2026 9:14 AM
To: Bob Miller <bob@example.com>
Subject: RE: Project kickoff

Hi Bob, could we meet Thursday?
"""

OWA_UNDERSCORES = """Thanks, received. I'll review the draft tonight and send comments tomorrow.

Regards
Bob

________________________________
From: Anna Schmidt <anna@example.com>
Sent: Monday, March 2, 2026 9:14 AM
To: Bob Miller
Subject: Draft v2

Attached is draft v2, please review.
"""

GMAIL_WRAPPED = """Sounds good, let's go with option B and revisit pricing next quarter.

Bob

On Mon, 2 Mar 2026 at 09:14, Anna Schmidt
<anna@example.com> wrote:
> Option A or option B? I lean towards B.
"""

IOS = """Can you send me the invoice number? I'll pay it today.

Sent from my iPhone

> On 2 Mar 2026, at 09:14, Anna Schmidt <anna@example.com> wrote:
>
> Invoice is overdue.
"""

GERMAN = """Hallo Anna,

vielen Dank, das passt so. Ich melde mich morgen wegen der Details.

Viele Grüße
Bob

Von: Anna Schmidt <anna@example.com>
Gesendet: Montag, 2. März 2026 09:14
An: Bob Miller <bob@example.com>
Betreff: AW: Angebot

Hallo Bob, anbei das Angebot.
"""

QUOTED_THREAD = """Agreed on all three points, I'll update the ticket accordingly.

> 1. Move the deadline to Friday
> 2. Assign QA to Maria
> 3. Skip the second review round
> -- Anna
"""

SIGNATURE_ONLY = """Hi Anna,

the server migration finished last night without issues. All services are back.

Best regards
Bob Miller
Senior Engineer, Example GmbH
Tel +49 30 1234567
www.example.com
"""

SHORT = """Hi Anna,
ok from my side.
Bob"""


# -------------------------------------------------------- unit tests --


def test_outlook_desktop_header_block():
    trimmed, chars, markers = trim_quoted(OUTLOOK_DESKTOP, "Bob Miller", "bob@example.com")
    assert "Original Message" not in trimmed and "anna@example.com" not in trimmed
    assert trimmed.endswith("Bob")
    assert chars == len(OUTLOOK_DESKTOP) - len(trimmed) > 0
    assert markers[0] == "outlook separator"


def test_owa_underscore_separator():
    trimmed, chars, markers = trim_quoted(OWA_UNDERSCORES, "Bob Miller")
    assert "____" not in trimmed and "Draft v2" not in trimmed
    assert trimmed.endswith("Regards\nBob")
    assert markers == ["outlook separator"]


def test_gmail_on_wrote_wrapped_two_lines():
    trimmed, chars, markers = trim_quoted(GMAIL_WRAPPED, "Bob Miller")
    assert "wrote:" not in trimmed and "Option A" not in trimmed
    assert trimmed.endswith("Bob")
    assert markers == ["on-wrote (wrapped)"]


def test_ios_sent_from_my_iphone():
    trimmed, chars, markers = trim_quoted(IOS, "Bob Miller")
    assert trimmed == "Can you send me the invoice number? I'll pay it today."
    assert "mobile signature" in markers
    assert chars > 0


def test_german_von_block():
    trimmed, chars, markers = trim_quoted(GERMAN, "Bob Miller")
    assert "Von:" not in trimmed and "Angebot" not in trimmed
    assert trimmed.endswith("Viele Grüße\nBob")
    assert markers == ["header block (foreign)"]


def test_quoted_gt_thread():
    trimmed, chars, markers = trim_quoted(QUOTED_THREAD, "Bob Miller")
    assert trimmed == "Agreed on all three points, I'll update the ticket accordingly."
    assert markers == ["quoted lines"]


def test_signature_only_by_sender_name():
    trimmed, chars, markers = trim_quoted(SIGNATURE_ONLY, "Bob Miller", "bob@example.com")
    assert "Tel" not in trimmed and "www.example.com" not in trimmed
    assert trimmed.endswith("Best regards")
    assert markers == ["name signature"]
    assert chars == len(SIGNATURE_ONLY) - len(trimmed)


def test_three_line_mail_not_trimmed():
    trimmed, chars, markers = trim_quoted(SHORT, "Bob Miller")
    assert trimmed == SHORT and chars == 0
    assert markers in ([], ["kept: too short"])


def test_too_short_keeps_original():
    body = "ok\n\nSent from my iPhone\n"
    trimmed, chars, markers = trim_quoted(body, "Bob")
    assert trimmed == body and chars == 0 and markers == ["kept: too short"]


def test_blank_lines_collapsed_and_crlf():
    body = "Line one here, long enough.\r\n\r\n\r\n\r\n\r\nLine two.\r\n-- \r\nsig\r\n"
    trimmed, chars, markers = trim_quoted(body, "")
    assert trimmed == "Line one here, long enough.\n\n\nLine two."
    assert markers == ["signature (--)"]


def test_empty_body():
    assert trim_quoted("", "Bob") == ("", 0, [])


# -------------------------------------------------------- tool tests --

pytestmark_tools = pytest.mark.skipif(sys.platform != "win32", reason="client modules import pywin32")


class FakeItem:
    Class = 43

    def __init__(self, entry_id, body, conversation=None):
        self.EntryID = entry_id
        self.Subject = "Subj"
        self.SenderName = "Bob Miller"
        self.SenderEmailAddress = "bob@example.com"
        self.SenderEmailType = "SMTP"
        self.To = "anna@example.com"
        self.CC = ""
        self.BCC = ""
        self.Recipients = None
        self.ReceivedTime = dt.datetime(2026, 3, 2, 9, 0, 0)
        self.SentOn = self.ReceivedTime
        self.UnRead = False
        self.FlagStatus = 0
        self.Attachments = None
        self.Importance = 1
        self.Categories = ""
        self.Body = body
        self.ConversationID = "conv-1"
        self.Parent = SimpleNamespace(Name="Inbox")
        self.PropertyAccessor = None
        self._conversation = conversation

    def GetConversation(self):
        return self._conversation


class FakeNamespace:
    def __init__(self, items):
        self._items = {i.EntryID: i for i in items}

    def GetItemFromID(self, entry_id, store_id=None):
        return self._items[entry_id]


class FakeBridge:
    def __init__(self, namespace):
        self._ns = namespace

    async def call(self, func, *args, **kwargs):
        return func(None, self._ns, *args, **kwargs)


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, name=None, **_kw):
        def deco(fn):
            self.tools[name or fn.__name__] = fn
            return fn

        return deco


def _tools(items):
    from outlook_mcp.tools import mail as mail_tools

    mcp = FakeMCP()
    mail_tools.register(mcp, FakeBridge(FakeNamespace(items)))
    return mcp.tools


FIELDS = ("body_trimmed", "trimmed_chars", "trim_markers")


@pytestmark_tools
def test_get_mail_fields_only_with_trim_quoted():
    tools = _tools([FakeItem("a", OUTLOOK_DESKTOP)])
    get_mail = tools["outlook_get_mail"]

    plain = asyncio.run(get_mail(entry_id="a", response_format="json")).structuredContent
    assert plain["body"] == OUTLOOK_DESKTOP
    assert not any(f in plain for f in FIELDS)

    result = asyncio.run(get_mail(entry_id="a", trim_quoted=True, response_format="json"))
    res = result.structuredContent
    assert res["body"] == OUTLOOK_DESKTOP
    assert all(f in res for f in FIELDS)
    assert "Original Message" not in res["body_trimmed"]
    assert res["trimmed_chars"] == len(OUTLOOK_DESKTOP) - len(res["body_trimmed"])
    assert res["trim_markers"] == ["outlook separator"]
    # Also present in the JSON text returned to the model.
    assert "body_trimmed" in json.loads(result.content[0].text)


@pytestmark_tools
def test_get_mail_no_body_no_trim_fields():
    tools = _tools([FakeItem("a", OUTLOOK_DESKTOP)])
    res = asyncio.run(tools["outlook_get_mail"](entry_id="a", include_body=False, trim_quoted=True)).structuredContent
    assert "body" not in res and not any(f in res for f in FIELDS)


@pytestmark_tools
def test_get_conversation_fields_only_with_trim_quoted():
    tools = _tools([FakeItem("a", GERMAN)])
    conv = tools["outlook_get_conversation"]

    plain = json.loads(asyncio.run(conv(entry_id="a", include_body=True)))
    assert not any(f in plain["items"][0] for f in FIELDS)

    res = json.loads(asyncio.run(conv(entry_id="a", include_body=True, trim_quoted=True)))
    item = res["items"][0]
    assert item["body"] == GERMAN
    assert all(f in item for f in FIELDS)
    assert "Von:" not in item["body_trimmed"]
    assert item["trim_markers"] == ["header block (foreign)"]

    # Without include_body there is nothing to trim.
    res = json.loads(asyncio.run(conv(entry_id="a", trim_quoted=True)))
    assert not any(f in res["items"][0] for f in FIELDS)
