# Zotero add-on management without a GUI (Zotero 7–10)

**Research date:** 2026-08-24.  This is a source/documentation review only.  No
Zotero management command was run, no GUI or profile was changed, and no software
was installed.

## Conclusion

Zotero 10 (and the reviewed Zotero 7–10 command-line code) does **not** expose an
official, non-interactive add-on-management CLI. Zotero's user-facing installation
documentation says to download an XPI and install it through Tools → Plugins:
[official plugin installation](https://www.zotero.org/support/plugins).  In particular, these are not
Zotero-supported commands:

* `zotero --install-addon FILE.xpi`
* `-install-global-extension`
* `--purgecaches` as an add-on installation/update operation

The first two are commonly confused with old Firefox/Gecko command-line options
(or with downstream launchers); they do not occur in Zotero 10's command-line
handlers. `--purgecaches` occurs in Zotero's *build/test* scripts, not as a
supported user add-on-management interface. The Zotero 10 handler accepts
`-datadir`, `-file`, `-url`, test/debug options, and integration options, then
opens/imports files; its file path handling installs CSL styles, not XPIs:
[`app/assets/commandLineHandler.js`, lines 30–104](https://github.com/zotero/zotero/blob/10.0/app/assets/commandLineHandler.js#L30-L104),
[`chrome/content/zotero/xpcom/commandLineHandler.js`, lines 30–141](https://github.com/zotero/zotero/blob/10.0/chrome/content/zotero/xpcom/commandLineHandler.js#L30-L141).
The same handler shape is present on the Zotero 7.0.0 tag and the current
Zotero source.

Zotero does integrate with Gecko's AddonManager internally. That is not a shell
API. Zotero's plug-in integration obtains add-ons and runs lifecycle methods
through AddonManager, for example `getAddonByID()`, `getAddonsByTypes()`, and
`onInstalling()`/`onInstalled()`:
[`xpcom/plugins.js`, lines 310–340 and 697–730](https://github.com/zotero/zotero/blob/10.0/chrome/content/zotero/xpcom/plugins.js#L310-L340).
There is no Zotero command-line bridge around the public Gecko method
`AddonManager.getInstallForFile()`.

## What the Gecko API does (and does not) imply

Mozilla documents `AddonManager.getInstallForFile(aFile, aMimetype, ... )` as a
JavaScript AddonManager API, returning an install object whose normal flow is
`install()` and whose state/lifecycle is managed by AddonManager:
[Mozilla AddonManager API, `getInstallForFile`](https://firefox-source-docs.mozilla.org/toolkit/mozapps/extensions/addon-manager/AddonManager.html#AddonManager.getInstallForFile),
[Mozilla AddonManager source](https://searchfox.org/mozilla-central/source/toolkit/mozapps/extensions/AddonManager.sys.mjs).
It is callable only from privileged code inside a running Zotero/Gecko process;
it is neither a Linux executable nor a promise that an arbitrary external
process can safely mutate a Zotero profile. Calling it would require a custom
in-process bootstrap/JS bridge, which this project explicitly does not want.

Likewise, AddonManager's `addon.userDisabled`, `appDisabled`, active state,
install location, lifecycle callbacks, compatibility checks, and startup-cache
invalidation are one coordinated state machine. A direct file copy is outside
that transaction. Replacing an XPI with the same add-on ID and version can
therefore leave a previously computed `appDisabled`/compatibility result (and
related startup-cache state) in effect until AddonManager performs a proper
install/restart. `purgecaches` is not a reliable or supported repair for this;
changing the manifest's Zotero compatibility range and increasing the version
are the maintainable fixes. Zotero's own install listener explicitly performs
shutdown/uninstall and notifies `startupcache-invalidate` for a managed install:
[`xpcom/plugins.js`, lines 709–725](https://github.com/zotero/zotero/blob/10.0/chrome/content/zotero/xpcom/plugins.js#L709-L725).

## Profile drop-in XPI

A file at `<profile>/extensions/<addon-id>.xpi` is a useful development
shortcut observed by the Firefox/Zotero extension loader, but it is not an
official Zotero CLI contract. The profile location itself is documented here:
[Zotero profile directory](https://www.zotero.org/support/kb/profile_directory).
Zotero's development documentation describes profile `extensions/` development
and notes cached extension state in `prefs.js` (including
`extensions.lastAppBuildId`/`extensions.lastAppVersion`), which is another reason
not to treat a copied XPI as an AddonManager install. It must not be confused with editing the generated
`extensions.json`, and it cannot provide AddonManager's install transaction,
compatibility-state reset, clean shutdown, or uninstall semantics. Use only
with Zotero stopped and an explicitly selected profile; treat it as a
version-controlled development launcher policy, not a general user-level
manager. It is deliberately not the recommended release update mechanism here.

## Updates and investigated ecosystem tools

An add-on manifest can declare an `applications.zotero.update_url`; the update
manifest maps the same add-on ID to a newer version, download URL, hash, and
compatible application range. Zotero's own plug-in development documentation
covers the XPI/manifest model:
[Zotero plug-in development](https://www.zotero.org/support/dev/client_coding/plugin_development).
The update URL is discovered from an installed add-on. Thus it does not install
an add-on into a fresh profile: the first install still has to be performed
through Zotero's normal Add-ons UI (or an explicitly approved in-process
installer). After that, auto-update can replace it through AddonManager. Every
release must increment the version and publish a matching, hashed update
manifest; keep `strict_min_version`/`strict_max_version` aligned with the
Zotero versions actually supported.

The surveyed ecosystem does not provide a user-level Zotero plug-in manager:

* [`zotero-plugin-toolkit`](https://github.com/windingwind/zotero-plugin-toolkit)
  is a library of APIs for plug-in developers, not an installer. Its deprecated
  [`pluginBridge.ts`](https://github.com/windingwind/zotero-plugin-toolkit/blob/main/src/utils/pluginBridge.ts)
  can call `AddonManager.getInstallForURL()` through a `zotero://plugin/`
  protocol, but that is an in-process/debug bridge, not a standalone CLI or a
  safe user-level manager.
* [`zotero-plugin-scaffold`](https://github.com/northword/zotero-plugin-scaffold)
  provides `zotero-plugin server`, `build`, and `release`; its documented
  `.env` contains a Zotero binary/profile for development and its dev mode is a
  build/runtime workflow, not a user package manager
  ([README lines 84–123, 136–151](https://github.com/northword/zotero-plugin-scaffold/blob/main/README.md#L84-L151)).
* [`Better Notes`](https://github.com/windingwind/zotero-better-notes) documents
  downloading an XPI and selecting “Install Add-on from file,” then `npm run
  build` for development; it has no CLI manager
  ([README lines 86–105, 237–250](https://github.com/windingwind/zotero-better-notes/blob/master/README.md#L86-L105)).

## Recommended Linux workflow for this repository

1. **One-time bootstrap:** install the signed/released XPI once using Zotero's
   normal Add-ons installation flow (human action; no headless command is
   claimed here).
2. **Release updates:** increment the XPI version, build it, publish the XPI
   and SHA-256 `updates.json` at the manifest's `update_url`, and let Zotero's
   official AddonManager auto-update it. Do not overwrite an XPI in a running
   profile.
3. **Development only:** if a fully unattended, desktop-free update is
   essential, use a small *restricted headless launcher* that (a) resolves an
   explicitly configured profile, (b) refuses to run while Zotero is running,
   (c) validates XPI contents and manifest ID/version/hash, (d) atomically
   replaces only `<profile>/extensions/<fixed-id>.xpi`, and (e) starts Zotero
   normally afterward. It must never edit `extensions.json`, inject arbitrary
   JavaScript, or expose a generic bridge. This is a local operational shortcut,
   not an official Zotero CLI.
4. For this repository's normal path, prefer the existing signed update
   manifest and `za-cli app doctor` verification after Zotero has restarted.

This is the smallest maintainable solution: one normal installation, then
versioned releases plus AddonManager auto-update. There is no supported way to
make first installation, upgrade, enable/disable, and uninstall all headless
using only Zotero's public CLI.
