from __future__ import annotations

import json
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
from . import sessions, sources


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
@click.option("--session", "session_id", help="Explicit Browsing Session ID.")
@click.option("--json", "json_output", is_flag=True, help="Emit compact JSON.")
@click.version_option(__version__, prog_name="za-cli")
@click.pass_context
def cli(ctx: click.Context, session_id: str | None, json_output: bool) -> None:
    """Local Zotero navigation, retrieval, and confirmed Full Text import/adoption."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = build_config(session_id, json_output)


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


def _update_index_after_mutation(
    ctx: click.Context, db: Database, item_key: str, semantic_index=None
) -> dict[str, Any] | None:
    semantic_index = semantic_index or _semantic_index(ctx)
    try:
        report = semantic_index.update(db, _config(ctx).data_dir, item_keys=[item_key])
        return {"ok": not bool(report.get("errors")), "report": report}
    except Exception as error:
        return {
            "ok": False,
            "error": {
                "code": getattr(error, "code", "INDEX_UPDATE_FAILED"),
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
            "index": _update_index_after_mutation(ctx, db, item_key),
        }, ok=False, code=error.code)
        ctx.exit(1)
    index_result = _update_index_after_mutation(ctx, db, item_key)
    result["index"] = index_result
    if index_result is not None and not index_result["ok"]:
        result["status"] = "committed_with_index_warning"
        emit(ctx, result, ok=False, code="INDEX_UPDATE_FAILED_AFTER_WRITE")
        ctx.exit(1)
    emit(ctx, result)


def _session(ctx: click.Context) -> dict:
    config = _config(ctx)
    if not config.session_id:
        raise CliError("SESSION_REQUIRED", "Pass --session with an explicit Browsing Session ID")
    return sessions.load(config.config_dir, config.session_id)


def _collection_scope(ctx: click.Context, db: Database, path: str) -> list[str]:
    current_key = None
    if not path.startswith("/") and path != "My Library":
        state, _ = _validated_location(ctx, db, _session(ctx))
        current_key = state.get("collection")
    collection = db.resolve_collection(path, current_key)
    return db.literature_keys(collection["key"] if collection else None)


def _validated_location(ctx: click.Context, db: Database, state: dict) -> tuple[dict, dict | None]:
    key = state.get("collection")
    if not key:
        return state, None
    collection = db.collection_by_key(key)
    if collection:
        return state, None
    state["collection"] = None
    sessions.save(_config(ctx).config_dir, state)
    return state, {"code": "COLLECTION_RESET", "message": f"Missing Collection {key}; reset to My Library"}


@cli.group("session")
def session_group() -> None:
    """Create and inspect independent Browsing Sessions."""


@session_group.command("create", help="Create an independent Browsing Session.")
@click.argument("session_id", required=False)
@click.pass_context
def session_create(ctx: click.Context, session_id: str | None) -> None:
    config = _config(ctx)
    emit(ctx, sessions.create(config.config_dir, session_id or config.session_id))


@session_group.command("status", help="Show the selected Browsing Session.")
@click.pass_context
def session_status(ctx: click.Context) -> None:
    state = _session(ctx)
    emit(ctx, {**state, "path": str(sessions.session_path(_config(ctx).config_dir, state["id"]))})


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


@app_group.command("doctor", help="Check Zotero, Extension, token, database, and Poppler.")
@click.option("--deep", is_flag=True, help="Also reconcile cached index statistics by scanning Passage metadata.")
@click.pass_context
def app_doctor(ctx: click.Context, deep: bool) -> None:
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
    database = {"ok": False, "path": str(config.data_dir / "zotero.sqlite")}
    if app["ready"]:
        try:
            database = {**Database(config.data_dir / "zotero.sqlite").schema_check(), "path": database["path"]}
        except CliError as exc:
            database["error"] = {"code": exc.code, "message": exc.message}
    checks = {"zotero": app, "database": database, "token": token, "bridge": bridge, "tools": tools, "index": index}
    ready = app["ready"] and database["ok"] and token["ok"] and bridge["ok"] and bridge["protocol"] == PROTOCOL and index["ok"] and all(v["ok"] for v in tools.values())
    emit(ctx, {"ready": ready, "protocol": PROTOCOL, "checks": checks}, ok=ready, code="READY" if ready else "DEGRADED")
    if not ready:
        ctx.exit(1)


@cli.command("pwd", help="Show this session's current Collection path.")
@click.pass_context
def pwd(ctx: click.Context) -> None:
    db = _database(ctx)
    state, warning = _validated_location(ctx, db, _session(ctx))
    collection = db.collection_by_key(state["collection"]) if state["collection"] else None
    emit(ctx, {"path": collection["path"] if collection else "/My Library", "collection": state["collection"], "warning": warning})


@cli.command("cd", help="Change this session's current Collection.")
@click.argument("target", required=False)
@click.option("--collection", "collection_key", help="Select a Collection by stable key.")
@click.pass_context
def cd(ctx: click.Context, target: str | None, collection_key: str | None) -> None:
    if bool(target) == bool(collection_key):
        raise CliError("INVALID_ARGUMENT", "Provide exactly one collection path or --collection KEY")
    db = _database(ctx)
    state, warning = _validated_location(ctx, db, _session(ctx))
    if collection_key:
        collection = db.collection_by_key(collection_key)
        if not collection:
            raise CliError("COLLECTION_NOT_FOUND", f"Collection not found: {collection_key}")
    else:
        collection = db.resolve_collection(target or "", state.get("collection"))
    state["collection"] = collection["key"] if collection else None
    sessions.save(_config(ctx).config_dir, state)
    emit(ctx, {"path": collection["path"] if collection else "/My Library", "collection": state["collection"], "warning": warning})


@cli.command("ls", help="List child Collections and Literature Items.")
@click.argument("target", required=False)
@click.option("--collection", "collection_key", help="List a Collection by stable key.")
@click.option("--offset", default=0, show_default=True, type=int, help="Skip this many entries.")
@click.option("--limit", default=50, show_default=True, type=int, help="Maximum entries to return.")
@click.pass_context
def ls_command(ctx: click.Context, target: str | None, collection_key: str | None, offset: int, limit: int) -> None:
    if target and collection_key:
        raise CliError("INVALID_ARGUMENT", "Use a collection path or --collection, not both")
    db = _database(ctx)
    state, warning = _validated_location(ctx, db, _session(ctx))
    key = state.get("collection")
    if collection_key:
        collection = db.collection_by_key(collection_key)
        if not collection:
            raise CliError("COLLECTION_NOT_FOUND", f"Collection not found: {collection_key}")
        key = collection["key"]
    elif target:
        collection = db.resolve_collection(target, key)
        key = collection["key"] if collection else None
    result = db.list_entries(key, offset=offset, limit=limit)
    result["warning"] = warning
    emit(ctx, result)


@cli.command("lookup", help="Show metadata for a Literature Item.")
@click.argument("item_key")
@click.pass_context
def lookup(ctx: click.Context, item_key: str) -> None:
    emit(ctx, _database(ctx).lookup(item_key))


@cli.command("source", help="Show the selected Markdown Full Text or fallback PDF.")
@click.argument("item_key")
@click.pass_context
def source_command(ctx: click.Context, item_key: str) -> None:
    config = _config(ctx)
    emit(ctx, sources.resolve_for_item(_database(ctx), item_key, config.data_dir))


@cli.command("read", help="Read bounded lines from the selected Full Text source.")
@click.argument("item_key")
@click.option("--start", default=1, show_default=True, type=int, help="First source line to read.")
@click.option("--limit", default=200, show_default=True, type=int, help="Maximum source lines to read.")
@click.option("--all", "all_text", is_flag=True, help="Emit untruncated raw full text.")
@click.pass_context
def read_command(ctx: click.Context, item_key: str, start: int, limit: int, all_text: bool) -> None:
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


@cli.command("find", help="Find exact text in the selected Full Text source.")
@click.argument("item_key")
@click.argument("query")
@click.option("--context", default=0, show_default=True, type=int, help="Surrounding lines per match.")
@click.option("--limit", default=20, show_default=True, type=int, help="Maximum matches to return.")
@click.pass_context
def find_command(ctx: click.Context, item_key: str, query: str, context: int, limit: int) -> None:
    config = _config(ctx)
    source = sources.resolve_for_item(_database(ctx), item_key, config.data_dir)
    emit(ctx, sources.lexical_find(source, query, limit=limit, context=context))


@cli.group("index")
def index_group() -> None:
    """Update and inspect the local semantic Passage index."""


@index_group.command("update", help="Explicitly update changed semantic Passages.")
@click.option("--force", is_flag=True, help="Rebuild selected records even when unchanged.")
@click.option("--item", "item_keys", multiple=True, help="Update only this Literature Item; repeatable.")
@click.option("--collection", help="Update only an explicit Collection path and descendants.")
@click.pass_context
def index_update(
    ctx: click.Context, force: bool, item_keys: tuple[str, ...], collection: str | None
) -> None:
    if item_keys and collection:
        raise CliError("INVALID_ARGUMENT", "Use --collection or --item, not both")
    config = _config(ctx)
    db = _database(ctx)
    for key in item_keys:
        db.lookup(key)
    selected_keys = _collection_scope(ctx, db, collection) if collection else list(item_keys) or None
    result = _semantic_index(ctx).update(
        db, config.data_dir, force=force, item_keys=selected_keys, show_progress=True
    )
    errors = result.get("errors", [])
    emit(ctx, result, ok=not errors, code="OK" if not errors else "INDEX_PARTIAL")
    if errors:
        ctx.exit(1)


@index_group.command("status", help="Show semantic index readiness and cached coverage.")
@click.option("--deep", is_flag=True, help="Reconcile cached statistics by scanning Passage metadata.")
@click.pass_context
def index_status(ctx: click.Context, deep: bool) -> None:
    emit(ctx, _semantic_index(ctx).status(deep=True) if deep else _semantic_index(ctx).status())


@index_group.command("inspect", help="Inspect indexed Passage metadata.")
@click.option("--limit", default=20, show_default=True, type=int, help="Maximum records to return.")
@click.option("--filter", "filter_text", help="Case-insensitive title or creator substring.")
@click.option("--documents", "show_documents", is_flag=True, help="Include stored Passage text.")
@click.option("--stats", is_flag=True, help="Include source and item-type counts.")
@click.pass_context
def index_inspect(
    ctx: click.Context, limit: int, filter_text: str | None, show_documents: bool, stats: bool
) -> None:
    emit(ctx, _semantic_index(ctx).inspect(
        limit=limit, filter_text=filter_text, show_documents=show_documents, stats=stats
    ))


@cli.command("search", help="Search indexed Passages by semantic similarity.")
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

    db = _database(ctx)
    item_keys = None
    if item_key:
        db.lookup(item_key)
        item_keys = [item_key]
    elif collection:
        item_keys = _collection_scope(ctx, db, collection)

    result = _semantic_index(ctx).search(
        query,
        limit=limit,
        filters=parsed_filters,
        item_keys=item_keys,
        item_scope=item_key is not None,
    )
    emit(ctx, result)


@cli.command("resolve", help="Create a verified parent item for a standalone PDF or EPUB.")
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
    if not confirm:
        raise CliError("CONFIRMATION_REQUIRED", "Pass --confirm to resolve document metadata")
    state = _session(ctx)
    config = _config(ctx)
    snapshot = sources.metadata_resolution_snapshot(
        _database(ctx), attachment_key, config.data_dir, markdown_path
    )
    try:
        result = BridgeClient(config.port, config.config_dir / "bridge-token").metadata_resolve(
            session_id=state["id"],
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
    """Audit, import, and safely adopt canonical Markdown Full Text."""


@fulltext_group.command("audit", help="Create a read-only Markdown migration plan.")
@click.option("--output", type=click.Path(path_type=Path), help="Write the compact read-only manifest.")
@click.pass_context
def fulltext_audit(ctx: click.Context, output: Path | None) -> None:
    config = _config(ctx)
    manifest = sources.fulltext_manifest(_database(ctx), config.data_dir)
    if output:
        sources.write_manifest(output, manifest)
        emit(ctx, {"output": str(output.expanduser().resolve()), "summary": manifest["summary"]})
    else:
        emit(ctx, manifest)


@fulltext_group.command("adopt", help="Copy one Markdown attachment into canonical Full Text.")
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
    if not confirm:
        raise CliError("CONFIRMATION_REQUIRED", "Pass --confirm to adopt Markdown Full Text")
    state = _session(ctx)
    config = _config(ctx)
    db = _database(ctx)
    snapshot = sources.adoption_snapshot(
        db, item_key, markdown_attachment_key, config.data_dir, replace_keys
    )
    _run_fulltext_write(
        ctx, db, item_key,
        lambda: BridgeClient(config.port, config.config_dir / "bridge-token").fulltext_adopt(
            session_id=state["id"],
            item_key=snapshot["itemKey"],
            attachment_key=snapshot["attachmentKey"],
            expected_path=snapshot["expectedPath"],
            expected_sha256=snapshot["expectedSha256"],
            replace_attachment_keys=snapshot["replaceAttachmentKeys"],
        ),
    )


@fulltext_group.command("import", help="Import one local Markdown file as canonical Full Text.")
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
    if not confirm:
        raise CliError("CONFIRMATION_REQUIRED", "Pass --confirm to import Markdown Full Text")
    state = _session(ctx)
    config = _config(ctx)
    db = _database(ctx)
    snapshot = sources.import_snapshot(db, item_key, markdown_path, replace_keys)
    _run_fulltext_write(
        ctx, db, item_key,
        lambda: BridgeClient(config.port, config.config_dir / "bridge-token").fulltext_import(
            session_id=state["id"],
            item_key=snapshot["itemKey"],
            source_path=snapshot["sourcePath"],
            expected_sha256=snapshot["expectedSha256"],
            replace_attachment_keys=snapshot["replaceAttachmentKeys"],
        ),
    )


@fulltext_group.command("migrate", help="Apply reviewed candidate entries from a migration plan.")
@click.argument("plan", type=click.Path(path_type=Path))
@click.option("--confirm", is_flag=True, help="Confirm all selected recoverable Zotero mutations.")
@click.pass_context
def fulltext_migrate(ctx: click.Context, plan: Path, confirm: bool) -> None:
    if not confirm:
        raise CliError("CONFIRMATION_REQUIRED", "Pass --confirm to apply a reviewed migration plan")
    state = _session(ctx)
    config = _config(ctx)
    db = _database(ctx)
    plan_path, candidates = sources.load_migration_candidates(plan, db, config.data_dir)
    bridge = BridgeClient(config.port, config.config_dir / "bridge-token")
    semantic_index = _semantic_index(ctx)
    results = []
    succeeded = failed = warnings = unknown = rollback_failed = 0
    for candidate in candidates:
        try:
            result = bridge.fulltext_adopt(
                session_id=state["id"],
                item_key=candidate["itemKey"],
                attachment_key=candidate["attachmentKey"],
                expected_path=candidate["expectedPath"],
                expected_sha256=candidate["expectedSha256"],
                replace_attachment_keys=candidate["replaceAttachmentKeys"],
            )
            succeeded += 1
            index_result = _update_index_after_mutation(
                ctx, db, candidate["itemKey"], semantic_index
            )
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
                    "index": _update_index_after_mutation(
                        ctx, db, candidate["itemKey"], semantic_index
                    ),
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
