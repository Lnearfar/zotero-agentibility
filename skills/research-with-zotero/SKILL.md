---
name: research-with-zotero
description: Use when helping a researcher search, navigate, read, verify, and manage full-text literature in a local Zotero library through za-cli.
license: Apache-2.0
compatibility: Linux; requires Zotero Desktop running, za-cli, the matching Zotero Extension, and Poppler.
---

# Research with Zotero

Use `za-cli` to research the local Zotero library and carry out user-requested changes.

## Command authority

The installed `za-cli --help` and nested command help are the sole authority for available commands, parameters, defaults, and outcomes. This skill supplies operating rules and common workflows, not a second command manual.

Start the requested operation directly. When details are unknown, read the relevant help, such as `za-cli fulltext import --help`; use top-level help to discover commands. Do not inspect repository source or assume planned capabilities exist. If an example here conflicts with installed help, follow the installed help.

## Research workflow

1. Search with a small result limit, then narrow using the first useful results:

   ```bash
   za-cli --json search "stability proof" --limit 5
   ```

2. Inspect promising Items and read the evidence needed for the answer:

   ```bash
   za-cli --json lookup ITEM_KEY
   za-cli --json read ITEM_KEY --start 1 --limit 40
   ```

   Use `find` for literal phrase verification and `source` to inspect the selected attachment. Read bounded passages; expand only as needed. Verify identity rather than choosing a paper from title similarity alone.

3. Answer from verified source text, not search snippets. Cite `[ITEM_KEY, fulltext.md, lines N–M]` or `[ITEM_KEY, PDF, page N]`. Never infer PDF pages from Markdown. State missing, ambiguous, partial, or OCR-limited evidence rather than filling gaps.

For catalog browsing rather than semantic content search:

```bash
za-cli --json ls
za-cli --json ls --collection COLLECTION_KEY
```

A missing semantic result does not prove an Item is absent from Zotero. Do not repeatedly broaden semantic queries to compensate for missing indexing.

## User-requested changes

Establish the target and intended changes before writing. Use explicit Item/Collection keys and the installed confirmed commands. User authorization must cover replacements or batch selections; `--confirm` is not itself evidence of user approval.

Choose the appropriate operation, then consult its help for details:

- Local PDF/EPUB: `add file`; a document already in Zotero without a parent: `resolve`. Use returned keys; do not guess metadata when recognition is unresolved.
- Local reviewed Markdown: `fulltext import`; an existing Markdown child: `fulltext adopt`.
- Bulk Markdown adoption: `fulltext audit`, review candidate decisions and exclusions with the user, then `fulltext migrate`.

When PDF-to-Markdown conversion is explicitly requested, use an available external conversion skill, review the output against the PDF, and import under the intended Literature Item:

```bash
za-cli --json fulltext import ITEM_KEY /path/to/fulltext.md --confirm
```

Report committed changes separately from warnings and failures. Do not blindly retry a write after a nonzero exit or lost connection; follow the command's outcome guidance. Never substitute direct Zotero database/storage writes or arbitrary JavaScript for a missing command. Do not permanently delete data or write to group libraries.

## Indexing and failures

The Zotero Extension owns background indexing. Do not run doctor or index maintenance before ordinary retrieval, wait for embedding after a successful write, or ask the user to maintain the index routinely.

On connectivity/dependency failures, use `za-cli --json app doctor`. For missing recent semantic results or an uninitialized index, inspect `index status` and Zotero's Agentibility Console, then follow the relevant index command help. Explicit freshness requests may justify maintenance; ordinary research does not.
