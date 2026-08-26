"""v0.5 server additions: fields / preview_chars on list, search and get
tools; include_slots / busy_blocks_only on free/busy; and the three
workflows computed in code (awaiting_reply, find, voice_sample). All
against fakes."""

import asyncio
import datetime as dt
import json
import re
import sys
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="client modules import pywin32"
)

ME = "hux@example.com"
LIKE = re.compile(r"LIKE '%(.*?)%'")
DATE_GE = re.compile(r"datereceived\" >= '(\d\d)/(\d\d)/(\d{4}) (\d\d):(\d\d) (AM|PM)'")


# ---------------------------------------------------------------- fakes --


class FakeAccessor:
    def __init__(self, props):
        self.props = props

    def GetProperty(self, tag):
        if tag not in self.props:
            raise RuntimeError("MAPI_E_NOT_FOUND")
        return self.props[tag]


class FakeRecipient:
    def __init__(self, name, address, kind=1):
        self.Name = name
        self.Address = address
        self.Type = kind
        self.PropertyAccessor = FakeAccessor({})
        self.AddressEntry = None


class FakeConversation:
    def __init__(self, items):
        self._items = list(items)

    def GetRootItems(self):
        return [self._items[0]]

    def GetChildren(self, node):
        if node is self._items[0]:
            return self._items[1:]
        return []


class FakeItem:
    Class = 43

    def __init__(
        self,
        entry_id,
        received,
        *,
        subject="Subj",
        sender="Bob Lee",
        sender_address="bob@example.com",
        to="Hux Waitt",
        recipients=None,
        body="body text here",
        conversation_id=None,
        folder="Inbox",
        message_id=None,
    ):
        self.EntryID = entry_id
        self.Subject = subject
        self.SenderName = sender
        self.SenderEmailAddress = sender_address
        self.SenderEmailType = "SMTP"
        self.To = to
        self.CC = ""
        self.BCC = ""
        self.Recipients = recipients
        self.ReceivedTime = received
        self.SentOn = received
        self.UnRead = False
        self.FlagStatus = 0
        self.Attachments = None
        self.Importance = 1
        self.Categories = ""
        self.Body = body
        self.ConversationID = conversation_id or f"conv-{entry_id}"
        self.Parent = SimpleNamespace(Name=folder)
        self.PropertyAccessor = FakeAccessor(
            {} if message_id is None else {"http://schemas.microsoft.com/mapi/proptag/0x1035001F": message_id}
        )
        self._conversation = None

    def GetConversation(self):
        return self._conversation


class FakeItems(list):
    """Understands just enough DASL: LIKE '%word%' on from / subject+body,
    and a datereceived lower bound."""

    def __init__(self, items):
        super().__init__(items)
        self.filters = []

    def Sort(self, key, descending=False):
        self.sort(key=lambda i: i.ReceivedTime, reverse=descending)

    def Restrict(self, dasl):
        self.filters.append(dasl)
        kept = list(self)
        m = DATE_GE.search(dasl)
        if m:
            mo, d, y, h, mi, ap = m.groups()
            hour = int(h) % 12 + (12 if ap == "PM" else 0)
            bound = dt.datetime(int(y), int(mo), int(d), hour, int(mi))
            kept = [i for i in kept if i.ReceivedTime >= bound]
        words = LIKE.findall(dasl)
        if words:
            w = words[0].lower()
            if "fromemail" in dasl:
                kept = [i for i in kept if w in (i.SenderName + " " + i.SenderEmailAddress).lower()]
            else:
                kept = [i for i in kept if w in (i.Subject + " " + i.Body).lower()]
        out = FakeItems(kept)
        out.filters = self.filters
        return out


class FakeFolder:
    def __init__(self, name, items=(), subfolders=()):
        self.Name = name
        self.Items = FakeItems(list(items))
        self.Folders = list(subfolders)
        self.FolderPath = f"\\\\Mailbox\\{name}"


