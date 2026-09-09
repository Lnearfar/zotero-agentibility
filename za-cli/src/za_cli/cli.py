from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import click

from . import __version__
from .bridge import BridgeClient, PROTOCOL, token_status
from .config import RuntimeConfig, build_config
from .db import Database
from .errors import CliError
from .http import probes, require_local_api
from . import sources


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _config(ctx: click.Context) -> RuntimeConfig:
    return ctx.find_root().obj["config"]


def _human(data: Any) -> None:
    if isinstance(data, str):
        click.echo(data)
    elif isinstance(data, dict) and "entries" in data and "path" in data:
        click.echo(data["path"])
        for entry in data["entries"]:
            marker = "C" if entry["kind"] == "collection" else "I"
            click.echo(f"[{marker}] {entry['name']}  {entry['key']}")
        click.echo(f"{data['offset'] + len(data['entries'])}/{data['total']}")
    elif isinstance(data, dict) and "matches" in data:
        for match in data["matches"]:
            click.echo(f"{match['location']}: {match['text']}")
        click.echo(f"{len(data['matches'])}/{data['total']} matches")
    elif isinstance(data, dict) and "results" in data and "query" in data:
        for match in data["results"]:
            location = match.get("provenance", {}).get("location", "unknown location")
            click.echo(f"[{match['item_key']}, {location}] {match['similarity_score']:.4f}")
            click.echo(match["matched_passage"])
        click.echo(f"{len(data['results'])}/{data['total_found']} results")
    elif isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                click.echo(f"{key}: {_json(value)}")
            elif value is not None:
                click.echo(f"{key}: {value}")
    elif isinstance(data, list):
        for value in data:
            click.echo(value if isinstance(value, str) else _json(value))
    else:
        click.echo(str(data))


def emit(ctx: click.Context, data: Any, *, ok: bool = True, code: str = "OK") -> None:
    if _config(ctx).json_output:
        click.echo(_json({"ok": ok, "code": code, "data": data}))
    else:
        _human(data)


def emit_error(ctx: click.Context, error: CliError) -> None:
    if _config(ctx).json_output:
        payload: dict[str, Any] = {"ok": False, "code": error.code, "error": {"message": error.message}}
        if error.details is not None:
            payload["error"]["details"] = error.details
        click.echo(_json(payload), err=True)
    else:
        click.echo(f"error[{error.code}]: {error.message}", err=True)
        if error.details is not None:
            click.echo(_json(error.details), err=True)


class RootGroup(click.Group):
    def invoke(self, ctx: click.Context) -> Any:
        try:
            return super().invoke(ctx)
        except CliError as error:
            emit_error(ctx, error)
            ctx.exit(error.exit_code)
        except (click.ClickException, click.exceptions.Exit):
            raise
        except Exception as exc:
            error = CliError("INTERNAL_ERROR", str(exc) or type(exc).__name__)
            emit_error(ctx, error)
            ctx.exit(1)


@click.group(cls=RootGroup, epilog="Run 'za-cli COMMAND --help' for command options.")
@click.option("--json", "json_output", is_flag=True, help="Emit compact JSON.")
@click.version_option(__version__, prog_name="za-cli")
@click.pass_context
def cli(ctx: click.Context, json_output: bool) -> None:
    """Local Zotero retrieval, document intake, and confirmed writes.

    Installed command help is the command reference. Use COMMAND --help, then
    COMMAND SUBCOMMAND --help for grouped operations. Unsupported operations
    are not implied by roadmap documentation.

    Put --json before the command for machine-readable output. Responses carry
    ok, code, and data or error; a nonzero exit does not necessarily mean a write
    was rolled back. read --all emits raw text even with --json.

    Writes require --confirm and operate in My Library through the running
    Zotero Extension. Omitting --confirm returns CONFIRMATION_REQUIRED, not a
    preview or dry run. WRITE_OUTCOME_UNKNOWN means inspect Zotero before any
    retry; an audit or index warning may follow an already committed write.

    Start retrieval directly; doctor and index maintenance are not prerequisites.
    search reads the semantic index; ls and lookup do not depend on that index.
    """
    ctx.ensure_object(dict)
    ctx.obj["config"] = build_config(json_output)


def _database(ctx: click.Context) -> Database:
    root = ctx.find_root()
    cached = root.obj.get("database")
    if cached is None:
        config = _config(ctx)
        require_local_api(config.port)
        cached = Database(config.data_dir / "zotero.sqlite")
        cached.schema_check()
        root.obj["database"] = cached
    return cached


def _semantic_index(ctx: click.Context):
    from .semantic import SemanticIndex, default_index_path

    config = _config(ctx)
    return SemanticIndex(default_index_path(config.data_dir))


def _index_queue(ctx: click.Context):
    from .index_queue import IndexQueue
    from .semantic import default_index_path

    return IndexQueue(default_index_path(_config(ctx).data_dir))


def _index_catalog(ctx: click.Context):
    from .catalog import LiveCatalog

    config = _config(ctx)
    return LiveCatalog(BridgeClient(config.port, config.config_dir / "bridge-token"))


def _queue_index_after_mutation(
    ctx: click.Context, item_key: str, queue=None, *, reason: str = "fulltext-mutation"
) -> dict[str, Any]:
    try:
        result = (queue or _index_queue(ctx)).enqueue([item_key], reason=reason)
        return {"ok": True, **result}
    except Exception as error:
        return {
            "ok": False,
            "error": {
                "code": getattr(error, "code", "INDEX_QUEUE_FAILED"),
                "message": str(error),
            },
        }


