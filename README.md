<div align="center">

# Zotero Agentibility

Making Zotero natively and safely operable for your AI agent — CLI, Skill, and Markdown integration, all in one.

[Introduction](#introduction) · [Installation](#installation) · [CLI reference](#cli-reference) · [Development](#development-history)

</div>

<!-- <p align="center">
  <img src="./assets/readme/zotero-markdown-compatibility.png" width="100%" alt="Excalidraw diagram: Zotero keeps the PDF as Source Document, adopts canonical fulltext.md, and exposes local search, exact reading, and confirmed Full Text operations to an agent">
</p>

<p align="center"><a href="./assets/readme/zotero-markdown-compatibility.excalidraw">Editable Excalidraw source</a></p> -->

---


## 1. Introduction

### Key Features and Overview 

- skill+cli: only load instruction prompts as LLM context when the task involves Zotero;
- add Markdown file integration; 
- semantic search with Markdown.
- ...





### Function Preview

Once installed, in any AI agent, you just say:
```txt
Explain to me what this concept is: Sampling-Based Methods for Optimal Control. My Zotero collection is '/My Library/control'.
```

Your Agent:
```txt
load skill:research-with-zotero
bash za-cli cd '/My Library/control'
bash za-cli search "sampling-based methods for optimal control" 
[get search results]
Agent: According to paper xxx , sampling-based methods are ...
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
$ bash za-cli --json read ITEM_KEY --start 1 --limit 200
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
Linux-only and supports Zotero 7–9. It requires Python 3.10+, [`uv`](https://docs.astral.sh/uv/), Poppler, `make`, `zip`, and `unzip`.


### Option 1: Install from the command line

Run these commands from a local checkout of this repository:

```bash
cd /path/to/zotero-paper-agent
sudo apt install poppler-utils make zip unzip
# Editable install: bare `zotero-cli` runs this checkout's source.
uv tool install --editable --force ./zotero-cli
make -C zotero-extension
```

In Zotero, open **Tools → Add-ons → Install Add-on From File**, select
`zotero-extension/build/zotero-paper-agent-*.xpi`, and restart Zotero.
Then install the Agent Skill:

```bash
skill_dir="$HOME/.agents/skills/research-with-zotero"
rm -rf "$skill_dir"
mkdir -p "$skill_dir"
cp -a skills/research-with-zotero/{SKILL.md,LICENSE,references} "$skill_dir/"

zotero-cli --version
zotero-cli --json app doctor
```

### Option 2: Ask your Agent to install it

```text
Install https://github.com/Lnearfar/zotero-paper-agent for me.
```

### Installation Summary: What Has Been Installed?

A uv tool: za-cli
An agent skill: research-with-zotero
A Zotero extension:



`doctor` checks Zotero, its Local API, the matching Extension and protocol, token permissions, Poppler, the database schema, and semantic-index readability.

| What it touches                                                     | Purpose                                                           |
| ------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `~/.local/share/uv/tools/zotero-cli/` and `~/.local/bin/zotero-cli` | CLI environment and executable                                    |
| Active Zotero profile `extensions/`                                 | Extension XPI, managed by Zotero                                  |
| `~/.agents/skills/research-with-zotero/`                            | Runtime Agent instructions                                        |
| `~/.config/zotero-paper-agent/`                                     | Mode-`0600` bridge token, sessions, and write audit               |
| `~/.local/share/zotero-paper-agent/index/<profile>/`                | Profile-specific Chroma Passage index                             |
| Zotero attachment storage                                           | Canonical `fulltext.md` only after an explicit confirmed adoption |

<details>
<summary><b>Development XPI upgrades</b></summary>

A development build can be installed without UI automation by closing Zotero and atomically replacing `<profile>/extensions/zotero-paper-agent@local.xpi`. Follow the guarded procedure in [`zotero-extension/README.md`](zotero-extension/README.md#development-install-or-upgrade); do not edit Zotero's generated `extensions.json`.

</details>

---

## Use Cases
task 1:

task 2:

task 3:

task 4:


---



## Getting Started

1. Confirm the local stack:

   ```bash
   zotero-cli --json app doctor
   ```

2. Build or refresh the index explicitly. Search won't update the index for you:

   ```bash
   zotero-cli --json index update
   # Or limit the work:
   zotero-cli --json index update --collection "/My Library/Project"
   zotero-cli --json index update --item ITEM_KEY
   ```

3. Discover papers, then inspect and verify a candidate:

   ```bash
   zotero-cli --json search "stability proof" --limit 10
   zotero-cli --json lookup ITEM_KEY
   zotero-cli --json source ITEM_KEY
   zotero-cli --json read ITEM_KEY --start 1 --limit 200
   zotero-cli --json find ITEM_KEY "exact phrase" --context 8
   ```

4. Create one Browsing Session when Collection navigation matters:

   ```bash
   session="${ZOTERO_CLI_SESSION:-${PI_SESSION_ID:-research-1}}"
   zotero-cli --json session create "$session"       # once
   zotero-cli --session "$session" --json ls
   zotero-cli --session "$session" --json cd "Project"
   zotero-cli --session "$session" --json pwd
   ```

Use `zotero-cli --help` and subcommand help as your go-to syntax reference. Human-readable output is the default; agents and scripts should pass `--json`.

## 3. CLI reference

| Command                       | Behavior                                                                             |
| ----------------------------- | ------------------------------------------------------------------------------------ |
| `app doctor`                  | Validate the local application, bridge, tools, schema, versions, and index           |
| `session create/status`       | Manage independent per-agent navigation state                                        |
| `pwd`, `cd`, `ls`             | Navigate Collection paths without using Zotero UI selection                          |
| `lookup`, `source`            | Inspect Literature Item metadata and preferred attachment                            |
| `read`, `find`                | Read bounded source lines or locate exact text; `read --all` emits complete raw text |
| `index update/status/inspect` | Explicitly maintain and diagnose the profile-specific Passage index                  |
| `search`                      | Search indexed Passages globally or within an explicit Collection/item scope         |
| `fulltext audit`              | Produce a read-only migration plan for existing Markdown attachments                 |
| `fulltext adopt`              | Import a reviewed existing Markdown child attachment as canonical Full Text          |
| `fulltext migrate`            | Apply only reviewed `candidate` entries from a migration plan                        |

<details>
<summary><b>Runtime files and concurrency</b></summary>

Browsing Sessions are separate mode-`0600` JSON files written atomically under `~/.config/zotero-paper-agent/sessions/`. Each session stores a stable Collection Key, so two agents can navigate different Collections without sharing a hidden working directory.

Semantic updates use a cross-process lock and bounded Chroma batches. Reads and searches can run concurrently. Extension writes pass through one bounded queue, and `~/.config/zotero-paper-agent/audit.jsonl` records only write time, Session ID, operation, affected keys, result, and error code. It excludes tokens, full text, note bodies, search queries, and read activity.

</details>

<details>
<summary><b>Current boundaries</b></summary>

General ingest, metadata editing, Collection mutation, duplicate merging, OCR, DOCX citation automation, and permanent deletion are not yet implemented. Converted images aren't bundled; for figures, go back to the PDF. The catalog and Full Text bridge work with My Library only; group libraries aren't supported yet.

The index is fresh and profile-specific. It neither reads nor migrates the old `zotero-mcp` Chroma database. External Zotero changes appear after the next explicit `index update`; failed extraction is reported as partial coverage rather than silently omitted.

</details>

## FAQ

### Does Markdown replace the PDF?

No. The PDF remains the Source Document and the place to verify page layout and figures. Canonical Markdown provides clean local Passage search and exact line addressing.

### Does this project convert PDFs to Markdown?

No. Conversion and OCR happen externally, on your terms — this project doesn't do them itself. The current bridge adopts an existing Markdown child attachment after path, hash, source-PDF, and conflict checks.

### Does paper content leave the machine?

The semantic index and embedding inference are local. Chroma may download the roughly 80 MB ONNX model on first use, and Zotero may synchronize stored attachments according to the user's own sync settings; this project has no telemetry and sends no paper text to an external embedding or LLM API.

## Contributing

Run the smallest complete local checks before submitting a change:

```bash
(cd zotero-cli && uv sync --locked && uv run python -m unittest discover -s tests -v)
make -C zotero-extension clean check
uvx --from skills-ref agentskills validate skills/research-with-zotero
```

Keep CLI syntax in Click help, multi-command research rules in the Skill, and durable design decisions in `docs/` or an ADR. Direct SQLite writes, arbitrary Zotero JavaScript, cloud processing of paper text, and permanent deletion are outside the project contract.

## Documentation

- [Domain language](CONTEXT.md)
- [CLI shape](docs/cli.md)
- [Semantic indexing](docs/indexing.md)
- [Extension bridge](docs/bridge.md)
- [Markdown migration](docs/migration.md)
- [Architecture decisions](docs/adr/)

## License and provenance

The repository is licensed under Apache-2.0. It is based on [`cli-anything-zotero`](https://github.com/PiaoyangGuohai1/cli-anything-zotero) at commit `f621952f3645546573d622440cbf707320f7a35f`; semantic-search behavior is also derived from [`zotero-mcp`](https://github.com/54yyyu/zotero-mcp) 0.6.2 under MIT. Modified-file provenance and retained licenses are recorded in [`zotero-cli/UPSTREAM.md`](zotero-cli/UPSTREAM.md), [`zotero-extension/UPSTREAM.md`](zotero-extension/UPSTREAM.md), and `zotero-cli/LICENSES/`.


### Uninstall

Remove **Zotero-Paper-Agent Bridge** in Zotero's Add-ons manager and restart Zotero, then run:

```bash
uv tool uninstall zotero-cli
rm -rf ~/.agents/skills/research-with-zotero
rm -rf ~/.config/zotero-paper-agent ~/.local/share/zotero-paper-agent
```

Removing project state does not remove Literature Items, PDFs, Markdown attachments, or Zotero's database. If this installation replaced a `zotero-cli` supplied by another uv tool, reinstall that tool to restore its executable.

## Development History

### v0.3.0

- Initial public release.
- CLI: catalog reads, sessions, source selection, bounded reading, local ONNX semantic search/index, fulltext audit/adopt/migrate.
- Extension: bearer-authenticated loopback `health` and `fulltext_adopt`.
- Skill: `research-with-zotero` agent workflow.
- Linux-only, Zotero 7–9, Python 3.10+.
