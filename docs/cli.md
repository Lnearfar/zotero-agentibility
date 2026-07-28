# CLI shape

This document defines the target interface. The implemented v0.1.2 read-only slice currently provides `session`, `app`, `pwd`, `cd`, `ls`, `lookup`, `source`, `read`, `find`, and `fulltext audit`; later commands below are not yet available. The installed command reference is `zotero-cli --help`, with `zotero-cli COMMAND --help` or nested group help for arguments and options.

The primary agent workflow uses top-level filesystem-style commands:

```text
pwd  cd  ls  read  find  search  lookup  source  fulltext  index
```

Safe functionality inherited from `cli-anything-zotero` remains under its existing groups, including `item`, `collection`, `add`, `import`, `export`, `note`, `tag`, and `app`. Zotero saved-search operations live under `saved-search` so `search` can mean passage-level semantic search.

Commands use an explicit Browsing Session ID. The Skill prefers `ZOTERO_CLI_SESSION`, then maps `PI_SESSION_ID`, and otherwise creates a session explicitly; it preserves that session across turns. Collection paths are navigational; Literature Items are addressed by Item Key. Sessions store stable Collection Keys and recompute display paths. An ambiguous path fails with candidate keys, and `cd --collection KEY` resolves it explicitly; a trashed current Collection resets the session to its Library root with a warning.

Multiple sessions may read concurrently. Zotero mutations use one bounded global write lock; slow preparation such as downloads, conversion, and embedding happens before or after the locked commit section.

Destructive CLI operations move Zotero objects to Trash and require explicit confirmation. The CLI has no permanent-delete or empty-trash operation.

Human-readable text remains the default. Agents and scripts pass `--json` for compact, stable result envelopes; diagnostics use stderr and failures remain non-zero. `read --all` emits untruncated raw full text.

`doctor` currently checks that Zotero is running, the shared bearer-token file has safe permissions, the Extension release and bridge protocol match the CLI, and required Linux tools are present. It will also check the semantic index once indexing is implemented.

`ls`, `search`, `find`, `read`, and indexing remain local. Network access occurs only for explicit DOI/arXiv/URL ingest, PDF fetching, metrics, or Zotero sync; responses identify the external source, and no command sends paper full text.

A mode-`0600` audit log covers writes only, recording time, Session ID, operation, affected keys, result, and error code. It excludes bearer tokens, full text, note bodies, search queries, and read activity.
