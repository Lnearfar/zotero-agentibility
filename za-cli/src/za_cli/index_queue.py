from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .errors import CliError

_ITEM_KEY = re.compile(r"^[A-Z0-9]{8}$")
_QUEUE_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IndexQueue:
    def __init__(self, index_path: Path):
        self.root = Path(index_path) / "queue"
        self.pending = self.root / "pending"
        self.failed = self.root / "failed"
        self.worker_lock = self.root / "worker.lock"
        self.active = self.root / "active"

    def _directories(self) -> None:
        self.pending.mkdir(parents=True, exist_ok=True)
        self.failed.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        directory_fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def enqueue(self, item_keys: Iterable[str], *, reason: str = "cli") -> dict[str, Any]:
        keys = list(dict.fromkeys(item_keys))
        if not keys:
            raise CliError("ITEM_REQUIRED", "Provide at least one Zotero Item Key")
        invalid = [key for key in keys if not _ITEM_KEY.fullmatch(key)]
        if invalid:
            raise CliError("INVALID_ITEM_KEY", f"Invalid Zotero Item Key: {invalid[0]}")
        self._directories()
        for key in keys:
            event = {
                "version": _QUEUE_VERSION,
                "item_key": key,
                "enqueued_at": _now(),
                "reason": reason,
            }
            fd, temporary = tempfile.mkstemp(prefix=".event-", suffix=".tmp", dir=self.pending)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(event, handle, ensure_ascii=False, separators=(",", ":"))
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                Path(temporary).replace(self.pending / f"{uuid.uuid4().hex}.json")
                self._fsync_directory(self.pending)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
        return {"queued": True, "item_keys": keys, "events": len(keys)}

    def _read_event(self, path: Path) -> dict[str, Any]:
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CliError("INVALID_QUEUE_EVENT", f"Unreadable queue event: {path.name}") from exc
        if not isinstance(event, dict):
            raise CliError("INVALID_QUEUE_EVENT", f"Invalid queue event: {path.name}")
        key = event.get("item_key")
        if event.get("version") != _QUEUE_VERSION or not isinstance(key, str) or not _ITEM_KEY.fullmatch(key):
            raise CliError("INVALID_QUEUE_EVENT", f"Invalid queue event: {path.name}")
        return event

    def _events(self) -> list[Path]:
        return sorted(self.pending.glob("*.json")) if self.pending.is_dir() else []

    def _worker_running(self) -> bool:
        if not self.worker_lock.exists():
            return False
        fd = os.open(self.worker_lock, os.O_RDWR)
        with os.fdopen(fd, "r+") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return False

    def runtime_status(self) -> dict[str, Any]:
        running = self._worker_running()
        return {"worker_running": running, "refreshing": running and self.active.exists()}

    def status(self) -> dict[str, Any]:
        events = self._events()
        keys = set()
        invalid = 0
        for path in events:
            try:
                keys.add(self._read_event(path)["item_key"])
            except CliError:
                invalid += 1
        failed = len(list(self.failed.glob("*.json"))) if self.failed.is_dir() else 0
        return {
            "pending_events": len(events),
            "pending_items": len(keys),
            "invalid_events": invalid,
            "failed_events": failed,
            **self.runtime_status(),
        }

    def work_once(self, semantic_index, db, data_dir: Path, *, limit: int = 100) -> dict[str, Any]:
        self._directories()
        snapshots: dict[str, list[Path]] = {}
        quarantined = 0
        for path in self._events():
            try:
                key = self._read_event(path)["item_key"]
            except CliError:
                path.replace(self.failed / path.name)
                self._fsync_directory(self.pending)
                self._fsync_directory(self.failed)
                quarantined += 1
                continue
            if key not in snapshots and len(snapshots) >= limit:
                continue
            snapshots.setdefault(key, []).append(path)
        keys = sorted(snapshots)
        if not keys:
            return {
                "processed_items": 0,
                "acknowledged_items": 0,
                "pending_items": self.status()["pending_items"],
                "quarantined_events": quarantined,
                "report": None,
            }

        self.active.write_text(json.dumps({"item_keys": keys}, separators=(",", ":")), encoding="utf-8")
        try:
            report = semantic_index.update(db, data_dir, item_keys=keys)
        finally:
            try:
                self.active.unlink()
            except FileNotFoundError:
                pass
        failed_keys = {
            str(error.get("item_key"))
            for error in report.get("errors", [])
            if error.get("item_key")
        }
        acknowledged = 0
        removed_events = False
        for key, paths in snapshots.items():
            if key in failed_keys:
                continue
            acknowledged += 1
            for path in paths:
                try:
                    path.unlink()
                    removed_events = True
                except FileNotFoundError:
                    pass
        if removed_events:
            self._fsync_directory(self.pending)
        return {
            "processed_items": len(keys),
            "acknowledged_items": acknowledged,
            "pending_items": self.status()["pending_items"],
            "quarantined_events": quarantined,
            "report": report,
        }

    @contextmanager
    def worker(self):
        self._directories()
        fd = os.open(self.worker_lock, os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "r+") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise CliError("CONCURRENT_WORKER", "Another index worker is already running") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def run(self, semantic_index, db, data_dir: Path, *, poll_seconds: float = 5) -> None:
        delay = poll_seconds
        with self.worker():
            while True:
                try:
                    result = self.work_once(semantic_index, db, data_dir)
                except Exception as error:
                    print(json.dumps({
                        "code": getattr(error, "code", "INDEX_WORKER_ERROR"),
                        "message": str(error),
                    }, ensure_ascii=False, separators=(",", ":")), file=sys.stderr, flush=True)
                    time.sleep(delay)
                    delay = min(delay * 2, 300)
                    continue
                if result["acknowledged_items"] < result["processed_items"]:
                    print(json.dumps({
                        "code": "INDEX_PARTIAL",
                        "errors": (result.get("report") or {}).get("errors", []),
                    }, ensure_ascii=False, separators=(",", ":")), file=sys.stderr, flush=True)
                    time.sleep(delay)
                    delay = min(delay * 2, 300)
                else:
                    delay = poll_seconds
                    if result["processed_items"] == 0:
                        time.sleep(poll_seconds)
