# Rename all project identifiers

> Superseded for tag naming by [ADR 0007](0007-shorten-zotero-attachment-tags.md). The runtime identifiers below are unchanged; the Zotero tag names are now `za-cli:md` and `za-cli:pdf`.

The project and repository are named **Zotero-Agentibility** / `zotero-agentibility`. The CLI component, Python distribution, and executable are `za-cli`, and its Python import namespace is `za_cli`.

Version 0.4.0 also renames project-owned runtime identifiers rather than retaining old compatibility names: Zotero tags are `za-cli:fulltext` and `za-cli:source`, the extension ID is `zotero-agentibility@local`, the bridge endpoint is `/zotero-agentibility/v1/operation`, and configuration and index state live under `zotero-agentibility` directories. Environment variables use the `ZA_CLI_*` prefix.
