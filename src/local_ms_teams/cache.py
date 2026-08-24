"""Find, copy and decode the Teams client's local cache.

The new Teams client keeps recent conversations in an IndexedDB (Chromium
LevelDB, V8-serialised values) under its EBWebView profile. The running
client locks those files, so ``take_snapshot`` copies the folder to a temp
dir, decodes the copy with ``ccl_chromium_reader`` and deletes the copy.

Schema mapping follows msteams-local-mcp (KamorionLabs, MIT); the code is
our own. One database per (tenant, user) is named
``Teams:<manager>:react-web-client:<tenantId>:<userObjectId>:<locale>``:
messages sit in ``Teams:replychain-manager:…`` / store ``replychains``,
chat metadata in ``Teams:conversation-manager:…`` / store ``conversations``.

``ccl_chromium_reader`` is imported inside ``_open_indexeddb`` so the server
starts without the ``teams`` extra; tests replace that attribute with a stub.
A module-level snapshot is reused for ``LOCAL_MS_TEAMS_SNAPSHOT_TTL`` seconds
(default 300) so one collect run copies the cache once.
"""

from __future__ import annotations

import collections
import dataclasses
import datetime as dt
import glob
import importlib.util
import os
import pathlib
import shutil
import tempfile
import time
from typing import Any, Callable, Optional

from local_ms_teams import records

ENV_PATH = "LOCAL_MS_TEAMS_LEVELDB"
ENV_TTL = "LOCAL_MS_TEAMS_SNAPSHOT_TTL"
DEFAULT_TTL = 300.0
LEVELDB_NAME = "https_teams.microsoft.com_0.indexeddb.leveldb"
BLOB_NAME = "https_teams.microsoft.com_0.indexeddb.blob"
WINDOWS_GLOB = "Packages/MSTeams_*/LocalCache/Microsoft/MSTeams/EBWebView/*/IndexedDB/" + LEVELDB_NAME
MACOS_GLOB = (
    "Library/Containers/com.microsoft.teams2/Data/Library/Application Support/"
    "Microsoft/MSTeams/EBWebView/*/IndexedDB/" + LEVELDB_NAME
)
STORES = {
    "replychain-manager": "replychains",
    "conversation-manager": "conversations",
}


class TeamsError(Exception):
    """The cache is missing, unreadable or the reader is not installed."""


@dataclasses.dataclass
class Snapshot:
    """Everything decoded from one copy of the cache, as plain dicts."""

    accounts: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    conversations: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    messages: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    taken_at: Optional[str] = None
    path: Optional[str] = None
    skipped: int = 0


# --- finding the cache -------------------------------------------------------


def cache_globs(env: Optional[dict[str, str]] = None) -> list[str]:
    """Candidate glob patterns: the Windows package folder, then the macOS one."""
    env = os.environ if env is None else env
    home = pathlib.Path(env.get("HOME") or env.get("USERPROFILE") or pathlib.Path.home())
    local = env.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
    return [os.path.join(local, WINDOWS_GLOB), str(home / MACOS_GLOB)]


def find_cache(env: Optional[dict[str, str]] = None) -> Optional[str]:
    """The LevelDB folder to read: ``LOCAL_MS_TEAMS_LEVELDB`` when set, else
    the first glob hit that is a folder, else None."""
    env = os.environ if env is None else env
    override = (env.get(ENV_PATH) or "").strip()
    if override:
        return override
    for pattern in cache_globs(env):
        for hit in sorted(glob.glob(pattern)):
            if os.path.isdir(hit):
                return hit
    return None


def blob_dir_for(leveldb_dir: str) -> Optional[str]:
    """The sibling ``.blob`` folder of a ``.leveldb`` folder when it exists."""
    parent, name = os.path.split(os.path.normpath(leveldb_dir))
    if name.endswith(".leveldb"):
        candidate = os.path.join(parent, name[: -len(".leveldb")] + ".blob")
        if os.path.isdir(candidate):
            return candidate
    return None


def reader_installed() -> bool:
    """True when ``ccl_chromium_reader`` (the ``teams`` extra) can be imported."""
    try:
        return importlib.util.find_spec("ccl_chromium_reader") is not None
    except (ImportError, ValueError):
        return False


def _open_indexeddb(leveldb_dir: str, blob_dir: Optional[str] = None) -> Any:
    """Open a copied LevelDB folder with ccl_chromium_reader. Imported here so
    the server starts without the extra; tests replace this attribute."""
    try:
        from ccl_chromium_reader import ccl_chromium_indexeddb
    except ImportError as exc:
        raise TeamsError(
            "ccl_chromium_reader is not installed: run `uv sync --extra teams` in the checkout, then restart Claude Code"
        ) from exc
    if blob_dir:
        return ccl_chromium_indexeddb.WrappedIndexDB(leveldb_dir, blob_dir)
    return ccl_chromium_indexeddb.WrappedIndexDB(leveldb_dir)


# --- decoding ----------------------------------------------------------------


