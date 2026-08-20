<div align="center">

# Zotero Agentibility

Making Zotero natively and safely operable for your AI agent — CLI, Skill, and Markdown integration, all in one.

[Introduction](#1-introduction) · [Installation](#2-installation) · [Use cases](#use-cases) · [CLI reference](#3-cli-reference) · [Uninstall](#uninstall)

</div>

<p align="center">
  <a href="./assets/readme/zotero-agentibility-demo.mp4">
    <img src="./assets/readme/zotero-agentibility-demo.gif" width="100%" alt="Live demo: Pi Agent searches Zotero, reads canonical Markdown Full Text, and answers with an exact Item Key and line citation">
  </a>
</p>

<p align="center"><sub>Live demo: Zotero → semantic search → exact Markdown reading → grounded answer. Click for MP4.</sub></p>

<!-- <p align="center">
  <img src="./assets/readme/zotero-markdown-compatibility.png" width="100%" alt="Excalidraw diagram: Zotero keeps the PDF as Source Document, adopts canonical fulltext.md, and exposes local search, exact reading, and confirmed Full Text operations to an agent">
</p>

<p align="center"><a href="./assets/readme/zotero-markdown-compatibility.excalidraw">Editable Excalidraw source</a></p> -->

---


## 1. Introduction

### Key Features and Overview

- Agent Skill + CLI: load Zotero instructions into LLM context only when the task needs them;
- canonical Markdown Full Text alongside the original PDF;
- local semantic search with exact line and page verification;
- confirmed Markdown import and adoption through a fixed authenticated Zotero Extension.





### Function Preview

Once installed, in any AI agent, you just say:
```txt
How does MPPI choose the control sequence? My Zotero Library is '/My Library'.
```

Your Agent:
```console
load skill:research-with-zotero
$ za-cli --json search "sampling-based methods for optimal control" --collection "/My Library" --limit 1
$ za-cli --json read BG62UI3J --start 66 --limit 8
MPPI samples control sequences from a Gaussian around the input mean, then selects their softmax cost-weighted average; lower-cost samples receive larger weights. [BG62UI3J, fulltext.md, lines 66-73]
```

#### Why Markdown Integration Is Important
Before: your AI agent finds `Attention is all you need.pdf`, reads the PDF, and gets something like:
```txt
In this work, we use sine and cosine functions of different frequencies:
PE(pos,2i) = sin(pos/100002i/dmodel)
PE(pos,2i+1) = cos(pos/100002i/dmodel)
```
❌ which gets the formula completely wrong.

With a PDF-to-Markdown converter (e.g. `mineru`, recommended), or an existing `Attention.md` file, here's what your AI agent actually sees:
```txt
$ za-cli --json read ITEM_KEY --start 1 --limit 200
[result] In this work, we use sine and cosine functions of different frequencies:
$$
\begin{array}{r} P E _ {(p o s, 2 i)} = \sin (p o s / 1 0 0 0 0 ^ {2 i / d _ {\mathrm{model}}}) \\ P E _ {(p o s, 2 i + 1)} = \cos (p o s / 1 0 0 0 0 ^ {2 i / d _ {\mathrm{model}}}) \end{array}\begin{array}{r} P E _ {(p o s, 2 i)} = \sin (p o s / 1 0 0 0 0 ^ {2 i / d _ {\mathrm{model}}}) \\ P E _ {(p o s, 2 i + 1)} = \cos (p o s / 1 0 0 0 0 ^ {2 i / d _ {\mathrm{model}}}) \end{array}
$$
```
✅ Now the formula comes through intact.

---


### Comparison with Other Projects

Zotero libraries are built around PDFs. Humans read PDFs just fine, but LLM-based AI agents need plain-text Markdown to read papers accurately. No single project covers all of this in one place.

- [`cli-anything-zotero`](https://github.com/PiaoyangGuohai1/cli-anything-zotero) provides broad Zotero automation, but no Markdown integration.
- [`zotero-mcp`](https://github.com/54yyyu/zotero-mcp) provides local semantic retrieval using parsed PDFs rather than precise Markdown.
- [`zotero-markdb-connect`](https://github.com/daeh/zotero-markdb-connect) is about Markdown notes, not the papers themselves as Markdown.


## 2. Installation

### Prerequisites
The current release is Linux-only and supports Zotero 7–9. It requires Python 3.10+, [`uv`](https://docs.astral.sh/uv/), Poppler, `make`, `zip`, and `unzip`.


### Option 1: Install from the command line

Run these commands from a local checkout of this repository:

```bash
cd /path/to/zotero-agentibility
sudo apt install poppler-utils make zip unzip
# Editable install: bare `za-cli` runs this checkout's source.
uv tool install --editable --force ./za-cli
make -C zotero-extension
mkdir -p "$HOME/.config/systemd/user"
install -m 0644 systemd/*.service systemd/*.timer "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now zotero-agentibility-index-worker.service \
  zotero-agentibility-index-reconcile.timer
```

For a non-default Zotero profile or port, put `ZOTERO_DATA_DIR=/path/to/Zotero` and/or `ZOTERO_HTTP_PORT=23119` in `~/.config/zotero-agentibility/environment`, then restart the worker. The file is local configuration and must not contain or be committed with bearer tokens.

In Zotero, open **Tools → Add-ons → Install Add-on From File**, select
`zotero-extension/build/zotero-agentibility-*.xpi`, and restart Zotero.
Then install the Agent Skill:

```bash
skill_dir="$HOME/.agents/skills/research-with-zotero"
rm -rf "$skill_dir"
mkdir -p "$skill_dir"
cp -a skills/research-with-zotero/{SKILL.md,LICENSE,references} "$skill_dir/"

za-cli --version
za-cli --json app doctor
```

### Option 2: Ask your Agent to install it

```text
Install https://github.com/Lnearfar/zotero-agentibility for me.
```

### Installation Summary: What Has Been Installed?

- a uv tool: `za-cli`;
- an Agent Skill: `research-with-zotero`;
- a Zotero Extension: **Zotero-Agentibility Bridge**;
- a user-level background index worker and 12-hour reconciliation timer.

`doctor` checks Zotero, its Local API, Extension protocol compatibility, token permissions, Poppler, the database schema, and cached semantic-index state. `doctor --deep` performs the expensive Passage-statistics reconciliation only for explicit diagnosis.

| What it touches                                                     | Purpose                                                           |
| ------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `~/.local/share/uv/tools/za-cli/` and `~/.local/bin/za-cli` | CLI environment and executable                                    |
| Active Zotero profile `extensions/`                                 | Extension XPI, managed by Zotero                                  |
| `~/.agents/skills/research-with-zotero/`                            | Runtime Agent instructions                                        |
| `~/.config/zotero-agentibility/`                                     | Mode-`0600` bridge token, sessions, and write audit               |
| `~/.local/share/zotero-agentibility/index/<profile>/`                | Profile-specific Chroma Passage index and durable refresh queue   |
| `~/.config/systemd/user/zotero-agentibility-index-*`                 | User-level worker and reconciliation timer                        |
| Zotero attachment storage                                           | Canonical `fulltext.md` only after an explicit confirmed import or adoption |

Project-owned identifiers use the new names consistently: Python namespace `za_cli`, Zotero tags `za-cli:fulltext` and `za-cli:source`, Extension ID `zotero-agentibility@local`, and bridge path `/zotero-agentibility/v1/operation`.

<details>
<summary><b>Development XPI upgrades</b></summary>

A development build can be installed without UI automation by closing Zotero and atomically replacing `<profile>/extensions/zotero-agentibility@local.xpi`. Follow the guarded procedure in [`zotero-extension/README.md`](zotero-extension/README.md#development-install-or-upgrade); do not edit Zotero's generated `extensions.json`.

</details>

---

## Use Cases

1. Search a Zotero Collection semantically, then verify the exact supporting Markdown lines or PDF pages.
2. Read formula-heavy papers from reviewed Markdown rather than lossy PDF text extraction.
3. Let multiple agents browse different Collections through independent Sessions.
4. Import a reviewed local Markdown file or adopt an existing Markdown attachment as canonical `fulltext.md` after explicit confirmation.


---



## Getting Started

1. Search the existing index immediately, then inspect and verify a candidate:

   ```bash
   za-cli --json search "stability proof" --limit 5
   za-cli --json lookup ITEM_KEY
   za-cli --json source ITEM_KEY
   za-cli --json read ITEM_KEY --start 1 --limit 200
   za-cli --json find ITEM_KEY "exact phrase" --context 8
   ```

   If search reports `INDEX_UNINITIALIZED`, initialize once with `za-cli --json index update`. Queue a known changed Item with `za-cli --json index refresh --item ITEM_KEY`; the installed user service processes it without blocking research.

2. Create one Browsing Session only when Collection navigation matters:

   ```bash
   session="${ZA_CLI_SESSION:-${PI_SESSION_ID:-research-1}}"
   za-cli --json session create "$session"       # once
   za-cli --session "$session" --json ls
   za-cli --session "$session" --json cd "Project"
   za-cli --session "$session" --json pwd
   ```

Use `za-cli --help` and subcommand help as your go-to syntax reference. Human-readable output is the default; agents and scripts should pass `--json`.

## 3. CLI reference

| Command                       | Behavior                                                                             |
| ----------------------------- | ------------------------------------------------------------------------------------ |
| `app doctor [--deep]`         | Validate the local stack from cached state; optionally reconcile index statistics   |
| `session create/status`       | Manage independent per-agent navigation state                                        |
| `pwd`, `cd`, `ls`             | Navigate Collection paths without using Zotero UI selection                          |
| `lookup`, `source`            | Inspect Literature Item metadata and preferred attachment                            |
| `read`, `find`                | Read bounded source lines or locate exact text; `read --all` emits complete raw text |
| `index update/reconcile/status/refresh/worker/inspect` | Maintain, queue, process, and diagnose the profile-specific Passage index |
| `search`                      | Search indexed Passages globally or within an explicit Collection/item scope         |
| `resolve`                     | Resolve a standalone PDF/EPUB through Zotero, with optional Markdown identifier fallback |
| `fulltext audit`              | Produce a read-only migration plan for existing Markdown attachments                 |
| `fulltext adopt`              | Adopt a reviewed existing Markdown child attachment as canonical Full Text           |
| `fulltext import`             | Import a reviewed local Markdown file while preserving the local source file         |
| `fulltext migrate`            | Apply only reviewed `candidate` entries from a migration plan                        |

<details>
<summary><b>Runtime files and concurrency</b></summary>

Browsing Sessions are separate mode-`0600` JSON files written atomically under `~/.config/zotero-agentibility/sessions/`. Each session stores a stable Collection Key, so two agents can navigate different Collections without sharing a hidden working directory.

Semantic writes use a cross-process update lock and bounded Chroma batches. A user systemd service runs one long-lived `index worker`, which checks Zotero's modification watermark, polls only the durable Item queue, and sleeps while idle. A low-priority timer performs full reconciliation every 12 hours. Reads and searches never wait for either process. Extension writes pass through one bounded Zotero queue, and `~/.config/zotero-agentibility/audit.jsonl` records only write time, Session ID, operation, affected keys, result, and error code. It excludes tokens, full text, note bodies, search queries, and read activity.

</details>

<details>
<summary><b>Current boundaries</b></summary>

General ingest, metadata editing, Collection mutation, duplicate merging, OCR, DOCX citation automation, and permanent deletion are not yet implemented. Converted images aren't bundled; for figures, go back to the PDF. The catalog and Full Text bridge work with My Library only; group libraries aren't supported yet.

The index is profile-specific and retrieval uses its current snapshot immediately. CLI Full Text changes enter the durable queue; the worker discovers parent and attachment metadata changes through a cheap SQLite watermark. The reconciliation timer catches deletions, linked-file edits, and missed events. Failed extraction is reported as partial coverage rather than silently omitted.

</details>

## FAQ

### Does Markdown replace the PDF?

No. The PDF remains the Source Document and the place to verify page layout and figures. Canonical Markdown provides clean local Passage search and exact line addressing.

### Does this project convert PDFs to Markdown?

No. Conversion and OCR happen externally, on your terms — this project doesn't do them itself. The bridge imports a reviewed local Markdown file or adopts an existing Markdown child attachment after path, hash, source-PDF, and conflict checks.

### Does paper content leave the machine?

The semantic index and embedding inference are local. Chroma may download the roughly 80 MB ONNX model on first use, and Zotero may synchronize stored attachments according to the user's own sync settings; this project has no telemetry and sends no paper text to an external embedding or LLM API.

## Contributing

Run the smallest complete local checks before submitting a change:

```bash
(cd za-cli && uv sync --locked && uv run python -m unittest discover -s tests -v)
make -C zotero-extension clean check
uvx --from skills-ref agentskills validate skills/research-with-zotero
```

Keep CLI syntax in Click help, multi-command research rules in the Skill, and durable design decisions in `docs/` or an ADR. Direct SQLite writes, arbitrary Zotero JavaScript, cloud processing of paper text, and permanent deletion are outside the project contract.

## Documentation

- [Domain language](CONTEXT.md)
- [CLI shape](docs/cli.md)
- [Semantic indexing](docs/indexing.md)
- [Extension bridge](docs/bridge.md)
- [Ingest and metadata resolution](docs/ingest.md)
- [Markdown migration](docs/migration.md)
- [Architecture decisions](docs/adr/)

## License and provenance

The repository is licensed under Apache-2.0. It is based on [`cli-anything-zotero`](https://github.com/PiaoyangGuohai1/cli-anything-zotero) at commit `f621952f3645546573d622440cbf707320f7a35f`; semantic-search behavior is also derived from [`zotero-mcp`](https://github.com/54yyyu/zotero-mcp) 0.6.2 under MIT. Modified-file provenance and retained licenses are recorded in [`za-cli/UPSTREAM.md`](za-cli/UPSTREAM.md), [`zotero-extension/UPSTREAM.md`](zotero-extension/UPSTREAM.md), and `za-cli/LICENSES/`.


### Uninstall

Remove **Zotero-Agentibility Bridge** in Zotero's Add-ons manager and restart Zotero, then run:

```bash
systemctl --user disable --now zotero-agentibility-index-worker.service \
  zotero-agentibility-index-reconcile.timer
rm -f ~/.config/systemd/user/zotero-agentibility-index-{worker,reconcile}.{service,timer}
systemctl --user daemon-reload
uv tool uninstall za-cli
rm -rf ~/.agents/skills/research-with-zotero
rm -rf ~/.config/zotero-agentibility ~/.local/share/zotero-agentibility
```

Removing project state does not remove Literature Items, PDFs, Markdown attachments, or Zotero's database.

## Development History

### v0.4.1

- Added true incremental indexing with lightweight source inventories and live progress.
- Added Zotero Extension updates through GitHub Releases.
- Decoupled CLI and Extension patch versions; bridge compatibility follows the protocol version.

### v0.4.0

- Renamed the project to Zotero Agentibility and the executable to `za-cli`.
- Added confirmed local Markdown import alongside attachment adoption.
- Unified the `za_cli` namespace, `za-cli:*` tags, Extension ID, bridge path, and state directories.
- Hardened stored-file path, symlink, replacement-key, and SHA-256 validation.

### v0.3.0

- Initial public release.
- CLI: catalog reads, sessions, source selection, bounded reading, local ONNX semantic search/index, fulltext audit/adopt/migrate.
- Extension: bearer-authenticated loopback `health` and `fulltext_adopt`.
- Skill: `research-with-zotero` agent workflow.
- Linux-only, Zotero 7–9, Python 3.10+.