class FakeNamespace:
    def __init__(self, inbox=None, sent=None, calendar=None, items=(), me=ME, my_name="Hux Waitt"):
        self._folders = {6: inbox or FakeFolder("Inbox"), 5: sent or FakeFolder("Sent Items"), 9: calendar or FakeFolder("Calendar")}
        self._items = {i.EntryID: i for i in items}
        self.Stores = []
        self.CurrentUser = FakeRecipient(my_name, me)

    def GetDefaultFolder(self, which):
        return self._folders[which]

    def GetItemFromID(self, entry_id, store_id=None):
        return self._items[entry_id]


def _t(day, hour=9, month=8):
    return dt.datetime(2026, month, day, hour, 0, 0)


def _thread(*items):
    conv = FakeConversation(items)
    for it in items:
        it._conversation = conv
        it.ConversationID = items[0].ConversationID
    return items


# ------------------------------------------------------------ fields --


def test_pick_and_apply_fields():
    from outlook_mcp.utils.fields import apply_fields, pick_fields

    item = {"entry_id": "a", "subject": "s", "preview": "p", "from": "f"}
    assert pick_fields(item, ["subject", "nope"]) == {"entry_id": "a", "subject": "s"}
    assert pick_fields(item, None) is item
    assert pick_fields(item, [" ", ""]) is item
    data = apply_fields({"count": 1, "items": [dict(item)]}, ["from"])
    assert data["items"] == [{"entry_id": "a", "from": "f"}] and data["fields"] == ["from"]
    assert apply_fields(dict(item), ["subject"]) == {"entry_id": "a", "subject": "s"}


def test_list_and_search_mails_fields_and_preview_chars():
    from outlook_mcp.client.mail import list_mails, search_mails

    a = FakeItem("a", _t(20), subject="Budget Q3", body="x" * 500)
    b = FakeItem("b", _t(21), subject="Offsite", body="short")
    ns = FakeNamespace(inbox=FakeFolder("Inbox", [a, b]))

    out = list_mails(None, ns, fields=["subject", "received", "bogus"], preview_chars=80)
    assert out["fields"] == ["subject", "received", "bogus"]
    assert out["items"][0] == {"entry_id": "b", "subject": "Offsite", "received": out["items"][0]["received"]}

    out = list_mails(None, ns, preview_chars=0)
    assert "preview" not in out["items"][0]
    out = list_mails(None, ns, preview_chars=10)
    assert out["items"][1]["preview"] == "x" * 10 + "…"

    out = search_mails(None, ns, query="budget", fields=["subject"], preview_chars=0)
    assert out["items"] == [{"entry_id": "a", "subject": "Budget Q3"}]
    # default shape is unchanged
    assert "preview" in search_mails(None, ns, query="budget")["items"][0]


def test_get_mail_and_conversation_fields():
    from outlook_mcp.client.mail import get_conversation, get_mail

    root, reply = _thread(FakeItem("r", _t(1), body="one"), FakeItem("r1", _t(2), body="two", folder="Sent Items"))
    ns = FakeNamespace(items=[root, reply])

    out = get_mail(None, ns, entry_id="r", fields=["subject", "conversation_id"])
    assert out == {"entry_id": "r", "subject": "Subj", "conversation_id": "conv-r"}

    out = get_conversation(None, ns, entry_id="r", include_body=True, fields=["body", "folder"], preview_chars=0)
    assert out["count"] == 2 and out["conversation_id"] == "conv-r"
    assert out["items"] == [
        {"entry_id": "r", "folder": "Inbox", "body": "one"},
        {"entry_id": "r1", "folder": "Sent Items", "body": "two"},
    ]
    out = get_conversation(None, ns, entry_id="r", preview_chars=0)
    assert "preview" not in out["items"][0] and "folder" in out["items"][0]


