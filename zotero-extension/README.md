# zotero-extension

Authenticated fixed-operation bridge for Zotero-Agentibility. Installation is manual and documented in the repository root README.

## Build

```bash
make
```

This validates the source and creates `build/zotero-agentibility-0.4.0.xpi`. Normal releases are installed through Zotero's Add-ons UI.

## Development install or upgrade

Zotero 9 scans `<profile>/extensions/<add-on-id>.xpi` on startup, so development builds can be installed without UI automation. **Close Zotero first**, set the exact active profile explicitly, validate the archive, and replace it atomically on the same filesystem:

Run from the repository root after selecting the active profile listed in `~/.zotero/zotero/profiles.ini`:

```bash
profile="${ZOTERO_PROFILE:?Set ZOTERO_PROFILE to the active Zotero profile directory}"
src="$PWD/zotero-extension/build/zotero-agentibility-0.4.0.xpi"
dst="$profile/extensions/zotero-agentibility@local.xpi"

if pgrep -x zotero >/dev/null || pgrep -x zotero-bin >/dev/null; then
  echo "Close Zotero before replacing its XPI" >&2
  exit 1
fi

test -d "$profile" || { echo "Zotero profile not found: $profile" >&2; exit 1; }
unzip -t "$src" >/dev/null
mkdir -p "$profile/extensions"
tmp=$(mktemp "$profile/extensions/.zotero-agentibility.XXXXXX")
trap 'rm -f "$tmp"' EXIT
cp -- "$src" "$tmp"
mv -f -- "$tmp" "$dst"
trap - EXIT
```

The destination filename must exactly match the manifest ID `zotero-agentibility@local`. Do not edit `extensions.json`; Zotero discovers or upgrades the XPI on its next start. The earlier failed profile-placement attempt used a Zotero-9-incompatible manifest—the placement mechanism was not the fault. This is an explicit development shortcut, not a cross-profile end-user installer; normal automatic releases should eventually use a real HTTPS `update_url` manifest.

On first startup the Extension creates `~/.config/zotero-agentibility/bridge-token` with mode `0600`. Protocol 1 allows `health` and fixed `fulltext_adopt` and `fulltext_import`; arbitrary JavaScript and generic Zotero mutation requests are unavailable. Writes are serialized and recorded without content in `~/.config/zotero-agentibility/audit.jsonl`.

Run `za-cli --json app doctor` after installing each matching release.
