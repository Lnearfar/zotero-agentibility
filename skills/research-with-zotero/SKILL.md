---
name: research-with-zotero
description: Use when searching, navigating, reading, verifying, organizing, importing, deduplicating, or managing full-text literature in a local Zotero library through za-cli.
license: Apache-2.0
compatibility: Linux; requires Zotero Desktop running, za-cli, the matching Zotero Extension, and Poppler.
---

# Research with Zotero

Use `$rwzSkillDir` for the absolute path to this skill directory. Replace it with that quoted path in Bash commands. Do not inspect the repository or read a bundled script unless its command fails.

## Start

Start the requested Zotero operation immediately. Do not run CLI help, `app doctor`, index status/update, or create a Browsing Session as routine preparation.

- For retrieval, follow `references/retrieval.md` and search the existing index first.
- Run command help only when needed syntax is unknown or a command rejects the attempted syntax.
- Run `za-cli --json app doctor` only after a CLI connectivity or dependency failure. Use `app doctor --deep` only for explicit index diagnosis.
- Create one Browsing Session only when Collection navigation or another command requires it. Prefer `ZA_CLI_SESSION`, then `PI_SESSION_ID`; create the chosen ID if status returns `SESSION_NOT_FOUND`. Pass it explicitly to session-aware commands.
- On `INDEX_UNINITIALIZED`, run `za-cli --json index update` once before retrying search. For an explicit freshness requirement, refresh the affected Item or Collection when known; use a full update only when the changed scope is unknown.

## Workflow boundary

CLI help owns installed command names, arguments, and options. This Skill owns the multi-command workflows, source-verification rules, and safety invariants below because command help cannot express them.

The installed CLI provides local semantic `search`, explicit index management, confirmed Full Text writes, and top-level `resolve` for standalone PDF/EPUB metadata. General ingest, merge, arbitrary metadata/Collection editing, and all other mutations remain unavailable.

## Route

- For semantic discovery, reading a known Item Key, quotation, or source verification, read and follow [references/retrieval.md](references/retrieval.md).
- For navigation only, use `pwd`, `cd`, and `ls`; Collection paths navigate, while Item Keys identify Literature Items. Canonical absolute paths begin with `/My Library/`; `My Library/...` is accepted as the same absolute path, while other paths are relative to the current Collection. If a path is ambiguous, use the reported Collection Key with `cd --collection`.
- For additions, metadata changes, Collection Membership, full-text changes, duplicate handling, or removal, read and follow [references/mutations.md](references/mutations.md).
- For adopting existing `source.md` or paper-named Markdown attachments in bulk, read and follow [references/migration.md](references/migration.md).

## Invariants

- A tagged Markdown child attachment is canonical Full Text regardless of PDF changes. Zotero Notes and Annotations are never Full Text.
- Search and read are side-effect-free. When initialization or explicit freshness requires indexing, run it as a separate visible command; never hide it inside search.
- Foreground retrieval reads the existing index; maintenance is not a prerequisite for search. Never ask the user to maintain the index manually.
- Treat search snippets as leads. Read the source Passage before making a factual claim.
- Cite verified claims as `[ITEM_KEY, fulltext.md, lines N–M]` or `[ITEM_KEY, PDF, page N]`. Never infer PDF pages for Markdown.
- Never write `zotero.sqlite`, execute arbitrary Zotero JavaScript, permanently delete data, or write to a group library.