def test_search_attachments_and_advanced_search_fields():
    from outlook_mcp.client.mail import advanced_search, search_attachments

    class Att:
        FileName = "Budget.xlsx"
        Size = 10
        PropertyAccessor = FakeAccessor({})

    class Atts(list):
        @property
        def Count(self):
            return len(self)

    a = FakeItem("a", _t(20))
    a.Attachments = Atts([Att()])
    ns = FakeNamespace(inbox=FakeFolder("Inbox", [a]))
    ns.Stores = [SimpleNamespace(GetRootFolder=lambda: FakeFolder("root"))]
    out = search_attachments(None, ns, query="budget", fields=["matches", "folder"])
    assert out["items"] == [{"entry_id": "a", "folder": "Inbox", "matches": [{"index": 1, "filename": "Budget.xlsx", "size_bytes": 10}]}]

    search = SimpleNamespace(Results=[a], Stop=lambda: None)
    app = SimpleNamespace(AdvancedSearch=lambda scope, dasl, sub, tag: search)
    out = advanced_search(app, ns, query="budget", fields=["subject"], _wait=lambda s, **kw: False)
    assert out["items"] == [{"entry_id": "a", "subject": "Subj"}] and out["count"] == 1


def test_list_events_and_get_event_fields():
    from outlook_mcp.client.calendar import get_event, list_events

    class FakeEvent:
        def __init__(self, entry_id, start):
            self.EntryID = entry_id
            self.GlobalAppointmentID = "G" + entry_id
            self.Subject = "Stand-up"
            self.Start = start
            self.End = start + dt.timedelta(minutes=30)
            self.Location = "Teams"
            self.Organizer = "Bob Lee"
            self.Recipients = None
            self.ResponseStatus = 3
            self.RecurrenceState = 0
            self.AllDayEvent = False
            self.Body = "agenda"
            self.ReminderMinutesBeforeStart = 15
            self.Categories = ""
            self.PropertyAccessor = None
            self.ReceivedTime = start

    class CalItems(list):
        IncludeRecurrences = False

        def Sort(self, key, descending=False):
            pass

        def Restrict(self, f):
            return self

    ev = FakeEvent("e1", _t(24, 9))
    cal = FakeFolder("Calendar")
    cal.Items = CalItems([ev])
    ns = FakeNamespace(calendar=cal, items=[ev])

    out = list_events(None, ns, start="2026-08-24T00:00:00", end="2026-08-24T23:59:59", fields=["subject", "start", "occurrence_key"])
    assert out["count"] == 1
    assert set(out["items"][0]) == {"entry_id", "subject", "start", "occurrence_key"}
    assert out["items"][0]["occurrence_key"].startswith("Ge1|2026-08-24T09:00")
    full = list_events(None, ns, start="2026-08-24T00:00:00", end="2026-08-24T23:59:59")["items"][0]
    assert "attendees" in full and "preview" in full

    out = get_event(None, ns, entry_id="e1", fields=["subject", "body"])
    assert out == {"entry_id": "e1", "subject": "Stand-up", "body": "agenda"}
    assert "reminder_minutes" in get_event(None, ns, entry_id="e1")


# ---------------------------------------------------------- free/busy --


class FbRecipient:
    def __init__(self, address, digits):
        self.Address = address
        self.Name = address
        self._digits = digits
        self.PropertyAccessor = FakeAccessor({})

    def Resolve(self):
        return True

    def FreeBusy(self, start, interval, full):
        return self._digits


class FbNamespace:
    def __init__(self, recipients):
        self._recipients = recipients
        self.CurrentUser = FbRecipient(ME, "")

    def CreateRecipient(self, addr):
        return self._recipients[addr]


