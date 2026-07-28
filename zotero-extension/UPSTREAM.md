# Upstream provenance

This extension is derived from `cli-anything-zotero`:

- Repository: <https://github.com/PiaoyangGuohai1/cli-anything-zotero>
- Commit: `f621952f3645546573d622440cbf707320f7a35f`
- Upstream paths: `cli_anything/zotero/plugin/zotero-cli-bridge/bootstrap.js` and `manifest.json`
- License: Apache License 2.0; see `LICENSE`

Both imported files were substantially modified for zotero-agent-library 0.1.0. The extension identity and endpoint are new. The upstream unauthenticated arbitrary-JavaScript endpoint was removed and replaced with a bearer-authenticated, bounded JSON endpoint whose sole operation is `health`. Linux token creation, permission checks, request validation, credential-log redaction, and clean endpoint removal were added. No upstream update URL is retained.
