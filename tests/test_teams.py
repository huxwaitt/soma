"""local_ms_teams: record parsers, cache finding, the stubbed snapshot and the four tools."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import pathlib

import pytest

from local_ms_teams import cache, records
from local_ms_teams.server import INSTALL_HINT, SIGNIN_HINT, build_server

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "teams"
TENANT = "11111111-1111-1111-1111-111111111111"
USER = "22222222-2222-2222-2222-222222222222"
ACCOUNT = {"key": f"{TENANT}:{USER}", "tenant_id": TENANT, "user_id": USER, "label": ""}
OTHER = {"key": "tenant-two:user-two", "tenant_id": "tenant-two", "user_id": "user-two", "label": "Globex"}
GROUP_ID = "19:aaaa0000bbbb1111cccc2222dddd3333@thread.v2"
ONE_ID = f"19:{USER}_33333333-3333-3333-3333-333333333333@unq.gbl.spaces"
MEETING_ID = "19:meeting_abcdef@thread.v2"
OTHER_ID = "19:other0000@thread.v2"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def utc(*parts):
    return dt.datetime(*parts, tzinfo=dt.timezone.utc)


def local_iso(when):
    return when.astimezone().replace(microsecond=0).isoformat()


def local_naive(when):
    return when.astimezone().replace(tzinfo=None, microsecond=0).isoformat()


def msg(mid, chat_id, when, sender, text, is_self=False, kind="Text", account=ACCOUNT["key"], org="ACME"):
    return {
        "id": mid,
        "chat_id": chat_id,
        "reply_chain_id": mid,
        "time": local_iso(when),
        "sender": sender,
        "sender_org": org,
        "sender_mri": "8:orgid:" + ("self" if is_self else "other"),
        "is_self": is_self,
        "text": text,
        "type": kind,
        "account": account,
    }


LONG = "Great, 12:30 at the canteen then. " + "x" * 400


def stub_snapshot(path):
    messages = records.parse_replychain(load("replychain.json"), ACCOUNT)
    messages += [
        msg("m10", ONE_ID, utc(2026, 8, 23, 8, 0), "Jane Doe", "Lunch?"),
        msg("m11", ONE_ID, utc(2026, 8, 23, 8, 5), "Me Myself", "Yes", is_self=True),
        msg("m12", ONE_ID, utc(2026, 8, 23, 8, 10), "Jane Doe", LONG),
        msg("m20", MEETING_ID, utc(2026, 8, 22, 15, 0), "Bob Stone", "Slides attached"),
        msg("m30", OTHER_ID, utc(2026, 8, 24, 7, 0), "Carol Ng", "Ping from the other tenant", account=OTHER["key"], org="Globex"),
    ]
    messages.sort(key=lambda m: (m["time"] or "", m["id"]))
    conversations = [
        records.parse_conversation(load("conversation_topic.json"), ACCOUNT),
        records.parse_conversation(load("conversation_1to1.json"), ACCOUNT),
        records.parse_conversation(
            {
                "id": MEETING_ID,
                "type": "Chat",
                "threadProperties": {"topic": "Supplier review", "meetingId": "abc"},
                "members": [{"mri": f"8:orgid:{USER}", "displayName": "Me Myself"}],
                "lastMessageTimeUtc": "2026-08-22T15:00:00Z",
            },
            ACCOUNT,
        ),
    ]
    return cache.Snapshot(
        accounts=[dict(ACCOUNT, label="ACME"), OTHER],
        conversations=conversations,
        messages=messages,
        taken_at="2026-08-24T18:00:00+02:00",
        path=str(path),
        skipped=1,
    )


@pytest.fixture
def teams(tmp_path, monkeypatch):
    leveldb = tmp_path / cache.LEVELDB_NAME
    leveldb.mkdir()
    snap = stub_snapshot(leveldb)
    calls = []

    def fake_take(path, now=None):
        calls.append(path)
        return snap

    monkeypatch.setattr(cache, "find_cache", lambda env=None: str(leveldb))
    monkeypatch.setattr(cache, "take_snapshot", fake_take)
    monkeypatch.setattr(cache, "reader_installed", lambda: True)
    monkeypatch.delenv(cache.ENV_TTL, raising=False)
    cache.clear()
    yield snap, calls
    cache.clear()


def call(server, name, args=None):
    out = asyncio.run(server.call_tool(name, args or {}))
    text = out[0].text if isinstance(out, list) else out[0][0].text
    return json.loads(text)


# --- records -----------------------------------------------------------------


def test_strip_html():
    assert records.strip_html("<p>Hi <b>there</b>&nbsp;&amp; you</p>\n<p>line</p>") == "Hi there & you line"
    assert records.strip_html(None) == ""
    assert records.strip_html("&lt;b&gt;kept&lt;/b&gt;") == "<b>kept</b>"


def test_to_local_iso_forms():
    want = utc(2026, 8, 24, 12, 3, 11)
    iso = records.to_local_iso("2026-08-24T12:03:11.123Z")
    assert iso == local_iso(want)
    assert dt.datetime.fromisoformat(iso) == want
    assert dt.datetime.fromisoformat(iso).utcoffset() is not None
    assert records.to_local_iso(1787573200000) == local_iso(utc(2026, 8, 24, 12, 6, 40))
    assert records.to_local_iso("1787573200000.0") == local_iso(utc(2026, 8, 24, 12, 6, 40))
    assert records.to_local_iso("2026-08-24T12:03:11") == local_iso(want)
    assert records.to_local_iso("2026-08-24T14:03:11+02:00") == local_iso(want)
    assert records.to_local_iso(None) is None
    assert records.to_local_iso("") is None
    assert records.to_local_iso("garbage") is None


def test_sender_name():
    assert records.sender_name("Jane Doe (ACME)") == ("Jane Doe", "ACME")
    assert records.sender_name("Jane Doe") == ("Jane Doe", "")
    assert records.sender_name("") == ("", "")


def test_is_system():
    assert records.is_system({"type": "ThreadActivity/AddMember", "text": "x"}) is True
    assert records.is_system({"type": "Text", "text": ""}) is True
    assert records.is_system({"type": "RichText/Html", "text": "hi"}) is False
    assert records.is_system({"type": "text", "text": "hi"}) is False


def test_parse_replychain_fixture():
    out = records.parse_replychain(load("replychain.json"), ACCOUNT)
    assert [m["id"] for m in out] == ["1787572991123", "1787573100000", "1787573200000"]
    first, second, third = out
    assert set(first) == {"id", "chat_id", "reply_chain_id", "time", "sender", "sender_org", "sender_mri", "is_self", "text", "type", "account"}
    assert first["chat_id"] == GROUP_ID
    assert first["reply_chain_id"] == "1787572991123"
    assert first["text"] == "Hi, can you send the Q3 budget? Thanks & regards"
    assert first["sender"] == "Jane Doe" and first["sender_org"] == "ACME"
    assert first["time"] == local_iso(utc(2026, 8, 24, 12, 3, 11))
    assert first["is_self"] is False
    assert second["is_self"] is True and second["text"] == "Sure, on its way."
    assert second["time"] == local_iso(utc(2026, 8, 24, 12, 5))
    assert third["type"] == "ThreadActivity/AddMember" and records.is_system(third)
    assert third["time"] == local_iso(utc(2026, 8, 24, 12, 6, 40))
    assert all(m["account"] == ACCOUNT["key"] for m in out)


def test_parse_replychain_self_by_mri():
    raw = load("replychain.json")
    del raw["messageMap"]["1787573100000"]["isSentByCurrentUser"]
    out = records.parse_replychain(raw, ACCOUNT)
    assert out[1]["is_self"] is True
    assert out[0]["is_self"] is False
    assert records.parse_replychain(raw, None)[1]["is_self"] is False
    assert records.parse_replychain({"messageMap": "no"}, ACCOUNT) == []
    assert records.parse_replychain(None, ACCOUNT) == []


def test_parse_conversation_topic():
    conv = records.parse_conversation(load("conversation_topic.json"), ACCOUNT)
    assert set(conv) == {"id", "title", "type", "members", "last_time", "account"}
    assert conv["id"] == GROUP_ID
    assert conv["title"] == "Q3 budget crew"
    assert conv["type"] == "group"
    assert [m["name"] for m in conv["members"]] == ["Me Myself", "Jane Doe", "Bob Stone"]
    assert conv["last_time"] == local_iso(utc(2026, 8, 24, 12, 5))
    assert conv["account"] == ACCOUNT["key"]
    assert records.chat_title(conv, USER) == "Q3 budget crew"


def test_parse_conversation_one_to_one():
    conv = records.parse_conversation(load("conversation_1to1.json"), ACCOUNT)
    assert conv["title"] == ""
    assert conv["type"] == "chat"
    assert conv["last_time"] == local_iso(utc(2026, 8, 23, 7, 30))
    assert records.chat_title(conv, USER) == "Jane Doe"
    assert records.chat_title(conv, None) == "Me Myself, Jane Doe"
    assert records.chat_title({"id": "x", "title": "", "members": []}, USER, "Bob Stone") == "Bob Stone"
    assert records.chat_title({"id": "x", "title": "", "members": []}, USER) == "x"
    assert records.parse_conversation({}, ACCOUNT) is None
    assert records.parse_conversation("no", ACCOUNT) is None


def test_conversation_types():
    meeting = records.parse_conversation({"id": "19:m@thread.v2", "type": "Chat", "threadProperties": {"meetingId": "1"}}, ACCOUNT)
    assert meeting["type"] == "meeting"
    channel = records.parse_conversation({"id": "19:c@thread.tacv2", "type": "Topic", "threadProperties": {"topic": "General"}}, ACCOUNT)
    assert channel["type"] == "channel"
    group = records.parse_conversation({"id": "19:g@thread.v2", "type": "Chat", "threadProperties": {"threadType": "groupchat"}}, ACCOUNT)
    assert group["type"] == "group"
    plain = records.parse_conversation({"id": "19:p@unq.gbl.spaces", "type": "Chat", "members": ["8:orgid:a", "8:orgid:b"]}, ACCOUNT)
    assert plain["type"] == "chat" and plain["members"][0] == {"name": "", "mri": "8:orgid:a"}


# --- cache -------------------------------------------------------------------


def test_find_cache_env_and_glob(tmp_path):
    env = {"LOCALAPPDATA": str(tmp_path), "HOME": str(tmp_path)}
    assert cache.find_cache(env) is None
    leveldb = tmp_path / "Packages" / "MSTeams_8wekyb3d8bbwe" / "LocalCache" / "Microsoft" / "MSTeams" / "EBWebView" / "Default" / "IndexedDB" / cache.LEVELDB_NAME
    leveldb.mkdir(parents=True)
    assert os.path.normpath(cache.find_cache(env)) == os.path.normpath(str(leveldb))
    override = tmp_path / "elsewhere.leveldb"
    assert cache.find_cache(dict(env, LOCAL_MS_TEAMS_LEVELDB=str(override))) == str(override)


class _Meta:
    def __init__(self, name, dbid_no):
        self.name = name
        self.dbid_no = dbid_no


class _Record:
    def __init__(self, value):
        self.value = value


class _Store:
    def __init__(self, values, bad=0):
        self.values = values
        self.bad = bad

    def iterate_records(self, bad_deserializer_data_handler=None):
        for _ in range(self.bad):
            if bad_deserializer_data_handler:
                bad_deserializer_data_handler(b"key", b"raw")
            yield _Record(None)
        for value in self.values:
            yield _Record(value)


class _Db:
    def __init__(self, stores):
        self.stores = stores

    def get_object_store_by_name(self, name):
        if name not in self.stores:
            raise KeyError(name)
        return self.stores[name]


class _Wrapped:
    """Stands in for ccl_chromium_reader's WrappedIndexDB."""

    def __init__(self, leveldb_dir, blob_dir=None):
        self.leveldb_dir = leveldb_dir
        self.blob_dir = blob_dir
        tail = f"react-web-client:{TENANT}:{USER}:en-us"
        self.database_ids = [
            _Meta(f"Teams:replychain-manager:{tail}", 1),
            _Meta(f"Teams:conversation-manager:{tail}", 2),
            _Meta(f"Teams:other-manager:{tail}", 3),
            _Meta("unrelated", 4),
            _Meta(None, 5),
        ]
        self._dbs = {
            1: _Db({"replychains": _Store([load("replychain.json"), "not a dict"], bad=1)}),
            2: _Db({"conversations": _Store([load("conversation_topic.json"), load("conversation_1to1.json"), {"no": "id"}])}),
            3: _Db({}),
            4: _Db({}),
            5: _Db({}),
        }

    def __getitem__(self, dbid_no):
        return self._dbs[dbid_no]


