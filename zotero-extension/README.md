# zotero-extension

Authenticated fixed-operation bridge for `zotero-agent-library`. Installation is manual and documented in the repository root README.

## Build

```bash
make
```

This validates the source and creates `build/zotero-agent-library-0.2.0.xpi`. Install that XPI through Zotero's Add-ons UI and restart Zotero.

On first startup the Extension creates `~/.config/zotero-agent-library/bridge-token` with mode `0600`. Protocol 1 allows `health` and fixed `fulltext_adopt`; arbitrary JavaScript and generic Zotero mutation requests are unavailable. Writes are serialized and recorded without content in `~/.config/zotero-agent-library/audit.jsonl`.

Run `zotero-cli --json app doctor` after installing each matching release.
