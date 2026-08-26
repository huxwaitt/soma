"""Field selection for tool results.

Every list/search/get tool accepts ``fields=[...]``. When given, each
returned item keeps only those keys (plus ``entry_id``, which is always
kept so the item can still be passed to another tool). Unknown names are
ignored rather than raised, so a caller can ask for a key that only some
shapes carry.
"""

from __future__ import annotations

from typing import Any

ALWAYS_KEEP = ("entry_id",)


def clean_fields(fields: list[str] | None) -> list[str] | None:
    """Normalise ``fields``: strip blanks, drop empties, ``None`` when unset."""
    if not fields:
        return None
    out = [str(f).strip() for f in fields if f is not None and str(f).strip()]
    return out or None


def pick_fields(item: dict[str, Any], fields: list[str] | None) -> dict[str, Any]:
    """Return ``item`` with only ``fields`` (and ``entry_id``) kept."""
    keep = clean_fields(fields)
    if keep is None:
        return item
    wanted = set(keep) | set(ALWAYS_KEEP)
    return {k: v for k, v in item.items() if k in wanted}


def apply_fields(data: dict[str, Any], fields: list[str] | None) -> dict[str, Any]:
    """Apply ``pick_fields`` to ``data["items"]`` when present, else to ``data``."""
    keep = clean_fields(fields)
    if keep is None:
        return data
    items = data.get("items")
    if isinstance(items, list):
        data["items"] = [pick_fields(i, keep) if isinstance(i, dict) else i for i in items]
        data["fields"] = keep
        return data
    return pick_fields(data, keep)