def test_take_snapshot_with_stub(tmp_path, monkeypatch):
    src = tmp_path / "IndexedDB" / cache.LEVELDB_NAME
    src.mkdir(parents=True)
    (src / "CURRENT").write_text("MANIFEST-000001\n")
    blob = tmp_path / "IndexedDB" / cache.BLOB_NAME
    blob.mkdir()
    (blob / "1").mkdir()
    opened = []

    def fake_open(leveldb_dir, blob_dir=None):
        assert pathlib.Path(leveldb_dir, "CURRENT").is_file()
        assert pathlib.Path(blob_dir, "1").is_dir()
        db = _Wrapped(leveldb_dir, blob_dir)
        opened.append(db)
        return db

    monkeypatch.setattr(cache, "_open_indexeddb", fake_open)
    snap = cache.take_snapshot(str(src), now="2026-08-24T18:00:00+02:00")
    db = opened[0]
    assert os.path.normpath(db.leveldb_dir) != os.path.normpath(str(src))
    assert os.path.basename(db.leveldb_dir) == cache.LEVELDB_NAME
    assert os.path.basename(db.blob_dir) == cache.BLOB_NAME
    assert not os.path.exists(os.path.dirname(db.leveldb_dir)), "the temp copy is deleted"
    assert (src / "CURRENT").is_file(), "the source is untouched"
    assert snap.path == str(src) and snap.taken_at == "2026-08-24T18:00:00+02:00"
    assert snap.skipped == 1
    assert snap.accounts == [{"key": ACCOUNT["key"], "tenant_id": TENANT, "user_id": USER, "label": "ACME"}]
    assert [m["id"] for m in snap.messages] == ["1787572991123", "1787573100000", "1787573200000"]
    assert sorted(c["id"] for c in snap.conversations) == sorted([GROUP_ID, ONE_ID])


