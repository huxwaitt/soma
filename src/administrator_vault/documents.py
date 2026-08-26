"""Read the text out of a file, part by part.

``extract(path)`` answers the same shape for every format it knows: a list of
sections, each with a locator the model can cite in a fact source
(``p3``, ``s4``, ``Sheet1``), the heading that names it and its text.

Word, PowerPoint and Excel files are read with the standard library
(a zip of xml parts); PDFs need ``pypdf``, which the ``search`` extra
installs. Plain text, markdown and csv are read as they are.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree as ET

from administrator_vault.store import VaultError

# file extension -> the format name written on the record
FORMATS = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".txt": "text",
    ".md": "markdown",
    ".csv": "csv",
}
PYPDF_MISSING = (
    "Reading a PDF needs pypdf, which is not installed. Install the 'search' extra "
    "(uv sync --extra search, or pip install \"outlook-classic-mcp[search]\") and try again."
)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
PML = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
SS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

_NUM_RE = re.compile(r"(\d+)")


def format_of(path: Any) -> str:
    """The format name of a file, or a refusal naming the extension."""
    ext = Path(str(path)).suffix.lower()
    fmt = FORMATS.get(ext)
    if not fmt:
        known = ", ".join(sorted(FORMATS))
        raise VaultError(f"cannot read {ext or '(no extension)'} files. Known: {known}.")
    return fmt


def _clean(text: str) -> str:
    return "\n".join(line.rstrip() for line in str(text).replace("\r\n", "\n").split("\n")).strip("\n")


def _section(locator: str, heading: str, text: str) -> dict[str, Any]:
    text = _clean(text)
    return {"locator": locator, "heading": heading, "text": text, "chars": len(text)}


def _answer(fmt: str, sections: list[dict[str, Any]]) -> dict[str, Any]:
    sections = [s for s in sections if s["text"] or s["heading"]]
    chars = sum(s["chars"] for s in sections)
    return {
        "format": fmt,
        "sections": sections,
        "parts": len(sections),
        "chars": chars,
        "empty": chars == 0,
    }


# ----------------------------------------------------------------------- pdf


def _pdf(p: Path) -> list[dict[str, Any]]:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise VaultError(PYPDF_MISSING) from None
    try:
        reader = PdfReader(str(p))
        pages = list(reader.pages)
    except Exception as exc:  # noqa: BLE001 - a broken file is a refusal, not a crash
        raise VaultError(f"That PDF could not be read: {exc}") from None
    out = []
    for n, page in enumerate(pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - one unreadable page does not lose the rest
            text = ""
        out.append(_section(f"p{n}", f"page {n}", text))
    return out


# ---------------------------------------------------------------------- docx


def _w_text(node: ET.Element) -> str:
    out = []
    for t in node.iter():
        if t.tag == W + "t":
            out.append(t.text or "")
        elif t.tag in (W + "tab",):
            out.append("\t")
        elif t.tag in (W + "br", W + "cr"):
            out.append("\n")
    return "".join(out)


def _w_style(par: ET.Element) -> str:
    style = par.find(W + "pPr/" + W + "pStyle")
    return (style.get(W + "val") or "") if style is not None else ""


def _docx(p: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(p) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(W + "body")
    if body is None:
        return []
    sections: list[tuple[str, list[str]]] = []
    for node in list(body):
        if node.tag == W + "p":
            text = _w_text(node).strip()
            if _w_style(node).lower().startswith("heading") and text:
                sections.append((text, []))
                continue
            if not text:
                continue
        elif node.tag == W + "tbl":
            rows = []
            for tr in node.findall(W + "tr"):
                cells = [" ".join(_w_text(tc).split()) for tc in tr.findall(W + "tc")]
                rows.append(" | ".join(cells))
            text = "\n".join(r for r in rows if r.strip(" |"))
            if not text:
                continue
        else:
            continue
        if not sections:
            sections.append(("", []))
        sections[-1][1].append(text)
    out = []
    for n, (heading, lines) in enumerate(sections, 1):
        out.append(_section(f"p{n}", heading or f"part {n}", "\n\n".join(lines)))
    return out


# ---------------------------------------------------------------------- pptx


def _a_text(node: ET.Element) -> str:
    """The text of one shape: one line per paragraph."""
    lines = []
    for par in node.iter(A + "p"):
        line = "".join(t.text or "" for t in par.iter(A + "t"))
        lines.append(line.rstrip())
    return "\n".join(l for l in lines if l.strip())


def _is_title(shape: ET.Element) -> bool:
    for ph in shape.iter(PML + "ph"):
        if (ph.get("type") or "") in ("title", "ctrTitle"):
            return True
    return False


def _sorted_parts(names: list[str], prefix: str) -> list[str]:
    keep = [n for n in names if n.startswith(prefix) and n.endswith(".xml")]

    def order(name: str) -> tuple[int, str]:
        m = _NUM_RE.search(name.rsplit("/", 1)[-1])
        return (int(m.group(1)) if m else 0, name)

    return sorted(keep, key=order)


def _pptx(p: Path) -> list[dict[str, Any]]:
    out = []
    with zipfile.ZipFile(p) as z:
        names = z.namelist()
        slides = _sorted_parts(names, "ppt/slides/slide")
        for n, name in enumerate(slides, 1):
            root = ET.fromstring(z.read(name))
            title, rest = "", []
            for shape in root.iter(PML + "sp"):
                text = _a_text(shape)
                if not text:
                    continue
                if not title and _is_title(shape):
                    title = " ".join(text.split())
                else:
                    rest.append(text)
            for tbl in root.iter(A + "tbl"):
                for tr in tbl.iter(A + "tr"):
                    cells = [" ".join(_a_text(tc).split()) for tc in tr.iter(A + "tc")]
                    row = " | ".join(cells)
                    if row.strip(" |"):
                        rest.append(row)
            notes_name = f"ppt/notesSlides/notesSlide{name.rsplit('slide', 1)[-1]}"
            if notes_name in names:
                notes = _a_text(ET.fromstring(z.read(notes_name)))
                notes = "\n".join(l for l in notes.split("\n") if l.strip() and l.strip() != str(n))
                if notes.strip():
                    rest.append("Notes: " + notes.strip())
            out.append(_section(f"s{n}", title or f"slide {n}", "\n\n".join(rest)))
    return out


# ---------------------------------------------------------------------- xlsx


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(SS + "t")) for si in root.findall(SS + "si")]


def _sheet_parts(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    """[(sheet name, part name)] in the workbook's own order."""
    root = ET.fromstring(z.read("xl/workbook.xml"))
    targets: dict[str, str] = {}
    if "xl/_rels/workbook.xml.rels" in z.namelist():
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        for r in rels.findall(PKG_REL + "Relationship"):
            target = (r.get("Target") or "").replace("\\", "/")
            if target.startswith("/"):  # a part named from the root of the file
                part = target.lstrip("/")
            elif target.startswith("xl/"):
                part = target
            else:
                part = "xl/" + target
            targets[r.get("Id") or ""] = part
    out = []
    for sheet in root.iter(SS + "sheet"):
        name = sheet.get("name") or ""
        part = targets.get(sheet.get(REL + "id") or "", "")
        if part and part in z.namelist():
            out.append((name, part))
    return out


