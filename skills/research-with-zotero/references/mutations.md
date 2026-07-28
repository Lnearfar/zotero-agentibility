# Mutations

Version 0.1.0 has no write commands. Explain that boundary and stop; the rules below constrain the later write-capable release and must never be simulated through SQLite or arbitrary JavaScript.

## Rules

- Run the command's dry run or preview when available. Show ambiguity before changing Zotero.
- Writes are My Library only and globally serialized. On a busy timeout, report a retryable failure; do not bypass the lock.
- Removal means Zotero Trash. Never request permanent deletion or empty Trash.
- A Literature Item may belong to several Collections. Removing a Collection Membership does not remove the item.
- Reuse an existing item only on exact Item Key, normalized DOI/arXiv/PMID/ISBN, or identical source SHA-256. Similar metadata is review-only.
- Local `add file PATH` must not create an unidentified standalone PDF. Use explicit `--lookup` for network metadata or `--parent ITEM_KEY` for a known item.
- A different incoming PDF never replaces an existing Source Document automatically.

## Full text

PDF-to-Markdown conversion is external to this project and runs only on explicit user intent. Give the external converter the selected PDF; do not require a particular converter. Import its resulting Markdown unchanged with the relevant `fulltext set`, `fulltext replace`, or `fulltext adopt` command.

Before replacement, identify the existing Markdown attachment. If several attachments are marked Full Text, stop and require an explicit attachment key. Preserve `distill.md` and all unrelated Markdown. Converted image assets are not imported; inspect the PDF when figures matter.

## Duplicates

Use duplicate detection as a report, not an automatic merge. The caller chooses the keeper. Preview merge first; union memberships, tags, notes, and attachments; collapse only byte-identical PDFs; retain different PDFs. Multiple marked Full Text attachments block merge until one is selected. Confirmed discarded items go to Trash.

## Network

Only explicit DOI/arXiv/URL ingest, PDF fetching, metrics, and Zotero sync may use external services. Tell the user which service was contacted. Never send Full Text.