def test_take_snapshot_missing_folder(tmp_path):
    with pytest.raises(cache.TeamsError):
        cache.take_snapshot(str(tmp_path / "nope"))


def test_open_indexeddb_without_reader(monkeypatch):
    monkeypatch.setattr(cache, "reader_installed", lambda: False)
    if cache.reader_installed():
        pytest.skip("reader installed")
    try:
        import ccl_chromium_reader  # noqa: F401
    except ImportError:
        with pytest.raises(cache.TeamsError, match="uv sync --extra teams"):
            cache._open_indexeddb("x", None)


def test_snapshot_ttl_and_refresh(teams, monkeypatch):
    snap, calls = teams
    server = build_server()
    call(server, "teams_status")
    call(server, "teams_list_chats")
    assert len(calls) == 1
    call(server, "teams_status", {"refresh": True})
    assert len(calls) == 2
    monkeypatch.setenv(cache.ENV_TTL, "0")
    call(server, "teams_search", {"query": "lunch"})
    call(server, "teams_search", {"query": "lunch"})
    assert len(calls) == 4


def test_snapshot_without_cache(monkeypatch):
    monkeypatch.setattr(cache, "find_cache", lambda env=None: None)
    cache.clear()
    with pytest.raises(cache.TeamsError):
        cache.snapshot()
    server = build_server()
    with pytest.raises(Exception):
        asyncio.run(server.call_tool("teams_list_chats", {}))


