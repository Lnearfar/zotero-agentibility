# Native capability surface

This is the executable checkpoint for the accepted broad native-first CLI plan. It separates the command surface installed in this branch from fixed operations that are planned, and names work that does not belong in the core. The matrix is a roadmap, not a claim that planned commands are available; verify installed names with `za-cli --help`.

## Status and milestone vocabulary

- **installed**: the command is present in the current Click tree and its runtime behavior ships.
- **planned**: the capability is accepted, but its command and fixed bridge operation still require implementation and validation.
- **deferred**: the capability is outside the core or needs a separate scope decision. It must not be approximated with a generic command.
- **prohibited**: the surface contradicts project invariants and is intentionally unavailable.

Named milestones avoid ambiguous phase numbers:

| Milestone | Exit condition |
| --- | --- |
| **Current Surface** | Existing navigation, retrieval, indexing, session/app, native recognition, and Markdown Full Text paths stay documented and validated. |
| **Local Document Intake** | **Installed.** `add file` copies a local PDF/EPUB into Zotero storage, preserves the source, applies the accepted identity/recognition/conflict behavior, uses an explicit Collection Key when requested or leaves the result Unfiled, and works in My Library. |
| **Library Organization** | Collection CRUD/membership, tags, and recoverable Trash/restore use native Zotero operations and explicit resource keys. |
| **Resource Editing** | Item metadata, creators, Notes, attachments, Related Items, and saved searches use bounded schemas and native Zotero validation. |
| **Duplicate Management** | Native duplicate detection is exposed for list/review, and keeper-selected native merge protects canonical Markdown and Source Document roles. |
| **Metadata Ingest and Exchange** | Identifier/URL and structured import/export operations are fixed and metadata-only; translator calls use `saveAttachments=false`. |
| **Library Operations** | Sync, bounded batch work, and future library-scoped controls remain explicit fixed operations. |
| **External PDF Acquisition Boundary** | A Human or browser Skill handles PDF discovery/download, campus authentication, cookies, and the decision to obtain a PDF. |
| **Multiple Libraries Decision** | Editable group-library support receives a separate permission and compatibility review; the first target remains My Library. |
| **Permanent Invariants** | Generic `execute`/`js`, direct SQLite or storage writes, and permanent purge remain prohibited. |

## Capability matrix

