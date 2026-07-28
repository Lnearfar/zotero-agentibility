# Existing Markdown migration

Migration turns selected existing Markdown child attachments into canonical Markdown Full Text without letting an LLM mutate Zotero directly. Version 0.1.1 implements the read-only audit and plan only; apply is a later phase.

## Current read-only snapshot

- 163 registered Markdown-path attachments under 87 Literature Items; every parent also has a PDF.
- 139 are stored attachments and 24 are linked attachments whose current paths are unavailable.
- The filesystem contains 140 Markdown files: 61 `source.md`, 61 `distill.md`, 2 `probe_distill.md`, and 16 title-like or other names.
- The implemented v0.1.1 active-item audit reports 242 records: 161 Markdown attachments plus 81 PDF records needed to expose ambiguous Source Documents. It finds 73 deterministic Markdown candidates, 63 excluded distillations, and 106 unresolved records: 79 ambiguous available PDFs, 24 missing linked Markdown files, 2 missing linked PDFs, and one existing `piga-2023-system-identification-output.md` that does not match its parent title. The two other registered Markdown attachments are excluded because their child attachment or parent item is in Zotero Trash.

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
5. Once implemented and live-validated, `fulltext migrate migration-plan.json --confirm` will execute fixed CLI/Extension operations. Version 0.1.1 stops after the reviewed plan.

## Apply invariants

For each confirmed item, the CLI revalidates attachment keys, file existence, and content SHA-256 before writing. It imports the selected bytes unchanged as stored `fulltext.md`, sets title `Markdown Full Text` and tag `zotero-cli:fulltext`, validates the new attachment, then moves the replaced Full Text candidate to Trash. Other Markdown such as `distill.md` remains untouched. Each successful item rebuilds only its semantic index entries; one failed item does not authorize guessing or changes to another.

The migration never writes `zotero.sqlite`, never follows a missing linked path heuristic, and never permanently deletes data.
