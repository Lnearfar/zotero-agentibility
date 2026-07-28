# zotero-cli

Read-only Linux CLI for a running local Zotero library. Installation is documented in the repository root README.

## Development

```bash
uv sync --locked
uv run python -m unittest discover -s tests -v
uv run zotero-cli --help
uv build
```

Set `ZOTERO_DATA_DIR` when Zotero data is not under `~/Zotero`, `ZOTERO_HTTP_PORT` when it is not 23119, and `ZOTERO_CLI_CONFIG_DIR` only for isolated tests.

## Command reference

`zotero-cli --help` lists every installed command with a short description. Use `zotero-cli COMMAND --help` or `zotero-cli GROUP COMMAND --help` for arguments and options.

Version 0.1.2 provides:

```text
session create/status
app status/doctor
pwd  cd  ls
lookup  source  read  find
fulltext audit
```

Zotero must be running with its Local API enabled. This slice never writes Zotero, accesses a non-loopback service, or performs semantic search.
