"""Workflows computed in code so the model only reads the answer.

Three read-only tools built on the mail client:

* ``awaiting_reply`` — sent threads where the user wrote last and nobody
  answered for N days.
* ``find`` — a fixed search plan (people in ``from``, words in
  subject/body) over several folders, merged per conversation, scored,
  with the best sentence pulled out of each body.
* ``voice_sample`` — openings and closings of the user's own sent mail,
  plus greeting / sign-off counts.

Everything is plain Python over COM reads; nothing here writes to Outlook.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable

from outlook_mcp.client.folders import _safe_get, resolve_folder
from outlook_mcp.client.mail import (
    _conversation_items,
    _iter_mail_items,
    _received_sort_key,
    _recipients,
    _search_items,
    _trim_quoted,
    _walk_folders,
    build_mail_filter,
    current_user_name,
    current_user_smtp,
    internet_message_id,
    sender_smtp,
)
from outlook_mcp.errors import OutlookError
from outlook_mcp.utils.formatting import from_iso, to_iso, truncate

# Calendar responses, auto-replies and read receipts sit in Sent Items
# but are never something the user is waiting on.
AUTO_SUBJECT_PREFIXES = (
    "accepted:",
    "tentative:",
    "declined:",
    "automatic reply:",
    "automatische antwort:",
    "read:",
    "zugesagt:",
    "abgelehnt:",
    "mit vorbehalt:",
)

SIGNOFFS = (
    "thanks",
    "thank you",
    "many thanks",
    "thx",
    "best",
    "all the best",
    "best regards",
    "kind regards",
    "warm regards",
    "regards",
    "cheers",
    "sincerely",
    "talk soon",
    "speak soon",
    "br",
    "viele grüße",
    "viele gruesse",
    "beste grüße",
    "liebe grüße",
    "schöne grüße",
    "mit freundlichen grüßen",
    "freundliche grüße",
    "herzliche grüße",
    "grüße",
    "gruß",
    "danke",
    "vielen dank",
    "vg",
    "lg",
    "mfg",
)

_SIG_DETAIL = re.compile(r"(\d{3,}|\bTel\b|\bMobile\b|\bMobil\b|\bPhone\b|\bFax\b|www\.|@|https?://)", re.I)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_TRAIL_PUNCT = re.compile(r"[\s,;:!.\-–—]+$")
_WORD_SPLIT = re.compile(r"[\s,<>;]+")


# ---------------------------------------------------------------- helpers --


def _now(now: dt.datetime | None) -> dt.datetime:
    return now.replace(tzinfo=None) if now is not None else dt.datetime.now()


def _naive(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=None)
    return None


def _trimmed_body(item: Any, sender_name: str = "") -> str:
    body = str(_safe_get(item, "Body", "") or "")
    name = sender_name or str(_safe_get(item, "SenderName", "") or "")
    trimmed, _chars, _markers = _trim_quoted(body, sender_name=name, sender_address=str(sender_smtp(item) or ""))
    return trimmed.replace("\r\n", "\n").replace("\r", "\n")


def _nonempty_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.split("\n") if ln.strip()]


def _norm(line: str) -> str:
    # lower(), not casefold(): "Grüße" must stay "grüße" so counts read naturally.
    return _TRAIL_PUNCT.sub("", line.strip()).lower()


def _name_tokens(name: str, address: str = "") -> set[str]:
    out: set[str] = set()
    name = (name or "").strip()
    if name:
        out.add(name.lower())
        parts = [p for p in re.split(r"[\s,]+", name) if len(p) > 1]
        if parts:
            out.add(parts[0].lower())
            out.add(parts[-1].lower())
    local = (address or "").split("@", 1)[0].lower()
    if local:
        out.add(local)
    return out


def _is_signoff(line: str) -> bool:
    n = _norm(line)
    if not n:
        return False
    if n in SIGNOFFS:
        return True
    return any(n.startswith(s + " ") or n.startswith(s + ",") for s in SIGNOFFS)


def _is_name_line(line: str, names: set[str]) -> bool:
    return _norm(line) in names


def _last_line(trimmed: str, names: set[str], max_chars: int = 200) -> str:
    """Last meaningful line the user wrote: skips sign-offs, the user's
    name, and signature details; falls back to the start of the body."""
    lines = _nonempty_lines(trimmed)
    for line in reversed(lines):
        if _is_signoff(line) or _is_name_line(line, names):
            continue
        if len(line) <= 60 and _SIG_DETAIL.search(line):
            continue
        return truncate(line, max_chars)
    return truncate(trimmed, max_chars)


def _match_person(person: str, from_address: str, from_name: str) -> bool:
    p = person.casefold().strip()
    if not p:
        return False
    hay_addr = (from_address or "").casefold()
    hay_name = (from_name or "").casefold()
    if p in hay_addr or p in hay_name:
        return True
    tokens = [t for t in _WORD_SPLIT.split(p) if t]
    return bool(tokens) and all(t in hay_addr or t in hay_name for t in tokens)


def best_sentence(text: str, words: Iterable[str], max_chars: int = 200) -> str:
    """The sentence of ``text`` holding the most of ``words`` (first on ties).

    Sentences are split on ``.``, ``!``, ``?`` and line breaks. With no
    words the first sentence is returned. Always cut to ``max_chars``.
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s and s.strip()]
    if not sentences:
        return ""
    wl = [w.casefold() for w in words if w]
    if not wl:
        return truncate(sentences[0], max_chars)
    best = sentences[0]
    best_hits = -1
    for s in sentences:
        low = s.casefold()
        hits = sum(1 for w in wl if w in low)
        if hits > best_hits:
            best, best_hits = s, hits
    return truncate(best, max_chars)