def _run_fulltext_write(ctx: click.Context, db: Database, item_key: str, write) -> None:
    try:
        result = write()
    except CliError as error:
        if error.code != "AUDIT_LOG_FAILED_AFTER_WRITE":
            raise
        details = error.details or {}
        emit(ctx, {
            "itemKey": item_key,
            "status": "committed_with_warning",
            "errorCode": error.code,
            "markdownAttachmentKey": details.get("markdown_attachment_key"),
            "trashedAttachmentKeys": details.get("trashed_attachment_keys", []),
            "index": _queue_index_after_mutation(ctx, item_key),
        }, ok=False, code=error.code)
        ctx.exit(1)
    index_result = _queue_index_after_mutation(ctx, item_key)
    result["index"] = index_result
    if index_result is not None and not index_result["ok"]:
        result["status"] = "committed_with_index_warning"
        emit(ctx, result, ok=False, code="INDEX_UPDATE_FAILED_AFTER_WRITE")
        ctx.exit(1)
    emit(ctx, result)


def _run_add_file_write(ctx: click.Context, write) -> None:
    try:
        result = write()
    except CliError as error:
        if error.code != "AUDIT_LOG_FAILED_AFTER_WRITE":
            raise
        details = error.details or {}
        parent_key = details.get("parent_item_key")
        data: dict[str, Any] = {
            "status": "committed_with_warning",
            "errorCode": error.code,
            "attachment_key": details.get("attachment_key"),
            "parent_item_key": parent_key,
            "collection_key": details.get("collection_key"),
        }
        if parent_key:
            data["index"] = _queue_index_after_mutation(ctx, parent_key, reason="document-add")
        if details.get("outcome") is not None:
            data["outcome"] = details["outcome"]
        emit(ctx, data, ok=False, code=error.code)
        ctx.exit(1)

    result.pop("status", None)
    parent_key = result.get("parent_item_key")
    parent_changed = result.pop("parent_changed", True)
    if parent_key and parent_changed:
        index_result = _queue_index_after_mutation(ctx, parent_key, reason="document-add")
        result["index"] = index_result
        if index_result is not None and not index_result["ok"]:
            result["status"] = "committed_with_index_warning"
            emit(ctx, result, ok=False, code="INDEX_UPDATE_FAILED_AFTER_WRITE")
            ctx.exit(1)
    emit(ctx, result)


def _collection_scope(ctx: click.Context, db: Database, path: str) -> list[str]:
    collection = db.resolve_collection(path, None)
    return db.literature_keys(collection["key"] if collection else None)


@cli.group("app")
def app_group() -> None:
    """Inspect Zotero and required local tools."""


@app_group.command("status", help="Probe Zotero Connector and Local API availability.")
@click.pass_context
def app_status(ctx: click.Context) -> None:
    config = _config(ctx)
    status = probes(config.port)
    status["database"] = {"path": str(config.data_dir / "zotero.sqlite"), "exists": (config.data_dir / "zotero.sqlite").is_file()}
    emit(ctx, status, ok=status["ready"], code="READY" if status["ready"] else "ZOTERO_UNAVAILABLE")
    if not status["ready"]:
        ctx.exit(1)


@app_group.command("doctor")
@click.option("--deep", is_flag=True, help="Also reconcile cached index statistics by scanning Passage metadata.")
@click.pass_context
def app_doctor(ctx: click.Context, deep: bool) -> None:
    """Check connectivity, dependencies, and background index maintenance.

    Checks Zotero, Extension protocol, token, database, Poppler, cached index
    status, and worker heartbeat/errors. DEGRADED exits nonzero; inspect the
    individual checks rather than assuming the library is unavailable.

    Use after a failure, not before ordinary retrieval. --deep scans Passage
    metadata and persists reconciled statistics; it can be slow and does not
    refresh document contents or start the worker.
    """
    config = _config(ctx)
    app = probes(config.port)
    token = token_status(config.config_dir / "bridge-token")
    bridge: dict[str, Any]
    if token["ok"]:
        try:
            health = BridgeClient(config.port, config.config_dir / "bridge-token").health()
            bridge = {
                "ok": health.get("ok") is True and health.get("protocol") == PROTOCOL,
                "protocol": health.get("protocol"),
                "extensionVersion": health.get("extension_version"),
                "cliVersion": __version__,
                "health": health,
            }
        except CliError as exc:
            bridge = {"ok": False, "protocol": None, "error": {"code": exc.code, "message": exc.message}}
    else:
        bridge = {"ok": False, "protocol": None, "error": "safe token unavailable"}
    tools = {name: {"ok": bool(shutil.which(name)), "path": shutil.which(name)} for name in ("pdftotext", "pdfinfo")}
    try:
        index = _semantic_index(ctx).status(deep=True) if deep else _semantic_index(ctx).status()
        index["ok"] = True
    except Exception as error:
        index = {"ok": False, "error": {"code": getattr(error, "code", "INDEX_ERROR"), "message": str(error)}}
    queue = _index_queue(ctx).status()
    index["queue"] = queue
    index["maintenance"] = {
        "ok": queue.get("worker_running") is True and queue.get("fresh") is True and not queue.get("last_error"),
        "worker_running": queue.get("worker_running", False),
        "fresh": queue.get("fresh", False),
        "refreshing": queue.get("refreshing", False),
        "last_error": queue.get("last_error"),
        "pending_items": queue.get("pending_items", 0),
    }
    database = {"ok": False, "path": str(config.data_dir / "zotero.sqlite")}
    if app["ready"]:
        try:
            database = {**Database(config.data_dir / "zotero.sqlite").schema_check(), "path": database["path"]}
        except CliError as exc:
            database["error"] = {"code": exc.code, "message": exc.message}
    checks = {"zotero": app, "database": database, "token": token, "bridge": bridge, "tools": tools, "index": index}
    ready = (
        app["ready"] and database["ok"] and token["ok"] and bridge["ok"]
        and bridge["protocol"] == PROTOCOL and index["ok"]
        and index["maintenance"]["ok"] and all(v["ok"] for v in tools.values())
    )
    emit(ctx, {"ready": ready, "protocol": PROTOCOL, "checks": checks}, ok=ready, code="READY" if ready else "DEGRADED")
    if not ready:
        ctx.exit(1)


