"""Small localhost HTTP client.

Modified implementation derived in part from cli-anything-zotero at
f621952f3645546573d622440cbf707320f7a35f. It is reduced to read-only probes
and authenticated fixed bridge operations; connector writes were removed.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .errors import CliError


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Treat redirects from localhost as responses; never forward credentials."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Response:
    status: int
    body: str

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except json.JSONDecodeError as exc:
            raise CliError("INVALID_RESPONSE", "Local endpoint returned invalid JSON") from exc


def request(
    port: int,
    path: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 3,
) -> Response:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        method=method,
        headers=headers or {},
    )
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect).open(req, timeout=timeout) as response:
            return Response(response.getcode(), response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return Response(exc.code, exc.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CliError("ZOTERO_UNAVAILABLE", f"Cannot reach Zotero on 127.0.0.1:{port}") from exc


def probes(port: int) -> dict:
    results: dict[str, dict] = {}
    for name, path, headers in (
        ("ping", "/connector/ping", {}),
        ("localApi", "/api/", {"Zotero-API-Version": "3"}),
    ):
        try:
            response = request(port, path, headers=headers)
            results[name] = {"ok": response.status == 200, "status": response.status}
        except CliError as exc:
            results[name] = {"ok": False, "status": None, "error": exc.message}
    results["running"] = results["ping"]["ok"]
    results["ready"] = results["ping"]["ok"] and results["localApi"]["ok"]
    return results


def require_local_api(port: int) -> None:
    status = probes(port)
    if not status["running"]:
        raise CliError("ZOTERO_NOT_RUNNING", "Zotero must be running")
    if not status["localApi"]["ok"]:
        raise CliError("LOCAL_API_UNAVAILABLE", "Zotero Local API must be enabled", details=status["localApi"])
