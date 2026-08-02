# Rename all project identifiers

The project and repository are named **Zotero-Agentibility** / `zotero-agentibility`. The CLI component, Python distribution, and executable are `za-cli`, and its Python import namespace is `za_cli`.

Version 0.4.0 also renames project-owned runtime identifiers rather than retaining old compatibility names: Zotero tags are `za-cli:fulltext` and `za-cli:source`, the extension ID is `zotero-agentibility@local`, the bridge endpoint is `/zotero-agentibility/v1/operation`, and configuration and index state live under `zotero-agentibility` directories. Environment variables use the `ZA_CLI_*` prefix.