@cli.command("ls")
@click.argument("target", required=False)
@click.option("--collection", "collection_key", help="List a Collection by stable key.")
@click.option("--offset", default=0, show_default=True, type=int, help="Skip this many entries.")
@click.option("--limit", default=50, show_default=True, type=int, help="Maximum entries to return.")
@click.pass_context
def ls_command(ctx: click.Context, target: str | None, collection_key: str | None, offset: int, limit: int) -> None:
    """List child Collections and Literature Items.

    Defaults to My Library. TARGET is a Collection path; --collection accepts
    a stable Collection Key instead. Do not supply both. This lists immediate
    entries, not recursive search results, and does not require a semantic index.

    Example: za-cli --json ls --collection COLLECTION_KEY --limit 20
    """
    if target and collection_key:
        raise CliError("INVALID_ARGUMENT", "Use a collection path or --collection, not both")
    db = _database(ctx)
    key = None
    if collection_key:
        collection = db.collection_by_key(collection_key)
        if not collection:
            raise CliError("COLLECTION_NOT_FOUND", f"Collection not found: {collection_key}")
        key = collection["key"]
    elif target:
        collection = db.resolve_collection(target, None)
        key = collection["key"] if collection else None
    result = db.list_entries(key, offset=offset, limit=limit)
    emit(ctx, result)


@cli.command("lookup", help="Show metadata for a Literature Item.")
@click.argument("item_key")
@click.pass_context
def lookup(ctx: click.Context, item_key: str) -> None:
    emit(ctx, _database(ctx).lookup(item_key))


@cli.command("source")
@click.argument("item_key")
@click.pass_context
def source_command(ctx: click.Context, item_key: str) -> None:
    """Show the selected Markdown Full Text or fallback document.

    Selection order: one canonical child tagged za-cli:md, one PDF tagged
    za-cli:pdf, or a sole PDF/EPUB. Canonical Markdown must be stored as
    fulltext.md with title 'Markdown Full Text'; it remains preferred even
    after PDF changes. Invalid or multiple marked sources are errors, not
    reasons to silently choose another attachment.

    Reports the attachment key, path, format, and file existence without
    indexing. A sole EPUB can be reported, but read/find cannot extract it.
    Notes, Annotations, and unmarked Markdown are not canonical Full Text.
    """
    config = _config(ctx)
    emit(ctx, sources.resolve_for_item(_database(ctx), item_key, config.data_dir))


@cli.command("read")
@click.argument("item_key")
@click.option("--start", default=1, show_default=True, type=int, help="First source line to read.")
@click.option("--limit", default=200, show_default=True, type=int, help="Maximum source lines to read.")
@click.option("--all", "all_text", is_flag=True, help="Emit untruncated raw full text.")
@click.pass_context
def read_command(ctx: click.Context, item_key: str, start: int, limit: int, all_text: bool) -> None:
    """Read bounded lines from the selected Markdown or PDF source.

    Uses the selection rules in source --help, without the semantic index.
    --start is a 1-based line number, not a PDF page number. JSON includes
    source identity, content, location, and nextStart for continuation.
    PDF extraction requires Poppler; scanned documents may require external
    OCR. EPUB returns UNSUPPORTED_SOURCE_FORMAT.

    --all ignores line bounds and writes raw full text, even with --json.
    The calling tool may still truncate that output. Prefer bounded reads.

    Example: za-cli --json read ITEM_KEY --start 1 --limit 40
    """
    config = _config(ctx)
    source = sources.resolve_for_item(_database(ctx), item_key, config.data_dir)
    result = sources.read_source(source, start=start, limit=limit, all_text=all_text)
    if all_text:
        sys.stdout.write(result["content"])
        return
    if config.json_output:
        emit(ctx, result)
    else:
        click.echo(result["content"], nl=False)
        click.echo(f"\n[{item_key}, {result['attachmentKey']}, {result['location']}]", err=True)


@cli.command("find")
@click.argument("item_key")
@click.argument("query")
@click.option("--context", default=0, show_default=True, type=int, help="Surrounding lines per match.")
@click.option("--limit", default=20, show_default=True, type=int, help="Maximum matches to return.")
@click.pass_context
def find_command(ctx: click.Context, item_key: str, query: str, context: int, limit: int) -> None:
    """Find literal text in the selected Markdown or PDF source.

    Case-insensitive substring matching within individual lines, not regex or
    semantic search. Uses source selection without an index; EPUB is unsupported.
    Returns matching lines and source locations, including PDF page numbers.
    --limit bounds returned matches, not the amount of source text scanned.

    Example: za-cli --json find ITEM_KEY "exact phrase" --context 3
    """
    config = _config(ctx)
    source = sources.resolve_for_item(_database(ctx), item_key, config.data_dir)
    emit(ctx, sources.lexical_find(source, query, limit=limit, context=context))