def test_free_busy_busy_blocks_only_and_include_slots():
    from outlook_mcp.client.freebusy import find_meeting_times, get_free_busy

    digits = "0" * 18 + "22" + "0" * 28  # 09:00-10:00 busy at 30 min
    ns = FbNamespace({"a@example.com": FbRecipient("a@example.com", digits)})
    out = get_free_busy(None, ns, addresses=["a@example.com"], start="2026-08-24T08:00", end="2026-08-24T12:00")
    p = out["people"][0]
    assert "slots" not in p and p["busy_blocks"][0]["start"][11:16] == "09:00" and p["has_data"]
    out = get_free_busy(None, ns, addresses=["a@example.com"], start="2026-08-24T08:00", end="2026-08-24T12:00", busy_blocks_only=False)
    assert len(out["people"][0]["slots"]) == 8

    digits15 = "0" * 36 + "2" * 4 + "0" * 56
    ns = FbNamespace({"a@example.com": FbRecipient("a@example.com", digits15)})
    out = find_meeting_times(None, ns, addresses=["a@example.com"], start="2026-08-24T00:00", end="2026-08-25T00:00", duration_minutes=30, include_self=False, max_results=2)
    assert "people" not in out and out["count"] == 2
    out = find_meeting_times(None, ns, addresses=["a@example.com"], start="2026-08-24T00:00", end="2026-08-25T00:00", duration_minutes=30, include_self=False, max_results=2, include_slots=True)
    assert out["people"][0]["address"] == "a@example.com"
    assert isinstance(out["people"][0]["slots"], list) and out["people"][0]["busy_blocks"][0]["status"] == "busy"
    assert isinstance(out["people"][0]["slots"][0]["start"], str)


# ------------------------------------------------------ awaiting_reply --


def _sent(entry_id, received, *, to_name="Tom Lee", to_addr="tom@acme.example", body=None, subject="Delivery", cc=()):
    recips = [FakeRecipient(to_name, to_addr, 1)] + [FakeRecipient(n, a, 2) for n, a in cc]
    return FakeItem(
        entry_id,
        received,
        subject=subject,
        sender="Hux Waitt",
        sender_address=ME,
        to=to_name,
        recipients=recips,
        body=body or "Hi Tom,\n\nCan you confirm 8 Sep works?\n\nThanks\nHux",
        folder="Sent Items",
        message_id=f"<{entry_id}@example.com>",
    )


def test_awaiting_reply_keeps_only_waiting_threads():
    from outlook_mcp.client.workflows import awaiting_reply

    now = _t(22, 10)
    # 1. waiting: my mail 6 days old, nobody answered
    s1, = _thread(_sent("s1", _t(16), subject="Delivery schedule"))
    # 2. answered: Tom replied after my mail
    s2, r2 = _thread(_sent("s2", _t(15), subject="Venue"), FakeItem("r2", _t(17), sender="Tom Lee", sender_address="tom@acme.example", folder="Inbox"))
    # 3. too young: sent yesterday
    s3, = _thread(_sent("s3", _t(21), subject="Spec"))
    # 4. to myself only
    s4, = _thread(_sent("s4", _t(10), to_name="Hux Waitt", to_addr=ME, subject="note to self"))
    # 5. calendar response
    s5, = _thread(_sent("s5", _t(10), subject="Accepted: Stand-up"))
    # 6. second mail of thread 1 (older), must not create a second thread
    s6 = FakeItem("s6", _t(12), sender="Hux Waitt", sender_address=ME, to="Tom Lee", folder="Sent Items")
    s6._conversation = s1._conversation
    s6.ConversationID = s1.ConversationID
    s1._conversation._items.append(s6)
    # 7. waiting, 10 days, body with signature details; cc only
    s7, = _thread(_sent("s7", _t(12), subject="Packaging", body="Hello Priya,\n\nWhich venue should I hold?\n\nBest regards,\nHux Waitt\nTel 0123 456789"))
    s7.Recipients = [FakeRecipient("Hux Waitt", ME, 1), FakeRecipient("Priya Nair", "priya@northwind.example", 2)]

    sent = FakeFolder("Sent Items", [s1, s2, s3, s4, s5, s6, s7])
    ns = FakeNamespace(sent=sent)
    out = awaiting_reply(None, ns, days=3, since_days=30, now=now)

    assert out["self"] == ME and out["folder"] == "Sent Items"
    assert out["threads_checked"] == 5 and out["capped"] is False  # s4 and s5 skipped before the cap, s6 folded into s1
    assert out["count"] == 2
    first, second = out["items"]
    assert first["subject"] == "Packaging" and first["days_waiting"] == 10
    assert first["to"] == ["priya@northwind.example"] and first["last_line"] == "Which venue should I hold?"
    assert second == {
        "conversation_id": s1.ConversationID,
        "entry_id": "s1",
        "internet_message_id": "<s1@example.com>",
        "subject": "Delivery schedule",
        "to": ["tom@acme.example"],
        "to_names": "Tom Lee",
        "last_sent": second["last_sent"],
        "days_waiting": 6,
        "last_line": "Can you confirm 8 Sep works?",
    }
    assert second["last_sent"].startswith("2026-08-16T09:00")
    assert "datereceived" in sent.Items.filters[0]

    # limit and cap
    out = awaiting_reply(None, ns, days=3, limit=1, now=now)
    assert out["count"] == 1 and out["items"][0]["subject"] == "Packaging"
    out = awaiting_reply(None, ns, days=3, max_conversations=1, now=now)
    assert out["capped"] is True and out["threads_checked"] == 1


