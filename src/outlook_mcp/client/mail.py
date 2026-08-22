"""Mail COM operations."""

from __future__ import annotations

import csv
import datetime as dt
import json
import ntpath
import os
import re
from typing import Any, Callable, Iterator

from outlook_mcp.client.folders import _safe_get, get_item_by_id, resolve_folder
from outlook_mcp.constants import (
    IMPORTANCE_MAP,
    OL_CLASS_MAIL,
    OL_CLASS_MEETING_REQUEST,
    OL_FORMAT_HTML,
    OL_FORMAT_PLAIN,
    OL_IMPORTANCE_NORMAL,
    OL_MAIL_ITEM,
    SAVE_AS_MAP,
)
from outlook_mcp.errors import OutlookError, is_disconnect_error
from outlook_mcp.utils.formatting import from_iso, to_iso, truncate
from outlook_mcp.utils.paths import (
    validate_attachment_path,
    validate_output_dir,
    validate_output_file,
)
from outlook_mcp.utils.safety import safe_dasl

WINDOWS_RESERVED_DEVICE_NAMES = {"CON", "PRN", "AUX", "NUL", "CLOCK$"} | {
    f"COM{i}" for i in range(1, 10)
} | {f"LPT{i}" for i in range(1, 10)}

# PR_SENT_REPRESENTING_SMTP_ADDRESS — unlike urn:schemas:httpmail:fromemail,
# this holds the real SMTP address even for Exchange senders (whose
# fromemail is an EX:/O=... distinguished name).
SMTP_PROPTAG = "http://schemas.microsoft.com/mapi/proptag/0x5D02001F"
# PR_SENDER_SMTP_ADDRESS — the actual sender (differs from the above for
# "send on behalf of" mail).
SENDER_SMTP_PROPTAG = "http://schemas.microsoft.com/mapi/proptag/0x5D01001F"
# PR_SMTP_ADDRESS on a Recipient object.
RECIPIENT_SMTP_PROPTAG = "http://schemas.microsoft.com/mapi/proptag/0x39FE001F"
# PR_INTERNET_MESSAGE_ID — the RFC 5322 Message-ID header. Stable across
# stores/mailboxes, unlike EntryID, so it is the right key for correlating
# a mail with external systems (ticketing, other mailboxes, mbox exports).
INTERNET_MESSAGE_ID_PROPTAG = "http://schemas.microsoft.com/mapi/proptag/0x1035001F"

# DASL property names used to build server-side Restrict filters.
DASL_SUBJECT = "urn:schemas:httpmail:subject"
DASL_BODY = "urn:schemas:httpmail:textdescription"
DASL_FROM_EMAIL = "urn:schemas:httpmail:fromemail"
DASL_FROM_NAME = "urn:schemas:httpmail:fromname"
DASL_RECEIVED = "urn:schemas:httpmail:datereceived"
DASL_READ = "urn:schemas:httpmail:read"
DASL_HAS_ATTACH = "urn:schemas:httpmail:hasattachment"

EXPORT_COLUMNS = (
    "entry_id",
    "subject",
    "from",
    "from_address",
    "to",
    "cc",
    "received",
    "sent",
    "unread",
    "flagged",
    "has_attachments",
    "importance",
    "categories",
    "conversation_id",
    "internet_message_id",
)


def internet_message_id(item: Any) -> str:
    """Return the RFC 5322 Message-ID header, or ``""`` when absent.

    Drafts and some locally created items have no Message-ID yet, and
    ``PropertyAccessor.GetProperty`` raises for a missing property, so
    every failure collapses to an empty string.
    """
    accessor = _safe_get(item, "PropertyAccessor")
    if accessor is None:
        return ""
    try:
        value = accessor.GetProperty(INTERNET_MESSAGE_ID_PROPTAG)
    except Exception:
        return ""
    return value if isinstance(value, str) else ""


def _looks_smtp(value: Any) -> bool:
    return isinstance(value, str) and "@" in value and not value.upper().startswith("/O=")


