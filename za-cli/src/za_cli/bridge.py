from __future__ import annotations

import json
import re
import stat
from pathlib import Path

from .errors import CliError
from .http import request

PROTOCOL = 1
OPERATIONS = {"health", "fulltext_adopt", "fulltext_import"}
PATH = "/zotero-agentibility/v1/operation"
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
        try:
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
                timeout=300 if operation != "health" else 3,
            )
        except CliError as error:
            if operation != "health" and error.code == "ZOTERO_UNAVAILABLE":
                raise CliError(
                    "WRITE_OUTCOME_UNKNOWN",
                    "Connection to Zotero was lost during the write; inspect the item before retrying",
                    details={"retryable": False},
                ) from error
            raise
        try:
            data = response.json()
        except CliError as error:
            if operation != "health":
                raise CliError(
                    "WRITE_OUTCOME_UNKNOWN",
                    "Zotero returned an incomplete write response; inspect the item before retrying",
                    details={"retryable": False},
                ) from error
            raise
        if response.status != 200:
            error = data.get("error") if isinstance(data, dict) else None
            if isinstance(error, dict) and isinstance(error.get("code"), str):
                details = error.get("details") if isinstance(error.get("details"), dict) else {}
                if error.get("retryable") is True:
                    details = {**details, "retryable": True}
                raise CliError(error["code"], str(error.get("message") or "Bridge operation failed"), details=details or None)
            if operation != "health":
                raise CliError(
                    "WRITE_OUTCOME_UNKNOWN",
                    "Zotero returned an unrecognized write error; inspect the item before retrying",
                    details={"retryable": False},
                )
            raise CliError("BRIDGE_HTTP_ERROR", f"Bridge returned HTTP {response.status}")
        protocol = data.get("protocol") if isinstance(data, dict) else None
        if protocol != PROTOCOL or not isinstance(data, dict) or data.get("ok") is not True:
            if operation != "health":
                raise CliError(
                    "WRITE_OUTCOME_UNKNOWN",
                    "Zotero returned an invalid write result; inspect the item before retrying",
                    details={"retryable": False},
                )
            if protocol != PROTOCOL:
                raise CliError(
                    "BRIDGE_PROTOCOL_MISMATCH",
                    f"Bridge protocol {protocol!r} does not match CLI protocol {PROTOCOL}",
                )
            raise CliError("INVALID_RESPONSE", "Bridge returned an invalid success envelope")
        return data

    def health(self) -> dict:
        return self.operation("health", {})

    def fulltext_adopt(
        self,
        *,
        session_id: str,
        item_key: str,
        attachment_key: str,
        expected_path: str,
        expected_sha256: str,
        replace_attachment_keys: list[str],
    ) -> dict:
        response = self.operation("fulltext_adopt", {
            "session_id": session_id,
            "item_key": item_key,
            "markdown_attachment_key": attachment_key,
            "expected_path": expected_path,
            "expected_sha256": expected_sha256,
            "replace_attachment_keys": replace_attachment_keys,
        })
        if response.get("operation") != "fulltext_adopt" or not isinstance(response.get("result"), dict):
            raise CliError(
                "WRITE_OUTCOME_UNKNOWN",
                "Zotero returned an invalid adoption result; inspect the item before retrying",
                details={"retryable": False},
            )
        return response["result"]

    def fulltext_import(
        self,
        *,
        session_id: str,
        item_key: str,
        source_path: str,
        expected_sha256: str,
        replace_attachment_keys: list[str],
    ) -> dict:
        response = self.operation("fulltext_import", {
            "session_id": session_id,
            "item_key": item_key,
            "source_path": source_path,
            "expected_sha256": expected_sha256,
            "replace_attachment_keys": replace_attachment_keys,
        })
        if response.get("operation") != "fulltext_import" or not isinstance(response.get("result"), dict):
            raise CliError(
                "WRITE_OUTCOME_UNKNOWN",
                "Zotero returned an invalid import result; inspect the item before retrying",
                details={"retryable": False},
            )
        return response["result"]
