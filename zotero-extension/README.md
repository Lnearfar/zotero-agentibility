# zotero-extension

Authenticated fixed-operation bridge for Zotero-Agentibility. Installation is manual and documented in the repository root README.

## Build

```bash
make
```

This reads the version from `manifest.json`, validates the source, creates `build/zotero-agentibility-<version>.xpi`, and regenerates the hashed `updates.json`. Install the current XPI through Zotero's Add-ons UI once; later releases can update automatically through GitHub Releases.

## Installation and release updates

Zotero 7–10 has no supported non-interactive add-on-management CLI. Install the XPI once through **Tools → Plugins → Install Plugin From File**. After that, publish every upgrade as a strictly newer version and let Zotero's AddonManager follow the manifest `update_url`; do not automate the desktop or edit `extensions.json`.

From a clean, validated release commit:

```bash
version=$(jq -r .version zotero-extension/manifest.json)
make -C zotero-extension clean all
git tag "v$version"
git push origin main "v$version"
gh release create "v$version" \
  "zotero-extension/build/zotero-agentibility-$version.xpi" \
  zotero-extension/updates.json \
  --title "v$version" --generate-notes
```

`updates.json` must name the same version, compatible Zotero range, versioned GitHub asset, and built XPI SHA-256. Zotero checks it through AddonManager. The agent verifies the installed version afterward with `za-cli --json app doctor`; it never takes screenshots or controls the Plugins UI. If an immediate update check is needed before Zotero's scheduled check, the Human may request it in the Plugins UI.

A stopped-profile XPI replacement is only an unsupported development fallback. It can leave stale AddonManager compatibility state—especially after an `appDisabled` result—even when the archive changed. Never use it as the release update path, never overwrite a running profile, and never edit generated add-on registry/cache files. The evidence and rejected pseudo-CLI flags are recorded in [`../docs/research/zotero-addon-cli-management.md`](../docs/research/zotero-addon-cli-management.md).

On first startup the Extension creates `~/.config/zotero-agentibility/bridge-token` with mode `0600`. Protocol 1 allows `health` plus fixed `add_file`, `metadata_resolve`, `fulltext_adopt`, and `fulltext_import` operations; arbitrary JavaScript and generic Zotero mutation requests are unavailable. Writes are serialized and recorded without content in `~/.config/zotero-agentibility/audit.jsonl`. Local-document reuse is authorized by a live stored-file SHA-256 (the Zotero attachment MD5 is only a prefilter). Add/recognition scans run outside the short mutation lock; EPUB attachments remain native sources but are not tagged `za-cli:pdf` (that marker is PDF-only).

Run `za-cli --json app doctor` after installation or an update; CLI and Extension patch versions may differ when bridge protocol 1 remains compatible.
