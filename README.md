# zotero-agent-library

Linux-first tools that let people and agents work from the same Zotero-managed literature and Full Text.

> **Status:** v0.1.1 is a runnable read-only slice. It supports Zotero navigation, metadata lookup, Markdown-first/PDF-fallback reading, lexical finding, and read-only Markdown migration audits. Semantic indexing and every Zotero mutation remain unimplemented until the authenticated Extension is live-validated.

## Components

This repository contains three independently installed components:

- `zotero-cli/`: Python CLI and `zotero_cli` namespace.
- `zotero-extension/`: authenticated fixed-operation Zotero Extension, packaged as an XPI.
- `skills/research-with-zotero/`: portable Agent Skill.

No component installs another one. All share the version in [`VERSION`](VERSION).

## Characteristics

The project follows the Ponytail principle: the shortest reliable path wins.

- One standalone CLI; no daemon, MCP server, compatibility layer, or automatic installer.
- Python standard library plus Click, using Zotero's existing Local API, immutable SQLite catalog, and system Poppler instead of new service layers.
- Markdown-first reading with PDF fallback and line/page provenance.
- Explicit per-agent sessions; no hidden global working Collection.
- Local, read-only behavior in v0.1.1; no telemetry, cloud LLM, implicit conversion, or Zotero mutation.
- Three independently replaceable components rather than cross-installing components.

## Requirements

- Linux.
- Zotero 7–9, running with its Local API enabled.
- Python 3.10 or newer and [`uv`](https://docs.astral.sh/uv/).
- Poppler (`pdftotext`, `pdfinfo`).
- `make`, `zip`, and `unzip` to build and inspect the XPI.

On Debian/Ubuntu:

```bash
sudo apt install poppler-utils make zip unzip
```

PDF-to-Markdown conversion and OCR are external to this project. The Skill may orchestrate a separately installed converter, but the CLI does not install or depend on one.

## Manual installation

Run these steps from the repository root.

### 1. CLI

The new executable intentionally replaces any existing `zotero-cli` on `PATH`:

```bash
uv tool install --force ./zotero-cli
zotero-cli --version
```

For development without installing it as a uv tool:

```bash
(cd zotero-cli && uv sync --locked && uv run zotero-cli --help)
```

### 2. Zotero Extension

Build the XPI:

```bash
make -C zotero-extension
```

In Zotero, open **Tools → Add-ons**, choose **Install Add-on From File**, select:

```text
zotero-extension/build/zotero-agent-library-0.1.1.xpi
```

Restart Zotero. On first startup the Extension creates `~/.config/zotero-agent-library/bridge-token` with mode `0600`. The current Extension exposes authenticated `health` only; it cannot mutate Zotero.

### 3. Agent Skill

Copy the Skill manually to a directory discovered by the Agent harness. The portable default is:

```bash
skill_dir=~/.agents/skills/research-with-zotero
rm -rf "$skill_dir"
mkdir -p "$skill_dir"
cp -a skills/research-with-zotero/{SKILL.md,LICENSE,references} "$skill_dir/"
```

The root README is the installation guide. `SKILL.md` contains runtime workflow instructions only.

### 4. Verify

```bash
command -v zotero-cli
zotero-cli --help
zotero-cli --json app doctor
```

All checks should pass after Zotero and the matching Extension are running. Use `zotero-cli COMMAND --help` or `zotero-cli GROUP COMMAND --help` for command-specific arguments and options.

## Installed locations

| Component | Default installed location |
| --- | --- |
| CLI executable | `~/.local/bin/zotero-cli`; confirm with `command -v zotero-cli` |
| CLI uv environment | `$(uv tool dir)/zotero-cli` (normally `~/.local/share/uv/tools/zotero-cli`) |
| Zotero Extension | Active Zotero profile's `extensions/`, managed by Zotero under ID `zotero-agent-library@local` |
| Agent Skill | `~/.agents/skills/research-with-zotero/` with the commands above, or the harness-specific skill directory you chose |
| Bridge token and session state | `~/.config/zotero-agent-library/` |

The built XPI remains at `zotero-extension/build/` in the checkout. Zotero's literature database and attachment storage remain in Zotero's own data directory and are not relocated.

## Uninstall

1. Remove **Zotero Agent Library Bridge** in Zotero's **Tools → Add-ons**, then restart Zotero.
2. Remove the CLI and Skill:

   ```bash
   uv tool uninstall zotero-cli
   rm -rf ~/.agents/skills/research-with-zotero
   ```

3. Optionally remove only this project's token and Browsing Sessions:

   ```bash
   rm -rf ~/.config/zotero-agent-library
   ```

Deleting runtime state does not delete Zotero items, PDFs, Markdown attachments, or the Zotero database. If installation replaced a `zotero-cli` supplied by another uv tool, reinstall that tool to restore its executable. Delete the Git checkout separately if it is no longer needed.

## Current CLI example

```bash
session="${ZOTERO_CLI_SESSION:-${PI_SESSION_ID:-my-session}}"
zotero-cli --json session create "$session"   # once
zotero-cli --session "$session" --json ls
zotero-cli --session "$session" --json lookup ITEM_KEY
zotero-cli --session "$session" --json source ITEM_KEY
zotero-cli --session "$session" --json read ITEM_KEY --start 1 --limit 200
zotero-cli --session "$session" --json find ITEM_KEY "exact phrase" --context 8
zotero-cli --session "$session" --json fulltext audit --output migration-plan.json
```

`read --all` emits untruncated raw text. Ordinary navigation and reading are local and side-effect-free. The current release has no `search`, `index`, `fulltext migrate`, ingest, merge, or write commands.

## Safety and privacy

- Direct Zotero SQLite writes are prohibited; current SQLite access is immutable and read-only.
- Zotero Notes and Annotations are never Markdown Full Text.
- Tagged canonical `fulltext.md` wins over PDF and remains canonical until explicitly replaced in a future write-capable release.
- The Extension never accepts JavaScript source.
- There is no telemetry and no paper Full Text is sent to an external service.
- Future writes are limited to My Library and Zotero Trash; group libraries remain read-only.

## Documentation

- [Domain language](CONTEXT.md)
- [CLI shape](docs/cli.md)
- [Extension protocol](docs/bridge.md)
- [Ingest and reuse](docs/ingest.md)
- [Existing Markdown migration](docs/migration.md)
- [Semantic indexing](docs/indexing.md)
- [Architecture decisions](docs/adr/)

This project is based on [`cli-anything-zotero`](https://github.com/PiaoyangGuohai1/cli-anything-zotero) at commit `f621952f3645546573d622440cbf707320f7a35f` under Apache-2.0; see [ADR 0004](docs/adr/0004-base-the-cli-on-cli-anything-zotero.md), `zotero-cli/UPSTREAM.md`, and `zotero-extension/UPSTREAM.md`.
