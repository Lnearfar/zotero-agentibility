# za-cli

Linux CLI for local Zotero navigation, metadata resolution, grounded reading, semantic Passage search, and confirmed Markdown Full Text import and adoption. Installation is documented in the repository root README.

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
session create/status
app status/doctor
pwd  cd  ls
lookup  source  read  find  search  resolve
index update/reconcile/status/refresh/worker/inspect
fulltext audit/adopt/import/migrate
```

Zotero must be running with its Local API enabled. Reads and Chroma ONNX search remain local and side-effect-free; Chroma may download the MiniLM model once, but paper content never leaves the machine. Metadata and Full Text writes require `--confirm` and a protocol-compatible authenticated Extension. `resolve ATTACHMENT_KEY --markdown PATH --confirm` uses Zotero's native PDF/EPUB recognizer first and an unambiguous Strong Identifier Markdown fallback second.

Full Text writes queue the affected Item for semantic refresh. The installed user systemd service runs `za-cli index worker`; `za-cli --json index worker --once` is available for one-shot operation and tests. The worker uses a cheap Zotero SQLite modification watermark, polls the durable queue, and sleeps while idle. A user timer first runs `index reconcile` about 15 minutes after activation, with randomized delay, and then about every 12 hours for full reconciliation.
