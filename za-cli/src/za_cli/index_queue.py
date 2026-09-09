from __future__ import annotations

import fcntl
import json
import os
import re
import signal
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, TextIO

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
        self.runtime = self.root / "runtime-state.json"

    def _directories(self) -> None:
        self.pending.mkdir(parents=True, exist_ok=True)
        self.failed.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _write_json(self, path: Path, value: dict[str, Any]) -> None:
        self._directories()
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            Path(temporary).replace(path)
            self._fsync_directory(path.parent)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def enqueue(self, item_keys: Iterable[str], *, reason: str = "cli") -> dict[str, Any]:
        keys = list(dict.fromkeys(item_keys))
        if not keys:
            raise CliError("ITEM_REQUIRED", "Provide at least one Zotero Item Key")
        invalid = [key for key in keys if not isinstance(key, str) or not _ITEM_KEY.fullmatch(key)]
        if invalid:
            raise CliError("INVALID_ITEM_KEY", f"Invalid Zotero Item Key: {invalid[0]}")
        self._directories()
        for key in keys:
            self._write_json(self.pending / f"{uuid.uuid4().hex}.json", {
                "version": _QUEUE_VERSION, "item_key": key, "enqueued_at": _now(), "reason": reason,
            })
        return {"queued": True, "item_keys": keys, "events": len(keys)}

    def _read_event(self, path: Path) -> dict[str, Any]:
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CliError("INVALID_QUEUE_EVENT", f"Unreadable queue event: {path.name}") from exc
        key = event.get("item_key") if isinstance(event, dict) else None
        if not isinstance(event, dict) or event.get("version") != _QUEUE_VERSION or not isinstance(key, str) or not _ITEM_KEY.fullmatch(key):
            raise CliError("INVALID_QUEUE_EVENT", f"Invalid queue event: {path.name}")
        return event

    def _events(self, directory: Path) -> list[Path]:
        return sorted(directory.glob("*.json")) if directory.is_dir() else []

    def _worker_running(self) -> bool:
        if not self.worker_lock.exists():
            return False
        with self.worker_lock.open("a+") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            return False

    def _runtime_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.runtime.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def runtime_status(self) -> dict[str, Any]:
        state = self._runtime_state()
        heartbeat = state.get("heartbeat")
        fresh = False
        if isinstance(heartbeat, str):
            try:
                fresh = 0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(heartbeat)).total_seconds() < 15
            except (ValueError, TypeError):
                pass
        running = self._worker_running()
        return {
            "worker_running": running,
            "refreshing": running and (self.active.exists() or state.get("phase") == "reconciling"),
            "fresh": fresh,
            "last_error": state.get("last_error"),
            "phase": state.get("phase"),
        }

    def status(self) -> dict[str, Any]:
        events = self._events(self.pending) + self._events(self.failed)
        keys, invalid = set(), 0
        for path in events:
            try:
                keys.add(self._read_event(path)["item_key"])
            except CliError:
                invalid += 1
        return {
            "pending_events": len(events), "pending_items": len(keys), "pending_keys": len(keys),
            "item_keys": sorted(keys),
            "invalid_events": invalid, "failed_events": len(self._events(self.failed)),
            "runtime": self._runtime_state(), **self.runtime_status(),
        }

    def _snapshot(self, limit: int, retry_seconds: float = 0) -> tuple[dict[str, list[Path]], int]:
        snapshots: dict[str, list[Path]] = {}
        quarantined = 0
        # New notifications always win over a retrying failure.
        for directory in (self.pending, self.failed):
            for path in self._events(directory):
                try:
                    key = self._read_event(path)["item_key"]
                except CliError:
                    if path.parent != self.failed:
                        path.replace(self.failed / path.name)
                        quarantined += 1
                    continue
                if directory == self.failed and key not in snapshots and time.time() - path.stat().st_mtime < retry_seconds:
                    continue
                if key not in snapshots and len(snapshots) >= limit:
                    continue
                snapshots.setdefault(key, []).append(path)
        if quarantined:
            self._fsync_directory(self.pending)
            self._fsync_directory(self.failed)
        return snapshots, quarantined

    def work_once(self, semantic_index, catalog, data_dir: Path, *, limit: int = 100, retry_seconds: float = 0) -> dict[str, Any]:
        self._directories()
        snapshots, quarantined = self._snapshot(limit, retry_seconds)
        keys = sorted(snapshots)
        if not keys:
            return {"processed_items": 0, "acknowledged_items": 0, "pending_items": self.status()["pending_items"],
                    "quarantined_events": quarantined, "report": None}
        self._write_json(self.active, {"item_keys": keys, "updated_at": _now()})
        try:
            report = semantic_index.update(catalog, data_dir, item_keys=keys)
        finally:
            try:
                self.active.unlink()
            except FileNotFoundError:
                pass
        failed_keys = {str(error.get("item_key")) for error in report.get("errors", []) if error.get("item_key")}
        acknowledged = 0
        for key, paths in snapshots.items():
            for path in paths:
                if key in failed_keys:
                    if path.parent != self.failed:
                        path.replace(self.failed / path.name)
                    os.utime(self.failed / path.name, None)
                    continue
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            if key not in failed_keys:
                acknowledged += 1
        self._fsync_directory(self.pending)
        self._fsync_directory(self.failed)
        return {"processed_items": len(keys), "item_keys": keys, "acknowledged_items": acknowledged,
                "pending_items": self.status()["pending_items"], "quarantined_events": quarantined, "report": report}

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
                try:
                    self.active.unlink()
                except FileNotFoundError:
                    pass
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def run_managed(self, semantic_index, catalog, data_dir: Path, *, input_stream: TextIO = sys.stdin,
                    output_stream: TextIO = sys.stdout, poll_seconds: float = 5,
                    retry_seconds: float = 30, reconcile_seconds: float = 43200) -> None:
        """Run under the extension; stdin EOF and shutdown both stop it safely."""
        wake = threading.Event()
        stop = threading.Event()
        state_lock = threading.Lock()
        output_lock = threading.Lock()
        state: dict[str, Any] = {
            "phase": "starting", "heartbeat": _now(), "pending_items": 0, "pending_keys": [],
            "active_item_keys": [], "last_error": None, "last_report": None, "last_updated": None,
            "last_reconcile": None, "count": None, "item_count": None, "item_stats": {}, "errors": {},
        }

        def publish(*, force: bool = False) -> None:
            with state_lock:
                queue_status = self.status()
                try:
                    active = json.loads(self.active.read_text(encoding="utf-8")).get("item_keys", [])
                except (OSError, json.JSONDecodeError):
                    active = []
                state.update({"heartbeat": _now(), "pending_items": queue_status["pending_items"],
                              "pending_keys": queue_status["item_keys"], "active_item_keys": active})
                snapshot = dict(state)
            with output_lock:
                self._write_json(self.runtime, snapshot)
                output_stream.write(json.dumps({"event": "status", "state": snapshot}, ensure_ascii=False,
                                               separators=(",", ":")) + "\n")
                output_stream.flush()

        def capture(report: dict[str, Any] | None, *, reconcile: bool = False, item_keys: Iterable[str] = ()) -> None:
            if report is None:
                return
            with state_lock:
                state["last_report"] = report
                state["last_updated"] = _now()
                if reconcile:
                    state["last_reconcile"] = state["last_updated"]
                state["last_error"] = None
                errors = {} if reconcile else dict(state["errors"])
                for key in item_keys:
                    errors.pop(key, None)
                errors.update({str(error.get("item_key")): {
                    "code": str(error.get("code") or "INDEX_WRITE_FAILED"), "message": str(error.get("error") or "")
                } for error in report.get("errors", []) if error.get("item_key")})
                state["errors"] = errors
                try:
                    index_state = semantic_index._state()
                    stats = index_state.get("stats") if isinstance(index_state.get("stats"), dict) else {}
                    state["count"] = stats.get("passages")
                    state["item_count"] = stats.get("items")
                    state["item_stats"] = index_state.get("item_stats") or {}
                except Exception:
                    pass

        def read_stdin() -> None:
            for line in input_stream:
                try:
                    message = json.loads(line)
                    if not isinstance(message, dict) or set(message) - {"operation", "item_keys"}:
                        raise CliError("INVALID_MANAGED_MESSAGE", "Managed worker received an invalid message")
                    operation = message.get("operation")
                    if operation == "enqueue" and set(message) == {"operation", "item_keys"}:
                        keys = message["item_keys"]
                        if not isinstance(keys, list) or len(keys) > 100:
                            raise CliError("INVALID_MANAGED_MESSAGE", "Enqueue requires at most 100 item keys")
                        self.enqueue(keys, reason="extension-notification")
                    elif operation == "shutdown" and set(message) == {"operation"}:
                        break
                    else:
                        raise CliError("INVALID_MANAGED_MESSAGE", "Managed worker received an invalid message")
                except Exception as error:
                    print(json.dumps({"code": getattr(error, "code", "INVALID_MANAGED_MESSAGE"),
                                      "message": str(error)}, separators=(",", ":")), file=sys.stderr, flush=True)
                wake.set()
            stop.set()
            wake.set()

        def heartbeat() -> None:
            try:
                while not stop.wait(poll_seconds):
                    publish()
            except (OSError, ValueError):
                stop.set()
                wake.set()

        def terminate(_signum, _frame) -> None:
            stop.set()
            wake.set()

        reader = threading.Thread(target=read_stdin, name="za-index-stdin", daemon=True)
        ticker = threading.Thread(target=heartbeat, name="za-index-heartbeat", daemon=True)
        with self.worker():
            old_handlers = {number: signal.signal(number, terminate) for number in (signal.SIGTERM, signal.SIGINT)
                            if threading.current_thread() is threading.main_thread()}
            reader.start()
            ticker.start()
            try:
                next_reconcile = 0.0
                while not stop.is_set():
                    if time.monotonic() >= next_reconcile:
                        with state_lock:
                            state.update(phase="reconciling", active_item_keys=[])
                        publish(force=True)
                        try:
                            report = semantic_index.update(catalog, data_dir)
                            capture(report, reconcile=True)
                            with state_lock:
                                state["last_error"] = None
                        except Exception as error:
                            with state_lock:
                                state["last_error"] = {"code": getattr(error, "code", "INDEX_RECONCILE_FAILED"),
                                                       "message": str(error)}
                        next_reconcile = time.monotonic() + (retry_seconds if state["last_error"] else reconcile_seconds)
                        publish(force=True)
                    if stop.is_set():
                        break
                    with state_lock:
                        state.update(phase="indexing", active_item_keys=[])
                    try:
                        result = self.work_once(semantic_index, catalog, data_dir, retry_seconds=retry_seconds)
                        capture(result.get("report"), item_keys=result.get("item_keys", []))
                        if result["processed_items"]:
                            publish(force=True)
                    except Exception as error:
                        with state_lock:
                            state["last_error"] = {"code": getattr(error, "code", "INDEX_WORKER_ERROR"),
                                                   "message": str(error)}
                        publish(force=True)
                    with state_lock:
                        state.update(phase="idle", active_item_keys=[])
                    publish(force=True)
                    wake.wait(poll_seconds)
                    wake.clear()
            finally:
                stop.set()
                ticker.join(timeout=poll_seconds + 1)
                with state_lock:
                    state.update(phase="stopped", active_item_keys=[])
                try:
                    publish(force=True)
                finally:
                    for number, handler in old_handlers.items():
                        signal.signal(number, handler)