@cli.group("index")
def index_group() -> None:
    """Update and inspect the local semantic Passage index.

    The Zotero Extension owns automatic indexing: it starts/stops the worker,
    queues changed Items, and schedules reconciliation. Agentibility Console
    shows lifecycle, queue, errors, and selected-Item coverage.

    Ordinary retrieval should not wait for maintenance. Use status to diagnose
    missing recent results, refresh to enqueue known Items, and update only
    when synchronous maintenance is explicitly needed. Do not launch a second
    worker or restore a separate systemd supervisor.
    """


@index_group.command("update")
@click.option("--force", is_flag=True, help="Rebuild selected records even when unchanged.")
@click.option("--item", "item_keys", multiple=True, help="Update only this Literature Item; repeatable.")
@click.option("--collection", help="Update only an explicit Collection path and descendants.")
@click.pass_context
def index_update(
    ctx: click.Context, force: bool, item_keys: tuple[str, ...], collection: str | None
) -> None:
    """Synchronously update changed semantic Passages.

    With no scope, updates the full library and initializes a missing index.
    Use repeatable --item keys or --collection PATH (including descendants),
    not both. Requires the running Extension's native catalog. Unchanged
    sources are skipped unless --force is given.

    Waits for extraction and embedding. INDEX_PARTIAL exits nonzero and reports
    per-item errors; successful Items remain indexed. Does not acknowledge
    existing refresh queue events. Prefer index refresh for asynchronous work.
    """
    if item_keys and collection:
        raise CliError("INVALID_ARGUMENT", "Use --collection or --item, not both")
    config = _config(ctx)
    selected_keys = _collection_scope(ctx, _database(ctx), collection) if collection else (list(item_keys) or None)
    result = _semantic_index(ctx).update(
        _index_catalog(ctx), config.data_dir, force=force, item_keys=selected_keys, show_progress=True
    )
    errors = result.get("errors", [])
    emit(ctx, result, ok=not errors, code="OK" if not errors else "INDEX_PARTIAL")
    if errors:
        ctx.exit(1)


@index_group.command("reconcile")
@click.pass_context
def index_reconcile(ctx: click.Context) -> None:
    """Reconcile the full library and emit a compact maintenance report.

    Synchronously updates changed sources and removes obsolete index records.
    Per-item coverage errors are summarized by code: INDEX_PARTIAL with ok=true
    and exit 0 means maintenance completed with incomplete coverage. Command
    failures still exit nonzero. Unlike index update, partial coverage alone
    is not a failed command. Automatic reconciliation belongs to the worker.
    """
    config = _config(ctx)
    report = _semantic_index(ctx).update(_index_catalog(ctx), config.data_dir)
    counts: dict[str, int] = {}
    for error in report.get("errors", []):
        code = str(error.get("code") or "INDEX_WRITE_FAILED")
        counts[code] = counts.get(code, 0) + 1
    result = {key: value for key, value in report.items() if key != "errors"}
    result["errors"] = {"count": sum(counts.values()), "by_code": counts}
    emit(ctx, result, code="OK" if not counts else "INDEX_PARTIAL")


@index_group.command("status")
@click.option("--deep", is_flag=True, help="Reconcile cached statistics by scanning Passage metadata.")
@click.pass_context
def index_status(ctx: click.Context, deep: bool) -> None:
    """Show semantic index readiness, cached coverage, and refresh queue.

    Reads persisted statistics by default, without scanning Passage metadata.
    --deep scans and persists reconciled statistics; it does not re-extract
    sources. A running idle worker is not actively refreshing. Queued Items
    are not necessarily indexed yet; inspect item errors and Console status.
    """
    result = _semantic_index(ctx).status(deep=True) if deep else _semantic_index(ctx).status()
    result["queue"] = _index_queue(ctx).status()
    emit(ctx, result)


@index_group.command("refresh")
@click.option("--item", "item_keys", multiple=True, required=True, help="Literature Item to refresh; repeatable.")
@click.pass_context
def index_refresh(ctx: click.Context, item_keys: tuple[str, ...]) -> None:
    """Queue selected Literature Items for background indexing.

    Durably enqueues repeatable parent Item Keys and returns immediately.
    Success means queued, not indexed; it neither starts a worker nor waits
    for embedding. The Extension-owned worker processes the queue.

    Use for explicit freshness or to retry INDEX_UPDATE_FAILED_AFTER_WRITE
    without repeating an already committed Zotero write.

    Example: za-cli --json index refresh --item ITEM_KEY
    """
    keys = list(dict.fromkeys(item_keys))
    emit(ctx, _index_queue(ctx).enqueue(keys, reason="explicit-refresh"))


@index_group.command("worker")
@click.option("--managed", is_flag=True, help="Run the extension-owned managed stdin runtime.")
@click.option("--data-dir", type=click.Path(path_type=Path), help="Zotero data directory supplied by the Extension.")
@click.option("--port", type=click.IntRange(1, 65535), help="Live Zotero HTTP port supplied by the Extension.")
@click.option("--config-dir", type=click.Path(path_type=Path), help="Bridge configuration directory supplied by the Extension.")
@click.option("--once", is_flag=True, help="Process one bounded queued batch and exit.")
@click.option("--poll-seconds", default=5.0, show_default=True, type=click.FloatRange(min=0.1),
              help="Managed status heartbeat interval.")
