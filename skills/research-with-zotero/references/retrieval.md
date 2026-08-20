# Retrieval

Find candidate Literature Items, read bounded source Passages, and return grounded answers. The hot path reads the existing semantic index; do not perform a full-library refresh before ordinary search.

## Workflow

1. Search immediately:

   ```bash
   za-cli --json search "stability proof" --limit 5
   ```

   Search covers My Library regardless of session cwd and returns cached index freshness metadata. `possibly_stale` is provenance, not a reason to block ordinary retrieval. Use `--collection PATH` for an explicit recursive Collection scope or `--item ITEM_KEY` for several matching Passages within one paper.
2. If search returns `INDEX_UNINITIALIZED`, initialize the index once with `za-cli --json index update`, report any partial errors, then retry. If the user explicitly requires newly synchronized content, queue known Items with `index refresh --item KEY`; use synchronous `index update --collection PATH` for a known Collection. Do not block the request on a full-library update when the changed scope is unknown.
3. Treat every semantic result as a lead. Inspect candidate metadata with `lookup ITEM_KEY`; do not select a paper from title similarity alone when identity matters.
4. Read every Passage needed for the answer:

   ```bash
   za-cli --json read ITEM_KEY --start LINE --limit 200
   ```

   Follow `nextStart` only as far as needed. Use `find ITEM_KEY "exact phrase" --context 8` for lexical confirmation. Use `read --all` only when the user explicitly requests the entire raw article; the Agent host may still truncate it.
5. Verify claim wording against returned source lines or PDF pages. If the source or index is partial, ambiguous, missing, or OCR-only, state that limit rather than filling the gap.
6. Answer concisely with Item Keys and exact locations. For a bibliography-style list, use `Author (Year), Title — Item Key: KEY`.

## Source selection

`source ITEM_KEY` reports the selected attachment. Markdown Full Text wins. Without Markdown, one PDF is selected automatically; multiple PDFs require an explicit source selection before reading or indexing. Never treat a Note, Annotation, `distill.md`, or `probe_distill.md` as paper Full Text.