# --- tools -------------------------------------------------------------------


def test_server_tools():
    server = build_server()
    assert server.name == "local-ms-teams"
    tools = asyncio.run(server.list_tools())
    assert {t.name for t in tools} == {"teams_status", "teams_list_chats", "teams_read_chat", "teams_search"}
    assert all(t.annotations.readOnlyHint for t in tools)


def test_status(teams):
    snap, _calls = teams
    out = call(build_server(), "teams_status")
    assert out["reader_installed"] is True and out["cache_found"] is True
    assert out["path"] == snap.path
    assert out["accounts"] == [{"key": ACCOUNT["key"], "label": "ACME"}, {"key": OTHER["key"], "label": "Globex"}]
    assert out["chats"] == 4
    assert out["messages"] == 7
    assert out["oldest"] == local_iso(utc(2026, 8, 22, 15, 0))
    assert out["newest"] == local_iso(utc(2026, 8, 24, 12, 5))
    assert out["snapshot_taken"] == "2026-08-24T18:00:00+02:00"
    assert out["skipped"] == 1
    assert out["hint"] is None


def test_status_without_reader_or_cache(monkeypatch):
    cache.clear()
    monkeypatch.setattr(cache, "reader_installed", lambda: False)
    monkeypatch.setattr(cache, "find_cache", lambda env=None: None)
    out = call(build_server(), "teams_status")
    assert out["reader_installed"] is False and out["cache_found"] is False
    assert out["path"] is None and out["accounts"] == [] and out["messages"] == 0
    assert out["hint"] == INSTALL_HINT
    monkeypatch.setattr(cache, "reader_installed", lambda: True)
    out = call(build_server(), "teams_status")
    assert out["hint"] == SIGNIN_HINT
    monkeypatch.setattr(cache, "find_cache", lambda env=None: "C:/Users/someone/missing.leveldb")
    out = call(build_server(), "teams_status")
    assert out["cache_found"] is False and out["path"].endswith("missing.leveldb")
    assert out["hint"] == SIGNIN_HINT


