# Semantic indexing

> Target design; semantic indexing is not implemented in v0.1.0.

## Planned update policy

- Build a fresh profile-specific Chroma index under `~/.local/share/zotero-agent-library/index/<zotero-profile>/` with Chroma's built-in ONNX `all-MiniLM-L6-v2` embedding model. Do not modify or migrate the existing zotero-mcp index; the user may remove it after validating the replacement. Semantic queries are English; query translation and cloud embeddings are outside the initial design.
- Resolve one preferred full-text source per Literature Item: use its tagged Markdown child attachment when present, regardless of PDF changes; otherwise fall back to the sole or explicitly selected Source Document. Multiple PDFs without Markdown require `source use` before reading or indexing. Include Literature Item metadata, but exclude Zotero Notes and Annotations so personal commentary cannot be mistaken for source text.
- Store source kind, attachment key, content hash, and Passage location with every indexed chunk.
- Index every Markdown Passage in batches without a silent per-item chunk cap. Any source-size or PDF-extraction limit marks the item as `partial` and reports the covered range.
- `fulltext set`, `fulltext replace`, and `fulltext use` rebuild only the affected Literature Item after the Zotero mutation succeeds.
- Changes made outside this CLI are discovered by an explicit incremental `zotero-cli index update`.
- `search` performs passage-level semantic similarity search by default, groups global results by Literature Item, and returns the best Passage for each distinct item. Session cwd never silently scopes it: the default covers the active Library, `--collection PATH` explicitly limits it recursively, and `--item ITEM_KEY` returns multiple matching Passages within one item. Search never starts an update implicitly. Exact metadata lookup and within-item lexical finding remain separate operations. No watcher, daemon, or scheduled refresh is part of the initial design.
- Replacing Markdown removes the item's old chunks before inserting the new Markdown chunks. Removing Markdown causes the next update to rebuild that item from its Source Document.

Agents treat search snippets only as leads and verify claims with `read`. Grounded answers cite `[ITEM_KEY, fulltext.md, lines N–M]` or `[ITEM_KEY, PDF, page N]`; Markdown never receives inferred PDF page numbers.

Revisit background updating only if manual incremental updates measurably leave the index stale in normal use.
