# Documentation Report: Native Zotero Control Surface

**Date:** 2026-08-23
**Project Type:** CODING + INFORMATIONAL
**Target:** broad native-first fixed-operation CLI checkpoint

## Coverage

- Requested documentation checkpoints: **10/10 addressed (100%)**.
- Bounded research chunks: **13/13 read (100%)**; no chunks were skimmed or skipped.
- Installed command tree: read from `za-cli/src/za_cli/cli.py`, verified with
  `za-cli --help` and nested group help.
- Fixed bridge operations: read from `za-cli/src/za_cli/bridge.py` and
  `zotero-extension/bootstrap.js`, verified with the extension static checker.

## Coverage ledger

| Chunk | Evidence read | State | Used in |
| --- | --- | --- | --- |
| Domain vocabulary and ownership | `CONTEXT.md` | read | capabilities, bridge, ingest |
| Current user-facing behavior | `README.md`, `za-cli/README.md` | read | README, CLI, current/planned labels |
| Current CLI contract | `docs/cli.md`, `za-cli/src/za_cli/cli.py`, `za-cli/tests/test_cli.py`, Click help | read | CLI tree, capabilities, report |
| Ingest and Full Text rules | `docs/ingest.md`, `docs/migration.md`, Skill mutation references | read | ingest, capabilities, Skill boundary |
| Bridge authority and protocol | `docs/bridge.md`, `za-cli/src/za_cli/bridge.py` | read | bridge, capabilities, ADR |
| Extension fixed operations | `zotero-extension/bootstrap.js`, `zotero-extension/check.sh`, `zotero-extension/README.md` | read | bridge, capabilities, validation |
| Existing architecture decisions | `docs/adr/0001` through `docs/adr/0007` | read | ADR 0008, authority wording |
| Native recognition research | `docs/research/zotero-metadata-recognition.md` | read | ingest, bridge, capabilities |
| Acquisition ecosystem memo | `docs/research/ai-literature-ingest-ecosystem.md` | read | revised memo, acquisition boundary |
| Retrieval/indexing context | `skills/research-with-zotero/references/retrieval.md`, `docs/indexing.md` | read | CLI installed surface and authority |
| Diagram checkpoint | `docs/overview.excalidraw` | read and JSON-validated | minimal text-only boundary update |
| Project validators and packaging | `za-cli/pyproject.toml`, `zotero-extension/Makefile`, `skills-lock.json` | read | validation plan |

No ledger item remains unmarked. The non-obvious concept preserved across the
new docs is that read-only SQLite can propose a candidate but cannot authorize a
write: a live Zotero transaction must recheck identity, hash, Source Document,
and Collection membership. The same Strong Identifier with a different Source
rolls back the new import; metadata-only network paths use
`saveAttachments=false`.

## Generated and updated artifacts

- `docs/capabilities.md` — capability/risk/status/milestone matrix and gates.
- `docs/cli.md` — installed versus planned Click trees and forbidden surfaces.
- `docs/ingest.md` — planned `add file` contract and current resolution/fulltext boundary.
- `docs/bridge.md` — native-first fixed-operation and authority model.
- `docs/adr/0008-broad-native-first-fixed-operations.md` — minimal accepted decision.
- `docs/research/ai-literature-ingest-ecosystem.md` — Human/browser acquisition boundary and metadata-only network policy.
- `docs/overview.excalidraw` — five stale labels updated in place; geometry and layout unchanged.
- `README.md` — current installed capability wording and roadmap link only.
- `skills/research-with-zotero/SKILL.md` and `references/mutations.md` — shallow boundary/routing clarification only.
- `.agents/doc/2026-08-23-control-surface.md` — this coverage ledger/report (repository-ignored artifact).

## Validation

- Relative Markdown links and local anchors: **pass** (custom repository check).
- `git diff --check`: **pass**.
- `python3 -m json.tool docs/overview.excalidraw`: **pass**.
- `(cd za-cli && uv sync --locked && uv run python -m unittest discover -s tests -v)`: **100 tests, OK**.
- `make -C zotero-extension clean check`: **pass** (`Static validation passed`).
- `uvx --from skills-ref agentskills validate skills/research-with-zotero`: **pass**.
- Canonical `doc` skill validator: **14 passed, 0 failed**.

## Gaps and deliberate boundaries

- Local Document Intake, Library Organization, Resource Editing, Duplicate
  Management, Metadata Ingest and Exchange, and Library Operations are planned
  only; this documentation checkpoint does not claim runtime implementation.
- PDF discovery/download, campus authentication, cookies, and the decision to
  download remain Human/browser Skill work rather than core coverage.
- Group-library support, OCR/conversion, generic `execute`/`js`, direct writes,
  and permanent purge remain deferred or prohibited by contract.
