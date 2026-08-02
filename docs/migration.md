# Existing Markdown migration

Migration turns selected existing Markdown child attachments into canonical Markdown Full Text without letting an LLM mutate Zotero directly. Version 0.4.0 implements both the read-only plan and explicitly confirmed apply.

## Current read-only snapshot

- 163 registered Markdown-path attachments under 87 Literature Items; every parent also has a PDF.
- 139 are stored attachments and 24 are linked attachments whose current paths are unavailable.
- The filesystem contains 140 Markdown files: 61 `source.md`, 61 `distill.md`, 2 `probe_distill.md`, and 16 title-like or other names.
- The pre-migration v0.2.0 active-item audit reported 242 records: 161 Markdown attachments plus 81 PDF records needed to expose ambiguous Source Documents. It found 73 deterministic Markdown candidates, 63 excluded distillations, and 106 unresolved records: 79 ambiguous available PDFs, 24 missing linked Markdown files, 2 missing linked PDFs, and one existing `piga-2023-system-identification-output.md` that does not match its parent title. The two other registered Markdown attachments are excluded because their child attachment or parent item is in Zotero Trash.

These counts are diagnostic, not migration decisions and may change with the Library.

## Workflow

1. `fulltext audit` performs no writes and emits `migration-plan.json` with parent Item Key, attachment key, path, link mode, existence, filename, content SHA-256, candidate class, and reason.
2. Deterministic rules classify obvious cases:
   - existing stored `source.md` and title-like paper Markdown are Full Text candidates;
   - `distill.md` and `probe_distill.md` remain ordinary attachments;
   - Zotero Notes and Annotations are never candidates;
   - missing linked files and multiple plausible candidates are unresolved.
3. If the host supports subagents, an inexpensive read-only subagent may review only unresolved entries and edit the plan. It never invokes Zotero writes.
4. A person reviews the summary and explicitly confirms the plan.
5. `fulltext migrate migration-plan.json --confirm` applies only entries whose `candidateClass` is exactly `candidate`. Canonical, excluded, and unresolved entries are untouched. Each item is independent: migration continues after a definite item failure, reports a partial failure, and exits nonzero. A lost bridge connection has an unknown outcome and stops the batch; a rollback failure also stops so its orphan attachment can be inspected. An audit failure after commit is reported as committed with warning rather than failed.

## Apply invariants

For each confirmed item, the CLI and Extension revalidate attachment keys, file path, and content SHA-256 before writing. The Extension imports the selected bytes unchanged as stored `fulltext.md`, sets title `Markdown Full Text` and tag `za-cli:fulltext`, validates the new attachment and hash, then moves the adopted source and explicitly selected prior Full Text attachments to Trash in one final Zotero transaction. Other Markdown such as `distill.md` remains untouched. Multiple marked Full Text attachments require repeatable `--replace ATTACHMENT_KEY` selections for `fulltext adopt`, or `replaceAttachmentKeys` in the plan. When the semantic index is initialized, a successful adoption rebuilds only the affected Literature Item; an index failure is reported as a committed warning and never misreports the Zotero write as rolled back.

The migration never writes `zotero.sqlite`, never follows a missing linked path heuristic, and never permanently deletes data.