@click.option("--retry-seconds", type=click.FloatRange(min=0.1), help="Failed-item retry interval supplied by the Extension.")
@click.option("--reconcile-seconds", type=click.FloatRange(min=0.1), help="Reconciliation interval supplied by the Extension.")
@click.pass_context
def index_worker(ctx: click.Context, managed: bool, once: bool, poll_seconds: float,
                 data_dir: Path | None, port: int | None, config_dir: Path | None,
                 retry_seconds: float | None, reconcile_seconds: float | None) -> None:
    """Process queued semantic index refreshes.

    Internal lifecycle command, normally started by the Zotero Extension.
    --managed uses NDJSON stdin/stdout and requires runtime settings supplied
    by the Extension, including retry and reconciliation intervals.

    --once processes one bounded batch for manual diagnostics when no worker
    is running. Failed Items remain queued; INDEX_PARTIAL exits nonzero.
    --managed and --once are mutually exclusive; one is required.
    """
    if managed and once:
        raise CliError("INVALID_ARGUMENT", "Use --managed or --once")
    if not managed and not once:
        raise CliError("MANAGED_REQUIRED", "Continuous index worker requires --managed")
    config = _config(ctx)
    config = RuntimeConfig(config.json_output,
                           data_dir.expanduser() if data_dir is not None else config.data_dir,
                           port if port is not None else config.port,
                           config_dir.expanduser() if config_dir is not None else config.config_dir)
    ctx.find_root().obj["config"] = config
    queue = _index_queue(ctx)
    semantic_index = _semantic_index(ctx)
    catalog = _index_catalog(ctx)
    if once:
        with queue.worker():
            result = queue.work_once(semantic_index, catalog, config.data_dir)
        errors = (result.get("report") or {}).get("errors", [])
        emit(ctx, result, ok=not errors, code="OK" if not errors else "INDEX_PARTIAL")
        if errors:
            ctx.exit(1)
        return
    if retry_seconds is None or reconcile_seconds is None:
        raise CliError("RUNTIME_CONFIG_REQUIRED", "Managed workers require --retry-seconds and --reconcile-seconds from index-runtime.json")
    queue.run_managed(semantic_index, catalog, config.data_dir, poll_seconds=poll_seconds,
                      retry_seconds=retry_seconds, reconcile_seconds=reconcile_seconds)


@index_group.command("inspect")
@click.option("--limit", default=20, show_default=True, type=int, help="Maximum records to return.")
@click.option("--filter", "filter_text", help="Case-insensitive title or creator substring.")
@click.option("--documents", "show_documents", is_flag=True, help="Include stored Passage text.")
@click.option("--stats", is_flag=True, help="Include source and item-type counts.")
@click.pass_context
def index_inspect(
    ctx: click.Context, limit: int, filter_text: str | None, show_documents: bool, stats: bool
) -> None:
    """Inspect indexed Passage metadata.

    Diagnostic view of the semantic index, not the Zotero catalog. Unlike quick
    index status, this scans stored records; --limit bounds displayed records.
    --documents includes indexed text, which may lag behind source changes.
    """
    emit(ctx, _semantic_index(ctx).inspect(
        limit=limit, filter_text=filter_text, show_documents=show_documents, stats=stats
    ))


@cli.command("search")
@click.argument("query")
@click.option("--limit", default=10, show_default=True, type=int, help="Maximum Literature Items or Passages.")
@click.option("--collection", help="Recursively scope to an explicit Collection path.")
@click.option("--item", "item_key", help="Return matching Passages from one Literature Item.")
@click.option("--filters", help="Additional Chroma metadata filter as JSON.")
@click.pass_context
def search_command(
    ctx: click.Context,
    query: str,
    limit: int,
    collection: str | None,
    item_key: str | None,
    filters: str | None,
) -> None:
    """Search indexed Passages by semantic similarity.

    Searches PDF/Markdown contents, not catalog titles or metadata-only Items.
    Defaults to the library index and one best Passage per matching Item;
    --item returns multiple Passages within one Item. --collection takes a
    recursive Collection path and cannot be combined with --item.
    --filters accepts a Chroma metadata JSON object, for example
    '{"item_type":"journalArticle"}'.

    Reads the existing index without refreshing it. Returned index freshness
    describes potentially stale results; no hit does not prove an Item is
    absent from Zotero. Use ls/lookup for catalog inspection and read/find to
    verify source passages before citing them.

    On INDEX_UNINITIALIZED, inspect index status and the Extension Console;
    index update can explicitly initialize it. For known changed Items use
    index refresh --item KEY rather than blocking on a full-library update.

    Example: za-cli --json search "stability proof" --limit 5
    """
    if collection and item_key:
        raise CliError("INVALID_ARGUMENT", "Use --collection or --item, not both")
    parsed_filters = None
    if filters:
        try:
            parsed_filters = json.loads(filters)
        except json.JSONDecodeError as exc:
            raise CliError("INVALID_FILTERS", "--filters must be valid JSON") from exc
        if not isinstance(parsed_filters, dict):
            raise CliError("INVALID_FILTERS", "--filters must be a JSON object")
        if "itemType" in parsed_filters and "item_type" not in parsed_filters:
            parsed_filters["item_type"] = parsed_filters.pop("itemType")

    item_keys = None
    if item_key:
        if not re.fullmatch(r"[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}", item_key):
            raise CliError("INVALID_ITEM_KEY", f"Invalid Zotero Item Key: {item_key}")
        item_keys = [item_key]
    elif collection:
        item_keys = _collection_scope(ctx, _database(ctx), collection)

    result = _semantic_index(ctx).search(
        query,
        limit=limit,
        filters=parsed_filters,
        item_keys=item_keys,
        item_scope=item_key is not None,
    )
    runtime = _index_queue(ctx).runtime_status()
    result.setdefault("index", {})["refreshing"] = runtime["refreshing"]
    emit(ctx, result)


