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


@click.group(cls=RootGroup, epilog="Run 'zotero-cli COMMAND --help' for command options.")
@click.option("--session", "session_id", help="Explicit Browsing Session ID.")
@click.option("--json", "json_output", is_flag=True, help="Emit compact JSON.")
@click.version_option(__version__, prog_name="zotero-cli")
@click.pass_context
def cli(ctx: click.Context, session_id: str | None, json_output: bool) -> None:
    """Read-only Zotero library navigation and grounded text retrieval."""
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


def _session(ctx: click.Context) -> dict:
    config = _config(ctx)
    if not config.session_id:
        raise CliError("SESSION_REQUIRED", "Pass --session with an explicit Browsing Session ID")
    return sessions.load(config.config_dir, config.session_id)


def _validated_location(ctx: click.Context, db: Database, state: dict) -> tuple[dict, dict | None]:
    key = state.get("collection")
    if not key:
        return state, None
    collection = db.collection_by_key(key)
    if collection:
        return state, collection
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
@click.pass_context
def app_doctor(ctx: click.Context) -> None:
    config = _config(ctx)
    app = probes(config.port)
    token = token_status(config.config_dir / "bridge-token")
    bridge: dict[str, Any]
    if token["ok"]:
        try:
            health = BridgeClient(config.port, config.config_dir / "bridge-token").health()
            bridge = {
                "ok": health.get("ok") is True and health.get("extension_version") == __version__,
                "protocol": health.get("protocol"),
                "extensionVersion": health.get("extension_version"),
                "expectedVersion": __version__,
                "health": health,
            }
        except CliError as exc:
            bridge = {"ok": False, "protocol": None, "error": {"code": exc.code, "message": exc.message}}
    else:
        bridge = {"ok": False, "protocol": None, "error": "safe token unavailable"}
    tools = {name: {"ok": bool(shutil.which(name)), "path": shutil.which(name)} for name in ("pdftotext", "pdfinfo")}
    database = {"ok": False, "path": str(config.data_dir / "zotero.sqlite")}
    if app["ready"]:
        try:
            database = {**Database(config.data_dir / "zotero.sqlite").schema_check(), "path": database["path"]}
        except CliError as exc:
            database["error"] = {"code": exc.code, "message": exc.message}
    checks = {"zotero": app, "database": database, "token": token, "bridge": bridge, "tools": tools}
    ready = app["ready"] and database["ok"] and token["ok"] and bridge["ok"] and bridge["protocol"] == PROTOCOL and all(v["ok"] for v in tools.values())
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


@cli.group("fulltext")
def fulltext_group() -> None:
    """Inspect existing Markdown attachments without mutation."""


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


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        result = cli.main(args=args, prog_name="zotero-cli", standalone_mode=False)
        return int(result or 0)
    except click.exceptions.Exit as exc:
        return int(exc.exit_code)
    except click.ClickException as exc:
        if "--json" in args:
            click.echo(_json({"ok": False, "code": "USAGE_ERROR", "error": {"message": exc.format_message()}}), err=True)
        else:
            exc.show()
        return int(exc.exit_code)