def _cell_value(c: ET.Element, strings: list[str]) -> str:
    kind = c.get("t") or ""
    if kind == "s":
        v = c.find(SS + "v")
        try:
            return strings[int((v.text or "0"))] if v is not None else ""
        except (ValueError, IndexError):
            return ""
    if kind == "inlineStr":
        return "".join(t.text or "" for t in c.iter(SS + "t"))
    v = c.find(SS + "v")
    return (v.text or "") if v is not None else ""


def _xlsx(p: Path) -> list[dict[str, Any]]:
    out = []
    with zipfile.ZipFile(p) as z:
        strings = _shared_strings(z)
        for name, part in _sheet_parts(z):
            root = ET.fromstring(z.read(part))
            lines = []
            for row in root.iter(SS + "row"):
                cells, first = [], ""
                for c in row.findall(SS + "c"):
                    value = " ".join(_cell_value(c, strings).split())
                    if value and not first:
                        first = c.get("r") or ""
                    cells.append(value)
                while cells and not cells[-1]:
                    cells.pop()
                if not any(cells):
                    continue
                lines.append((f"{first}: " if first else "") + " | ".join(cells))
            out.append(_section(name or f"sheet{len(out) + 1}", name, "\n".join(lines)))
    return out


# ------------------------------------------------------------------- plain text


def _plain(p: Path, fmt: str) -> list[dict[str, Any]]:
    raw = p.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 decodes anything
        text = raw.decode("utf-8", "replace")
    if fmt == "csv":
        rows = list(csv.reader(io.StringIO(text, newline="")))
        text = "\n".join(" | ".join(cell.strip() for cell in row) for row in rows if any(c.strip() for c in row))
    return [_section("p1", p.stem, text)]


# ----------------------------------------------------------------------- api


def extract(path: Any) -> dict[str, Any]:
    """The text of a file as {format, sections, parts, chars, empty}.

    Each section is {locator, heading, text, chars}. ``empty`` is true when
    nothing could be read at all — a scanned PDF with no text layer, or an
    empty file."""
    p = Path(str(path))
    fmt = format_of(p)
    if not p.is_file():
        raise VaultError(f"No such file: {p}")
    try:
        if fmt == "pdf":
            sections = _pdf(p)
        elif fmt == "docx":
            sections = _docx(p)
        elif fmt == "pptx":
            sections = _pptx(p)
        elif fmt == "xlsx":
            sections = _xlsx(p)
        else:
            sections = _plain(p, fmt)
    except VaultError:
        raise
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise VaultError(f"That {fmt} file could not be read: {exc}") from None
    except OSError as exc:
        raise VaultError(f"That file could not be read: {exc}") from None
    return _answer(fmt, sections)


def full_text(result: dict[str, Any], sections: Optional[list[dict[str, Any]]] = None) -> str:
    """Every section of an extract as one markdown text with its headings."""
    out = []
    for s in sections if sections is not None else result["sections"]:
        out.append(f"### {s['locator']} — {s['heading']}")
        out.append("")
        out.append(s["text"])
        out.append("")
    return "\n".join(out).strip("\n")


__all__ = ["FORMATS", "extract", "format_of", "full_text"]
