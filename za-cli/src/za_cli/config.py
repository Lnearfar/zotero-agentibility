from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeConfig:
    json_output: bool
    data_dir: Path
    port: int
    config_dir: Path


def build_config(json_output: bool) -> RuntimeConfig:
    try:
        port = int(os.environ.get("ZOTERO_HTTP_PORT", "23119"))
    except ValueError as exc:
        from .errors import CliError

        raise CliError("INVALID_PORT", "ZOTERO_HTTP_PORT must be an integer") from exc
    return RuntimeConfig(
        json_output=json_output,
        data_dir=Path(os.environ.get("ZOTERO_DATA_DIR", "~/Zotero")).expanduser(),
        port=port,
        config_dir=Path(
            os.environ.get("ZA_CLI_CONFIG_DIR", "~/.config/zotero-agentibility")
        ).expanduser(),
    )
