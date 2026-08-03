# Retrieval

Find candidate Literature Items, read bounded source Passages, and return grounded answers.

## Workflow

1. Before the first semantic search in each conversation, refresh once; tell the user before starting an unscoped library refresh because a first compatibility pass or many changed sources can take time, but do not delegate the command to the user:

   ```bash
   za-cli --json index status
   za-cli --json index update
   za-cli --json search "stability proof" --limit 10
   ```

   Do not repeat the full update in the same conversation unless the library changes. Report partial indexing errors rather than hiding missing coverage. Search covers My Library regardless of session cwd; use `--collection PATH` for an explicit recursive Collection scope or `--item ITEM_KEY` for several matching Passages within one paper.
2. Treat every semantic result as a lead. Inspect candidate metadata with `lookup ITEM_KEY`; do not select a paper from title similarity alone when identity matters.
3. Read every Passage needed for the answer:

   ```bash
   za-cli --session "$session" --json read ITEM_KEY --start LINE --limit 200
   ```

   Follow `nextStart` only as far as needed. Use `find ITEM_KEY "exact phrase" --context 8` for lexical confirmation. Use `read --all` only when the user explicitly requests the entire raw article; the Agent host may still truncate it.
4. Verify claim wording against returned source lines or PDF pages. If the source or index is partial, ambiguous, missing, or OCR-only, state that limit rather than filling the gap.
5. Answer concisely with Item Keys and exact locations. For a bibliography-style list, use `Author (Year), Title — Item Key: KEY`.

## Source selection

`source ITEM_KEY` reports the selected attachment. Markdown Full Text wins. Without Markdown, one PDF is selected automatically; multiple PDFs require an explicit source selection before reading or indexing. Never treat a Note, Annotation, `distill.md`, or `probe_distill.md` as paper Full Text.
