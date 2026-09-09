---
name: research-with-zotero
description: Use when helping a researcher search, navigate, read, verify, and manage full-text literature in a local Zotero library through za-cli.
license: Apache-2.0
compatibility: Linux; requires Zotero Desktop running, za-cli, the matching Zotero Extension, and Poppler.
---

# Research with Zotero

Instructions for using `za-cli` with the local Zotero library.

## What is `za-cli`?

A command-line interface for searching, reading, and managing Zotero literature.

- Semantic search across PDF and Markdown contents.
- Library and Collection browsing.
- Canonical Markdown storage alongside PDFs.
- Local PDF/EPUB import and metadata recognition.

Start the requested operation directly. Use command `--help` when syntax is unknown, not as routine preparation. Zotero's Extension starts the indexing worker and shows its status in the **Agentibility Console**.

## Common workflows

### A1: Search contents in the library

```bash
za-cli --json search "stability proof" --limit 5
za-cli --json lookup ITEM_KEY
za-cli --json read ITEM_KEY --start 1 --limit 40
```

Search first, then read promising sources before answering. For filtering, quotations, and source verification, read [references/retrieval.md](references/retrieval.md).

### A2: Convert a PDF to canonical Markdown

1. When requested, use an available conversion skill to convert the PDF to Markdown.
2. Review the output against the PDF.
3. With the user's approval, import it under the Literature Item:

```bash
za-cli --json fulltext import ITEM_KEY /path/to/fulltext.md --confirm
```

Zotero stores the Markdown attachment; the background worker updates the index. Do not wait for embedding or ask the user to maintain the index manually.

### A3: Resolve a standalone document

For a PDF/EPUB already in Zotero without a parent Literature Item, get the user's approval and run:

```bash
za-cli --json resolve ATTACHMENT_KEY --confirm
```

Use the returned `parent_item_key` for subsequent Full Text imports. If recognition is unresolved, report it rather than guessing metadata. For reviewed-Markdown fallback and write outcomes, read [references/mutations.md](references/mutations.md).

### A4: Add a local PDF or EPUB

With the user's approval:

```bash
za-cli --json add file /path/to/paper.pdf --confirm
```

This preserves the local file, copies it into Zotero, and attempts metadata recognition. For an existing parent, Collection placement, and duplicate handling, read [references/mutations.md](references/mutations.md).

### A5: Browse the library

```bash
za-cli --json ls
za-cli --json ls --collection COLLECTION_KEY
```

For bulk adoption of existing Markdown attachments, read [references/migration.md](references/migration.md).

## Rules

- Zotero owns its data. Writes require user intent and the installed confirmed commands; never write its database/storage directly, execute arbitrary Zotero JavaScript, permanently delete data, or write to group libraries.
- A child attachment tagged `za-cli:md` is canonical Full Text, even after PDF changes. Notes and Annotations are not Full Text.
- Search and read do not change the library or trigger indexing. Do not run doctor or index maintenance before ordinary retrieval.
- On a connectivity/dependency failure, use `za-cli --json app doctor`. For missing recent semantic results, inspect `index status` and Zotero's Agentibility Console; a missing semantic result does not prove the Item is absent from Zotero. Follow the retrieval reference for index initialization or explicit freshness.
- Cite verified passages as `[ITEM_KEY, fulltext.md, lines N–M]` or `[ITEM_KEY, PDF, page N]`. Never infer PDF pages from Markdown or treat search snippets as verified claims.

Use `$rwzSkillDir` for the absolute path to this skill directory. Replace it with that quoted path in Bash commands. Do not inspect the repository or read a bundled script unless its command fails.