| Zotero-native capability | Fixed `za-cli` command surface | Main risk and required guardrail | Status | Milestone |
| --- | --- | --- | --- | --- |
| Read the local catalog and navigate Collections | `pwd`, `cd`, `ls`, `lookup`, `source` | The read-only SQLite snapshot can be stale or schema-incompatible. Revalidate live state before a write; address Items by Item Key. | **installed** | Current Surface |
| Retrieve grounded Passages | `read`, `find`, `search` | Semantic results are leads and indexing can be asynchronous or partial. Read the source Passage or PDF page before making a claim. | **installed** | Current Surface |
| Isolate navigation and inspect runtime health | `session create/status`, `app status/doctor` | Shared navigation state and incompatible bridge versions can produce unsafe assumptions. Use explicit Session IDs and protocol checks. | **installed** | Current Surface |
| Recognize an existing standalone PDF/EPUB | `resolve ATTACHMENT_KEY [--markdown PATH] --confirm` | Zotero recognition can fail or return an unsafe match. Keep the attachment, require verified identity, and leave unresolved documents unresolved. | **installed** | Current Surface |
| Adopt or import canonical Markdown Full Text | `fulltext audit/adopt/import/migrate` | Paths, hashes, Source selection, and replacement keys can go stale. Validate live state, preserve local sources, and move replaced objects only to Trash. | **installed** | Current Surface |
| Maintain the local Passage index | `index update/reconcile/status/refresh/worker/inspect` | Maintenance must not block retrieval or silently erase usable records. Keep the durable queue, bounded worker, and partial-coverage report. | **installed** | Current Surface |
| Add a local document as a Zotero-owned stored copy | `add file PATH [--parent ITEM_KEY] [--collection COLLECTION_KEY] --confirm` | Uses `Zotero.Attachments.importFromFile`, never a linked-file shortcut or direct storage write. Preserves the source; no Collection means Unfiled. | **installed** | Local Document Intake |
| Run native recognition during local-file intake | `add file PATH` by default; `--parent` bypasses recognition | Recognition runs on the imported Zotero copy. Failure returns a successful Unrecognized Document rather than guessing metadata. | **installed** | Local Document Intake |
| Reuse exact file/work identity | `add file` | An identical stored attachment is reused idempotently. The same Strong Identifier with a different Source erases the incoming import and reports a conflict; it never replaces the source silently. | **installed** | Local Document Intake |
| Report fuzzy duplicate candidates during intake | `add file` | `Zotero.Duplicates` title/creator/year evidence is a candidate only. Add with a warning; never auto-reuse or auto-merge from fuzzy evidence. | **installed** | Local Document Intake |
| Create, inspect, edit, trash, and restore Literature Items | `item get/list/create/update/trash/restore`, `item relate/unrelate` | Mutable titles are not identity. `item update` uses a restricted Zotero JSON patch; tags, Collections, children, and relations stay separate. | **planned** | Resource Editing |
| Manage child attachments and Source selection | `attachment list/get/add/link/recognize/rename/reparent/trash/restore/select-source` | Use Zotero attachment APIs, preserve alternatives, and never mark every PDF as `za-cli:pdf`. Linked files are a later explicit slice, not `add file`. | **planned** | Resource Editing |
| Create and organize Collections | `collection list/get/create/rename/move/trash/restore/add-item/remove-item` | Membership removal is not Item deletion. Writes use explicit Collection Keys and never inherit session cwd. Membership changes are idempotent. | **planned** | Library Organization |
| Manage tags | `tag list/items/add/remove/rename/color` | Tag collisions and reserved role tags can change source selection. Delegate normalization/merge to Zotero and preserve `za-cli:md`/`za-cli:pdf` semantics. | **planned** | Library Organization |
| Manage Zotero Notes | `note list/get/create/update/trash/restore` | Notes are Zotero HTML and are not Markdown Full Text. Keep bodies out of audit records; do not invent a Markdown converter. | **planned** | Resource Editing |
| Detect, review, and merge Duplicate Items | `duplicate list/review/merge --keeper ITEM_KEY --confirm` | Use `Zotero.Duplicates` and native merge. The keeper's fields win initially; conflicting `za-cli:md` or `za-cli:pdf` roles block merge until selected. | **planned** | Duplicate Management |
| Manage saved searches | `saved-search list/get/create/update/trash/restore` | Conditions and scope can be surprising. Accept only Zotero's validated condition schema; do not expose an arbitrary query/eval path. | **planned** | Resource Editing |
| Add metadata by identifier or URL | `add identifier`, `add url` | Provider/translator results can be ambiguous. Fetch metadata only, report the source, use `saveAttachments=false`, and require confirmation for the Zotero write. | **planned** | Metadata Ingest and Exchange |
| Import and export structured metadata | `import ris/bibtex/csl-json`, `export ris/bibtex/csl-json` | Conversion can lose fields or import attachments. The first import slice is metadata-only; local attachments enter through `add file`. | **planned** | Metadata Ingest and Exchange |
| Coordinate Zotero synchronization | `sync status/run` | Zotero owns sync state and attachment policy. Expose status and an explicit native run request without choosing which PDFs Zotero downloads. | **planned** | Library Operations |
| Apply bounded multi-resource writes | repeated keys, initially at most 100 per command | Prevalidate all requested resources and use one Zotero transaction when the native operation supports it. Do not invent a partial-success framework. | **planned** | Library Operations |
| Discover/download PDFs or use campus auth/cookies | No core command | Paywalls, institutional licenses, robots, copyright, and bearer-like cookies are outside the CLI trust seam. Core accepts a selected local file or existing Zotero Item. | **deferred** | External PDF Acquisition Boundary |
| OCR and PDF-to-Markdown conversion | No core command | Conversion quality, assets, and model/network policy belong to external tools. Core imports reviewed local Markdown only. | **deferred** | External PDF Acquisition Boundary |
| Group-library mutations | No current command | Permissions and sync behavior need a separate policy and compatibility matrix. Do not infer group write access from My Library behavior. | **deferred** | Multiple Libraries Decision |
| Generic JavaScript or arbitrary command execution | **No command by design** | A generic evaluator would create an unaudited Zotero writer. Fixed schemas are the security seam. | **prohibited** | Permanent Invariants |
| Direct SQLite/storage writes or permanent purge | **No command by design** | SQLite is read-only advisory state and Zotero storage is not an application interface. Live Zotero operations and recoverable Trash are mandatory. | **prohibited** | Permanent Invariants |

## Implementation checkpoint

A planned row is complete only when its command appears in Click help, each write maps to a named schema-validated bridge operation, the Extension reloads live Zotero state before commit, failures report an explicit outcome, and public CLI/bridge seams are covered by tests. All writes require `--confirm`; high-risk operations also provide a read-only review command. Exact options belong in Click help once implemented; this matrix owns capability, risk, and release status.

The non-obvious invariant is deliberate: read-only SQLite can make a fast candidate list, but it cannot authorize a write. The live Zotero transaction decides whether identity, Source Document, hash, permissions, and Collection Membership are still valid. See [CLI shape](cli.md), [ingest and reuse](ingest.md), [bridge protocol](bridge.md), and [ADR 0008](adr/0008-broad-native-first-fixed-operations.md).
