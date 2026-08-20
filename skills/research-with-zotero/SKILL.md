---
name: research-with-zotero
description: Use when searching, navigating, reading, verifying, organizing, importing, deduplicating, or managing full-text literature in a local Zotero library through za-cli.
license: Apache-2.0
compatibility: Linux; requires Zotero Desktop running, za-cli, the matching Zotero Extension, and Poppler.
---

# Research with Zotero

Use `$rwzSkillDir` for the absolute path to this skill directory. Replace it with that quoted path in Bash commands. Do not inspect the repository or read a bundled script unless its command fails.

## Start

1. Run `za-cli --help` to verify the installed CLI and see its current commands. CLI help is authoritative for command syntax:
   - run `za-cli COMMAND --help` for a top-level command;
   - run `za-cli GROUP COMMAND --help` for a grouped command.
   Do not inspect the package or invent a command when help is sufficient.
2. Run `za-cli --json app doctor`. Stop and report the failed check if Zotero, the Extension, token permissions, protocol version, or Poppler is unavailable. Do not install components.
3. Choose one Browsing Session ID for the whole conversation:
   - use `ZA_CLI_SESSION` when set;
   - otherwise use `PI_SESSION_ID` when set;
   - otherwise run `za-cli --json session create` once and keep the returned ID.
4. For a selected environment-provided ID, run `za-cli --session <ID> --json session status`. If and only if it returns `SESSION_NOT_FOUND`, create it with `za-cli --json session create <ID>`; stop on any other error.
5. Pass `--session <ID>` explicitly to every session-aware command. Never rely on Zotero UI selection or a global cwd.

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
- Search and read are side-effect-free. Run indexing as an explicit preceding step, never as a hidden side effect.
- The Agent owns index freshness; never ask the user to run `index update`. Follow the refresh points in the retrieval and mutation references.
- Treat search snippets as leads. Read the source Passage before making a factual claim.
- Cite verified claims as `[ITEM_KEY, fulltext.md, lines N–M]` or `[ITEM_KEY, PDF, page N]`. Never infer PDF pages for Markdown.
- Never write `zotero.sqlite`, execute arbitrary Zotero JavaScript, permanently delete data, or write to a group library.