@cli.group("add")
def add_group() -> None:
    """Add local PDF and EPUB documents through Zotero."""


@add_group.command("file")
@click.argument("path", type=click.Path(path_type=Path))
@click.option("--collection", "collection_key", help="Add the imported or reused item to this Collection Key.")
@click.option("--parent", "parent_item_key", help="Attach to this existing Literature Item Key without recognition.")
@click.option("--confirm", is_flag=True, help="Confirm the recoverable Zotero mutation.")
@click.pass_context
def add_file(
    ctx: click.Context,
    path: Path,
    collection_key: str | None,
    parent_item_key: str | None,
    confirm: bool,
) -> None:
    """Add one local PDF or EPUB document.

    Copies a regular, non-symlink local file into Zotero storage, preserving
    the original. File contents must match the PDF/EPUB extension. My Library
    only; no URL download. Native metadata recognition runs unless --parent
    explicitly supplies an existing Literature Item.

    Without --collection, newly created Items are Unfiled; existing membership
    of a reused or explicit parent is preserved. --collection adds membership
    rather than moving the Item out of other Collections.

    Outcomes: added, added_unrecognized (successful standalone import, no
    parent), or reused (identical stored source). Use returned attachment_key
    and parent_item_key, not guessed metadata. Ambiguous identity or a Strong
    Identifier with a different existing source is a conflict; different PDFs
    are not automatically replaced, and fuzzy matches are not merged.

    Parent changes queue indexing without waiting for embedding. An index
    warning after commit must not trigger another import; retry index refresh
    for the returned parent key. WRITE_OUTCOME_UNKNOWN or ROLLBACK_FAILED
    requires inspecting the reported Zotero Items before retrying.

    Requires --confirm; omitting it is not a preview.
    Example: za-cli --json add file /path/to/paper.pdf --confirm
    """
    if not confirm:
        raise CliError("CONFIRMATION_REQUIRED", "Pass --confirm to add a local document")
    config = _config(ctx)
    db = _database(ctx)
    snapshot = sources.add_file_snapshot(db, path, collection_key, parent_item_key)
    _run_add_file_write(
        ctx,
        lambda: BridgeClient(config.port, config.config_dir / "bridge-token").add_file(
            library_id=snapshot["libraryID"],
            source_path=snapshot["sourcePath"],
            expected_sha256=snapshot["expectedSha256"],
            collection_key=snapshot["collectionKey"],
            parent_item_key=snapshot["parentItemKey"],
        ),
    )


@cli.command("resolve")
@click.argument("attachment_key")
@click.option("--markdown", "markdown_path", type=click.Path(path_type=Path), help="Reviewed Markdown fallback for identifier lookup.")
@click.option("--confirm", is_flag=True, help="Confirm the recoverable Zotero mutation.")
@click.pass_context
def metadata_resolve(
    ctx: click.Context,
    attachment_key: str,
    markdown_path: Path | None,
    confirm: bool,
) -> None:
    """Create a verified parent item for a standalone PDF or EPUB.

    ATTACHMENT_KEY identifies an existing parentless document in My Library,
    not a local file or a Literature Item. Invokes Zotero's native recognizer.
    --markdown supplies reviewed local Markdown for identifier-based metadata
    lookup only if native recognition fails; it does not import Full Text.
    The fallback requires an unambiguous Strong Identifier and matching title.

    On success, use returned parent_item_key for subsequent fulltext import.
    METADATA_UNRESOLVED is not permission to invent metadata or a title-only
    parent. Recognition may contact external metadata services.

    Requires --confirm, not a dry run. A committed audit warning is not a
    rollback; inspect unknown write outcomes before retrying.

    Example: za-cli --json resolve ATTACHMENT_KEY --confirm
    """
    if not confirm:
        raise CliError("CONFIRMATION_REQUIRED", "Pass --confirm to resolve document metadata")
    config = _config(ctx)
    snapshot = sources.metadata_resolution_snapshot(
        _database(ctx), attachment_key, config.data_dir, markdown_path
    )
    try:
        result = BridgeClient(config.port, config.config_dir / "bridge-token").metadata_resolve(
            attachment_key=snapshot["attachmentKey"],
            expected_path=snapshot["expectedPath"],
            expected_sha256=snapshot["expectedSha256"],
            markdown_path=snapshot["markdownPath"],
            markdown_sha256=snapshot["markdownSha256"],
        )
    except CliError as error:
        if error.code != "AUDIT_LOG_FAILED_AFTER_WRITE":
            raise
        details = error.details or {}
        emit(ctx, {
            "attachment_key": attachment_key,
            "parent_item_key": details.get("parent_item_key"),
            "status": "committed_with_warning",
            "errorCode": error.code,
        }, ok=False, code=error.code)
        ctx.exit(1)
    emit(ctx, result)


