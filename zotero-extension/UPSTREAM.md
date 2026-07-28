# Upstream provenance

This extension is derived from `cli-anything-zotero`:

- Repository: <https://github.com/PiaoyangGuohai1/cli-anything-zotero>
- Commit: `f621952f3645546573d622440cbf707320f7a35f`
- Upstream paths: `cli_anything/zotero/plugin/zotero-cli-bridge/bootstrap.js` and `manifest.json`
- License: Apache License 2.0; see `LICENSE`

Both imported files were initially and substantially modified for zotero-paper-agent 0.1.0. The extension identity and endpoint are new. The upstream unauthenticated arbitrary-JavaScript endpoint was removed and replaced with a bearer-authenticated, bounded JSON endpoint limited to `health` and fixed Full Text adoption. Linux token creation, permission checks, request validation, credential-log redaction, write serialization, audit logging, and clean endpoint removal were added. No upstream update URL is retained; Zotero's mandatory manifest field uses an inert loopback URL.
