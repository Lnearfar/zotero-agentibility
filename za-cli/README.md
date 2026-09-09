# za-cli

Linux CLI for local Zotero navigation, local PDF/EPUB intake, metadata resolution, grounded reading, semantic Passage search, and confirmed Markdown Full Text import and adoption. Installation is documented in the repository root README.

## Development

```bash
uv sync --locked
uv run python -m unittest discover -s tests -v
uv run za-cli --help
uv build
```

Set `ZOTERO_DATA_DIR` when Zotero data is not under `~/Zotero`, `ZOTERO_HTTP_PORT` when it is not 23119, and `ZA_CLI_CONFIG_DIR` only for isolated tests.

## Command reference

`za-cli --help` lists every installed command with a short description. Use `za-cli COMMAND --help` or `za-cli GROUP COMMAND --help` for arguments and options.

The current release provides:

```text
app status/doctor
add file
ls
lookup  source  read  find  search  resolve
index update/reconcile/status/refresh/worker/inspect
fulltext audit/adopt/import/migrate
```

Zotero must be running with its Local API enabled. Reads and Chroma ONNX search remain local and side-effect-free; Chroma may download the MiniLM model once, but paper content never leaves the machine. Writes require `--confirm` and a protocol-compatible authenticated Extension. `add file PATH` copies a selected local PDF/EPUB into Zotero and recognizes it by default; it never downloads a document. A sole EPUB can be reported by `source`, but `read`/`find` require Markdown or PDF. `resolve ATTACHMENT_KEY --markdown PATH --confirm` resolves a standalone document already in Zotero.

Full Text writes and native Zotero notifications queue affected Items for semantic refresh. The Extension launches `za-cli index worker --managed` with Zotero and owns its shutdown. The child uses native catalog snapshots through the authenticated bridge, processes durable queue events, and reconciles on startup and every 12 hours. The Agentibility Console displays lifecycle, queue, active work, errors, and selected Item coverage. `za-cli --json index worker --once` is available for diagnosis.
