# Upstream provenance

This component is based on inspection of [`PiaoyangGuohai1/cli-anything-zotero`](https://github.com/PiaoyangGuohai1/cli-anything-zotero) at commit `f621952f3645546573d622440cbf707320f7a35f` (Apache License 2.0).

Safe relevant behavior was reimplemented for this read-only slice: Linux Zotero path discovery, immutable read-only SQLite access, Local API probing, attachment path resolution, compact agent results, and locked session persistence. The implementation is materially rewritten under the `zotero_cli` namespace and removes direct SQLite writes, arbitrary JavaScript, cloud LLMs, semantic indexing, DOCX automation, REPL support, and installers.

Files carrying a source-level derivation notice:

- `src/zotero_cli/db.py`
- `src/zotero_cli/http.py`
- `src/zotero_cli/sessions.py`
- `src/zotero_cli/sources.py`

The upstream Apache-2.0 `LICENSE` is included unchanged. No upstream NOTICE file existed at the pinned commit.