def test_awaiting_reply_without_current_user_uses_sender_of_sent_mail():
    from outlook_mcp.client.workflows import awaiting_reply

    s1, = _thread(_sent("s1", _t(10)))
    ns = FakeNamespace(sent=FakeFolder("Sent Items", [s1]))
    ns.CurrentUser = None
    out = awaiting_reply(None, ns, now=_t(22))
    assert out["self"] == ME and out["count"] == 1


# ---------------------------------------------------------------- find --


def test_best_sentence_picks_most_query_words():
    from outlook_mcp.client.workflows import best_sentence

    text = "Hi Sam.\nWe agreed on the Q3 budget yesterday! Let me know.\nBudget stays flat?"
    assert best_sentence(text, ["budget", "agreed"]) == "We agreed on the Q3 budget yesterday!"
    assert best_sentence(text, []) == "Hi Sam."
    assert best_sentence("", ["x"]) == ""
    assert best_sentence("a" * 300, ["x"]).endswith("…") and len(best_sentence("a" * 300, ["x"])) == 201


def test_find_merges_scores_and_snippets():
    from outlook_mcp.client.workflows import find

    sam_budget = FakeItem("a", _t(10), subject="Q3 budget", sender="Sam Ortiz", sender_address="sam@example.com", body="Hi.\nWe agreed the budget stays at 120k.\nBye")
    sam_other = FakeItem("b", _t(12), subject="Lunch", sender="Sam Ortiz", sender_address="sam@example.com", body="pizza?")
    bob_budget = FakeItem("c", _t(11), subject="Re: budget", sender="Bob Lee", sender_address="bob@example.com", body="budget looks fine")
    old = FakeItem("d", _t(1, month=6), subject="budget 2025", sender="Sam Ortiz", sender_address="sam@example.com", body="old")
    # a newer reply in the same conversation as sam_budget, found via the word search, sits in Sent
    my_reply = FakeItem("e", _t(13), subject="Re: Q3 budget", sender="Hux Waitt", sender_address=ME, body="Agreed, budget it is.", folder="Sent Items", conversation_id="conv-a")
    inbox = FakeFolder("Inbox", [sam_budget, sam_other, bob_budget, old])
    sent = FakeFolder("Sent Items", [my_reply])
    ns = FakeNamespace(inbox=inbox, sent=sent)

    out = find(None, ns, people=["Sam"], words=["budget", "agreed"], since="2026-08-01T00:00:00", limit=3)
    assert out["folders_searched"] == 2 and out["searches"] == 6  # 3 queries x 2 folders
    assert out["candidates"] == 3  # conv-a (a + e merged), b, c; d is before since
    # b and c tie on 4; the newer one (b) comes first
    assert [i["entry_id"] for i in out["items"]] == ["e", "b", "c"]
    top = out["items"][0]
    assert top["folder"] == "Sent Items" and top["conversation_id"] == "conv-a"
    # newest mail of the conversation is from me, so no person score: subject 2 + body 2 + date 1
    assert top["score"] == 5 and top["snippet"] == "Agreed, budget it is."
    assert top["body_read"] is True
    assert out["items"][1]["score"] == 4 and out["items"][1]["snippet"] == "pizza?"  # person 3 + date 1
    assert out["items"][2]["score"] == 4  # subject 2 + body 1 + date 1
    assert set(top) == {"entry_id", "conversation_id", "subject", "from_address", "received", "score", "snippet", "folder", "body_read"}

    out = find(None, ns, people=["sam@example.com"], folders=["inbox"])
    assert out["searches"] == 1 and [i["entry_id"] for i in out["items"]] == ["b", "a", "d"]
    assert out["items"][0]["score"] == 3 and out["items"][1]["snippet"] == "Hi."

    with pytest.raises(Exception, match="at least one"):
        find(None, ns)


