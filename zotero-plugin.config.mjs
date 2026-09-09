import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "zotero-plugin-scaffold";

const root = dirname(fileURLToPath(import.meta.url));
const parameters = JSON.parse(
  readFileSync(resolve(root, "zotero-plugin.dev.json"), "utf8"),
);

export default defineConfig({
  name: "Zotero-Agentibility Bridge",
  logLevel: parameters.logLevel,
  id: "zotero-agentibility@local",
  namespace: "agentibility",
  xpiName: "zotero-agentibility",
  source: ["zotero-extension", "./index-runtime.json"],
  dist: ".scaffold/build",
  build: {
    assets: [
      "zotero-extension/manifest.json",
      "zotero-extension/bootstrap.js",
      "zotero-extension/runtime.js",
      "zotero-extension/locale/**/*.*",
      "zotero-extension/icons/*.svg",
      "zotero-extension/LICENSE",
      "zotero-extension/UPSTREAM.md",
      "index-runtime.json",
    ],
    fluent: {
      prefixLocaleFiles: false,
      prefixFluentMessages: false,
      dts: false,
    },
    prefs: {
      prefixPrefKeys: false,
      dts: false,
    },
    makeManifest: {
      enable: false,
    },
  },
  server: {
    devtools: false,
    startArgs: parameters.zotero.startArgs,
    prefs: {
      "devtools.debugger.remote-websocket": false,
      "extensions.zotero.httpServer.enabled": true,
      "extensions.zotero.httpServer.localAPI.enabled": true,
      "extensions.zotero.httpServer.port": parameters.zotero.httpPort,
      "extensions.zotero.sync.autoSync": false,
      "extensions.zotero.firstRun2": false,
      "extensions.zotero-agentibility.zaCliPath": resolve(
        root,
        parameters.worker.executablePath,
      ),
    },
    asProxy: false,
    prebuild: true,
    createProfileIfMissing: true,
  },
});
