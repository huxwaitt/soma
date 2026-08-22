"""Deterministic quoted-history and signature trimming for plain-text mail bodies.

``trim_quoted`` never touches the caller's ``body``; it returns a trimmed
copy plus how many characters were removed and which rules fired. Rules
are regex/line based (no ML, no locale data) so results are reproducible
across runs and machines.
"""

from __future__ import annotations

import re

MIN_KEEP_CHARS = 20
SIGNATURE_WINDOW = 12

_OUTLOOK_SEPARATOR = re.compile(r"^\s*(-{3,}\s*Original Message\s*-{3,}|_{20,})\s*$", re.I)
_HEADER_LINE = re.compile(
    r"^\s*(From|Sent|To|Cc|Subject|Date"  # EN
    r"|Von|Gesendet|An|Betreff|Datum"  # DE
    r"|De|Envoyé|Envoye|À|A|Objet"  # FR
    r"|Da|Inviato|Oggetto)\s*:",  # IT
    re.I,
)
_FOREIGN_FROM = re.compile(r"^\s*(Von|De|Da)\s*:", re.I)
_EN_FROM = re.compile(r"^\s*From\s*:", re.I)
_ON_WROTE_ONE_LINE = re.compile(r"^\s*On .+ wrote:\s*$")
_ON_START = re.compile(r"^\s*On .+$")
_WROTE_END = re.compile(r".*wrote:\s*$")
_QUOTE_LINE = re.compile(r"^\s*>")
_SIG_DASHES = re.compile(r"^-- ?$")
_MOBILE_SIG = re.compile(r"^\s*(Sent from my .+|Get Outlook for .+|Von meinem .+ gesendet)\s*$", re.I)
_SIG_DETAIL = re.compile(r"(\d|\bTel\b|\bMobile\b|\bMobil\b|\bPhone\b|\bFax\b|www\.|@)", re.I)
_BLANK_RUN = re.compile(r"\n[ \t]*\n[ \t]*\n(?:[ \t]*\n)+")


def _find_history_cut(lines: list[str]) -> tuple[int | None, str | None]:
    """Return (line index to cut at, marker) for the earliest history marker."""
    n = len(lines)
    best: tuple[int, str] | None = None

    def offer(idx: int, marker: str) -> None:
        nonlocal best
        if best is None or idx < best[0]:
            best = (idx, marker)

    for i, line in enumerate(lines):
        # 1. Outlook separator followed within 3 lines by From:
        if _OUTLOOK_SEPARATOR.match(line):
            for j in range(i + 1, min(n, i + 4)):
                if _EN_FROM.match(lines[j]) or _FOREIGN_FROM.match(lines[j]):
                    offer(i, "outlook separator")
                    break
        # 2./4. Header block: 2+ consecutive header lines, starting with From/Von/De/Da
        if (_EN_FROM.match(line) or _FOREIGN_FROM.match(line)) and i + 1 < n and _HEADER_LINE.match(lines[i + 1]):
            offer(i, "header block (foreign)" if _FOREIGN_FROM.match(line) else "header block")
        # 3. "On ... wrote:" possibly wrapped over two lines
        if _ON_WROTE_ONE_LINE.match(line):
            offer(i, "on-wrote")
        elif _ON_START.match(line) and i + 1 < n and _WROTE_END.match(lines[i + 1]) and not _QUOTE_LINE.match(lines[i + 1]):
            offer(i, "on-wrote (wrapped)")
        # 5. Run of 3+ ">" lines
        if _QUOTE_LINE.match(line) and (i == 0 or not _QUOTE_LINE.match(lines[i - 1])):
            run = 0
            while i + run < n and _QUOTE_LINE.match(lines[i + run]):
                run += 1
            if run >= 3:
                offer(i, "quoted lines")
    if best is None:
        return None, None
    return best


def _name_tokens(sender_name: str) -> set[str]:
    name = (sender_name or "").strip()
    if not name:
        return set()
    tokens = {name.casefold()}
    parts = [p for p in re.split(r"[\s,]+", name) if len(p) > 1]
    if parts:
        tokens.add(parts[0].casefold())
        tokens.add(parts[-1].casefold())
    return tokens


def _find_signature_cut(lines: list[str], sender_name: str) -> tuple[int | None, str | None]:
    n = len(lines)
    for i, line in enumerate(lines):
        if _SIG_DASHES.match(line):
            return i, "signature (--)"
    for i, line in enumerate(lines):
        if _MOBILE_SIG.match(line):
            return i, "mobile signature"
    tokens = _name_tokens(sender_name)
    if tokens:
        start = max(0, n - SIGNATURE_WINDOW)
        for i in range(start, n):
            if lines[i].strip().casefold() not in tokens:
                continue
            tail = [ln for ln in lines[i + 1 :] if ln.strip()]
            if 1 <= len(tail) <= 8 and all(len(ln) <= 80 for ln in tail) and any(_SIG_DETAIL.search(ln) for ln in tail):
                return i, "name signature"
    return None, None


def trim_quoted(body: str, sender_name: str = "", sender_address: str = "") -> tuple[str, int, list[str]]:
    """Strip quoted history and the trailing signature from a plain-text body.

    Returns ``(trimmed, trimmed_chars, markers)``. ``body`` is never
    modified. If trimming would leave fewer than ``MIN_KEEP_CHARS``
    characters the original is returned with ``markers == ["kept: too short"]``.
    """
    if not body:
        return body, 0, []
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    markers: list[str] = []

    cut, marker = _find_history_cut(lines)
    if cut is not None:
        lines = lines[:cut]
        markers.append(marker or "history")

    sig, marker = _find_signature_cut(lines, sender_name)
    if sig is not None:
        lines = lines[:sig]
        markers.append(marker or "signature")

    trimmed = "\n".join(lines).rstrip()
    trimmed = _BLANK_RUN.sub("\n\n\n", trimmed)

    if not markers:
        return body, 0, []
    if len(trimmed.strip()) < MIN_KEEP_CHARS:
        return body, 0, ["kept: too short"]
    return trimmed, max(0, len(body) - len(trimmed)), markers
