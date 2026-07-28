# Semantic indexing and search

## Compatibility baseline

The behavioral baseline is the locally installed `zotero-mcp-server` 0.6.2 semantic search, not the single-vector title/abstract experiment in `cli-anything-zotero`. The replacement must preserve these local-default capabilities:

- persistent Chroma passage vectors using its local ONNX `all-MiniLM-L6-v2` embedding;
- explicit update, force rebuild, status, and database inspection;
- 1,500-character passages with 200-character overlap and natural-boundary splitting;
- Literature Item metadata plus attachment full text in the embedding input;
- metadata filters, recursive Collection scope, and per-item scope;
- global result grouping by Literature Item after over-fetching Passage candidates;
- `1 - distance` similarity score, complete matched Passage text, and a 320-character query-term snippet;
- incremental replacement, stale-chunk and deleted-item removal, bounded Chroma batches, and a cross-process update lock;
- source, attachment, hash, chunk, and location provenance on every result.

`search` never updates the index implicitly. Search snippets are leads; agents verify claims with `read`.

## Intentional project differences

These are earlier project decisions, not reduced search behavior:

- Canonical Markdown Full Text is indexed first; the selected Source Document PDF is fallback. Zotero Notes and Annotations are excluded.
- Markdown is indexed completely. There is no silent per-item chunk cap; a real extraction limit must set `partial` and report its covered range.
- The index is fresh and profile-specific under `~/.local/share/zotero-paper-agent/index/<zotero-profile>/`; the existing `~/.config/zotero-mcp/chroma_db` is never read, changed, or migrated.
- Only Chroma's local ONNX MiniLM embedding is supported. Cloud embeddings, OpenAI Batch, query translation, and sending paper text off-machine are prohibited.
- The installed reranker is disabled and depends on PyTorch/Transformers; it is not part of the ONNX-only runtime selected for this project.
- Updating is explicit. There is no startup/pre-search update, watcher, daemon, or scheduled refresh.
- The CLI reads the active local My Library through immutable SQLite and local attachment files; it does not silently fall back to a remote Zotero API. Zotero Desktop must still be running, as required project-wide; “local-only” does not mean offline SQLite operation.

## Passage and metadata contract

Each Chroma record stores an exact source Passage as its document. Matching the baseline's `structured metadata + full text` chunking, the Literature Item title, creators, abstract, publication, and tags prefix the first Passage's embedding input; subsequent vectors represent their source Passages rather than repeating a long metadata prefix that would consume MiniLM's 256-token window. Scalar metadata remains attached to every record:

- Item Key, item type, title, creators, dates, DOI, publication, and tags;
- source kind, attachment key, source SHA-256, and item/source fingerprint;
- chunk index/count, character offsets, and `partial` coverage state;
- exact Markdown line range, or PDF page/page range when page boundaries are present.

Grounded citations use `[ITEM_KEY, fulltext.md, lines N–M]` or `[ITEM_KEY, PDF, page N]`. Markdown never receives inferred PDF page numbers.

## Commands and scope

- `zotero-cli index update [--force]` scans My Library explicitly and incrementally rebuilds changed sources; `--collection PATH` or repeatable `--item KEY` provides an explicit scoped update.
- `zotero-cli index status` reports path, model, count, item count, source coverage, and last update without modifying the index.
- `zotero-cli index inspect` exposes stored metadata and optional Passage documents for diagnosis.
- `zotero-cli search QUERY` searches the active Library and returns the best Passage for each distinct Literature Item.
- `zotero-cli search QUERY --collection PATH` restricts results to that Collection and descendants.
- `zotero-cli search QUERY --item ITEM_KEY` returns multiple matching Passages from one Literature Item.
- `--filters JSON` preserves generic Chroma metadata filtering. Session cwd never scopes semantic search.

A successful CLI-originated Full Text mutation rebuilds only the affected Literature Item. If rebuilding fails, the Zotero mutation remains committed and is reported with an index warning. Changes made outside this CLI are found by the next explicit `index update`.

Replacing Markdown removes obsolete chunks after the replacement chunks are prepared. Removing Markdown causes the next update to rebuild from the selected Source Document. Failed extraction or embedding does not silently erase the previous usable records.