def test_find_walks_subfolders_and_reads_bodies_only_for_top():
    from outlook_mcp.client.workflows import find

    sub = FakeFolder("Projects", [FakeItem("p", _t(21), subject="budget plan", body="deep budget")])
    inbox = FakeFolder("Inbox", [FakeItem(f"i{n}", _t(1 + n % 20, 8), subject="budget", body="budget") for n in range(25)], [sub])
    ns = FakeNamespace(inbox=inbox, sent=FakeFolder("Sent Items"))
    out = find(None, ns, words=["budget"], folders=["inbox"], include_subfolders=True, limit=30, body_top=5)
    assert out["folders_searched"] == 2 and out["candidates"] == 26
    assert sum(1 for i in out["items"] if i["body_read"]) == 5
    assert out["items"][0]["entry_id"] == "p" and out["items"][0]["folder"] == "Projects"  # subject 2 + body 1


# -------------------------------------------------------- voice_sample --


def test_voice_sample_by_address_and_fallback():
    from outlook_mcp.client.workflows import voice_sample

    def mail(i, to_addr, body, subject="Subj"):
        return _sent(f"m{i}", _t(1 + i), to_name=to_addr.split("@")[0], to_addr=to_addr, body=body, subject=subject)

    tom = "tom@acme.example"
    items = [
        mail(1, tom, "Hi Tom,\n\nCan you confirm the date?\n\nThanks\nHux\n\nFrom: Tom\nSent: x\nTo: y\nSubject: z\nold quoted"),
        mail(2, tom, "Hi Tom,\n\nSending the spec now. Let me know what you think about it.\n\nBest regards,\nHux Waitt\nTel 0123"),
        mail(3, tom, "Hello Tom,\n\nDone.\n\nCheers,\nHux"),
        mail(4, "jane@example.com", "Good morning Jane,\n\nBudget attached.\n\nViele Grüße\nHux"),
        mail(5, "jane@example.com", "Jane, quick one: is Thursday ok?\n\nThanks\nHux"),
    ]
    ns = FakeNamespace(sent=FakeFolder("Sent Items", items))

    out = voice_sample(None, ns, address=tom, n=10, max_chars=50)
    assert out["used_address"] is True and out["matched"] == 3 and out["count"] == 3
    assert [i["to"] for i in out["items"]] == [[tom]] * 3
    newest = out["items"][0]
    assert newest["entry_id"] == "m3" and newest["opening"] == "Hello Tom,\n\nDone.\n\nCheers,\nHux" and newest["closing"] == ["Cheers,", "Hux"]
    assert out["items"][2]["opening"] == "Hi Tom,\n\nCan you confirm the date?\n\nThanks\nHux"  # quoted history cut
    # the name + phone signature is cut by trim_quoted, so the closing ends at the sign-off
    assert out["items"][1]["opening"].endswith("…")
    assert out["items"][1]["closing"] == ["Sending the spec now. Let me know what you think about it.", "Best regards,"]
    assert out["stats"]["greeting_counts"] == {"hi": 2, "hello": 1}
    assert out["stats"]["signoff_counts"] == {"best regards": 1, "cheers": 1, "thanks": 1}
    assert out["stats"]["avg_chars"] > 0

    # fewer than 3 to Jane -> overall newest n
    out = voice_sample(None, ns, address="jane@example.com", n=4)
    assert out["used_address"] is False and out["matched"] == 2 and out["count"] == 4
    assert [i["entry_id"] for i in out["items"]] == ["m5", "m4", "m3", "m2"]
    assert out["stats"]["greeting_counts"] == {"good morning": 1, "hello": 1, "hi": 1, "jane": 1}
    assert out["stats"]["signoff_counts"]["viele grüße"] == 1

    out = voice_sample(None, ns, n=2)
    assert out["address"] == "" and out["used_address"] is False and out["count"] == 2


