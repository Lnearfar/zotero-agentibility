# CLI shape

This document separates the command surface installed in the current release
from the accepted target shape. The installed tree is authoritative for what
can be invoked today; the planned tree is a checkpoint for the broad
native-first fixed-operation CLI and is not a release claim. The capability,
risk, and milestone matrix is in [capabilities.md](capabilities.md).

## Installed command tree

The current Click tree (`za-cli --help`) is:

```text
za-cli
├── app
│   ├── status
│   └── doctor [--deep]
├── add
│   └── file PATH [--collection KEY] [--parent KEY] --confirm
├── ls
├── lookup ITEM_KEY
├── source ITEM_KEY
├── read ITEM_KEY
├── find ITEM_KEY QUERY
├── search QUERY
├── resolve ATTACHMENT_KEY [--markdown PATH] --confirm
├── fulltext
│   ├── audit
│   ├── adopt ITEM_KEY MARKDOWN_ATTACHMENT_KEY --confirm
│   ├── import ITEM_KEY MARKDOWN_PATH --confirm
│   └── migrate PLAN --confirm
└── index
    ├── update
    ├── reconcile
    ├── status
    ├── refresh
    ├── worker
    └── inspect
```

The stable high-frequency top-level façade is `ls`, `lookup`, `source`,
`read`, `find`, `search`, and `resolve`. It stays top-level even as resource
groups are added. `search` is passage-level semantic search, not a
bibliographic web search. `resolve` operates on a PDF or EPUB that already
exists in Zotero: it runs Zotero's native recognizer first and uses the
reviewed Strong Identifier Markdown fallback only when needed.

`add file` is the installed local PDF/EPUB intake command; it copies through
Zotero, recognizes by default, and never downloads a document. `source` reports
a sole EPUB fallback, but `read` and `find` support only Markdown/PDF and return
`UNSUPPORTED_SOURCE_FORMAT` for EPUB. `fulltext` and
`index` and `app` are installed groups, not planned placeholders. Exact
arguments and output envelopes belong to Click help.

## Planned resource-group tree

The following tree shows the accepted target shape and marks the group that is
partially installed:

```text
za-cli
├── item get/list/create/update/trash/restore/relate/unrelate
├── attachment list/get/add/link/recognize/rename/reparent/trash/restore/select-source
├── collection list/get/create/rename/move/trash/restore/add-item/remove-item
├── tag list/items/add/remove/rename/color
├── note list/get/create/update/trash/restore
├── duplicate list/review/merge
├── saved-search list/get/create/update/trash/restore
├── add file [installed]; identifier/url [planned]
├── import ris/bibtex/csl-json
├── export ris/bibtex/csl-json
├── sync status/run
├── fulltext          [installed; future additions remain fixed operations]
├── index             [installed; future additions remain fixed operations]
└── app               [installed; future additions remain fixed operations]
```

These are fixed resource operations, not an unbounded dispatcher. `item update`
uses a restricted Zotero JSON patch; tags, Collections, children, and relations
remain separate. Notes use Zotero HTML rather than a custom Markdown converter.
`duplicate merge` requires a caller-selected keeper; the keeper's fields win in
the first implementation, so a caller updates chosen fields before merging.
Metadata import and identifier/URL ingest set `saveAttachments=false`.

The installed `add file` contract is specified in [ingest.md](ingest.md).
Planned command details must be added to Click help when implemented and must
receive the milestone and risk checks in [capabilities.md](capabilities.md).

There is no `execute`, `js`, `eval`, or equivalent generic command in either
tree. Arbitrary JavaScript and direct SQLite/storage writes are prohibited
contract surfaces, not deferred aliases for a future implementation.

## Scope and identity

Collection paths remain the human navigation interface. `ls` defaults to My
Library; callers select another scope with a Collection path or `--collection
KEY`. An ambiguous path fails with candidate keys. Every write addresses Items
and Collections by explicit stable key. For `add file`, omitting `--collection
KEY` means Unfiled.

Agents may read and search concurrently. Every Zotero write requires
`--confirm`, uses one bounded global write lock, reloads live state, and appends
an audit record. High-risk writes also have a read-only review operation.
Destructive operations move objects to Zotero Trash; there is no
permanent-delete or empty-trash command. Repeated-key writes are initially
bounded to 100 resources and prevalidate all inputs before a native transaction.

Human-readable text is the default. Agents and scripts pass `--json` for
compact, stable result envelopes; diagnostics use stderr and failures remain
non-zero. `read --all` emits untruncated raw full text.

## Authority and network boundary

The CLI may use an immutable, read-only SQLite snapshot for catalog inventory,
navigation, and index hints. That snapshot is never a write path or a final
conflict decision. The Extension re-reads live Zotero state and performs every
installed or planned mutation through a named fixed operation; see
[bridge.md](bridge.md).

Installed `resolve` may contact services through Zotero's native recognizer and
identifier translators. The accepted planned identifier, URL, and metadata
import paths may also use the network, but only for metadata and with
`saveAttachments=false`. PDF discovery, PDF download, campus authentication,
cookies, and the decision whether to obtain a PDF belong to the human or a
browser Skill. The core accepts a local file or an existing Zotero item and
never sends paper Full Text to a metadata route.

`app doctor` checks Zotero, the shared bearer token, bridge protocol, required
Linux tools, database schema, cached index state, and whether the index worker is
running. A stopped worker makes the result `DEGRADED`, because new Zotero
changes cannot reach the index. `index worker` is a long-lived foreground
process installed through user systemd; the timer runs `index reconcile` for
maintenance. Search remains on the current index snapshot and never performs a
hidden update.
