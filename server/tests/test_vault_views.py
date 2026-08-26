"""The four Bases views shipped by vault_init: well-formed, and only referencing
properties the note schemas define (plus the optional keys vault.md allows)."""

from __future__ import annotations

import re

import pytest

from soma_vault import notes, store

VIEW_NAMES = ("People", "Follow-ups", "Meetings", "Emails", "Wiki")

# Optional frontmatter keys vault.md / meeting-note.md allow on top of the required ones.
OPTIONAL_KEYS = {
    "email": {"has_attachments", "attachments", "msg_file"},
    "meeting": {"entry_id", "all_day"},
    "person": {"company", "source", "org", "title", "summary", "status", "verified", "flags"},
    # wiki pages (wiki.md): the keys the code keeps in every page's frontmatter
    "wiki": {"type", "title", "aliases", "summary", "status", "owner", "org", "due", "created", "updated", "verified", "sources", "open_items", "flags", "created_by", "domains", "last_done",
             "outcome", "decided", "by", "superseded_by", "reversal", "options_rejected", "links", "risks"},
}

# Which note types each view may reference (a view over several folders may use keys of each).
VIEW_TYPES = {
    "People": ("person",),
    "Follow-ups": ("email", "meeting"),
    "Meetings": ("meeting",),
    "Emails": ("email",),
    "Wiki": ("person", "wiki"),
}

KNOWN_FILE_PROPS = {
    "file.name", "file.path", "file.folder", "file.ext", "file.size", "file.ctime",
    "file.mtime", "file.links", "file.tags",
}


def view_path(name: str):
    return store.VIEWS_DIR / f"{name}.base"


def allowed_note_keys(view: str) -> set[str]:
    keys: set[str] = set()
    for t in VIEW_TYPES[view]:
        if t in notes.SCHEMAS:
            keys.update(notes.SCHEMAS[t]["required"])
        keys.update(OPTIONAL_KEYS.get(t, set()))
    return keys


def parse_simple_yaml(text: str) -> dict:
    """Small indentation-based reader for the subset used in .base files:
    mappings, block lists, scalars. Enough to check structure without pyyaml."""

    def strip_scalar(s: str):
        s = s.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
            return s[1:-1]
        return s

    lines = [(len(l) - len(l.lstrip(" ")), l.strip()) for l in text.splitlines() if l.strip()]

    def parse_block(i: int, indent: int):
        if lines[i][1].startswith("- "):
            out_list = []
            while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
                item = lines[i][1][2:]
                if re.match(r"^[A-Za-z_.\-]+:(\s|$)", item) and not item.startswith(("'", '"')):
                    # a mapping that starts on the "- " line
                    key, _, val = item.partition(":")
                    sub: dict = {}
                    if val.strip():
                        sub[key.strip()] = strip_scalar(val)
                        i += 1
                    else:
                        child, i = parse_block(i + 1, lines[i + 1][0])
                        sub[key.strip()] = child
                    while i < len(lines) and lines[i][0] == indent + 2 and not lines[i][1].startswith("- "):
                        k, _, v = lines[i][1].partition(":")
                        if v.strip():
                            sub[k.strip()] = strip_scalar(v)
                            i += 1
                        else:
                            child, i = parse_block(i + 1, lines[i + 1][0])
                            sub[k.strip()] = child
                    out_list.append(sub)
                else:
                    out_list.append(strip_scalar(item))
                    i += 1
            return out_list, i
        out: dict = {}
        while i < len(lines) and lines[i][0] == indent and not lines[i][1].startswith("- "):
            key, _, val = lines[i][1].partition(":")
            if val.strip():
                out[key.strip()] = strip_scalar(val)
                i += 1
            else:
                child, i = parse_block(i + 1, lines[i + 1][0])
                out[key.strip()] = child
        return out, i

    data, end = parse_block(0, 0)
    assert end == len(lines), "indentation does not line up"
    return data


