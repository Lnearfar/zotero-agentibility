# Mutations

Writes are limited to `resolve`, `fulltext import`, `fulltext adopt`, and `fulltext migrate`. For general additions, arbitrary metadata or Collection changes, duplicate merging, removal, and every other mutation, explain that boundary and stop; never simulate a missing command through SQLite or arbitrary JavaScript.

## Rules

- Run the command's dry run or preview when available. Show ambiguity before changing Zotero.
- Writes are My Library only and globally serialized. On a busy timeout, report a retryable failure; do not bypass the lock.
- Removal means Zotero Trash. Never request permanent deletion or empty Trash.
- A Literature Item may belong to several Collections. Removing a Collection Membership does not remove the item.
- Reuse an existing item only on exact Item Key, normalized DOI/arXiv/PMID/ISBN, or identical source SHA-256. Similar metadata is review-only.
- Local `add file PATH` must not create an unidentified standalone PDF. Use explicit `--lookup` for network metadata or `--parent ITEM_KEY` for a known item.
- A different incoming PDF never replaces an existing Source Document automatically.

## Metadata resolution

For a standalone PDF or EPUB, run `resolve ATTACHMENT_KEY [--markdown PATH] --confirm` only after explicit user confirmation. It invokes Zotero's native recognizer first; reviewed Markdown is an accuracy-first fallback only when it yields one Strong Identifier and a matching translated title. On success, use the returned `parent_item_key` for any following `fulltext import`. On `METADATA_UNRESOLVED`, report the ambiguity and do not create a title-only parent manually.

## Full text

PDF-to-Markdown conversion is external to this project and runs only on explicit user intent. Version 0.4.0 can import a reviewed local converter output with `fulltext import ITEM_KEY PATH --confirm` or adopt an existing Zotero Markdown child attachment. Import preserves the local file and requires a regular non-symlink `.md`; never import `distill.md` or `probe_distill.md`.

Before import or adoption, identify the selected local path or Markdown attachment and run the command without `--confirm` only to inspect help—not as a dry run. If marked Full Text attachments already exist, supply every reported key explicitly with repeatable `--replace KEY`; then require the user's confirmation before adding `--confirm`. Preserve `distill.md`, `probe_distill.md`, and unrelated Markdown. Converted image assets are not imported; inspect the PDF when figures matter.

## Index freshness

- Successful `fulltext import`, `fulltext adopt`, and `fulltext migrate` durably queue the affected Item for the background index worker. Do not wait for embedding. If enqueueing fails after the Zotero write commits, report the index warning; `index refresh --item ITEM_KEY` can retry enqueueing.
- After the Agent observes a new or replaced PDF/Markdown attachment from Zotero sync or another approved tool, run `index refresh --item ITEM_KEY`. If affected keys are unknown or the change was a bulk sync, leave full reconciliation to explicit maintenance rather than blocking the current request.
- Never ask the user to maintain the index manually.

## Duplicates

Use duplicate detection as a report, not an automatic merge. The caller chooses the keeper. Preview merge first; union memberships, tags, notes, and attachments; collapse only byte-identical PDFs; retain different PDFs. Multiple marked Full Text attachments block merge until one is selected. Confirmed discarded items go to Trash.

## Network

Only explicit DOI/arXiv/URL ingest, PDF fetching, metrics, and Zotero sync may use external services. Tell the user which service was contacted. Never send Full Text.
