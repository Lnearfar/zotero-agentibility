# Mutations

Version 0.2.0 writes only through `fulltext adopt` and `fulltext migrate`. For additions, metadata or Collection changes, duplicate merging, removal, and every other mutation, explain that boundary and stop; never simulate a missing command through SQLite or arbitrary JavaScript.

## Rules

- Run the command's dry run or preview when available. Show ambiguity before changing Zotero.
- Writes are My Library only and globally serialized. On a busy timeout, report a retryable failure; do not bypass the lock.
- Removal means Zotero Trash. Never request permanent deletion or empty Trash.
- A Literature Item may belong to several Collections. Removing a Collection Membership does not remove the item.
- Reuse an existing item only on exact Item Key, normalized DOI/arXiv/PMID/ISBN, or identical source SHA-256. Similar metadata is review-only.
- Local `add file PATH` must not create an unidentified standalone PDF. Use explicit `--lookup` for network metadata or `--parent ITEM_KEY` for a known item.
- A different incoming PDF never replaces an existing Source Document automatically.

## Full text

PDF-to-Markdown conversion is external to this project and runs only on explicit user intent. Version 0.2.0 can adopt an existing Zotero Markdown child attachment; it cannot attach an arbitrary converter output. If the output is not already attached, explain that boundary rather than bypassing Zotero.

Before adoption, identify the selected Markdown attachment and run the command without `--confirm` only to inspect help—not as a dry run. If marked Full Text attachments already exist, supply every reported key explicitly with repeatable `--replace KEY`; then require the user's confirmation before adding `--confirm`. Preserve `distill.md`, `probe_distill.md`, and unrelated Markdown. Converted image assets are not imported; inspect the PDF when figures matter.

## Duplicates

Use duplicate detection as a report, not an automatic merge. The caller chooses the keeper. Preview merge first; union memberships, tags, notes, and attachments; collapse only byte-identical PDFs; retain different PDFs. Multiple marked Full Text attachments block merge until one is selected. Confirmed discarded items go to Trash.

## Network

Only explicit DOI/arXiv/URL ingest, PDF fetching, metrics, and Zotero sync may use external services. Tell the user which service was contacted. Never send Full Text.
