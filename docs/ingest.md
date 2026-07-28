# Ingest and reuse

`add` searches the active library before creating a Literature Item. Exact Item Key, normalized scholarly identifier, or identical file SHA-256 reuses the existing item; title/author/year similarity only reports a candidate. `add file PATH` remains local and refuses to create an unidentified standalone PDF: a new unmatched file requires explicit `--lookup` for network metadata resolution or `--parent ITEM_KEY` to attach it to a known item.

When an existing item is reused, requested Collection Memberships and missing metadata are added without removing existing state:

- An identical incoming PDF is not uploaded again.
- If no Source Document exists, the incoming PDF may become it.
- If a Source Document exists and the incoming PDF hash differs, the item and membership are reused but the new PDF is not attached or substituted automatically. The command reports the conflict.
- Adding or replacing PDFs does not change the canonical Markdown Full Text; only an explicit `fulltext replace` changes it.

PDFs dragged directly into the Zotero UI bypass CLI preflight and may create Duplicate Items. Duplicate detection reports these later; merging remains explicit and moves discarded items to Trash.

## Duplicate merging

Item merging is a dry run unless explicitly confirmed with a caller-selected keeper. It unions Collection Memberships, tags, notes, and child attachments; byte-identical PDFs collapse to one while different PDFs remain as alternatives. More than one marked Markdown Full Text blocks the merge until one is selected. Merged-away Literature Items move to Trash.

## Existing Markdown

`fulltext audit` reports unmarked Markdown attachment candidates, multiple candidates, missing files, and ambiguous source PDFs without changing Zotero; it never treats Zotero Notes or Annotations as candidates. `fulltext adopt ITEM_KEY MD_ATTACHMENT_KEY` explicitly copies the selected content unchanged into canonical `fulltext.md`, records its Source Document, and moves the replaced full-text attachment to Trash. Other Markdown attachments remain unmarked and untouched; multiple source PDFs require explicit selection.
