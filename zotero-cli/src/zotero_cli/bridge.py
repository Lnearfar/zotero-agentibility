from __future__ import annotations

import json
import re
import stat
from pathlib import Path

from .errors import CliError
from .http import request

PROTOCOL = 1
OPERATIONS = {"health"}
PATH = "/zotero-agent-library/v1/operation"
_TOKEN = re.compile(r"^[0-9a-f]{64}$")


def token_status(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        return {"ok": False, "path": str(path), "mode": None, "error": "missing or non-regular"}
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        return {"ok": False, "path": str(path), "mode": f"{mode:04o}", "error": "mode must be 0600"}
    try:
        token = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return {"ok": False, "path": str(path), "mode": "0600", "error": "unreadable"}
    if not _TOKEN.fullmatch(token):
        return {"ok": False, "path": str(path), "mode": "0600", "error": "token must be 64 lowercase hex characters"}
    return {"ok": True, "path": str(path), "mode": "0600"}


class BridgeClient:
    def __init__(self, port: int, token_path: Path):
        self.port = port
        self.token_path = token_path

    def operation(self, operation: str, arguments: dict | None = None) -> dict:
        if operation not in OPERATIONS:
            raise CliError("UNSUPPORTED_OPERATION", f"Unsupported bridge operation: {operation}")
        status = token_status(self.token_path)
        if not status["ok"]:
            raise CliError("UNSAFE_BRIDGE_TOKEN", "Bridge token is missing or unsafe", details=status)
        token = self.token_path.read_text(encoding="utf-8").strip()
        body = json.dumps(
            {"protocol": PROTOCOL, "operation": operation, "arguments": arguments or {}},
            separators=(",", ":"),
        ).encode("utf-8")
        response = request(
            self.port,
            PATH,
            method="POST",
            body=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        if response.status != 200:
            raise CliError("BRIDGE_HTTP_ERROR", f"Bridge returned HTTP {response.status}")
        data = response.json()
        protocol = data.get("protocol") if isinstance(data, dict) else None
        if protocol != PROTOCOL:
            raise CliError(
                "BRIDGE_PROTOCOL_MISMATCH",
                f"Bridge protocol {protocol!r} does not match CLI protocol {PROTOCOL}",
            )
        return data

    def health(self) -> dict:
        return self.operation("health", {})