@cli.group("fulltext")
def fulltext_group() -> None:
    """Audit, import, and safely adopt canonical Markdown Full Text.

    Canonical Full Text is a stored child named fulltext.md, titled
    'Markdown Full Text', and tagged za-cli:md. It takes precedence over PDFs
    for reading and semantic indexing. Notes and derived summaries are not
    Full Text. PDF/OCR conversion and review happen outside this CLI.

    import copies a local Markdown file; adopt copies an existing child
    attachment and trashes its old attachment; audit/migrate handle reviewed
    batches. Writes require --confirm and never permanently purge attachments.
    Successful changes queue indexing without waiting for embedding.

    INDEX_UPDATE_FAILED_AFTER_WRITE means the Zotero write committed: retry
    index refresh --item KEY, not the write. An audit failure after write also
    means committed. On WRITE_OUTCOME_UNKNOWN or ROLLBACK_FAILED, inspect
    reported Items and any orphan attachment before attempting another write.
    """


@fulltext_group.command("audit")
@click.option("--output", type=click.Path(path_type=Path), help="Write the compact read-only manifest.")
@click.pass_context
def fulltext_audit(ctx: click.Context, output: Path | None) -> None:
    """Create a read-only Markdown migration plan.

    Audits existing attachments without changing Zotero. Emits the manifest,
    or writes it to --output and returns a summary. Entries are classified as
    canonical, candidate, unresolved, or excluded. Missing/ambiguous sources
    need review; distill.md and probe_distill.md are excluded.

    Review candidate decisions and exclusions before fulltext migrate. Only
    entries whose candidateClass is 'candidate' are applied, with at most one
    selected attachment per parent. Do not invent missing paths or identities.

    Example: za-cli --json fulltext audit --output migration-plan.json
    """
    config = _config(ctx)
    manifest = sources.fulltext_manifest(_database(ctx), config.data_dir)
    if output:
        sources.write_manifest(output, manifest)
        emit(ctx, {"output": str(output.expanduser().resolve()), "summary": manifest["summary"]})
    else:
        emit(ctx, manifest)


@fulltext_group.command("adopt")
@click.argument("item_key")
@click.argument("markdown_attachment_key")
@click.option("--replace", "replace_keys", multiple=True, help="Explicit marked Full Text attachment to replace.")
@click.option("--confirm", is_flag=True, help="Confirm the recoverable Zotero mutation.")
@click.pass_context
def fulltext_adopt(
    ctx: click.Context,
    item_key: str,
    markdown_attachment_key: str,
    replace_keys: tuple[str, ...],
    confirm: bool,
) -> None:
    """Copy one Markdown attachment into canonical Full Text.

    MARKDOWN_ATTACHMENT_KEY must be an existing Markdown child of ITEM_KEY,
    with an accessible non-symlink file, not distill.md or probe_distill.md.
    Stores a canonical fulltext.md child, then moves the adopted attachment
    and explicitly replaced Full Text attachments to Zotero Trash.

    Supply every other child tagged za-cli:md using repeatable --replace.
    FULLTEXT_CONFLICT reports requiredAttachmentKeys; inspect them and obtain
    approval for replacement. Unrelated Markdown attachments are preserved.
    This is not a PDF conversion or a tag-only operation.

    Requires --confirm; no dry run. Indexing is queued after commit; see
    fulltext --help for committed warnings and unknown-outcome retry rules.

    Example: za-cli --json fulltext adopt ITEM_KEY ATTACHMENT_KEY --confirm
    """
    if not confirm:
        raise CliError("CONFIRMATION_REQUIRED", "Pass --confirm to adopt Markdown Full Text")
    config = _config(ctx)
    db = _database(ctx)
    snapshot = sources.adoption_snapshot(
        db, item_key, markdown_attachment_key, config.data_dir, replace_keys
    )
    _run_fulltext_write(
        ctx, db, item_key,
        lambda: BridgeClient(config.port, config.config_dir / "bridge-token").fulltext_adopt(
            item_key=snapshot["itemKey"],
            attachment_key=snapshot["attachmentKey"],
            expected_path=snapshot["expectedPath"],
            expected_sha256=snapshot["expectedSha256"],
            replace_attachment_keys=snapshot["replaceAttachmentKeys"],
        ),
    )


@fulltext_group.command("import")
@click.argument("item_key")
@click.argument("markdown_path", type=click.Path(path_type=Path))
@click.option("--replace", "replace_keys", multiple=True, help="Explicit marked Full Text attachment to replace.")
@click.option("--confirm", is_flag=True, help="Confirm the recoverable Zotero mutation.")
@click.pass_context
def fulltext_import(
    ctx: click.Context,
    item_key: str,
    markdown_path: Path,
    replace_keys: tuple[str, ...],
    confirm: bool,
) -> None:
    """Import one local Markdown file as canonical Full Text.

    ITEM_KEY is an existing Literature Item. MARKDOWN_PATH must be a regular
    non-symlink .md file, not distill.md or probe_distill.md. Copies it into
    Zotero as fulltext.md while preserving the local original. Conversion and
    review against the PDF are external; referenced image assets are not
    imported, so consult the PDF when figures matter.

    Supply all existing children tagged za-cli:md using repeatable --replace.
    FULLTEXT_CONFLICT reports requiredAttachmentKeys; inspect and approve
    them before replacement. Replaced attachments go to Trash; unrelated
    Markdown is preserved.

    Requires --confirm; no dry run. Indexing is queued after commit; see
    fulltext --help for committed warnings and unknown-outcome retry rules.

    Example: za-cli --json fulltext import ITEM_KEY /path/to/fulltext.md --confirm
    """
    if not confirm:
        raise CliError("CONFIRMATION_REQUIRED", "Pass --confirm to import Markdown Full Text")
    config = _config(ctx)
    db = _database(ctx)
    snapshot = sources.import_snapshot(db, item_key, markdown_path, replace_keys)
    _run_fulltext_write(
        ctx, db, item_key,
        lambda: BridgeClient(config.port, config.config_dir / "bridge-token").fulltext_import(
            item_key=snapshot["itemKey"],
            source_path=snapshot["sourcePath"],
            expected_sha256=snapshot["expectedSha256"],
            replace_attachment_keys=snapshot["replaceAttachmentKeys"],
        ),
    )


