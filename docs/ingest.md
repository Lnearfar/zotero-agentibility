# Ingest and reuse

The current release does not install `add` or general ingest. It can resolve a
standalone PDF/EPUB that is already in Zotero with
`resolve ATTACHMENT_KEY [--markdown PATH] --confirm`, and it can import or adopt
reviewed Markdown Full Text for a known Literature Item. The contract below is
the accepted implementation checkpoint for the planned native-first
`add file` path; it must not be described as an available command until it
appears in `za-cli --help`.

## Planned `add file` contract

`add file PATH` accepts a user-selected local document and creates a Zotero-
owned stored copy. The planned shape is:

```text
za-cli --json add file PATH --collection COLLECTION_KEY --confirm
za-cli --json add file PATH --confirm
za-cli --json add file PATH --parent ITEM_KEY --collection COLLECTION_KEY --confirm
```

These are planned examples, not commands in the current release.

1. **Local input and storage.** `PATH` is a regular local file selected by the
   caller. The CLI hashes it before the write, and the Extension imports a copy
   into Zotero storage through Zotero's attachment API. The source file remains
   at `PATH` and is never moved, deleted, or rewritten. A linked-file shortcut
   or direct storage/SQLite write is not an implementation of this contract.
2. **Explicit placement.** `--collection COLLECTION_KEY` adds an explicit
   Collection Membership. Omitting it leaves a newly created top-level object
   Unfiled; the command never inherits a session's cwd. Reusing an existing item
   adds the requested membership without removing existing memberships. My
   Library is the first supported library; the operation schema retains
   `library_id` for a later group-library decision.
3. **Default native recognition.** Without `--parent`, the imported standalone
   attachment is passed to Zotero's native PDF/EPUB recognizer. The operation
   keeps the original document available while recognition runs. A verified
   native parent is preferred; a failed or unverifiable result is reported as
   an Unrecognized Document rather than becoming a title-only guessed item.
   The existing `resolve` path remains available for a later explicit retry.
4. **Explicit parent bypass.** With `--parent ITEM_KEY`, the command attaches
   the imported copy to that live, editable My Library Literature Item and does
   **not** run document recognition. This is the caller's identity decision;
   the command still performs the hash, source, permission, and conflict checks.
5. **Source role.** When the imported PDF is the selected Source Document, mark
   that attachment with `za-cli:pdf`. The marker identifies the selected source
   role; it does not mark every PDF child. A different PDF never silently
   replaces an existing Source Document.

## Identity, reuse, and conflict behavior

Preflight and the live commit use the following order:

- An exact Item Key, normalized Strong Identifier (DOI, ISBN, arXiv ID, PMID,
  or ADS Bibcode), or identical source-file SHA-256 is eligible for reuse.
  An identical incoming file is not copied a second time; requested Collection
  Membership is made idempotently on the reused item.
- A Strong Identifier that matches an existing item while the incoming Source
  Document has a different hash is a **Source conflict**, not a replacement.
  The newly imported copy is rolled back, the existing item and source remain
  untouched, and the result contains the conflicting Item/attachment keys.
  Retrying requires a new explicit decision; it never falls through to merge.
- Title/author/year similarity is a fuzzy candidate only. The add operation
  creates the new Literature Item and returns candidate keys as a warning;
  fuzzy evidence never silently reuses an item and never triggers an automatic
  merge.
- A duplicate created by Zotero UI or another tool is reported by duplicate
  detection. The caller chooses the keeper and explicitly confirms any merge;
  byte-identical PDFs may collapse, different PDFs remain as alternatives, and
  discarded items go to Zotero Trash.

The live operation repeats all identity and placement checks after acquiring the
Zotero write lock. A read-only SQLite result can suggest a reuse or candidate,
but it cannot authorize the commit. If the live check detects a changed hash,
identifier, Collection, or Source Document, it aborts or rolls back rather than
writing through a stale plan.

## Metadata-only network paths

Known identifiers and URLs may be resolved through Zotero's maintained native
translator machinery when a future `add identifier`, `add url`, or structured
metadata `import` operation is implemented. Such requests are metadata-only:
network access is explicit, the provider is reported, and translator calls use
`saveAttachments=false`. They do not discover or download a PDF, reuse browser
cookies, authenticate to a campus proxy, or upload paper Full Text. A local file
or an existing Zotero item is the only input to the core's attachment path.

## Current metadata resolution

`resolve ATTACHMENT_KEY --markdown PATH --confirm` turns an Unrecognized Document
already present in Zotero into a Literature Item without manual UI entry. The
Extension calls Zotero's native recognizer first. If that does not yield a
verified parent, reviewed Markdown may supply exactly one normalized Strong
Identifier to `Zotero.Translate.Search`; the translated result must match the
Markdown title. Ambiguous identifiers, title-only matches, and translator
conflicts remain unresolved.

Resolution preserves the attachment's Collection Memberships, reparents the
original document, and returns the parent Item Key. Markdown import is a
separate explicit step so a successful metadata write is not undone merely
because Full Text import needs to be retried.

## Markdown Full Text

`fulltext import ITEM_KEY PATH --confirm` copies a reviewed local Markdown file
unchanged into canonical `fulltext.md` while preserving the local source. The
source must be a regular non-symlink `.md` file; `distill.md` and
`probe_distill.md` are rejected. Existing canonical Full Text requires every
marked attachment key to be supplied explicitly with repeatable `--replace`.

`fulltext audit` reports unmarked Markdown attachment candidates, multiple
candidates, missing files, and ambiguous source PDFs without changing Zotero;
it never treats Zotero Notes or Annotations as candidates.
`fulltext adopt ITEM_KEY MD_ATTACHMENT_KEY --confirm` explicitly copies the
selected content unchanged into canonical `fulltext.md`, marks the unique
Source Document, and moves the adopted source and any explicitly selected
`--replace` Full Text attachments to Trash. Other Markdown attachments remain
unmarked and untouched; multiple source PDFs require explicit selection.
