# CLI shape

This document defines the target interface. The current release provides `session`, `app`, `pwd`, `cd`, `ls`, `lookup`, `source`, `read`, `find`, `search`, `resolve`, `index update/status/refresh/worker/inspect`, `fulltext audit`, `fulltext adopt`, `fulltext import`, and `fulltext migrate`; later command groups below are not yet available. The installed command reference is `za-cli --help`, with `za-cli COMMAND --help` or nested group help for arguments and options.

The primary agent workflow uses top-level filesystem-style commands:

```text
pwd  cd  ls  read  find  search  lookup  source  resolve  fulltext  index
```

Planned post-v0.4 functionality derived from `cli-anything-zotero` may use groups such as `item`, `collection`, `add`, `import`, `export`, `note`, `tag`, and `saved-search`; these groups are not currently installed. The top-level `search` command remains passage-level semantic search. `resolve ATTACHMENT_KEY [--markdown PATH] --confirm` resolves one standalone PDF or EPUB through Zotero's native recognizer, with an accuracy-first Strong Identifier Markdown fallback, and returns the parent Item Key for the existing `fulltext import` command.

Collection navigation and mutations use an explicit Browsing Session ID. Global semantic search, lookup, reading, and index management do not require one or inherit session cwd. The Skill creates a session only when a requested operation needs navigation state, preferring `ZA_CLI_SESSION` and then `PI_SESSION_ID`. Collection paths are navigational; Literature Items are addressed by Item Key. Canonical absolute Collection paths begin with `/My Library/`; the CLI also accepts `My Library/...` as the same absolute path, while other paths remain relative to the current Collection. Sessions store stable Collection Keys and recompute display paths. An ambiguous path fails with candidate keys, and `cd --collection KEY` resolves it explicitly; a trashed current Collection resets the session to its Library root with a warning.

Multiple sessions may read concurrently. Zotero mutations use one bounded global write lock; slow preparation such as downloads, conversion, and embedding happens before or after the locked commit section.

Destructive CLI operations move Zotero objects to Trash and require explicit confirmation. The CLI has no permanent-delete or empty-trash operation.

Human-readable text remains the default. Agents and scripts pass `--json` for compact, stable result envelopes; diagnostics use stderr and failures remain non-zero. `read --all` emits untruncated raw full text.

`doctor` checks that Zotero is running, the shared bearer-token file has safe permissions, the Extension bridge protocol is compatible with the CLI, required Linux tools are present, and reads cached semantic-index state. `doctor --deep` additionally reconciles cached index statistics by traversing Passage metadata and is reserved for explicit diagnosis.

`index refresh` only queues selected Items. `index worker --once` drains one bounded batch; `index worker` is a long-lived polling process that sleeps while idle and does not daemonize itself. Full reconciliation remains an explicit `index update` operation.

`ls`, `search`, `find`, `read`, and indexing remain local. Network access occurs only for explicit DOI/arXiv/URL ingest, PDF fetching, metrics, or Zotero sync; responses identify the external source, and no command sends paper full text.

A mode-`0600` audit log covers writes only, recording time, Session ID, operation, affected keys, result, and error code. It excludes bearer tokens, full text, note bodies, search queries, and read activity.