# --------------------------------------------------------- registration --


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


def test_workflow_tool_wrappers_return_json():
    from outlook_mcp.tools import mail as mail_tools
    from outlook_mcp.tools import workflows as wf_tools

    s1, = _thread(_sent("s1", _t(10), subject="Delivery"))
    inbox = FakeFolder("Inbox", [FakeItem("a", _t(20), subject="budget", body="budget talk")])
    ns = FakeNamespace(inbox=inbox, sent=FakeFolder("Sent Items", [s1]), items=[s1])
    mcp = FakeMCP()
    wf_tools.register(mcp, FakeBridge(ns))
    mail_tools.register(mcp, FakeBridge(ns))
    assert {"outlook_awaiting_reply", "outlook_find", "outlook_voice_sample"} <= set(mcp.tools)

    res = json.loads(asyncio.run(mcp.tools["outlook_awaiting_reply"](days=1)))
    assert res["count"] == 1 and res["items"][0]["subject"] == "Delivery"
    res = json.loads(asyncio.run(mcp.tools["outlook_find"](words=["budget"], folders=["inbox"])))
    assert res["count"] == 1 and res["items"][0]["snippet"] == "budget talk"
    res = json.loads(asyncio.run(mcp.tools["outlook_voice_sample"](n=1)))
    assert res["count"] == 1 and res["items"][0]["closing"] == ["Thanks", "Hux"]
    res = json.loads(asyncio.run(mcp.tools["outlook_get_conversation"](entry_id="s1", fields=["subject"], preview_chars=0)))
    assert res["items"] == [{"entry_id": "s1", "subject": "Delivery"}]


def test_server_has_46_outlook_tools_and_new_params():
    from outlook_mcp.server import build_server

    mcp, _bridge = build_server()
    tools = {t.name: t for t in asyncio.run(mcp.list_tools()) if t.name.startswith("outlook_")}
    assert len(tools) == 46
    assert {"outlook_awaiting_reply", "outlook_find", "outlook_voice_sample"} <= set(tools)
    for name in (
        "outlook_list_mails",
        "outlook_search_mails",
        "outlook_get_mail",
        "outlook_get_conversation",
        "outlook_list_events",
        "outlook_get_event",
        "outlook_advanced_search",
        "outlook_search_attachments",
    ):
        assert "fields" in tools[name].inputSchema["properties"], name
    for name in ("outlook_list_mails", "outlook_search_mails", "outlook_get_conversation"):
        assert tools[name].inputSchema["properties"]["preview_chars"]["default"] == 200
    assert tools["outlook_find_meeting_times"].inputSchema["properties"]["include_slots"]["default"] is False
    assert tools["outlook_get_free_busy"].inputSchema["properties"]["busy_blocks_only"]["default"] is True
