# Ingest and reuse

The installed local intake command is:

```text
za-cli --session SESSION --json add file PATH [--collection COLLECTION_KEY] [--parent ITEM_KEY] --confirm
```

It imports a user-selected local PDF or EPUB through Zotero. General identifier/URL ingest, PDF acquisition, and duplicate merge remain planned.

## `add file` contract

1. **Zotero-owned copy.** `PATH` must be a regular non-symlink PDF or EPUB. The CLI records a SHA-256 review snapshot; the Extension asks Zotero to detect the MIME type, then calls `Zotero.Attachments.importFromFile`. Zotero copies the document into attachment storage. The source file is never moved, deleted, or rewritten.
2. **Explicit placement.** `--collection COLLECTION_KEY` adds an explicit Collection Membership. Omitting it leaves a new top-level object Unfiled. The command never inherits a Browsing Session's current Collection. Reusing an existing Literature Item adds the requested membership without removing existing memberships.
3. **Default native recognition.** Without `--parent`, the Extension runs Zotero's native PDF/EPUB recognizer on the imported copy. A verified parent is used; failed or unverifiable recognition returns `added_unrecognized` and keeps the standalone Unrecognized Document rather than guessing metadata.
4. **Explicit parent.** `--parent ITEM_KEY` attaches the imported copy to that live, editable My Library Literature Item and skips recognition. If the parent has no Source Document, the incoming PDF/EPUB becomes the selected source. If it already has a source, the incoming document remains an alternate and does not replace or acquire the source marker.
5. **Source role.** Only a selected PDF child receives `za-cli:pdf`; a sole EPUB is an unmarked fallback Source Document. `source` reports its metadata and path, while `read`/`find` return `UNSUPPORTED_SOURCE_FORMAT` until reviewed Markdown exists. Standalone Unrecognized Documents receive no source role. `add file` never changes canonical Markdown Full Text.
6. **Library scope.** The first implementation writes only My Library. The fixed operation carries `library_id` so a later group-library milestone can add explicit permission handling without changing the command's identity model.

## Outcomes

Successful JSON results use an `outcome` field:

- `added`: Zotero imported the document and it has a parent Literature Item;
- `added_unrecognized`: Zotero imported the document but no verified parent was found;
- `reused`: an identical stored attachment or exact Strong Identifier reused existing Zotero state.

If a parent changed, the CLI enqueues that Item for background indexing. A queue failure after Zotero commits returns `status: committed_with_index_warning`; it does not roll back the Zotero write.

## Identity, reuse, and conflicts

A bounded add-flow guard serializes intake identity decisions without holding the global bridge write lock across full-library scans, native recognition, or fuzzy duplicate checks. Short mutation sections acquire the global lock and revalidate live state.

- Existing stored PDF/EPUB attachments are filtered by active library state and file size. Zotero's MD5 is only a cheap prefilter; live stored-file SHA-256 authorizes exact reuse and Strong-Identifier source equality. One exact match is reused; multiple exact matches return `IDENTICAL_ATTACHMENT_AMBIGUOUS` rather than choosing arbitrarily.
- An exact Strong Identifier (DOI, ISBN, arXiv ID, PMID, or ADS Bibcode) can reuse one existing Literature Item. If it has no Source Document, the incoming document is attached. If it has a different or ambiguous source, the operation returns `SOURCE_DOCUMENT_CONFLICT`.
- A rejected recognizer candidate and every incoming object created by a failed `add file` operation are erased through Zotero-native rollback. Pre-existing user objects are never erased. The local source remains untouched.
- Title/creator/year similarity comes only from `Zotero.Duplicates`. It produces warning candidates after the new Literature Item is committed; it never causes reuse or automatic merge.
- An identical attachment requested with a different explicit parent returns `ATTACHMENT_PARENT_CONFLICT`; the command does not silently reparent an existing user attachment.

Read-only SQLite may validate a candidate key quickly, but it cannot authorize the write. The Extension reloads live Items, Collections, permissions, attachment paths, MIME types, and hashes before the final Zotero transaction.

## Metadata-only network paths

Future `add identifier`, `add url`, and structured metadata `import` operations may call Zotero translators with `saveAttachments=false`. They do not discover or download PDFs, use browser cookies, authenticate to a campus proxy, or transmit paper Full Text. A Human or browser Skill decides whether to obtain a PDF and hands the core a local path or an existing Zotero Item.

## Existing-document metadata resolution

`resolve ATTACHMENT_KEY [--markdown PATH] --confirm` handles an Unrecognized Document already in Zotero. It calls Zotero's native recognizer first. If that does not yield a verified parent, reviewed Markdown may supply exactly one Strong Identifier to `Zotero.Translate.Search`; the translated result must match the Markdown title. Ambiguous identifiers, title-only matches, and translator conflicts remain unresolved.

Resolution preserves Collection Memberships, reparents the original document, and returns the parent Item Key. Markdown import remains separate so a successful metadata write is not undone when Full Text processing needs a retry.

## Markdown Full Text

`fulltext import ITEM_KEY PATH --confirm` copies reviewed local Markdown unchanged into canonical `fulltext.md` while preserving the source. The source must be a regular non-symlink `.md`; `distill.md` and `probe_distill.md` are rejected. Existing canonical Full Text requires every marked attachment key to be supplied explicitly with repeatable `--replace`.

`fulltext audit` reports candidates and conflicts without writing. `fulltext adopt ITEM_KEY MD_ATTACHMENT_KEY --confirm` copies the selected attachment into canonical `fulltext.md`, marks the unique Source Document, and moves the adopted source and explicitly selected replaced Full Text attachments to Trash. Zotero Notes and Annotations are never Full Text.