def sender_smtp(item: Any) -> str:
    """Return the sender's SMTP address, resolving Exchange ``EX`` addresses.

    ``SenderEmailAddress`` is fine for internet mail but for Exchange
    senders it is a legacy DN (``/O=EXCHANGELABS/OU=.../CN=...``). Try,
    in order: the raw value if it is already SMTP; the MAPI SMTP
    proptags via ``PropertyAccessor``; ``Sender.GetExchangeUser()``;
    and finally fall back to whatever Outlook gave us.
    """
    raw = _safe_get(item, "SenderEmailAddress", "") or ""
    if _safe_get(item, "SenderEmailType", "") != "EX" and _looks_smtp(raw):
        return raw

    accessor = _safe_get(item, "PropertyAccessor")
    if accessor is not None:
        for tag in (SMTP_PROPTAG, SENDER_SMTP_PROPTAG):
            try:
                value = accessor.GetProperty(tag)
            except Exception:
                continue
            if _looks_smtp(value):
                return value

    try:
        sender = item.Sender
        if sender is not None:
            exchange_user = sender.GetExchangeUser()
            if exchange_user is not None:
                primary = exchange_user.PrimarySmtpAddress
                if _looks_smtp(primary):
                    return primary
    except Exception:
        pass
    return raw


def recipient_smtp(recipient: Any) -> str:
    """Return a Recipient's SMTP address, resolving Exchange DNs."""
    raw = _safe_get(recipient, "Address", "") or ""
    if _looks_smtp(raw):
        return raw
    accessor = _safe_get(recipient, "PropertyAccessor")
    if accessor is not None:
        try:
            value = accessor.GetProperty(RECIPIENT_SMTP_PROPTAG)
            if _looks_smtp(value):
                return value
        except Exception:
            pass
    try:
        entry = recipient.AddressEntry
        exchange_user = entry.GetExchangeUser() if entry is not None else None
        if exchange_user is not None and _looks_smtp(exchange_user.PrimarySmtpAddress):
            return exchange_user.PrimarySmtpAddress
    except Exception:
        pass
    return raw