def test_status_reports_read_error(teams, monkeypatch):
    def boom(path, now=None):
        raise cache.TeamsError("bad leveldb")

    monkeypatch.setattr(cache, "take_snapshot", boom)
    out = call(build_server(), "teams_status")
    assert out["cache_found"] is True and "bad leveldb" in out["hint"]


def test_list_chats_order_and_window(teams):
    server = build_server()
    out = call(server, "teams_list_chats")
    assert [c["id"] for c in out["chats"]] == [GROUP_ID, OTHER_ID, ONE_ID, MEETING_ID]
    assert out["total_messages"] == 7 and out["capped"] is False
    group = out["chats"][0]
    assert set(group) == {"id", "title", "type", "members", "count", "last_time", "last_sender", "preview", "account"}
    assert group["title"] == "Q3 budget crew" and group["type"] == "group" and group["count"] == 2
    assert group["last_sender"] == "Me Myself" and group["preview"] == "Sure, on its way."
    assert group["last_time"] == local_iso(utc(2026, 8, 24, 12, 5))
    other = out["chats"][1]
    assert other["title"] == "Carol Ng" and other["type"] == "chat" and other["members"] == [] and other["account"] == OTHER["key"]
    one = out["chats"][2]
    assert one["title"] == "Jane Doe" and len(one["members"]) == 2
    assert out["chats"][3]["type"] == "meeting" and out["chats"][3]["title"] == "Supplier review"

    since = local_naive(utc(2026, 8, 24, 0, 0))
    out = call(server, "teams_list_chats", {"since": since})
    assert [c["id"] for c in out["chats"]] == [GROUP_ID, OTHER_ID] and out["total_messages"] == 3
    out = call(server, "teams_list_chats", {"since": since, "account": ACCOUNT["key"]})
    assert [c["id"] for c in out["chats"]] == [GROUP_ID]
    out = call(server, "teams_list_chats", {"until": local_naive(utc(2026, 8, 23, 23, 59))})
    assert [c["id"] for c in out["chats"]] == [ONE_ID, MEETING_ID]
    out = call(server, "teams_list_chats", {"since": local_naive(utc(2026, 8, 23, 8, 5)), "until": local_naive(utc(2026, 8, 23, 8, 5))})
    assert out["total_messages"] == 1, "bounds are inclusive"
    out = call(server, "teams_list_chats", {"limit": 1})
    assert len(out["chats"]) == 1 and out["capped"] is True
    with pytest.raises(Exception):
        call(server, "teams_list_chats", {"since": "yesterday"})


