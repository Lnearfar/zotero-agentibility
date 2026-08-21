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
- The index is fresh and profile-specific under `~/.local/share/zotero-agentibility/index/<zotero-profile>/`; the existing `~/.config/zotero-mcp/chroma_db` is never read, changed, or migrated.
- Only Chroma's local ONNX MiniLM embedding is supported. Cloud embeddings, OpenAI Batch, query translation, and sending paper text off-machine are prohibited.
- The installed reranker is disabled and depends on PyTorch/Transformers; it is not part of the ONNX-only runtime selected for this project.
- Foreground retrieval uses the existing index immediately. Changed Literature Items enter a durable refresh queue and an independent worker performs scoped updates; search never waits for maintenance. There is no startup/pre-search full update.
- The CLI reads the active local My Library through immutable SQLite and local attachment files; it does not silently fall back to a remote Zotero API. Zotero Desktop must still be running, as required project-wide; “local-only” does not mean offline SQLite operation.

## Passage and metadata contract

Each Chroma record stores an exact source Passage as its document. Matching the baseline's `structured metadata + full text` chunking, the Literature Item title, creators, abstract, publication, and tags prefix the first Passage's embedding input; subsequent vectors represent their source Passages rather than repeating a long metadata prefix that would consume MiniLM's 256-token window. Scalar metadata remains attached to every record:

- Item Key, item type, title, creators, dates, DOI, publication, and tags;
- source kind, attachment key, source SHA-256, and item/source fingerprint;
- chunk index/count, character offsets, and `partial` coverage state;
- exact Markdown line range, or PDF page/page range when page boundaries are present.

Grounded citations use `[ITEM_KEY, fulltext.md, lines N–M]` or `[ITEM_KEY, PDF, page N]`. Markdown never receives inferred PDF page numbers.

## Commands and scope

- `za-cli index update [--force]` synchronously compares a stored per-Item inventory with current Zotero revisions and source file stats, then reads, extracts, splits, and embeds only new or changed sources. `--collection PATH` or repeatable `--item KEY` provides an explicit scoped update; `--force` rebuilds the selected scope. Keep this for initialization, diagnosis, and operator recovery.
- `za-cli index reconcile` performs a full synchronous update for scheduled maintenance, emits compact error counts instead of every Item error, and exits successfully when the pass completed even if coverage remains partial.
- `za-cli index refresh --item KEY` durably queues one or more Literature Items and returns without embedding.
- `za-cli index worker --once` discovers changes, consumes one bounded queue batch, and exits nonzero when any Item remains failed. `za-cli index worker` is a long-lived foreground process; it sleeps when idle and does not daemonize itself. Installation registers it as a low-priority user systemd service.
- `za-cli index status` reads persisted readiness, freshness, coverage, worker state, and queue backlog without traversing Chroma. Legacy state may report `stats_stale` until the next update or explicit `index status --deep` reconciliation.
- `za-cli index status --deep` traverses Passage metadata, refreshes persisted statistics, and is reserved for explicit diagnosis rather than agent startup.
- `za-cli index inspect` exposes stored metadata and optional Passage documents for diagnosis.
- `za-cli search QUERY` searches the active Library and returns the best Passage for each distinct Literature Item plus cached `index` freshness metadata. Reading freshness never triggers maintenance or a Passage traversal; `possibly_stale` remains true until dirty tracking can account for external Zotero changes.
- `za-cli search QUERY --collection PATH` restricts results to that Collection and descendants.
- `za-cli search QUERY --item ITEM_KEY` returns multiple matching Passages from one Literature Item.
- `--filters JSON` preserves generic Chroma metadata filtering. Session cwd never scopes semantic search.

A successful CLI-originated Full Text mutation durably queues the affected Literature Item. If enqueueing fails, the Zotero mutation remains committed and is reported with an index warning. Zotero parent/attachment metadata changes are discovered automatically by the worker's SQLite watermark; externally edited linked-file contents without a Zotero metadata change are covered by periodic `index reconcile`. Use explicit `index update` or `index reconcile` for unknown bulk changes or operator recovery. Indexes created before the inventory format receive one full compatibility pass; subsequent unchanged updates perform only the cheap SQLite inventory and file-stat scan.

## Refresh queue and worker

Queue events live beside the profile-specific index under `queue/pending/`. Each mode-`0600` JSON event contains one Item Key, enqueue time, and reason; atomic rename and directory `fsync` make acknowledgement crash-safe. The worker snapshots at most 100 distinct keys, coalesces duplicates, and calls the existing scoped `SemanticIndex.update(item_keys=...)`. Events created during an update remain for the next batch.

One non-blocking `worker.lock` permits a single worker. `update.lock` still serializes Chroma writes against explicit synchronous updates. The worker deletes and directory-syncs only snapshot events for successful Item Keys; failed keys, lock contention, or process termination leave events pending for retry. While a worker processes the queue, malformed events move to `queue/failed/`; without a worker they remain counted as invalid pending events. Reprocessing after a crash is safe because source signatures make unchanged scoped updates idempotent.

The continuous worker polls the small durable queue and performs a lightweight SQLite watermark query; it does not scan the full library, Chroma, or full text on each cycle. Failed batches are logged to stderr and retry with process-local exponential backoff capped at five minutes. A synchronous `index update` does not acknowledge queued events, because a concurrent event may represent a later change; a subsequent worker pass safely rechecks and acknowledges them. Search's `refreshing` flag means a worker is actively processing a batch, not merely alive, and does not weaken `possibly_stale: true`.

The worker maintains a global UTC time cursor in `watermark.json`, querying Zotero parent and attachment `dateModified` values between the cursor and the current cycle time. The first run establishes the current cursor without historical backfill; later cycles enqueue changed parent Item Keys. The query overlaps the boundary timestamp, so it may repeat an Item but cannot lose a same-second change; scoped source signatures make repetition cheap. This detects Zotero metadata/attachment changes without scanning the full library, Chroma, or full text.

A low-priority user timer first runs full `index reconcile` about 15 minutes after activation, with up to 15 minutes of randomized delay, and then schedules it about every 12 hours. It catches deleted Items, externally edited linked files, and missed events. Zotero Extension notifier integration remains a future lower-latency producer. Search continues to report `possibly_stale: true` because worker/timer maintenance is asynchronous.

Replacing Markdown removes obsolete chunks after the replacement chunks are prepared. Removing Markdown or deleting a queued Literature Item removes its stale indexed Passages during the scoped update. Failed extraction or embedding does not silently erase the previous usable records.