def _recipients(item: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    recipients = _safe_get(item, "Recipients")
    if not recipients:
        return out
    try:
        for r in recipients:
            out.append(
                {
                    "name": _safe_get(r, "Name", ""),
                    "address": recipient_smtp(r),
                    "type": {1: "to", 2: "cc", 3: "bcc"}.get(_safe_get(r, "Type"), "to"),
                }
            )
    except Exception:
        pass
    return out


def _dasl_date(value: dt.datetime) -> str:
    # Both Jet and DASL date literals must be 12-hour + AM/PM; %H with %p
    # would emit e.g. "14:30 PM", which Outlook misparses.
    return value.strftime("%m/%d/%Y %I:%M %p")


def build_mail_filter(
    *,
    unread_only: bool = False,
    since: str | None = None,
    until: str | None = None,
    from_address: str | None = None,
    has_attachments: bool | None = None,
    extra: list[str] | None = None,
) -> str | None:
    """Build a DASL ``@SQL=`` Restrict filter from the common mail filters.

    Every clause is pushed into Outlook's own index so the COM loop only
    ever touches matching items; enumerating a 20k-item Inbox in Python
    to find five unread mails from one sender is what made the original
    ``list_mails`` slow. Returns ``None`` when no clause applies.
    """
    clauses: list[str] = list(extra or [])
    if unread_only:
        clauses.append(f'"{DASL_READ}" = 0')
    if has_attachments is not None:
        clauses.append(f'"{DASL_HAS_ATTACH}" = {1 if has_attachments else 0}')
    since_dt = from_iso(since)
    until_dt = from_iso(until)
    if since_dt:
        clauses.append(f"\"{DASL_RECEIVED}\" >= '{_dasl_date(since_dt)}'")
    if until_dt:
        clauses.append(f"\"{DASL_RECEIVED}\" <= '{_dasl_date(until_dt)}'")
    if from_address:
        esc = safe_dasl(from_address)
        clauses.append(
            f"(\"{DASL_FROM_EMAIL}\" LIKE '%{esc}%' OR "
            f"\"{SMTP_PROPTAG}\" LIKE '%{esc}%' OR "
            f"\"{SENDER_SMTP_PROPTAG}\" LIKE '%{esc}%')"
        )
    if not clauses:
        return None
    return "@SQL=" + " AND ".join(clauses)


def _iter_mail_items(folder_obj: Any, dasl: str | None) -> Iterator[Any]:
    """Yield mail/meeting-request items newest-first, applying ``dasl``."""
    items = folder_obj.Items
    items.Sort("[ReceivedTime]", True)
    if dasl:
        items = items.Restrict(dasl)
    for item in items:
        cls = _safe_get(item, "Class")
        if cls in (OL_CLASS_MAIL, OL_CLASS_MEETING_REQUEST):
            yield item


def split_search_words(query: str) -> tuple[str, list[str]]:
    """Split a search query into (anchor, remaining_words), lowercased.

    The anchor is the longest word — the most selective term to push
    down into the DASL Restrict. The remaining words are verified in
    Python per item, because DASL can't reliably AND two LIKEs on the
    same property (verified live: it returns zero rows).
    """
    words = [w.lower() for w in query.split() if w]
    if not words:
        return query.lower(), []
    anchor = max(words, key=len)
    remaining = list(words)
    remaining.remove(anchor)
    return anchor, remaining


def search_clause(anchor: str, scope: str) -> str:
    """DASL clause (without ``@SQL=``) matching ``anchor`` in ``scope``."""
    esc = safe_dasl(anchor)
    if scope == "subject":
        return f"\"{DASL_SUBJECT}\" LIKE '%{esc}%'"
    if scope == "from":
        return (
            f"(\"{DASL_FROM_EMAIL}\" LIKE '%{esc}%' OR "
            f"\"{DASL_FROM_NAME}\" LIKE '%{esc}%' OR "
            f"\"{SMTP_PROPTAG}\" LIKE '%{esc}%' OR "
            f"\"{SENDER_SMTP_PROPTAG}\" LIKE '%{esc}%')"
        )
    # subject_body (default)
    return f"(\"{DASL_SUBJECT}\" LIKE '%{esc}%' OR \"{DASL_BODY}\" LIKE '%{esc}%')"


def _search_haystack(item: Any, scope: str) -> str:
    if scope == "subject":
        fields = ("Subject",)
    elif scope == "from":
        fields = ("SenderName", "SenderEmailAddress")
    else:  # subject_body
        fields = ("Subject", "Body")
    return " ".join(str(_safe_get(item, f, "") or "") for f in fields).lower()


def _mail_summary(item: Any) -> dict[str, Any]:
    attachments = _safe_get(item, "Attachments")
    return {
        "entry_id": _safe_get(item, "EntryID"),
        "subject": _safe_get(item, "Subject", ""),
        "from": _safe_get(item, "SenderName"),
        "from_address": sender_smtp(item),
        "to": _safe_get(item, "To", ""),
        "received": to_iso(_safe_get(item, "ReceivedTime")),
        "unread": bool(_safe_get(item, "UnRead", False)),
        "flagged": _safe_get(item, "FlagStatus") == 2,  # olFlagMarked
        "has_attachments": attachments.Count > 0 if attachments else False,
        "importance": _safe_get(item, "Importance"),
        "internet_message_id": internet_message_id(item),
        "preview": truncate(_safe_get(item, "Body", ""), 200),
    }


def _mail_row(item: Any) -> dict[str, Any]:
    """Flat, export-friendly row (no preview/body, adds cc/sent/categories)."""
    attachments = _safe_get(item, "Attachments")
    return {
        "entry_id": _safe_get(item, "EntryID"),
        "subject": _safe_get(item, "Subject", ""),
        "from": _safe_get(item, "SenderName"),
        "from_address": sender_smtp(item),
        "to": _safe_get(item, "To", ""),
        "cc": _safe_get(item, "CC", ""),
        "received": to_iso(_safe_get(item, "ReceivedTime")),
        "sent": to_iso(_safe_get(item, "SentOn")),
        "unread": bool(_safe_get(item, "UnRead", False)),
        "flagged": _safe_get(item, "FlagStatus") == 2,
        "has_attachments": attachments.Count > 0 if attachments else False,
        "importance": _safe_get(item, "Importance"),
        "categories": _safe_get(item, "Categories", ""),
        "conversation_id": _safe_get(item, "ConversationID"),
        "internet_message_id": internet_message_id(item),
    }


def _mail_full(
    item: Any,
    include_body: bool = True,
    include_html: bool = False,
    max_body_chars: int = 10000,
) -> dict[str, Any]:
    attachments = []
    if _safe_get(item, "Attachments"):
        for i, att in enumerate(item.Attachments, start=1):
            attachments.append(
                {
                    "index": i,
                    "filename": att.FileName,
                    "size_bytes": _safe_get(att, "Size"),
                }
            )
    result = {
        "entry_id": _safe_get(item, "EntryID"),
        "conversation_id": _safe_get(item, "ConversationID"),
        "internet_message_id": internet_message_id(item),
        "subject": _safe_get(item, "Subject", ""),
        "from": _safe_get(item, "SenderName"),
        "from_address": sender_smtp(item),
        "to": _safe_get(item, "To", ""),
        "cc": _safe_get(item, "CC", ""),
        "bcc": _safe_get(item, "BCC", ""),
        "recipients": _recipients(item),
        "received": to_iso(_safe_get(item, "ReceivedTime")),
        "sent": to_iso(_safe_get(item, "SentOn")),
        "unread": bool(_safe_get(item, "UnRead", False)),
        "flagged": _safe_get(item, "FlagStatus") == 2,  # olFlagMarked
        "importance": _safe_get(item, "Importance"),
        "categories": _safe_get(item, "Categories", ""),
        "attachments": attachments,
    }
    if include_body:
        body = _safe_get(item, "Body", "") or ""
        if max_body_chars and len(body) > max_body_chars:
            result["body"] = body[:max_body_chars].rstrip()
            result["body_truncated"] = True
            result["body_total_chars"] = len(body)
        else:
            result["body"] = body
    if include_html:
        # Full HTML of a styled corporate mail easily runs to tens of
        # kilobytes — only fetch when explicitly asked for.
        result["html_body"] = _safe_get(item, "HTMLBody", "")
    return result


def list_mails(
    outlook: Any,
    namespace: Any,
    *,
    folder: str | None = "inbox",
    limit: int = 25,
    offset: int = 0,
    unread_only: bool = False,
    since: str | None = None,
    until: str | None = None,
    from_address: str | None = None,
    has_attachments: bool | None = None,
) -> dict[str, Any]:
    f = resolve_folder(namespace, folder)
    dasl = build_mail_filter(
        unread_only=unread_only,
        since=since,
        until=until,
        from_address=from_address,
        has_attachments=has_attachments,
    )

    results: list[dict[str, Any]] = []
    skipped = 0
    for item in _iter_mail_items(f, dasl):
        if skipped < offset:
            skipped += 1
            continue
        results.append(_mail_summary(item))
        if len(results) >= limit:
            break

    return {
        "folder": f.Name,
        "count": len(results),
        "offset": offset,
        "limit": limit,
        "items": results,
        "has_more": len(results) == limit,
        "next_offset": offset + len(results) if len(results) == limit else None,
    }


def search_mails(
    outlook: Any,
    namespace: Any,
    *,
    query: str,
    folder: str | None = "inbox",
    limit: int = 25,
    scope: str = "subject_body",
    since: str | None = None,
    until: str | None = None,
    unread_only: bool = False,
    has_attachments: bool | None = None,
) -> dict[str, Any]:
    f = resolve_folder(namespace, folder)

    # Multi-word queries: Restrict on the most selective word, then
    # require the remaining words per item in Python (see
    # split_search_words for why DASL can't do the AND itself).
    remaining: list[str] = []
    if scope == "dasl":
        # Caller is explicitly passing a raw DASL filter; don't mangle it,
        # and don't try to AND our own clauses onto it.
        dasl = query if query.lstrip().upper().startswith("@SQL=") else f"@SQL={query}"
    else:
        anchor, remaining = split_search_words(query)
        dasl = build_mail_filter(
            unread_only=unread_only,
            since=since,
            until=until,
            has_attachments=has_attachments,
            extra=[search_clause(anchor, scope)],
        )

    results: list[dict[str, Any]] = []
    for item in _iter_mail_items(f, dasl):
        if remaining:
            haystack = _search_haystack(item, scope)
            if not all(word in haystack for word in remaining):
                continue
        results.append(_mail_summary(item))
        if len(results) >= limit:
            break

    return {
        "query": query,
        "scope": scope,
        "folder": f.Name,
        "count": len(results),
        "items": results,
    }


def get_mail(
    outlook: Any,
    namespace: Any,
    *,
    entry_id: str,
    include_body: bool = True,
    include_html: bool = False,
    max_body_chars: int = 10000,
) -> dict[str, Any]:
    return _mail_full(
        get_item_by_id(namespace, entry_id),
        include_body=include_body,
        include_html=include_html,
        max_body_chars=max_body_chars,
    )


def _received_sort_key(item: Any) -> Any:
    value = _safe_get(item, "ReceivedTime")
    try:
        return value.timestamp()
    except Exception:
        return float("inf")


def _walk_conversation(node: Any, conversation: Any) -> Iterator[Any]:
    """Depth-first yield of ``node`` and all its descendants."""
    yield node
    children = conversation.GetChildren(node)
    if not children:
        return
    for child in children:
        yield from _walk_conversation(child, conversation)


def get_conversation(
    outlook: Any,
    namespace: Any,
    *,
    entry_id: str,
    include_body: bool = False,
    max_body_chars: int = 2000,
    limit: int = 200,
) -> dict[str, Any]:
    """Return every mail in the conversation (thread) containing ``entry_id``.

    Uses ``MailItem.GetConversation()`` and walks the conversation tree
    from its root items, so replies filed in other folders (Sent Items,
    sub-folders) are included. Items are returned oldest-first so the
    thread reads top-to-bottom. When Outlook reports no conversation
    (IMAP/POP stores, drafts), the single anchor item is returned.
    """
    anchor = get_item_by_id(namespace, entry_id)
    conversation_id = _safe_get(anchor, "ConversationID")

    def describe(item: Any) -> dict[str, Any]:
        out = _mail_summary(item)
        out["conversation_id"] = _safe_get(item, "ConversationID")
        out["folder"] = _safe_get(_safe_get(item, "Parent"), "Name")
        if include_body:
            body = _safe_get(item, "Body", "") or ""
            if max_body_chars and len(body) > max_body_chars:
                out["body"] = body[:max_body_chars].rstrip()
                out["body_truncated"] = True
                out["body_total_chars"] = len(body)
            else:
                out["body"] = body
        return out

    try:
        conversation = anchor.GetConversation()
    except Exception:
        conversation = None

    if conversation is None:
        return {
            "conversation_id": conversation_id,
            "count": 1,
            "truncated": False,
            "items": [describe(anchor)],
        }

    collected: list[Any] = []
    seen: set[Any] = set()
    for root in conversation.GetRootItems():
        for node in _walk_conversation(root, conversation):
            if _safe_get(node, "Class") not in (OL_CLASS_MAIL, OL_CLASS_MEETING_REQUEST):
                continue
            key = _safe_get(node, "EntryID")
            if key in seen:
                continue
            seen.add(key)
            collected.append(node)

    if not collected:
        collected = [anchor]
    collected.sort(key=_received_sort_key)
    truncated = len(collected) > limit
    items = [describe(item) for item in collected[:limit]]
    return {
        "conversation_id": conversation_id,
        "count": len(items),
        "truncated": truncated,
        "items": items,
    }


def send_mail(
    outlook: Any,
    namespace: Any,
    *,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    html: bool = False,
    attachments: list[str] | None = None,
    importance: str = "normal",
    save_only: bool = False,
) -> dict[str, Any]:
    mail = outlook.CreateItem(OL_MAIL_ITEM)
    mail.To = "; ".join(to)
    if cc:
        mail.CC = "; ".join(cc)
    if bcc:
        mail.BCC = "; ".join(bcc)
    mail.Subject = subject
    if html:
        mail.BodyFormat = OL_FORMAT_HTML
        mail.HTMLBody = body
    else:
        mail.BodyFormat = OL_FORMAT_PLAIN
        mail.Body = body
    mail.Importance = IMPORTANCE_MAP.get(importance.lower(), OL_IMPORTANCE_NORMAL)

    for raw_path in attachments or []:
        mail.Attachments.Add(validate_attachment_path(raw_path))

    if save_only:
        mail.Save()
        return {
            "status": "saved_to_drafts",
            "entry_id": mail.EntryID,
            "subject": mail.Subject,
        }

    mail.Send()
    return {
        "status": "sent",
        "to": to,
        "cc": cc or [],
        "bcc": bcc or [],
        "subject": subject,
    }


def reply_mail(
    outlook: Any,
    namespace: Any,
    *,
    entry_id: str,
    body: str,
    reply_all: bool = False,
    html: bool = False,
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    original = get_item_by_id(namespace, entry_id)
    reply = original.ReplyAll() if reply_all else original.Reply()
    if html:
        reply.BodyFormat = OL_FORMAT_HTML
        reply.HTMLBody = body + (reply.HTMLBody or "")
    else:
        reply.Body = body + "\n\n" + (reply.Body or "")
    for raw_path in attachments or []:
        reply.Attachments.Add(validate_attachment_path(raw_path))
    # Cache properties BEFORE Send(): once the reply is sent, the underlying
    # COM object has effectively moved from Drafts to Sent Items and reading
    # any of its properties raises a "item has been moved or deleted" COM
    # error. Surfacing that as a failure causes upstream AI agents to retry
    # and send duplicates, even though the original Send() succeeded.
    reply_subject = reply.Subject
    reply.Send()
    return {
        "status": "sent",
        "reply_all": reply_all,
        "in_reply_to": entry_id,
        "subject": reply_subject,
    }


def forward_mail(
    outlook: Any,
    namespace: Any,
    *,
    entry_id: str,
    to: list[str],
    body: str = "",
    cc: list[str] | None = None,
    html: bool = False,
) -> dict[str, Any]:
    original = get_item_by_id(namespace, entry_id)
    fwd = original.Forward()
    fwd.To = "; ".join(to)
    if cc:
        fwd.CC = "; ".join(cc)
    if body:
        if html:
            fwd.BodyFormat = OL_FORMAT_HTML
            fwd.HTMLBody = body + (fwd.HTMLBody or "")
        else:
            fwd.Body = body + "\n\n" + (fwd.Body or "")
    # Cache properties BEFORE Send(): once the forward is sent, the underlying
    # COM object has effectively moved from Drafts to Sent Items and reading
    # any of its properties raises a "item has been moved or deleted" COM
    # error. Surfacing that as a failure causes upstream AI agents to retry
    # and send duplicates, even though the original Send() succeeded.
    fwd_subject = fwd.Subject
    fwd.Send()
    return {"status": "sent", "forwarded": entry_id, "to": to, "subject": fwd_subject}


def move_mail(outlook: Any, namespace: Any, *, entry_id: str, target_folder: str) -> dict[str, Any]:
    item = get_item_by_id(namespace, entry_id)
    target = resolve_folder(namespace, target_folder)
    moved = item.Move(target)
    return {"status": "moved", "new_entry_id": moved.EntryID, "folder": target.Name}


def delete_mail(outlook: Any, namespace: Any, *, entry_id: str) -> dict[str, Any]:
    item = get_item_by_id(namespace, entry_id)
    subject = _safe_get(item, "Subject", "")
    item.Delete()
    return {"status": "deleted", "subject": subject, "entry_id": entry_id}


def mark_mail(
    outlook: Any,
    namespace: Any,
    *,
    entry_id: str,
    read: bool | None = None,
    flagged: bool | None = None,
) -> dict[str, Any]:
    item = get_item_by_id(namespace, entry_id)
    if read is not None:
        item.UnRead = not read
    if flagged is not None:
        item.FlagStatus = 2 if flagged else 0
    item.Save()
    return {
        "status": "updated",
        "entry_id": entry_id,
        "unread": bool(item.UnRead),
        "flagged": item.FlagStatus == 2,
    }


def save_attachments(
    outlook: Any,
    namespace: Any,
    *,
    entry_id: str,
    output_dir: str,
    attachment_index: int | None = None,
) -> dict[str, Any]:
    item = get_item_by_id(namespace, entry_id)
    out_dir = validate_output_dir(output_dir)
    saved: list[str] = []
    attachments = list(item.Attachments)
    if attachment_index is not None:
        if attachment_index < 1 or attachment_index > len(attachments):
            raise OutlookError(
                f"attachment_index {attachment_index} out of range "
                f"(message has {len(attachments)} attachments, 1-indexed)."
            )
        attachments = [attachments[attachment_index - 1]]

    for att in attachments:
        # Sender-controlled filename. Reject anything containing path
        # separators, drive-letter prefixes, dot-only names, or reserved
        # Windows device names. These are signals of a path-traversal
        # attempt by the sender, not legitimate attachments.
        raw = att.FileName or ""
        if not raw or raw in (".", ".."):
            raise OutlookError(f"Attachment has invalid filename: {raw!r}")
        if "\\" in raw or "/" in raw:
            raise OutlookError(
                f"Attachment filename contains path separators "
                f"(rejected for safety): {raw!r}"
            )
        if ":" in raw:
            raise OutlookError(
                f"Attachment filename contains colon "
                f"(rejected for safety): {raw!r}"
            )
        # Defense in depth: basename should be a no-op after the checks
        # above, but use it anyway in case ntpath sees something we missed.
        safe_name = ntpath.basename(raw)
        if safe_name != raw:
            raise OutlookError(
                f"Attachment filename did not normalize cleanly: {raw!r}"
            )
        stem = safe_name.lstrip(".").split(".", 1)[0].upper()
        if stem in WINDOWS_RESERVED_DEVICE_NAMES:
            raise OutlookError(
                f"Attachment has reserved Windows device name: {safe_name!r}"
            )

        # Mails often carry several attachments with the same name (e.g.
        # multiple inline "image.png") — uniquify instead of overwriting.
        target = os.path.join(out_dir, safe_name)
        base, ext = os.path.splitext(safe_name)
        counter = 1
        while os.path.exists(target):
            target = os.path.join(out_dir, f"{base} ({counter}){ext}")
            counter += 1
        att.SaveAsFile(target)
        saved.append(target)
    return {
        "status": "saved",
        "count": len(saved),
        "files": saved,
        "output_dir": out_dir,
    }


# --------------------------------------------------------------------------
# Bulk operations
# --------------------------------------------------------------------------


def _bulk(
    namespace: Any,
    entry_ids: list[str],
    op: Callable[[Any], dict[str, Any]],
    *,
    stop_on_error: bool = False,
) -> dict[str, Any]:
    """Apply ``op`` to every item, collecting per-item successes/failures.

    One MCP round-trip instead of N. A failure on one item (stale id,
    item already moved...) does not abort the batch unless
    ``stop_on_error`` is set; a *disconnect* (Outlook died) is always
    re-raised so the bridge can reconnect and retry the whole call.
    """
    succeeded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for entry_id in entry_ids:
        try:
            result = op(get_item_by_id(namespace, entry_id))
            result.setdefault("entry_id", entry_id)
            succeeded.append(result)
        except BaseException as exc:  # noqa: BLE001
            if is_disconnect_error(exc):
                raise
            failed.append({"entry_id": entry_id, "error": str(exc)})
            if stop_on_error:
                break
    return {
        "status": "ok" if not failed else ("partial" if succeeded else "failed"),
        "requested": len(entry_ids),
        "succeeded": len(succeeded),
        "failed": len(failed),
        "results": succeeded,
        "failures": failed,
    }


def bulk_move_mails(
    outlook: Any,
    namespace: Any,
    *,
    entry_ids: list[str],
    target_folder: str,
    stop_on_error: bool = False,
) -> dict[str, Any]:
    target = resolve_folder(namespace, target_folder)

    def op(item: Any) -> dict[str, Any]:
        subject = _safe_get(item, "Subject", "")
        moved = item.Move(target)
        return {"subject": subject, "new_entry_id": _safe_get(moved, "EntryID")}

    out = _bulk(namespace, entry_ids, op, stop_on_error=stop_on_error)
    out["folder"] = target.Name
    return out


def bulk_delete_mails(
    outlook: Any,
    namespace: Any,
    *,
    entry_ids: list[str],
    stop_on_error: bool = False,
) -> dict[str, Any]:
    def op(item: Any) -> dict[str, Any]:
        subject = _safe_get(item, "Subject", "")
        item.Delete()
        return {"subject": subject}

    return _bulk(namespace, entry_ids, op, stop_on_error=stop_on_error)


def bulk_mark_mails(
    outlook: Any,
    namespace: Any,
    *,
    entry_ids: list[str],
    read: bool | None = None,
    flagged: bool | None = None,
    categories: list[str] | None = None,
    stop_on_error: bool = False,
) -> dict[str, Any]:
    if read is None and flagged is None and categories is None:
        raise OutlookError("Nothing to do: pass at least one of read, flagged, categories.")

    def op(item: Any) -> dict[str, Any]:
        if read is not None:
            item.UnRead = not read
        if flagged is not None:
            item.FlagStatus = 2 if flagged else 0
        if categories is not None:
            item.Categories = ", ".join(categories)
        item.Save()
        return {
            "subject": _safe_get(item, "Subject", ""),
            "unread": bool(_safe_get(item, "UnRead", False)),
            "flagged": _safe_get(item, "FlagStatus") == 2,
            "categories": _safe_get(item, "Categories", ""),
        }

    return _bulk(namespace, entry_ids, op, stop_on_error=stop_on_error)


# --------------------------------------------------------------------------
# Export / save-as
# --------------------------------------------------------------------------


def _write_rows(path: str, rows: list[dict[str, Any]], fmt: str, columns: tuple[str, ...]) -> None:
    if fmt == "json":
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2, ensure_ascii=False, default=str)
        return
    # utf-8-sig so Excel opens non-ASCII subjects correctly when the user
    # double-clicks the CSV.
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def export_mails(
    outlook: Any,
    namespace: Any,
    *,
    output_path: str,
    entry_ids: list[str] | None = None,
    folder: str | None = "inbox",
    limit: int = 1000,
    unread_only: bool = False,
    since: str | None = None,
    until: str | None = None,
    from_address: str | None = None,
    has_attachments: bool | None = None,
    include_body: bool = False,
    max_body_chars: int = 2000,
    fmt: str = "csv",
) -> dict[str, Any]:
    """Write a table of mail metadata to a CSV or JSON file.

    Either pass explicit ``entry_ids`` or the same filters as
    ``list_mails`` (applied server-side via DASL). Designed so the result
    can be picked up by pandas / Excel / Power Automate without another
    round-trip through the model.
    """
    fmt = fmt.lower()
    if fmt not in ("csv", "json"):
        raise OutlookError("fmt must be 'csv' or 'json'.")
    path = validate_output_file(output_path, allowed_suffixes=(".csv", ".json"))

    columns = EXPORT_COLUMNS + (("body",) if include_body else ())

    def row_for(item: Any) -> dict[str, Any]:
        row = _mail_row(item)
        if include_body:
            body = _safe_get(item, "Body", "") or ""
            row["body"] = body[:max_body_chars] if max_body_chars else body
        return row

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    source: str
    if entry_ids:
        source = "entry_ids"
        for entry_id in entry_ids:
            try:
                rows.append(row_for(get_item_by_id(namespace, entry_id)))
            except BaseException as exc:  # noqa: BLE001
                if is_disconnect_error(exc):
                    raise
                failures.append({"entry_id": entry_id, "error": str(exc)})
    else:
        f = resolve_folder(namespace, folder)
        source = f.Name
        dasl = build_mail_filter(
            unread_only=unread_only,
            since=since,
            until=until,
            from_address=from_address,
            has_attachments=has_attachments,
        )
        for item in _iter_mail_items(f, dasl):
            rows.append(row_for(item))
            if len(rows) >= limit:
                break

    _write_rows(path, rows, fmt, columns)
    return {
        "status": "exported",
        "format": fmt,
        "path": path,
        "source": source,
        "count": len(rows),
        "truncated": not entry_ids and len(rows) >= limit,
        "failures": failures,
    }


_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _filename_from_subject(subject: str, suffix: str) -> str:
    stem = _UNSAFE_FILENAME_CHARS.sub("_", subject or "").strip(" .")[:120] or "message"
    if stem.split(".", 1)[0].upper() in WINDOWS_RESERVED_DEVICE_NAMES:
        stem = f"_{stem}"
    return stem + suffix


def save_mail_as(
    outlook: Any,
    namespace: Any,
    *,
    entry_id: str,
    output_dir: str,
    fmt: str = "msg",
    filename: str | None = None,
) -> dict[str, Any]:
    """Save a mail item to disk as .msg (full fidelity), .txt, or .html."""
    fmt = fmt.lower()
    if fmt not in SAVE_AS_MAP:
        raise OutlookError(f"fmt must be one of: {', '.join(sorted(SAVE_AS_MAP))}.")
    save_type, suffix = SAVE_AS_MAP[fmt]
    item = get_item_by_id(namespace, entry_id)
    out_dir = validate_output_dir(output_dir)

    if filename:
        if "\\" in filename or "/" in filename or ":" in filename:
            raise OutlookError("filename must be a bare file name, not a path.")
        if not filename.lower().endswith(suffix):
            filename += suffix
    else:
        filename = _filename_from_subject(_safe_get(item, "Subject", ""), suffix)

    target = os.path.join(out_dir, filename)
    base, ext = os.path.splitext(filename)
    counter = 1
    while os.path.exists(target):
        target = os.path.join(out_dir, f"{base} ({counter}){ext}")
        counter += 1
    item.SaveAs(target, save_type)
    return {
        "status": "saved",
        "entry_id": entry_id,
        "format": fmt,
        "path": target,
        "subject": _safe_get(item, "Subject", ""),
    }
