# Retrieval

Find candidate Literature Items, read bounded source Passages, and return grounded answers.

## Workflow

1. Obtain a stable Item Key from the user or by navigating known Collections with `ls`. Version 0.2.0 has no library-wide semantic search; report that limitation rather than scanning the entire Library.
2. Inspect candidate metadata with `lookup ITEM_KEY`. Do not select a paper from title similarity alone when identity matters.
3. Read every Passage needed for the answer:

   ```bash
   zotero-cli --session "$session" --json read ITEM_KEY --start LINE --limit 200
   ```

   Follow `nextStart` only as far as needed. Use `find ITEM_KEY "exact phrase" --context 8` for lexical confirmation. Use `read --all` only when the user explicitly requests the entire raw article; the Agent host may still truncate it.
4. Verify claim wording against returned source lines or PDF pages. If the source is partial, ambiguous, missing, or OCR-only, state that limit rather than filling the gap.
5. Answer concisely with Item Keys and exact locations. For a bibliography-style list, use `Author (Year), Title — Item Key: KEY`.

## Source selection

`source ITEM_KEY` reports the selected attachment. Markdown Full Text wins. Without Markdown, one PDF is selected automatically; multiple PDFs require an explicit source selection before reading or indexing. Never treat a Note, Annotation, `distill.md`, or `probe_distill.md` as paper Full Text.