@fulltext_group.command("migrate")
@click.argument("plan", type=click.Path(path_type=Path))
@click.option("--confirm", is_flag=True, help="Confirm all selected recoverable Zotero mutations.")
@click.pass_context
def fulltext_migrate(ctx: click.Context, plan: Path, confirm: bool) -> None:
    """Apply reviewed candidate entries from a migration plan.

    PLAN is the JSON manifest from fulltext audit. Review its decisions and
    obtain approval before --confirm. Only candidateClass='candidate' entries
    are selected, at most one per parent. Keys, paths, file identity, and
    replacement selections are revalidated; stale plans require a new audit.
    Uses fulltext adopt semantics, including trashing adopted/replaced
    attachments and queueing indexing. No preview is provided by omitting
    --confirm.

    The batch is not atomic. Ordinary per-item failures allow later entries
    to continue; unknown write outcomes and rollback failures stop the batch.
    Output reports attempted, succeeded, failed, warnings, skipped, and per-item
    results. Partial failures and committed warnings exit nonzero.

    Do not replay the entire plan after an error. Inspect successes, unknown
    outcomes, and any orphanAttachmentKey first. Retry only index refresh for
    committed index warnings; audit/review remaining writes again.

    Example: za-cli --json fulltext migrate migration-plan.json --confirm
    """
    if not confirm:
        raise CliError("CONFIRMATION_REQUIRED", "Pass --confirm to apply a reviewed migration plan")
    config = _config(ctx)
    db = _database(ctx)
    plan_path, candidates = sources.load_migration_candidates(plan, db, config.data_dir)
    bridge = BridgeClient(config.port, config.config_dir / "bridge-token")
    queue = _index_queue(ctx)
    results = []
    succeeded = failed = warnings = unknown = rollback_failed = 0
    for candidate in candidates:
        try:
            result = bridge.fulltext_adopt(
                item_key=candidate["itemKey"],
                attachment_key=candidate["attachmentKey"],
                expected_path=candidate["expectedPath"],
                expected_sha256=candidate["expectedSha256"],
                replace_attachment_keys=candidate["replaceAttachmentKeys"],
            )
            succeeded += 1
            index_result = _queue_index_after_mutation(ctx, candidate["itemKey"], queue)
            if index_result is not None and not index_result["ok"]:
                warnings += 1
            results.append({
                "itemKey": candidate["itemKey"],
                "status": "committed_with_index_warning"
                    if index_result is not None and not index_result["ok"] else "success",
                "markdownAttachmentKey": result.get("markdown_attachment_key"),
                "index": index_result,
            })
        except CliError as error:
            if error.code == "AUDIT_LOG_FAILED_AFTER_WRITE":
                succeeded += 1
                warnings += 1
                results.append({
                    "itemKey": candidate["itemKey"],
                    "status": "committed_with_warning",
                    "errorCode": error.code,
                    "markdownAttachmentKey": (error.details or {}).get("markdown_attachment_key"),
                    "index": _queue_index_after_mutation(ctx, candidate["itemKey"], queue),
                })
                continue
            if error.code == "WRITE_OUTCOME_UNKNOWN":
                unknown += 1
                results.append({
                    "itemKey": candidate["itemKey"],
                    "status": "outcome_unknown",
                    "errorCode": error.code,
                    "message": error.message,
                })
                break
            if error.code == "ROLLBACK_FAILED":
                failed += 1
                rollback_failed += 1
                results.append({
                    "itemKey": candidate["itemKey"],
                    "status": "rollback_failed",
                    "errorCode": error.code,
                    "orphanAttachmentKey": (error.details or {}).get("attachment_key"),
                })
                break
            failed += 1
            results.append({
                "itemKey": candidate["itemKey"],
                "status": "failed",
                "errorCode": error.code,
                "message": error.message,
            })
    skipped = len(candidates) - len(results)
    summary = {
        "plan": str(plan_path),
        "attempted": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "warnings": warnings,
        "outcomeUnknown": unknown,
        "rollbackFailed": rollback_failed,
        "skipped": skipped,
        "results": results,
    }
    ok = failed == 0 and warnings == 0 and unknown == 0
    code = "OK" if ok else "OUTCOME_UNKNOWN" if unknown else "ROLLBACK_FAILED" if rollback_failed else "PARTIAL_FAILURE" if failed else "COMMITTED_WITH_WARNING"
    emit(ctx, summary, ok=ok, code=code)
    if not ok:
        ctx.exit(1)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        result = cli.main(args=args, prog_name="za-cli", standalone_mode=False)
        return int(result or 0)
    except click.exceptions.Exit as exc:
        return int(exc.exit_code)
    except click.ClickException as exc:
        if "--json" in args:
            click.echo(_json({"ok": False, "code": "USAGE_ERROR", "error": {"message": exc.format_message()}}), err=True)
        else:
            exc.show()
        return int(exc.exit_code)
