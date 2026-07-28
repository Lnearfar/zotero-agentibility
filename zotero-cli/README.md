# zotero-cli

Linux CLI for local Zotero navigation, grounded reading, semantic Passage search, and confirmed Markdown Full Text adoption. Installation is documented in the repository root README.

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

Version 0.3.0 provides:

```text
session create/status
app status/doctor
pwd  cd  ls
lookup  source  read  find  search
index update/status/inspect
fulltext audit/adopt/migrate
```

Zotero must be running with its Local API enabled. Reads and Chroma ONNX search remain local and side-effect-free; Chroma may download the MiniLM model once, but paper content never leaves the machine. Full Text writes require `--confirm` and the matching authenticated Extension.