def test_list_chats_include_messages(teams):
    server = build_server()
    out = call(server, "teams_list_chats", {"include_messages": True, "per_chat": 2, "max_chars": 50})
    one = next(c for c in out["chats"] if c["id"] == ONE_ID)
    assert [m["id"] for m in one["messages"]] == ["m11", "m12"]
    assert one["truncated"] == 1
    assert set(one["messages"][0]) == {"id", "time", "sender", "sender_org", "is_self", "text", "truncated"}
    assert one["messages"][0]["is_self"] is True and one["messages"][0]["truncated"] is False
    long = one["messages"][1]
    assert long["truncated"] is True and long["text"].endswith("…") and len(long["text"]) <= 51
    assert one["preview"].endswith("…")
    group = next(c for c in out["chats"] if c["id"] == GROUP_ID)
    assert group["truncated"] == 0 and len(group["messages"]) == 2, "system messages are left out"


def test_list_chats_fields(teams):
    out = call(build_server(), "teams_list_chats", {"fields": ["id", "title", "nope"]})
    assert all(set(c) == {"id", "title"} for c in out["chats"])


def test_read_chat(teams):
    server = build_server()
    out = call(server, "teams_read_chat", {"chat_id": ONE_ID})
    assert out["chat"]["title"] == "Jane Doe" and out["chat"]["count"] == 3
    assert [m["id"] for m in out["messages"]] == ["m10", "m11", "m12"]
    assert out["truncated"] == 0
    assert out["messages"][2]["truncated"] is False, "max_chars 600 keeps the long text"
    out = call(server, "teams_read_chat", {"chat_id": ONE_ID, "limit": 2, "max_chars": 40})
    assert [m["id"] for m in out["messages"]] == ["m11", "m12"] and out["truncated"] == 1
    assert out["messages"][1]["truncated"] is True
    out = call(server, "teams_read_chat", {"chat_id": ONE_ID, "since": local_naive(utc(2026, 8, 23, 8, 5)), "fields": ["id", "text"]})
    assert out["messages"] == [{"id": "m11", "text": "Yes"}, {"id": "m12", "text": LONG}]
    out = call(server, "teams_read_chat", {"chat_id": GROUP_ID})
    assert out["chat"]["title"] == "Q3 budget crew" and [m["id"] for m in out["messages"]] == ["1787572991123", "1787573100000"]
    out = call(server, "teams_read_chat", {"chat_id": OTHER_ID})
    assert out["chat"]["title"] == "Carol Ng" and out["chat"]["account"] == OTHER["key"]
    with pytest.raises(Exception):
        call(server, "teams_read_chat", {"chat_id": "19:unknown@thread.v2"})


def test_search(teams):
    server = build_server()
    out = call(server, "teams_search", {"query": "BUDGET"})
    assert out["total"] == 1 and out["capped"] is False
    hit = out["hits"][0]
    assert hit["chat_id"] == GROUP_ID and hit["chat_title"] == "Q3 budget crew" and hit["sender"] == "Jane Doe"
    assert set(hit) == {"id", "time", "sender", "sender_org", "is_self", "text", "truncated", "chat_id", "chat_title"}
    out = call(server, "teams_search", {"query": "jane"})
    assert [h["id"] for h in out["hits"]] == ["1787572991123", "m12", "m10"], "newest first"
    out = call(server, "teams_search", {"query": "jane", "limit": 1})
    assert len(out["hits"]) == 1 and out["total"] == 3 and out["capped"] is True
    out = call(server, "teams_search", {"query": "jane", "since": local_naive(utc(2026, 8, 24, 0, 0))})
    assert [h["id"] for h in out["hits"]] == ["1787572991123"]
    out = call(server, "teams_search", {"query": "ping", "account": ACCOUNT["key"]})
    assert out["total"] == 0
    out = call(server, "teams_search", {"query": "ping"})
    assert out["hits"][0]["chat_title"] == "Carol Ng"
    out = call(server, "teams_search", {"query": "addmember"})
    assert out["total"] == 0, "system messages are not searched"
    with pytest.raises(Exception):
        call(server, "teams_search", {"query": "   "})


def test_markdown_format(teams):
    server = build_server()
    out = asyncio.run(server.call_tool("teams_list_chats", {"response_format": "markdown", "include_messages": True}))
    text = out[0].text if isinstance(out, list) else out[0][0].text
    assert "**Q3 budget crew**" in text and "Sure, on its way." in text
    out = asyncio.run(server.call_tool("teams_status", {"response_format": "markdown"}))
    text = out[0].text if isinstance(out, list) else out[0][0].text
    assert "- cache_found: True" in text