def _database_parts(name: str) -> Optional[tuple[str, dict[str, Any]]]:
    """``Teams:<manager>:react-web-client:<tenant>:<user>:<locale>`` ->
    (manager, account dict) or None for any other database."""
    parts = (name or "").split(":")
    if len(parts) < 5 or parts[0] != "Teams" or parts[1] not in STORES:
        return None
    tenant_id, user_id = parts[-3], parts[-2]
    if not tenant_id or not user_id:
        return None
    return parts[1], {"key": f"{tenant_id}:{user_id}", "tenant_id": tenant_id, "user_id": user_id, "label": ""}


def _label(messages: list[dict[str, Any]]) -> str:
    """Org name seen on the account's own messages, else the most common org."""
    own = collections.Counter(m["sender_org"] for m in messages if m.get("is_self") and m.get("sender_org"))
    if own:
        return own.most_common(1)[0][0]
    every = collections.Counter(m["sender_org"] for m in messages if m.get("sender_org"))
    return every.most_common(1)[0][0] if every else ""


def _walk(db: Any, on_skip: Callable[[], None]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    accounts: dict[str, dict[str, Any]] = {}
    conversations: list[dict[str, Any]] = []
    messages: dict[tuple[str, str, str], dict[str, Any]] = {}

    def bad_record(*_args: Any, **_kwargs: Any) -> None:
        on_skip()

    for meta in db.database_ids:
        found = _database_parts(getattr(meta, "name", "") or "")
        if found is None:
            continue
        manager, account = found
        account = accounts.setdefault(account["key"], account)
        try:
            store = db[meta.dbid_no].get_object_store_by_name(STORES[manager])
        except Exception:
            continue
        try:
            for record in store.iterate_records(bad_deserializer_data_handler=bad_record):
                value = getattr(record, "value", None)
                if not isinstance(value, dict):
                    continue
                if manager == "replychain-manager":
                    for message in records.parse_replychain(value, account):
                        messages[(account["key"], message["chat_id"], message["id"])] = message
                else:
                    conversation = records.parse_conversation(value, account)
                    if conversation is not None:
                        conversations.append(conversation)
        except Exception:
            on_skip()
    return accounts, conversations, list(messages.values())


def take_snapshot(path: str, now: Optional[str] = None) -> Snapshot:
    """Copy the ``.leveldb`` folder (and the sibling ``.blob`` folder when
    present) to a temp dir, decode the copy, delete it."""
    if not path or not os.path.isdir(path):
        raise TeamsError(f"Teams cache folder not found: {path!r}")
    skipped = [0]

    def on_skip() -> None:
        skipped[0] += 1

    tmp = tempfile.mkdtemp(prefix="local-ms-teams-")
    try:
        leveldb_copy = os.path.join(tmp, os.path.basename(os.path.normpath(path)))
        shutil.copytree(path, leveldb_copy)
        blob_copy = None
        blob_src = blob_dir_for(path)
        if blob_src:
            blob_copy = os.path.join(tmp, os.path.basename(blob_src))
            shutil.copytree(blob_src, blob_copy)
        db = _open_indexeddb(leveldb_copy, blob_copy)
        accounts, conversations, messages = _walk(db, on_skip)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    for account in accounts.values():
        account["label"] = _label([m for m in messages if m["account"] == account["key"]])
    messages.sort(key=lambda m: (m["time"] or "", m["chat_id"], m["id"]))
    conversations.sort(key=lambda c: (c["account"], c["id"]))
    taken = now or dt.datetime.now().astimezone().replace(microsecond=0).isoformat()
    return Snapshot(
        accounts=sorted(accounts.values(), key=lambda a: a["key"]),
        conversations=conversations,
        messages=messages,
        taken_at=taken,
        path=path,
        skipped=skipped[0],
    )


# --- the reused snapshot -----------------------------------------------------

_state: dict[str, Any] = {"snapshot": None, "at": 0.0}


def ttl_seconds(env: Optional[dict[str, str]] = None) -> float:
    env = os.environ if env is None else env
    try:
        return max(0.0, float(env.get(ENV_TTL, "") or DEFAULT_TTL))
    except ValueError:
        return DEFAULT_TTL


def snapshot(refresh: bool = False, path: Optional[str] = None) -> Snapshot:
    """The decoded cache, reused for the TTL; ``refresh`` forces a new copy."""
    path = path or find_cache()
    if not path:
        raise TeamsError("Teams cache not found: sign in to the new Teams client once on this machine, or set LOCAL_MS_TEAMS_LEVELDB")
    cached: Optional[Snapshot] = _state["snapshot"]
    age = time.monotonic() - _state["at"]
    if not refresh and cached is not None and cached.path == path and age < ttl_seconds():
        return cached
    fresh = take_snapshot(path)
    _state["snapshot"] = fresh
    _state["at"] = time.monotonic()
    return fresh


def clear() -> None:
    """Drop the reused snapshot (tests, and after an error)."""
    _state["snapshot"] = None
    _state["at"] = 0.0
