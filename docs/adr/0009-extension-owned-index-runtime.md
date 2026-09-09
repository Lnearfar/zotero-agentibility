# ADR 0009: Extension-owned indexing and Agentibility Console

Status: Accepted

## Context

Index maintenance needs the current Zotero library and a visible owner. The standalone worker's SQLite watermark could miss committed changes while its immutable reader observed older database pages. A regular read-only connection encountered Zotero locking. A running process alone also gave an incomplete health signal: queued work could stall while the process stayed alive.

The user chose a single Zotero-owned runtime with an Item-pane console and removal of the systemd lifecycle.

## Decision

The Extension launches the installed Python CLI as a supervised child when Zotero starts, forwards native Item notifications, and stops the child when the Extension shuts down. The child retains local PDF extraction, ONNX embeddings, Chroma, the durable refresh queue, and cross-process update locking.

Indexing obtains metadata and attachment inventory through a fixed authenticated `index_catalog` operation implemented with native Zotero reads. This operation observes the same current state as Zotero's UI. It supplies explicit scoped snapshots and a full snapshot for reconciliation. Snapshot failures preserve existing index records and queued work.

The Extension and child exchange bounded newline-delimited JSON commands and status events over process pipes. Status includes heartbeat, active work, queue counts, errors, and cached coverage. The Agentibility Console renders global status and the selected Item's coverage in Zotero's Item pane.

Startup and periodic reconciliation recover missed notifications and external linked-file changes. Foreground search continues against the existing index. The Extension is the sole automatic lifecycle owner; the repository retires systemd units and SQLite watermark polling.

## Consequences

Automatic indexing follows Zotero's lifetime. Disabling the Extension stops automatic maintenance and preserves the index and durable queue. The Python CLI remains an installed prerequisite, with an unavailable executable shown as a console fault.

Coverage errors such as a missing source remain visible per Item. Worker liveness, recent heartbeat, and successful catalog access provide distinct health evidence. Validation must exercise native changes through to indexing and console state, along with startup, shutdown, and restart behavior.
