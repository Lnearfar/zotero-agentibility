# Documentation Report: Local Document Intake

**Date:** 2026-08-23  
**Project Type:** CODING + INFORMATIONAL  
**Target:** installed `add file` vertical slice and Zotero 10 compatibility

## Coverage

- Requested behavior contracts documented: **8/8 (100%)**.
- Bounded research chunks read: **10/10 (100%)**.
- Runtime status: Python/static validation complete; Zotero 10 Extension 0.5.0 is active and bridge health is READY. Mutation-free intake cases remain pending.

## Coverage ledger

| Chunk | Evidence read | State | Used in |
| --- | --- | --- | --- |
| Domain and ownership | `CONTEXT.md` | read | Source/Unrecognized/Trash language |
| Accepted capability plan | `docs/capabilities.md`, ADR 0008 | read | installed/planned status |
| CLI implementation | `za-cli/src/za_cli/cli.py`, Click help | read | command syntax and outcomes |
| CLI preflight | `za-cli/src/za_cli/sources.py` | read | path/hash/key checks |
| Bridge client | `za-cli/src/za_cli/bridge.py` | read | fixed request schema |
| Extension implementation | `zotero-extension/bootstrap.js` | read | native import, recognition, rollback, audit |
| Public tests | `za-cli/tests/test_cli.py`, `test_bridge.py`, `test_sources.py` | read | documented observable behavior |
| Extension validation | `zotero-extension/check.sh`, `manifest.json`, `README.md` | read | prohibited surfaces and Zotero compatibility |
| Zotero 10 native implementation | installed `omni.ja` server, Items, MIME, Duplicates, recognition sources | read | API compatibility and native-first claims |
| Agent workflow | Skill and `references/mutations.md` | read | routing and operational boundary |

## Generated and updated

- `CONTEXT.md`, `README.md`, `za-cli/README.md` — Source Document language, installed command, and PDF-acquisition boundary.
- `docs/cli.md`, `docs/ingest.md`, `docs/bridge.md`, `docs/capabilities.md` — installed interface, operation contract, native seam, and milestone status.
- `docs/research/ai-literature-ingest-ecosystem.md` — current intake capability without changing the Human/browser download boundary.
- `skills/research-with-zotero/SKILL.md`, `references/mutations.md` — shallow routing and outcome handling.
- `zotero-extension/README.md` — `add_file` and Zotero 10 development compatibility.

## Non-obvious invariant

A failed intake erases only objects created by that operation through Zotero's native object lifecycle. It never purges a pre-existing attachment. An unresolved successful intake is different: the standalone attachment is committed without a source role and returns `added_unrecognized`. Zotero's MD5 is only an exact-match prefilter; stored-file SHA-256 authorizes reuse.

## Validation

- Python unittest discovery: **112 tests passed**.
- Node syntax and Extension static build: **passed**.
- Skill validator: **valid**; canonical doc validator: **14/14 passed**.
- Relative Markdown links/anchors: **passed for 22 Markdown files**.
- Excalidraw JSON and `git diff --check`: **passed**.
- Live Zotero 10 bridge health: **passed** (`extensionVersion=0.5.0`, protocol 1, `app doctor` READY).
- Mutation-free exact-reuse/conflict smoke cases: **pending** to avoid running a full attachment scan while the user is active.

## Remaining gaps

- Identifier/URL metadata ingest, resource editing, organization, duplicate merge, and sync control remain planned.
- PDF discovery/download, campus authentication, cookies, OCR, and PDF-to-Markdown remain outside core.
- Full recognizer success and rollback races require a disposable Zotero fixture before they can be automated without changing a real library.
