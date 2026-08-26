"""Pure parsers for the records found in the Teams cache.

Nothing here touches the disk or the clock: every function takes a decoded
IndexedDB value (a plain dict) and returns plain dicts, so the fixtures under
``tests/fixtures/teams/`` test them directly.

Shapes:

- message: ``{id, chat_id, reply_chain_id, time, sender, sender_org,
  sender_mri, is_self, text, type, account}``
- conversation: ``{id, title, type, members: [{name, mri}], last_time,
  account}`` with ``type`` one of chat, group, channel, meeting

Times are local ISO strings with offset, as the Outlook tools return them.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from typing import Any, Optional

_BLOCK_RE = re.compile(r"</?(?:p|div|br|li|ul|ol|tr|td|th|h[1-6]|blockquote|pre|table)\b[^>]*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_ORG_RE = re.compile(r"^(.*?)\s*\(([^()]*)\)\s*$")

TEXT_TYPES = {"text", "richtext/html"}


def strip_html(value: Any) -> str:
    """Plain text from a Teams message body: tags out, entities unescaped,
    whitespace collapsed to single spaces."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if not isinstance(value, str):
        value = str(value)
    text = _TAG_RE.sub("", _BLOCK_RE.sub(" ", value))
    text = html.unescape(text).replace("\xa0", " ")
    return _WS_RE.sub(" ", text).strip()


def to_local_iso(ts: Any) -> Optional[str]:
    """Teams time (ISO UTC such as ``2026-08-24T12:03:11.123Z`` or epoch
    milliseconds) as a local ISO string with offset, seconds precision.
    Returns None when the value is empty or unreadable."""
    if ts is None or ts == "":
        return None
    parsed: Optional[dt.datetime] = None
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        parsed = _from_epoch(float(ts))
    elif isinstance(ts, str):
        raw = ts.strip()
        try:
            parsed = _from_epoch(float(raw))
        except ValueError:
            try:
                parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    try:
        return parsed.astimezone().replace(microsecond=0).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _from_epoch(value: float) -> Optional[dt.datetime]:
    if value <= 0:
        return None
    seconds = value / 1000.0 if abs(value) > 1e11 else value
    try:
        return dt.datetime.fromtimestamp(seconds, tz=dt.timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def sender_name(display: Any) -> tuple[str, str]:
    """``"Jane Doe (ACME)"`` -> ``("Jane Doe", "ACME")``; without the bracket
    the org is ''."""
    text = strip_html(display)
    match = _ORG_RE.match(text)
    if not match:
        return text, ""
    return match.group(1).strip(), match.group(2).strip()


def is_self_mri(mri: Any, account: Optional[dict[str, Any]]) -> bool:
    """A member / sender mri (``8:orgid:<guid>``) belongs to the account when
    it ends with the account's user id."""
    user_id = str((account or {}).get("user_id") or "").strip().lower()
    if not user_id or not mri:
        return False
    return str(mri).strip().lower().endswith(user_id)


def is_system(message: dict[str, Any]) -> bool:
    """A parsed message is system noise when its type is outside Text /
    RichText/Html or its text is empty."""
    kind = str(message.get("type") or "").strip().lower()
    if kind not in TEXT_TYPES:
        return True
    return not (message.get("text") or "").strip()


def parse_replychain(value: Any, account: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Messages of one ``replychains`` record, oldest first. System messages
    are kept (``type`` tells) so the caller decides; see ``is_system``."""
    if not isinstance(value, dict):
        return []
    message_map = value.get("messageMap") or {}
    if not isinstance(message_map, dict):
        return []
    chat_id = str(value.get("conversationId") or "")
    chain_id = str(value.get("replyChainId") or "")
    key = (account or {}).get("key") or ""
    out: list[dict[str, Any]] = []
    for map_id, raw in message_map.items():
        if not isinstance(raw, dict):
            continue
        name, org = sender_name(raw.get("imDisplayName") or "")
        mri = str(raw.get("from") or "")
        if raw.get("isSentByCurrentUser") is not None:
            is_self = bool(raw.get("isSentByCurrentUser"))
        else:
            is_self = is_self_mri(mri, account)
        out.append(
            {
                "id": str(raw.get("id") or map_id),
                "chat_id": str(raw.get("conversationId") or chat_id),
                "reply_chain_id": chain_id,
                "time": to_local_iso(raw.get("originalArrivalTime") or raw.get("composetime")),
                "sender": name,
                "sender_org": org,
                "sender_mri": mri,
                "is_self": is_self,
                "text": strip_html(raw.get("content")),
                "type": str(raw.get("messageType") or ""),
                "account": key,
            }
        )
    out.sort(key=lambda m: (m["time"] or "", m["id"]))
    return out


def _conversation_type(value: dict[str, Any], props: dict[str, Any], members: list[dict[str, Any]]) -> str:
    kind = str(value.get("type") or "").strip().lower()
    thread_type = str(props.get("threadType") or "").strip().lower()
    chat_id = str(value.get("id") or "").lower()
    if props.get("meetingId") or props.get("meetingType") or "meeting" in kind or "meeting" in thread_type:
        return "meeting"
    if (
        kind in {"topic", "space", "channel"}
        or thread_type in {"topic", "space", "channel"}
        or chat_id.endswith("@thread.tacv2")
        or chat_id.endswith("@thread.skype")
    ):
        return "channel"
    if "group" in kind or "group" in thread_type or props.get("isGroupChat") or len(members) > 2:
        return "group"
    return "chat"


def parse_conversation(value: Any, account: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """One ``conversations`` record as a conversation dict, or None when it
    has no id. ``title`` is the topic only; ``chat_title`` gives the display
    name of chats without a topic."""
    if not isinstance(value, dict):
        return None
    chat_id = str(value.get("id") or "").strip()
    if not chat_id:
        return None
    props = value.get("threadProperties")
    if not isinstance(props, dict):
        props = {}
    members: list[dict[str, Any]] = []
    raw_members = value.get("members") or []
    if isinstance(raw_members, dict):
        raw_members = list(raw_members.values())
    if not isinstance(raw_members, list):
        raw_members = []
    for raw in raw_members:
        if isinstance(raw, str):
            members.append({"name": "", "mri": raw})
        elif isinstance(raw, dict):
            name, _org = sender_name(raw.get("displayName") or raw.get("name") or "")
            members.append({"name": name, "mri": str(raw.get("mri") or raw.get("id") or "")})
    last = value.get("lastMessage") if isinstance(value.get("lastMessage"), dict) else {}
    last_time = to_local_iso(
        value.get("lastMessageTimeUtc") or last.get("originalArrivalTime") or last.get("composetime")
    )
    return {
        "id": chat_id,
        "title": strip_html(props.get("topic") or value.get("topic") or ""),
        "type": _conversation_type(value, props, members),
        "members": members,
        "last_time": last_time,
        "account": (account or {}).get("key") or "",
    }


def chat_title(conversation: dict[str, Any], self_mri: Any = None, last_sender: Optional[str] = None) -> str:
    """Display name of a chat: its topic, else the members' names without the
    account's own entry joined with ", ", else the last sender, else the id."""
    title = (conversation.get("title") or "").strip()
    if title:
        return title
    self_suffix = str(self_mri or "").strip().lower()
    names: list[str] = []
    for member in conversation.get("members") or []:
        mri = str(member.get("mri") or "").lower()
        if self_suffix and (mri == self_suffix or mri.endswith(self_suffix)):
            continue
        name = (member.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    if names:
        return ", ".join(names)
    if last_sender:
        return last_sender
    return conversation.get("id") or ""
