# Upstream provenance

This component is based on inspection of [`PiaoyangGuohai1/cli-anything-zotero`](https://github.com/PiaoyangGuohai1/cli-anything-zotero) at commit `f621952f3645546573d622440cbf707320f7a35f` (Apache License 2.0).

Safe relevant behavior was reimplemented: Linux Zotero path discovery, immutable read-only SQLite access, Local API probing, attachment path resolution, compact agent results, and locked session persistence. Confirmed Full Text writes use this project's separate fixed-operation authenticated Extension rather than upstream's eval bridge. The implementation is materially rewritten under the `za_cli` namespace and removes direct SQLite writes, arbitrary JavaScript, cloud LLMs, DOCX automation, REPL support, and installers.

The semantic-search behavior, natural-boundary passage splitting, lexical matched snippet, Chroma grouping, and local update lifecycle were also derived from the locally installed [`54yyyu/zotero-mcp`](https://github.com/54yyyu/zotero-mcp) 0.6.2 under the MIT License, then rewritten for canonical-Markdown-first source selection, complete uncapped indexing, exact source provenance, and an ONNX-only local runtime. Its license is retained at `LICENSES/zotero-mcp-MIT.txt`.

Files carrying a source-level derivation notice:

- `src/za_cli/db.py`
- `src/za_cli/http.py`
- `src/za_cli/sessions.py`
- `src/za_cli/sources.py`
- `src/za_cli/semantic.py`

The upstream Apache-2.0 `LICENSE` is included unchanged. No upstream NOTICE file existed at the pinned commit.
