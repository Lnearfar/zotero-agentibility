"""Per-agent browsing sessions.

Modified implementation derived in part from cli-anything-zotero at
f621952f3645546573d622440cbf707320f7a35f. Replaced its single shared,
truncate-in-place state file with validated IDs and per-session locked atomic files.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .errors import CliError

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def validate_id(session_id: str) -> str:
    if not _ID.fullmatch(session_id) or session_id in {".", ".."}:
        raise CliError(
            "INVALID_SESSION_ID",
            "Session ID must be 1-64 letters, digits, dots, underscores, or hyphens and start alphanumeric",
        )
    return session_id


def sessions_dir(config_dir: Path) -> Path:
    return config_dir / "sessions"


def session_path(config_dir: Path, session_id: str) -> Path:
    return sessions_dir(config_dir) / f"{validate_id(session_id)}.json"


@contextmanager
def _lock(path: Path, *, exclusive: bool) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = path.with_suffix(".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "r+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_unlocked(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CliError("SESSION_NOT_FOUND", f"Browsing Session does not exist: {path.stem}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise CliError("SESSION_CORRUPT", f"Browsing Session is unreadable: {path.stem}") from exc
    if data.get("id") != path.stem or data.get("collection") is not None and not isinstance(data.get("collection"), str):
        raise CliError("SESSION_CORRUPT", f"Browsing Session has invalid state: {path.stem}")
    return {"id": data["id"], "collection": data.get("collection")}


def load(config_dir: Path, session_id: str) -> dict:
    path = session_path(config_dir, session_id)
    with _lock(path, exclusive=False):
        return _read_unlocked(path)


def save(config_dir: Path, state: dict) -> dict:
    session_id = validate_id(str(state.get("id", "")))
    payload = {"id": session_id, "collection": state.get("collection")}
    if payload["collection"] is not None and not isinstance(payload["collection"], str):
        raise CliError("INVALID_SESSION_STATE", "Collection key must be a string or null")
    path = session_path(config_dir, session_id)
    with _lock(path, exclusive=True):
        fd, temp_name = tempfile.mkstemp(prefix=f".{session_id}.", dir=path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
    return payload


def create(config_dir: Path, session_id: str | None = None) -> dict:
    session_id = validate_id(session_id or secrets.token_hex(8))
    path = session_path(config_dir, session_id)
    with _lock(path, exclusive=True):
        if path.exists():
            raise CliError("SESSION_EXISTS", f"Browsing Session already exists: {session_id}")
        payload = {"id": session_id, "collection": None}
        fd, temp_name = tempfile.mkstemp(prefix=f".{session_id}.", dir=path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
    return payload
