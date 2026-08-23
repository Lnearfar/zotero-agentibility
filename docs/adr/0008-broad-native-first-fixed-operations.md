# Broad native-first fixed-operation CLI

**Status:** Accepted

## Decision

Zotero-Agentibility will expose a broad, resource-oriented CLI through named,
validated fixed operations. Each command delegates identity, attachment
storage, metadata translation, organization, and synchronization to live Zotero
APIs rather than recreating Zotero transactions in the CLI. Read-only SQLite
access remains an acceleration layer for catalog reads and indexing; live Zotero
state is the only write authority.

The surface keeps the high-frequency top-level retrieval/navigation commands
and adds explicit resource groups as capabilities mature. It does not expose a
generic `execute`/`js` path, direct SQLite or storage writes, or permanent
purge.

## Consequences

The bridge and CLI must grow operation-by-operation with exact schemas, live
state checks, confirmation, audit, rollback/outcome reporting, and compatible
Zotero-version tests. PDF acquisition and browser authentication remain outside
the core boundary. Command names, options, and milestone details belong in
[capabilities.md](../capabilities.md), [cli.md](../cli.md), [ingest.md](../ingest.md),
and [bridge.md](../bridge.md), not in additional ADRs.
