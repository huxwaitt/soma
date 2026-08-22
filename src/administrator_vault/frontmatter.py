"""Tiny YAML frontmatter reader and writer.

Only the subset the plugin writes is supported: ``key: value`` scalars,
double- or single-quoted strings, ``[a, b]`` inline lists, ``- x`` block
lists, booleans, integers. No nesting, no anchors, no multi-line strings.
No pyyaml dependency.
"""

from __future__ import annotations

import re
from typing import Any

_INT_RE = re.compile(r"^-?\d+$")
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_NEEDS_QUOTE_CHARS = set(':#[]{}"\'|>&*!%`')
_SPECIAL_START = set("-?:,[]{}#&*!|>'\"%@`")
# Keys whose string values are always quoted (ids, subjects, locations).
ALWAYS_QUOTED = {
    "entry_id", "internet_message_id", "conversation_id", "global_id",
    "occurrence_key", "subject", "location", "msg_file",
}


class FrontmatterError(ValueError):
    """Raised when a frontmatter block cannot be read or written."""


# --------------------------------------------------------------------------- read


def _unquote(raw: str) -> str:
    q = raw[0]
    inner = raw[1:-1]
    if q == '"':
        return inner.replace('\\"', '"').replace("\\\\", "\\")
    return inner.replace("''", "'")


def parse_scalar(raw: str) -> Any:
    s = raw.strip()
    if s == "":
        return ""
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return _unquote(s)
    if s == "[]":
        return []
    if s.startswith("[") and s.endswith("]"):
        return [parse_scalar(p) for p in _split_inline(s[1:-1])]
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "~"):
        return None
    if _INT_RE.match(s):
        return int(s)
    return s


def _split_inline(s: str) -> list[str]:
    parts: list[str] = []
    buf = ""
    quote: str | None = None
    for ch in s:
        if quote:
            buf += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf += ch
        elif ch == ",":
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf)
    return parts


def parse_frontmatter_block(block: str) -> dict[str, Any]:
    """Parse the text between the ``---`` fences into a dict."""
    data: dict[str, Any] = {}
    list_key: str | None = None
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if stripped.startswith("- ") or stripped == "-":
            if list_key is None:
                raise FrontmatterError(f"List item without a key: {line!r}")
            if not isinstance(data[list_key], list):
                data[list_key] = []
            data[list_key].append(parse_scalar(stripped[1:]))
            continue
        if line[0] in " \t":
            raise FrontmatterError(f"Unexpected indented line: {line!r}")
        if ":" not in line:
            raise FrontmatterError(f"Line is not 'key: value': {line!r}")
        key, _, value = line.partition(":")
        key = key.strip()
        if not key:
            raise FrontmatterError(f"Empty key in line: {line!r}")
        value = value.strip()
        if value == "":
            data[key] = ""
            list_key = key
        else:
            data[key] = parse_scalar(value)
            list_key = None
    return data


def split_note(text: str) -> tuple[dict[str, Any], str, str]:
    """Split a note into (frontmatter dict, raw frontmatter block, body).

    A note without a frontmatter block returns ``({}, "", text)``.
    """
    if not text.startswith("---"):
        return {}, "", text
    lines = text.split("\n")
    if lines[0].rstrip("\r") != "---":
        return {}, "", text
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r") == "---":
            block = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1 :])
            if body.startswith("\n"):
                body = body[1:]
            return parse_frontmatter_block(block), block, body
    raise FrontmatterError("Frontmatter block is not closed with '---'.")


# -------------------------------------------------------------------------- write


def quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def format_scalar(value: Any, key: str = "") -> str:
    if value is None:
        return '""'
    if key in ALWAYS_QUOTED and isinstance(value, str):
        return quote(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    s = str(value)
    if s == "":
        return '""'
    if s != s.strip():
        return quote(s)
    if s[0] in _SPECIAL_START:
        return quote(s)
    if any(ch in _NEEDS_QUOTE_CHARS for ch in s):
        return quote(s)
    if _ISO_RE.match(s):
        return quote(s)
    low = s.lower()
    if low in ("true", "false", "null", "~", "yes", "no", "on", "off") or _INT_RE.match(s):
        return quote(s)
    try:
        float(s)
        return quote(s)
    except ValueError:
        pass
    return s


def format_frontmatter(data: dict[str, Any]) -> str:
    """Serialize a dict as a frontmatter block including the fences."""
    out = ["---"]
    for key, value in data.items():
        if isinstance(value, (list, tuple)):
            if not value:
                out.append(f"{key}: []")
            else:
                out.append(f"{key}:")
                for item in value:
                    if isinstance(item, (list, tuple, dict)):
                        raise FrontmatterError(f"Nested lists are not supported ({key}).")
                    out.append(f"  - {format_scalar(item)}")
        elif isinstance(value, dict):
            raise FrontmatterError(f"Nested mappings are not supported ({key}).")
        else:
            out.append(f"{key}: {format_scalar(value, key)}")
    out.append("---")
    return "\n".join(out) + "\n"


def replace_keys(block: str, updates: dict[str, Any]) -> str:
    """Replace the value of top-level scalar keys inside a raw frontmatter
    block, line by line, leaving every other line byte-for-byte intact.
    Keys that are not present are appended at the end of the block."""
    lines = block.split("\n")
    done: set[str] = set()
    for i, line in enumerate(lines):
        if not line or line[0] in " \t" or line.lstrip().startswith("-"):
            continue
        key = line.partition(":")[0].strip()
        if key in updates and key not in done:
            lines[i] = f"{key}: {format_scalar(updates[key], key)}"
            done.add(key)
    for key, value in updates.items():
        if key not in done:
            lines.append(f"{key}: {format_scalar(value, key)}")
    return "\n".join(lines)


def replace_list_key(block: str, key: str, items: list[Any]) -> str:
    """Replace (or add) a block-list key inside a raw frontmatter block."""
    lines = block.split("\n")
    new_lines = [f"{key}:"] + [f"  - {format_scalar(i)}" for i in items] if items else [f"{key}: []"]
    out: list[str] = []
    i = 0
    replaced = False
    while i < len(lines):
        line = lines[i]
        if line and line[0] not in " \t" and line.partition(":")[0].strip() == key and not replaced:
            i += 1
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or lines[i].lstrip().startswith("- ")):
                if not lines[i].strip():
                    break
                i += 1
            out.extend(new_lines)
            replaced = True
            continue
        out.append(line)
        i += 1
    if not replaced:
        out.extend(new_lines)
    return "\n".join(out)
