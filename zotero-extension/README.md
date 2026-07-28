# zotero-extension

Authenticated fixed-operation bridge for `zotero-agent-library`. Installation is manual and documented in the repository root README.

## Build

```bash
make
```

This validates the source and creates `build/zotero-agent-library-0.1.0.xpi`. Install that XPI through Zotero's Add-ons UI and restart Zotero.

On first startup the Extension creates `~/.config/zotero-agent-library/bridge-token` with mode `0600`. Protocol 1 currently allows only `health`; arbitrary JavaScript and Zotero mutations are not implemented.

The static check passes on Linux. Zotero runtime compatibility of the server hooks and Gecko token-file APIs must be confirmed by installing the XPI and running `zotero-cli --json app doctor`.