# ---------------------------------------------------------- awaiting_reply --


def awaiting_reply(
    outlook: Any,
    namespace: Any,
    *,
    days: int = 3,
    since_days: int = 30,
    limit: int = 50,
    folder: str = "sent",
    max_conversations: int = 60,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Sent threads where the user's mail is the newest and is older than ``days``.

    Groups sent mail by ``ConversationID`` (newest first), reads each
    conversation once (at most ``max_conversations``), and keeps the
    threads whose last item is from the user, older than ``days`` and
    addressed to somebody else. ``items`` are sorted longest wait first.
    """
    if days < 0:
        raise OutlookError("days cannot be negative.")
    if since_days < 1:
        raise OutlookError("since_days must be at least 1.")
    now_dt = _now(now)
    me = (current_user_smtp(namespace) or "").casefold()
    my_name = current_user_name(namespace)
    f = resolve_folder(namespace, folder)
    since_dt = now_dt - dt.timedelta(days=since_days)
    dasl = build_mail_filter(since=since_dt.isoformat())

    seen_conv: set[Any] = set()
    seen_entry: set[Any] = set()
    threads_checked = 0
    scanned = 0
    capped = False
    found: list[dict[str, Any]] = []

    for item in _iter_mail_items(f, dasl):
        scanned += 1
        subject = str(_safe_get(item, "Subject", "") or "")
        if subject.casefold().startswith(AUTO_SUBJECT_PREFIXES):
            continue
        if not (_safe_get(item, "To", "") or ""):
            continue
        entry_id = _safe_get(item, "EntryID")
        if entry_id in seen_entry:
            continue
        conv_id = _safe_get(item, "ConversationID") or entry_id
        if conv_id in seen_conv:
            continue
        if threads_checked >= max_conversations:
            capped = True
            break
        seen_conv.add(conv_id)
        threads_checked += 1
        if not me:
            # No CurrentUser (IMAP/POP profile): the sender of a sent item is us.
            me = (sender_smtp(item) or "").casefold()

        thread = _conversation_items(item)
        for t in thread:
            seen_entry.add(_safe_get(t, "EntryID"))
        last = thread[-1]
        last_from = (sender_smtp(last) or "").casefold()
        if not last_from or last_from != me:
            continue  # somebody else wrote last: they answered
        received = _naive(_safe_get(last, "ReceivedTime"))
        if received is None or now_dt - received < dt.timedelta(days=days):
            continue
        recipients = _recipients(last)
        to = [r["address"] for r in recipients if r["type"] == "to" and (r["address"] or "").casefold() != me]
        if not to:
            to = [r["address"] for r in recipients if r["type"] == "cc" and (r["address"] or "").casefold() != me]
        if recipients and not to:
            continue  # mail to oneself is not a follow-up
        names = _name_tokens(my_name or str(_safe_get(last, "SenderName", "") or ""), me)
        found.append(
            {
                "conversation_id": _safe_get(last, "ConversationID") or conv_id,
                "entry_id": _safe_get(last, "EntryID"),
                "internet_message_id": internet_message_id(last),
                "subject": str(_safe_get(last, "Subject", "") or ""),
                "to": to,
                "to_names": str(_safe_get(last, "To", "") or ""),
                "last_sent": to_iso(_safe_get(last, "ReceivedTime")),
                "days_waiting": (now_dt.date() - received.date()).days,
                "last_line": _last_line(_trimmed_body(last, my_name), names),
            }
        )

    found.sort(key=lambda i: i["days_waiting"], reverse=True)
    items = found[:limit]
    return {
        "days": days,
        "since": to_iso(since_dt),
        "folder": f.Name,
        "self": me,
        "sent_scanned": scanned,
        "threads_checked": threads_checked,
        "capped": capped,
        "count": len(items),
        "items": items,
    }


# -------------------------------------------------------------------- find --

SCORE_PERSON = 3
SCORE_SUBJECT_WORD = 2
SCORE_BODY_WORD = 1
SCORE_DATE_FIT = 1


def find(
    outlook: Any,
    namespace: Any,
    *,
    people: list[str] | None = None,
    words: list[str] | None = None,
    since: str | None = None,
    until: str | None = None,
    folders: list[str] | None = None,
    include_subfolders: bool = False,
    limit: int = 10,
    per_search: int = 50,
    body_top: int = 20,
) -> dict[str, Any]:
    """Run the find search plan in code and return the top ``limit`` threads.

    Per folder: one ``from`` search per person and one ``subject_body``
    search per word. Hits are merged and reduced to one (newest) mail per
    conversation, then scored: person match +3 each, word in subject +2
    each, word in the trimmed body +1 each (bodies are read only for the
    ``body_top`` best candidates), date inside ``since``/``until`` +1.
    """
    people = [p.strip() for p in (people or []) if p and p.strip()]
    words = [w.strip().casefold() for w in (words or []) if w and w.strip()]
    if not people and not words:
        raise OutlookError("Pass at least one person or one word.")
    folder_specs = [s for s in (folders or ["inbox", "sent"]) if s]
    since_dt = from_iso(since)
    until_dt = from_iso(until)

    candidates: dict[Any, dict[str, Any]] = {}
    searches = 0
    folders_searched = 0

    def add(item: Any, folder_name: str) -> None:
        key = _safe_get(item, "ConversationID") or _safe_get(item, "EntryID")
        cur = candidates.get(key)
        if cur is None or _received_sort_key(item) > _received_sort_key(cur["item"]):
            candidates[key] = {"item": item, "folder": folder_name}

    for spec in folder_specs:
        root = resolve_folder(namespace, spec)
        for fo in _walk_folders(root, include_subfolders):
            folders_searched += 1
            name = str(_safe_get(fo, "Name", "") or "")
            plan = [(p, "from") for p in people] + [(w, "subject_body") for w in words]
            for query, scope in plan:
                searches += 1
                for item in _search_items(fo, query=query, scope=scope, since=since, until=until, limit=per_search):
                    add(item, name)

    scored: list[dict[str, Any]] = []
    for entry in candidates.values():
        item = entry["item"]
        from_address = str(sender_smtp(item) or "")
        from_name = str(_safe_get(item, "SenderName", "") or "")
        subject = str(_safe_get(item, "Subject", "") or "")
        subject_low = subject.casefold()
        score = SCORE_PERSON * sum(1 for p in people if _match_person(p, from_address, from_name))
        score += SCORE_SUBJECT_WORD * sum(1 for w in words if w in subject_low)
        received = _naive(_safe_get(item, "ReceivedTime"))
        if (since_dt or until_dt) and received is not None:
            if (since_dt is None or received >= since_dt) and (until_dt is None or received <= until_dt):
                score += SCORE_DATE_FIT
        scored.append(
            {
                "entry_id": _safe_get(item, "EntryID"),
                "conversation_id": _safe_get(item, "ConversationID"),
                "subject": subject,
                "from_address": from_address,
                "received": to_iso(_safe_get(item, "ReceivedTime")),
                "score": score,
                "snippet": "",
                "folder": entry["folder"],
                "body_read": False,
                "_item": item,
                "_sort": _received_sort_key(item),
            }
        )

    scored.sort(key=lambda c: (c["score"], c["_sort"]), reverse=True)
    for cand in scored[:body_top]:
        trimmed = _trimmed_body(cand["_item"])
        low = trimmed.casefold()
        cand["score"] += SCORE_BODY_WORD * sum(1 for w in words if w in low)
        cand["snippet"] = best_sentence(trimmed, words)
        cand["body_read"] = True
    scored.sort(key=lambda c: (c["score"], c["_sort"]), reverse=True)

    items = []
    for cand in scored[:limit]:
        cand.pop("_item", None)
        cand.pop("_sort", None)
        items.append(cand)
    return {
        "people": people,
        "words": words,
        "since": since,
        "until": until,
        "folders": folder_specs,
        "folders_searched": folders_searched,
        "searches": searches,
        "candidates": len(scored),
        "count": len(items),
        "items": items,
    }


# ------------------------------------------------------------ voice_sample --


def _greeting(lines: list[str]) -> str:
    if not lines:
        return ""
    first = lines[0]
    if len(first) > 60:
        return ""  # no greeting line, the mail starts with the text
    parts = [p for p in _WORD_SPLIT.split(_norm(first)) if p]
    if not parts:
        return ""
    if parts[0] in ("good", "guten", "gute") and len(parts) > 1:
        return parts[0] + " " + parts[1]
    return parts[0]


def _signoff(lines: list[str], names: set[str]) -> str:
    tail = lines[-4:]
    for line in reversed(tail):
        if _is_name_line(line, names):
            continue
        if _SIG_DETAIL.search(line):
            continue
        if _is_signoff(line):
            return _norm(line)
        words = [w for w in _WORD_SPLIT.split(line) if w]
        if len(words) <= 3 and not re.search(r"[.?!].", line) and not line.rstrip().endswith("?"):
            return _norm(line)
    return ""


def _closing(lines: list[str]) -> list[str]:
    return lines[-2:]


def _counts(values: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        if v:
            out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def voice_sample(
    outlook: Any,
    namespace: Any,
    *,
    address: str | None = None,
    n: int = 10,
    max_chars: int = 300,
    min_matches: int = 3,
    scan_limit: int = 300,
) -> dict[str, Any]:
    """Openings and closings of the user's sent mail, for a voice profile.

    With ``address`` the newest ``n`` sent mails to that address are used
    when at least ``min_matches`` exist (scanning at most ``scan_limit``
    sent items); otherwise the newest ``n`` sent mails overall. Each body
    is trimmed (no quoted history, no signature) before sampling.
    """
    if n < 1:
        raise OutlookError("n must be at least 1.")
    f = resolve_folder(namespace, "sent")
    my_name = current_user_name(namespace)
    me = current_user_smtp(namespace)
    addr = (address or "").strip().casefold()

    matched: list[Any] = []
    overall: list[Any] = []
    scanned = 0
    for item in _iter_mail_items(f, None):
        scanned += 1
        if len(overall) < n:
            overall.append(item)
        if addr:
            recipients = _recipients(item)
            hay = " ".join((r["address"] or "").casefold() for r in recipients)
            hay += " " + str(_safe_get(item, "To", "") or "").casefold()
            if addr in hay:
                matched.append(item)
                if len(matched) >= n:
                    break
            if scanned >= scan_limit:
                break
        elif len(overall) >= n:
            break

    used_address = bool(addr) and len(matched) >= min_matches
    sample = matched[:n] if used_address else overall

    items: list[dict[str, Any]] = []
    greetings: list[str] = []
    signoffs: list[str] = []
    lengths: list[int] = []
    for item in sample:
        sender_name = my_name or str(_safe_get(item, "SenderName", "") or "")
        names = _name_tokens(sender_name, me or str(sender_smtp(item) or ""))
        trimmed = _trimmed_body(item, sender_name)
        lines = _nonempty_lines(trimmed)
        recipients = _recipients(item)
        to = [r["address"] for r in recipients if r["type"] == "to" and r["address"]]
        if not to:
            to = [p.strip() for p in str(_safe_get(item, "To", "") or "").split(";") if p.strip()]
        items.append(
            {
                "entry_id": _safe_get(item, "EntryID"),
                "to": to,
                "subject": str(_safe_get(item, "Subject", "") or ""),
                "sent": to_iso(_safe_get(item, "SentOn") or _safe_get(item, "ReceivedTime")),
                "opening": truncate(trimmed, max_chars),
                "closing": _closing(lines),
            }
        )
        greetings.append(_greeting(lines))
        signoffs.append(_signoff(lines, names))
        lengths.append(len(trimmed))

    return {
        "address": address or "",
        "used_address": used_address,
        "matched": len(matched),
        "scanned": scanned,
        "count": len(items),
        "items": items,
        "stats": {
            "avg_chars": round(sum(lengths) / len(lengths)) if lengths else 0,
            "greeting_counts": _counts(greetings),
            "signoff_counts": _counts(signoffs),
        },
    }
