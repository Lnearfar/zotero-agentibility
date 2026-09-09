# Developer workflow

This repository has a small npm wrapper around the pinned `zotero-plugin-scaffold` release. It builds the existing extension sources and runs Zotero only with an isolated development environment.

## First setup

Node.js 22.8 or newer, npm, Git, and the Linux Zotero installation are required. Install the Python worker environment with the repository's lockfile:

```bash
uv sync --project za-cli
npm install
```

The worker executable used by the extension is `za-cli/.venv/bin/za-cli`.

Machine-specific developer parameters live in the root [`zotero-plugin.dev.json`](../zotero-plugin.dev.json). The checked-in values use `/usr/lib/zotero/zotero-bin` and `/usr/lib/zotero/app/application.ini`; adjust `zotero.binaryPath` and `zotero.applicationPath` when Zotero is installed elsewhere. The generated launcher uses `exec` with `-app` first, so Scaffold owns the actual Zotero PID rather than a launcher child. Placing `-app` after Scaffold's arguments starts Firefox instead on this installation. The HOME, profile, and data paths stay below ignored `.scaffold/` directories and must never point at a production Zotero profile or data directory.

## Build

```bash
npm run build
```

Scaffold copies the current extension assets into `.scaffold/build/addon/`:

- `manifest.json`, `bootstrap.js`, and `runtime.js`
- `index-runtime.json`
- `locale/**`, `icons/*.svg`, `LICENSE`, and `UPSTREAM.md`

`build.makeManifest.enable` is false, so the production `zotero-extension/manifest.json` is copied as-is and is not regenerated. The existing `zotero-extension/check.sh` release path is independent and unchanged. The build writes only ignored `.scaffold/` output.

## Watch and bounded startup

For normal development, run:

```bash
npm start
```

The default is headless. Remove `--headless` from `zotero.startArgs` to open a visible development window; this is still the separate development library. `zotero.httpPort` is distinct from the normal library's port. Set `logLevel` to `DEBUG` only for launch diagnosis.

Scaffold prebuilds the add-on, starts the configured Zotero binary with its dedicated profile/data directory, installs the unpacked add-on through the Zotero 7+ remote debugging path, and watches the extension directory plus `index-runtime.json`. `server.asProxy` is disabled; the proxy path is not used and no `extensions.json` is edited.

For a bounded native startup smoke run, use:

```bash
npm run dev:once
```

The wrapper waits for Scaffold's `Server Ready!` connection/install signal, waits the configured `devOnce.settleMs` for native startup, then sends an interrupt only to its Scaffold child. It exits nonzero if readiness is not reached before `devOnce.readyTimeoutMs`. This checks development startup, not full indexing correctness; it launches Zotero, so it is not part of static build validation. Allow the worker's configured shutdown grace period before checking for orphan processes.

The development profile disables sync and selects raw TCP RDP (`devtools.debugger.remote-websocket=false`) to match Scaffold's client.

The wrapper derives Scaffold's required environment variables from `zotero-plugin.dev.json` and sets a no-op fallback for Scaffold's process-global shutdown hook. Use the npm scripts rather than invoking Scaffold directly, so shutdown cannot target an unrelated Zotero process. No user configuration is read from environment variables.

## Worker and isolated state

`zotero-plugin.config.mjs` writes the following preference into the dedicated development profile's `prefs.js`:

```text
extensions.zotero-agentibility.zaCliPath = <repo>/za-cli/.venv/bin/za-cli
```

At runtime, the extension passes the dedicated Zotero data directory and config directory to the worker. The resulting state is separated from production:

- bridge token: `.scaffold/zotero-home/.config/zotero-agentibility/bridge-token`
- Zotero database and attachment data: `.scaffold/zotero-data/`
- semantic index: `.scaffold/zotero-home/.local/share/zotero-agentibility/index/<profile-id>/`

All of these paths are ignored. The worker executable remains in the repository's Python environment and is not copied into the add-on.

## Static checks

The minimal checks for this workflow are:

```bash
node --check scripts/zotero-plugin-dev.mjs
node --check zotero-plugin.config.mjs
npm run build
```

There is no npm test framework in this scaffold integration. Run native acceptance separately with `npm run dev:once` and inspect the development profile/worker lifecycle there.

## Native acceptance record

The 0.7.1 fix was also verified by installing the built XPI through RDP in isolated Zotero, confirming its resource URI starts with `jar:`, Console registration, exactly one worker, and no orphan on exit. Unpacked Scaffold acceptance alone does not validate packaged resources. Read bundled configuration via `NetUtil.newChannel()` and `Zotero.File.getContentsAsync(channel)`; passing a `jar:` string routes through Zotero HTTP, which fails on URI username handling.

Verified on the installed Linux/Zotero 10 runtime using only `.scaffold/` state:

- RDP temporary installation without a manually installed XPI.
- Agentibility Console section registered with Zotero's native ItemPaneManager.
- A natively added Literature Item and canonical Markdown attachment became semantically searchable without manual enqueueing or index update.
- A filesystem change triggered Scaffold rebuild/reload; the old worker was replaced by exactly one new worker.
- Disabling the add-on stopped its worker; re-enabling started one worker.
- Development shutdown left no worker after its shutdown grace period.

This verifies registration and lifecycle, not a visual layout inspection. The normal Zotero profile and installed release were not changed.
