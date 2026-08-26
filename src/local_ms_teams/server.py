"""FastMCP server ``local-ms-teams``: read-only tools over the Teams cache."""

from __future__ import annotations

import datetime as dt
import functools
import json
import os
from typing import Annotated, Any, Callable, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from local_ms_teams import cache
from local_ms_teams.records import chat_title, is_system

INSTRUCTIONS = """\
This server reads the new Teams client's local message cache on this machine
and answers from a copy of it. Nothing in Teams is changed, no network call is
made, and only what the client has synced (recent history) is there.

teams_status tells whether the reader extra and the cache are present and
gives the one-line fix when not. teams_list_chats lists chats with activity in
a window (newest first, optional messages per chat), teams_read_chat returns
one chat's messages oldest-first, teams_search finds messages by text or
sender. Times in and out are local ISO strings; since/until without an
offset are read as local time. The snapshot is reused for
LOCAL_MS_TEAMS_SNAPSHOT_TTL seconds (default 300); refresh=true copies the
cache again. Every tool returns JSON unless response_format='markdown'.

# The parameters the tools share

since / until: local ISO datetime bounds, both inclusive, e.g.
2026-08-24T00:00.
limit: how many chats, messages or hits to return at most; on
teams_read_chat the newest are the ones kept.
per_chat: how many messages to keep per chat when include_messages is true.
include_messages: add messages[] to every chat, oldest first, the newest
per_chat kept.
max_chars: cut message text at that many characters; the text then ends in …
and the item carries truncated=true.
account: an account key '<tenantId>:<userObjectId>' as teams_status lists
them; omit for all of them.
fields: which keys to return per item; omit for all of them.
refresh: copy and decode the cache again instead of reusing the snapshot.
response_format: 'json' (the default) or 'markdown'.

# What each tool returns

## teams_status
{reader_installed, cache_found, path, accounts: [{key, label}], chats,
messages, oldest, newest, snapshot_taken, skipped, hint}. hint holds the
one-line fix when the reader extra is missing, nobody has signed in, or the
cache holds no messages yet.

## teams_list_chats
{chats: [{id, title, type (chat, group, channel, meeting), members, count,
last_time, last_sender, preview, account}], total_messages, capped}. With
include_messages each chat also carries messages[] and truncated, the number
of older messages cut.

## teams_read_chat
{chat: {id, title, type, members, count, last_time, last_sender, preview,
account}, messages: [{id, time, sender, sender_org, is_self, text,
truncated}], truncated (the older messages cut by limit)}. chat_id is the id
as teams_list_chats returned it (19:...@thread.v2 or ...@unq.gbl.spaces).

## teams_search
query is matched case-insensitively as a substring of both the message text
and the sender name. Returns {hits: [{id, time, sender, sender_org, is_self,
text, truncated, chat_id, chat_title}], total, capped}, newest first.
"""

INSTALL_HINT = "install the `teams` extra: `uv sync --extra teams` in the checkout, then restart Claude Code"
SIGNIN_HINT = "sign in to the new Teams client once on this machine (or set LOCAL_MS_TEAMS_LEVELDB to the .leveldb folder)"