@pytest.fixture(params=VIEW_NAMES)
def view(request):
    name = request.param
    text = view_path(name).read_text(encoding="utf-8")
    return name, text, parse_simple_yaml(text)


def test_views_dir_has_exactly_the_shipped_files():
    names = sorted(p.stem for p in store.VIEWS_DIR.glob("*.base"))
    assert names == sorted(VIEW_NAMES)


def test_no_tabs_and_even_indentation(view):
    _name, text, _ = view
    assert "\t" not in text
    for line in text.splitlines():
        indent = len(line) - len(line.lstrip(" "))
        assert indent % 2 == 0, line


def test_top_level_keys(view):
    name, _text, data = view
    assert "filters" in data and "views" in data, name
    assert set(data) <= {"filters", "formulas", "properties", "views"}, name
    assert isinstance(data["views"], list) and data["views"], name


def test_global_filter_stays_inside_soma(view):
    name, _text, data = view
    conds = data["filters"]["and"]
    assert any(isinstance(c, str) and c.startswith('file.inFolder("Soma') for c in conds), name


def test_every_view_is_a_named_table(view):
    name, _text, data = view
    for v in data["views"]:
        assert v["type"] == "table", name
        assert v["name"], name
        assert set(v) <= {"type", "name", "filters", "order", "sort", "groupBy", "limit"}, (name, set(v))
        assert isinstance(v["order"], list) and v["order"], (name, v["name"])
        for s in v.get("sort", []):
            assert set(s) == {"property", "direction"}, (name, v["name"])
            assert s["direction"] in ("ASC", "DESC")
        if "groupBy" in v:
            assert set(v["groupBy"]) == {"property", "direction"}, (name, v["name"])


def test_note_references_exist_in_schemas(view):
    name, text, _ = view
    allowed = allowed_note_keys(name)
    used = set(re.findall(r"\bnote\.([A-Za-z_]+)", text))
    assert used <= allowed, (name, used - allowed)


def test_formula_references_are_declared(view):
    name, text, data = view
    declared = set(data.get("formulas", {}))
    used = set(re.findall(r"\bformula\.([A-Za-z_]+)", text))
    assert used <= declared, (name, used - declared)
    assert declared <= used, (name, declared - used)  # no dead formulas


def test_file_references_are_known(view):
    name, text, _ = view
    used = set(re.findall(r"\bfile\.[A-Za-z]+", text))
    methods = {"file.inFolder"}
    assert used <= KNOWN_FILE_PROPS | methods, (name, used - KNOWN_FILE_PROPS - methods)


def test_property_display_names_point_at_used_columns(view):
    name, _text, data = view
    props = set(data.get("properties", {}))
    columns = {c for v in data["views"] for c in v["order"]}
    columns |= {v["groupBy"]["property"] for v in data["views"] if "groupBy" in v}
    assert props <= columns, (name, props - columns)


def test_quotes_balanced_per_line(view):
    name, text, _ = view
    for line in text.splitlines():
        assert line.count('"') % 2 == 0, (name, line)
        assert line.count("'") % 2 == 0, (name, line)


def test_pyyaml_agrees_when_available(view):
    yaml = pytest.importorskip("yaml")
    name, text, data = view
    ref = yaml.safe_load(text)
    assert set(ref) == set(data), name
    assert [v["name"] for v in ref["views"]] == [v["name"] for v in data["views"]], name


def test_vault_init_ships_the_views(tmp_path, monkeypatch):
    root = tmp_path / "My Vault"
    root.mkdir()
    monkeypatch.setenv("SOMA_VAULT", str(root))
    result = store.init(created_by="soma/0.0.4")
    for name in VIEW_NAMES:
        rel = f"Soma/_views/{name}.base"
        assert rel in result["created"]
        assert (root / rel).read_text(encoding="utf-8") == view_path(name).read_text(encoding="utf-8")
    assert not (root / ".obsidian").exists()
