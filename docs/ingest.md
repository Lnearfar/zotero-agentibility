# Ingest and reuse

`add` searches the active library before creating a Literature Item. Exact Item Key, normalized scholarly identifier, or identical file SHA-256 reuses the existing item; title/author/year similarity only reports a candidate. `add file PATH` remains local and refuses to create an unidentified standalone PDF: a new unmatched file requires explicit `--lookup` for network metadata resolution or `--parent ITEM_KEY` to attach it to a known item.

When an existing item is reused, requested Collection Memberships and missing metadata are added without removing existing state:

- An identical incoming PDF is not uploaded again.
- If no Source Document exists, the incoming PDF may become it.
- If a Source Document exists and the incoming PDF hash differs, the item and membership are reused but the new PDF is not attached or substituted automatically. The command reports the conflict.
- Adding or replacing PDFs does not change the canonical Markdown Full Text; only an explicit `fulltext import --replace` or `fulltext adopt --replace` changes it.

PDFs dragged directly into the Zotero UI bypass CLI preflight and may create Duplicate Items. Duplicate detection reports these later; merging remains explicit and moves discarded items to Trash.

## Duplicate merging

Item merging is a dry run unless explicitly confirmed with a caller-selected keeper. It unions Collection Memberships, tags, notes, and child attachments; byte-identical PDFs collapse to one while different PDFs remain as alternatives. More than one marked Markdown Full Text blocks the merge until one is selected. Merged-away Literature Items move to Trash.

## Metadata resolution

`resolve ATTACHMENT_KEY --markdown PATH --confirm` turns an Unrecognized Document into a Literature Item without manual Zotero UI entry. Zotero's native PDF/EPUB recognizer runs first and must return a Strong Identifier; if it cannot, the reviewed Markdown may supply exactly one normalized DOI, ISBN, arXiv ID, PMID, or ADS Bibcode for `Zotero.Translate.Search`. ISBN-10 and its equivalent ISBN-13 count as one identity. Ambiguous identifiers, title-only records, and mismatched translated titles remain unresolved.

Resolution preserves Collection Memberships, attaches the original PDF or EPUB to the resulting Literature Item, and returns the new parent Item Key. Markdown import remains a separate explicit step so a successful metadata write is not rolled back merely because Full Text import needs to be retried.

## Markdown Full Text

`fulltext import ITEM_KEY PATH --confirm` copies a reviewed local Markdown file unchanged into canonical `fulltext.md` while preserving the local source. The source must be a regular non-symlink `.md` file; `distill.md` and `probe_distill.md` are rejected. Existing canonical Full Text requires every marked attachment key to be supplied explicitly with repeatable `--replace`.

`fulltext audit` reports unmarked Markdown attachment candidates, multiple candidates, missing files, and ambiguous source PDFs without changing Zotero; it never treats Zotero Notes or Annotations as candidates. `fulltext adopt ITEM_KEY MD_ATTACHMENT_KEY --confirm` explicitly copies the selected content unchanged into canonical `fulltext.md`, marks the unique Source Document, and moves the adopted source and any explicitly selected `--replace` Full Text attachments to Trash. Other Markdown attachments remain unmarked and untouched; multiple source PDFs require explicit selection.