# Module-level aliases: with ``from __future__ import annotations`` every hint
# is a string resolved against module globals when FastMCP builds the schema.
Refresh = bool
Since = Optional[str]
Until = Optional[str]
ChatLimit = Annotated[int, Field(ge=1, le=500)]
MessageLimit = Annotated[int, Field(ge=1, le=2000)]
HitLimit = Annotated[int, Field(ge=1, le=500)]
IncludeMessages = bool
PerChat = Annotated[int, Field(ge=1, le=500)]
MaxChars = Annotated[int, Field(ge=20, le=20000)]
Account = Optional[str]
Fields = Optional[list[str]]
ChatId = Annotated[str, Field(min_length=1, description="Chat id from teams_list_chats.")]
Query = Annotated[str, Field(min_length=1, description="Substring of the text or the sender.")]
ResponseFormat = str


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _guard(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Turn cache errors into RuntimeError so the host marks isError."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except cache.TeamsError as exc:
            raise RuntimeError(str(exc)) from exc

    return wrapper


# --- helpers -----------------------------------------------------------------


def _bound(value: Optional[str], name: str) -> Optional[dt.datetime]:
    """since / until as an aware datetime; a naive string is local time."""
    if value is None or not str(value).strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise RuntimeError(f"{name}: not an ISO datetime: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def _when(iso: Optional[str]) -> Optional[dt.datetime]:
    if not iso:
        return None
    try:
        parsed = dt.datetime.fromisoformat(iso)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.astimezone()


def _in_window(message: dict[str, Any], lo: Optional[dt.datetime], hi: Optional[dt.datetime]) -> bool:
    if lo is None and hi is None:
        return True
    when = _when(message.get("time"))
    if when is None:
        return False
    if lo is not None and when < lo:
        return False
    if hi is not None and when > hi:
        return False
    return True


def _sort_key(message: dict[str, Any]) -> tuple[str, str]:
    return (message.get("time") or "", message.get("id") or "")


def _cut(text: str, max_chars: int) -> tuple[str, bool]:
    text = text or ""
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars].rstrip() + "…", True


def _pick(item: dict[str, Any], fields: Optional[list[str]]) -> dict[str, Any]:
    if not fields:
        return item
    return {k: item[k] for k in fields if k in item}


def _render_message(message: dict[str, Any], max_chars: int) -> dict[str, Any]:
    text, truncated = _cut(message.get("text") or "", max_chars)
    return {
        "id": message["id"],
        "time": message.get("time"),
        "sender": message.get("sender") or "",
        "sender_org": message.get("sender_org") or "",
        "is_self": bool(message.get("is_self")),
        "text": text,
        "truncated": truncated,
    }


def _live_messages(snap: cache.Snapshot, account: Optional[str], lo: Optional[dt.datetime], hi: Optional[dt.datetime]) -> list[dict[str, Any]]:
    """Non-system messages of the account inside the window, oldest first."""
    out = [
        m
        for m in snap.messages
        if not is_system(m) and (not account or m.get("account") == account) and _in_window(m, lo, hi)
    ]
    out.sort(key=_sort_key)
    return out


def _conversation_map(snap: cache.Snapshot) -> dict[str, dict[str, Any]]:
    return {c["id"]: c for c in snap.conversations}


def _user_ids(snap: cache.Snapshot) -> dict[str, str]:
    return {a["key"]: a.get("user_id") or "" for a in snap.accounts}


def _chat_entry(snap: cache.Snapshot, chat_id: str, messages: list[dict[str, Any]], max_chars: int) -> dict[str, Any]:
    """One chat as the tools return it, from its conversation record (when
    the cache has one) and its messages in the window (oldest first)."""
    conv = _conversation_map(snap).get(chat_id) or {"id": chat_id, "title": "", "type": "chat", "members": [], "last_time": None, "account": ""}
    last = messages[-1] if messages else None
    account = conv.get("account") or (last or {}).get("account") or ""
    self_id = _user_ids(snap).get(account, "")
    title = chat_title(conv, self_id, (last or {}).get("sender") or None)
    preview, _cut_flag = _cut((last or {}).get("text") or "", max_chars)
    return {
        "id": chat_id,
        "title": title,
        "type": conv.get("type") or "chat",
        "members": conv.get("members") or [],
        "count": len(messages),
        "last_time": (last or {}).get("time") or conv.get("last_time"),
        "last_sender": (last or {}).get("sender") or "",
        "preview": preview,
        "account": account,
    }


def _group_by_chat(messages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for m in messages:
        grouped.setdefault(m["chat_id"], []).append(m)
    return grouped


def _newest_first(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(entries, key=lambda e: e.get("last_time") or "", reverse=True)


# --- markdown ----------------------------------------------------------------


def _clock(iso: Optional[str]) -> str:
    when = _when(iso)
    return when.strftime("%a %d %b %H:%M") if when else "?"


def _md_message(m: dict[str, Any], indent: str = "") -> str:
    who = "me" if m.get("is_self") else (m.get("sender") or "?")
    return f"{indent}- {_clock(m.get('time'))} **{who}**: {m.get('text') or ''}"


def _markdown(data: dict[str, Any]) -> str:
    lines: list[str] = []
    if isinstance(data.get("chats"), list):
        for chat in data["chats"]:
            head = f"- **{chat.get('title') or chat.get('id')}** ({chat.get('type')}, {chat.get('count')} msgs, last {_clock(chat.get('last_time'))} by {chat.get('last_sender') or '?'})"
            if chat.get("preview"):
                head += f": {chat['preview']}"
            lines.append(head)
            for m in chat.get("messages") or []:
                lines.append(_md_message(m, "  "))
        lines.append(f"\n{len(data['chats'])} chats, {data.get('total_messages', 0)} messages" + (" (capped)" if data.get("capped") else ""))
    elif isinstance(data.get("hits"), list):
        for m in data["hits"]:
            lines.append(_md_message(m) + f"  _({m.get('chat_title') or m.get('chat_id')})_")
        lines.append(f"\n{data.get('total', 0)} hits" + (" (capped)" if data.get("capped") else ""))
    elif isinstance(data.get("chat"), dict):
        chat = data["chat"]
        lines.append(f"## {chat.get('title') or chat.get('id')} ({chat.get('type')}, {chat.get('count')} msgs)")
        for m in data.get("messages") or []:
            lines.append(_md_message(m))
        if data.get("truncated"):
            lines.append(f"\n{data['truncated']} older messages not shown")
    else:
        for key, value in data.items():
            if isinstance(value, (list, dict)):
                value = json.dumps(value, ensure_ascii=False)
            lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def _out(data: dict[str, Any], response_format: str) -> str:
    if (response_format or "json").lower() == "markdown":
        return _markdown(data)
    return _json(data)


# --- server ------------------------------------------------------------------


# Keywords whose value is a map of *names* to schemas: their keys are
# parameter names, never schema metadata, so they are recursed into but never
# filtered — a tool may well take a parameter called "title".
_SCHEMA_MAPS = ("properties", "$defs", "definitions", "patternProperties")
_SCHEMA_LISTS = ("anyOf", "oneOf", "allOf", "prefixItems")
_SCHEMA_VALUES = ("items", "additionalProperties", "not", "contains")


def _drop_titles(schema: Any) -> Any:
    """Strip pydantic's generated "title" metadata from a parameter schema.

    Pydantic titles a field by title-casing its own name ("max_chars" ->
    "Max Chars") and the argument model after the tool, so every one of them
    repeats a name the schema already carries. Validation reads the argument
    model, not this dict, so nothing about what a tool accepts changes.
    """
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "title":
            continue
        if key in _SCHEMA_MAPS and isinstance(value, dict):
            out[key] = {name: _drop_titles(sub) for name, sub in value.items()}
        elif key in _SCHEMA_LISTS and isinstance(value, list):
            out[key] = [_drop_titles(sub) for sub in value]
        elif key in _SCHEMA_VALUES and isinstance(value, dict):
            out[key] = _drop_titles(value)
        else:
            out[key] = value
    return out


def _trim_schemas(mcp: FastMCP) -> None:
    for tool in mcp._tool_manager.list_tools():
        tool.parameters = _drop_titles(tool.parameters)


def build_server() -> FastMCP:
    mcp = FastMCP("local-ms-teams", instructions=INSTRUCTIONS)
    register(mcp)
    return mcp


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name="teams_status",
        annotations={"title": "Teams cache status", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    )
    @_guard
    def teams_status(refresh: Refresh = False, response_format: ResponseFormat = "json") -> str:
        """Report whether the reader extra and the Teams cache are present, with the accounts, the chat and message counts and the snapshot's time span. Never fails; hint holds the one-line fix when something is missing."""
        installed = cache.reader_installed()
        path = cache.find_cache()
        found = bool(path and os.path.isdir(path))
        out: dict[str, Any] = {
            "reader_installed": installed,
            "cache_found": found,
            "path": path,
            "accounts": [],
            "chats": 0,
            "messages": 0,
            "oldest": None,
            "newest": None,
            "snapshot_taken": None,
            "skipped": 0,
            "hint": None,
        }
        if not installed:
            out["hint"] = INSTALL_HINT
        elif not found:
            out["hint"] = SIGNIN_HINT
        else:
            try:
                snap = cache.snapshot(refresh=refresh, path=path)
            except Exception as exc:  # the status tool reports, it does not fail
                out["hint"] = f"could not read the cache: {exc}"
                return _out(out, response_format)
            live = [m for m in snap.messages if not is_system(m)]
            times = sorted(m["time"] for m in live if m.get("time"))
            out.update(
                accounts=[{"key": a["key"], "label": a.get("label") or ""} for a in snap.accounts],
                chats=len({m["chat_id"] for m in live} | {c["id"] for c in snap.conversations}),
                messages=len(live),
                oldest=times[0] if times else None,
                newest=times[-1] if times else None,
                snapshot_taken=snap.taken_at,
                skipped=snap.skipped,
            )
            if not live:
                out["hint"] = "the cache holds no messages yet: open a few chats in Teams so the client syncs them"
        return _out(out, response_format)

    @mcp.tool(
        name="teams_list_chats",
        annotations={"title": "List chats with activity", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    )
    @_guard
    def teams_list_chats(
        since: Since = None,
        until: Until = None,
        limit: ChatLimit = 30,
        include_messages: IncludeMessages = False,
        per_chat: PerChat = 20,
        max_chars: MaxChars = 300,
        account: Account = None,
        fields: Fields = None,
        refresh: Refresh = False,
        response_format: ResponseFormat = "json",
    ) -> str:
        """List the chats with a message in the window, newest activity first, each with its title, type, members, count and a preview of the last message. Returns {chats, total_messages, capped}."""
        lo, hi = _bound(since, "since"), _bound(until, "until")
        snap = cache.snapshot(refresh=refresh)
        live = _live_messages(snap, account, lo, hi)
        entries = []
        for chat_id, messages in _group_by_chat(live).items():
            entry = _chat_entry(snap, chat_id, messages, max_chars)
            if include_messages:
                keep = messages[-per_chat:]
                entry["messages"] = [_render_message(m, max_chars) for m in keep]
                entry["truncated"] = len(messages) - len(keep)
            entries.append(entry)
        entries = _newest_first(entries)
        capped = len(entries) > limit
        chats = [_pick(e, fields) for e in entries[:limit]]
        return _out({"chats": chats, "total_messages": len(live), "capped": capped}, response_format)

    @mcp.tool(
        name="teams_read_chat",
        annotations={"title": "Read one chat", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    )
    @_guard
    def teams_read_chat(
        chat_id: ChatId,
        since: Since = None,
        until: Until = None,
        limit: MessageLimit = 100,
        max_chars: MaxChars = 600,
        fields: Fields = None,
        refresh: Refresh = False,
        response_format: ResponseFormat = "json",
    ) -> str:
        """Read one chat's messages inside the window, oldest first. Returns {chat, messages, truncated}, where truncated counts the older messages limit cut."""
        lo, hi = _bound(since, "since"), _bound(until, "until")
        snap = cache.snapshot(refresh=refresh)
        known = chat_id in _conversation_map(snap) or any(m["chat_id"] == chat_id for m in snap.messages)
        if not known:
            raise RuntimeError(f"unknown chat id: {chat_id}")
        messages = [m for m in _live_messages(snap, None, lo, hi) if m["chat_id"] == chat_id]
        keep = messages[-limit:]
        out = {
            "chat": _chat_entry(snap, chat_id, messages, max_chars),
            "messages": [_pick(_render_message(m, max_chars), fields) for m in keep],
            "truncated": len(messages) - len(keep),
        }
        return _out(out, response_format)

    @mcp.tool(
        name="teams_search",
        annotations={"title": "Search messages", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    )
    @_guard
    def teams_search(
        query: Query,
        since: Since = None,
        limit: HitLimit = 30,
        max_chars: MaxChars = 300,
        account: Account = None,
        refresh: Refresh = False,
        response_format: ResponseFormat = "json",
    ) -> str:
        """Find the messages whose text or sender name holds the query, newest first. Returns {hits, total, capped}, each hit with its chat_id and chat_title."""
        needle = query.strip().lower()
        if not needle:
            raise RuntimeError("query must not be empty")
        lo = _bound(since, "since")
        snap = cache.snapshot(refresh=refresh)
        live = _live_messages(snap, account, lo, None)
        matches = [m for m in live if needle in (m.get("text") or "").lower() or needle in (m.get("sender") or "").lower()]
        matches.sort(key=_sort_key, reverse=True)
        titles: dict[str, str] = {}
        hits = []
        for m in matches[:limit]:
            chat_id = m["chat_id"]
            if chat_id not in titles:
                titles[chat_id] = _chat_entry(snap, chat_id, [m], max_chars)["title"]
            hit = _render_message(m, max_chars)
            hit["chat_id"] = chat_id
            hit["chat_title"] = titles[chat_id]
            hits.append(hit)
        return _out({"hits": hits, "total": len(matches), "capped": len(matches) > limit}, response_format)

    _trim_schemas(mcp)
