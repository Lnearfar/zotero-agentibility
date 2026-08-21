# Shorten Zotero attachment role tags

The project changes its Zotero attachment markers:

- `za-cli:fulltext` → `za-cli:md`
- `za-cli:source` → `za-cli:pdf`

`za-cli:md` continues to mean canonical Markdown Full Text.
It does not mark arbitrary Markdown attachments.

`za-cli:pdf` continues to mean the selected Source Document PDF.
It does not mark every PDF attachment.

The semantic roles and source-selection rules are unchanged.
