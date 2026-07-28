from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from zotero_cli.bridge import BridgeClient, token_status
from zotero_cli.errors import CliError


class FakeResponse:
    def __init__(self, body=b'{"ok":true,"protocol":1,"extension_version":"0.3.0"}', status=200):
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def getcode(self):
        return self.status

    def read(self):
        return self.body


class BridgeTests(unittest.TestCase):
    @mock.patch("zotero_cli.http.urllib.request.build_opener")
    def test_authenticated_health_operation(self, build_opener):
        build_opener.return_value.open.return_value = FakeResponse()
        with tempfile.TemporaryDirectory() as tmp:
            token = Path(tmp) / "bridge-token"
            token.write_text("a" * 64 + "\n", encoding="utf-8")
            os.chmod(token, 0o600)
            result = BridgeClient(23119, token).health()
        request = build_opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:23119/zotero-paper-agent/v1/operation")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + "a" * 64)
        self.assertEqual(
            request.data,
            b'{"protocol":1,"operation":"health","arguments":{}}',
        )
        self.assertTrue(result["ok"])

    @mock.patch("zotero_cli.http.urllib.request.build_opener")
    def test_fulltext_adopt_uses_fixed_authenticated_schema(self, build_opener):
        build_opener.return_value.open.return_value = FakeResponse(
            b'{"ok":true,"protocol":1,"operation":"fulltext_adopt","result":{"markdown_attachment_key":"NEWW2345"}}'
        )
        with tempfile.TemporaryDirectory() as tmp:
            token = Path(tmp) / "bridge-token"
            token.write_text("a" * 64 + "\n", encoding="utf-8")
            os.chmod(token, 0o600)
            result = BridgeClient(23119, token).fulltext_adopt(
                session_id="agent-1",
                item_key="ABCD2345",
                attachment_key="EFGH6789",
                expected_path="/tmp/source.md",
                expected_sha256="b" * 64,
                replace_attachment_keys=["JKLM2345"],
            )
        request = build_opener.return_value.open.call_args.args[0]
        self.assertEqual(json.loads(request.data), {
            "protocol": 1,
            "operation": "fulltext_adopt",
            "arguments": {
                "session_id": "agent-1",
                "item_key": "ABCD2345",
                "markdown_attachment_key": "EFGH6789",
                "expected_path": "/tmp/source.md",
                "expected_sha256": "b" * 64,
                "replace_attachment_keys": ["JKLM2345"],
            },
        })
        self.assertEqual(result["markdown_attachment_key"], "NEWW2345")

    @mock.patch("zotero_cli.http.urllib.request.build_opener")
    def test_bridge_preserves_structured_write_error(self, build_opener):
        build_opener.return_value.open.return_value = FakeResponse(
            b'{"ok":false,"protocol":1,"error":{"code":"STALE_ATTACHMENT_HASH","message":"changed","retryable":false,"details":{"attachment_key":"EFGH6789"}}}',
            409,
        )
        with tempfile.TemporaryDirectory() as tmp:
            token = Path(tmp) / "bridge-token"
            token.write_text("a" * 64 + "\n", encoding="utf-8")
            os.chmod(token, 0o600)
            with self.assertRaises(CliError) as caught:
                BridgeClient(23119, token).operation("fulltext_adopt", {})
        self.assertEqual(caught.exception.code, "STALE_ATTACHMENT_HASH")
        self.assertEqual(caught.exception.details, {"attachment_key": "EFGH6789"})

    @mock.patch("zotero_cli.http.urllib.request.build_opener")
    def test_invalid_write_response_has_unknown_outcome(self, build_opener):
        build_opener.return_value.open.return_value = FakeResponse(b"{")
        with tempfile.TemporaryDirectory() as tmp:
            token = Path(tmp) / "bridge-token"
            token.write_text("a" * 64 + "\n", encoding="utf-8")
            os.chmod(token, 0o600)
            with self.assertRaises(CliError) as caught:
                BridgeClient(23119, token).operation("fulltext_adopt", {})
        self.assertEqual(caught.exception.code, "WRITE_OUTCOME_UNKNOWN")

    @mock.patch("zotero_cli.http.urllib.request.build_opener")
    def test_lost_write_connection_has_unknown_outcome(self, build_opener):
        build_opener.return_value.open.side_effect = TimeoutError()
        with tempfile.TemporaryDirectory() as tmp:
            token = Path(tmp) / "bridge-token"
            token.write_text("a" * 64 + "\n", encoding="utf-8")
            os.chmod(token, 0o600)
            with self.assertRaises(CliError) as caught:
                BridgeClient(23119, token).operation("fulltext_adopt", {})
        self.assertEqual(caught.exception.code, "WRITE_OUTCOME_UNKNOWN")

    def test_token_format_matches_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            token = Path(tmp) / "bridge-token"
            token.write_text("not-a-token\n", encoding="utf-8")
            os.chmod(token, 0o600)
            self.assertFalse(token_status(token)["ok"])
            token.write_text("b" * 64 + "\n", encoding="utf-8")
            self.assertTrue(token_status(token)["ok"])


if __name__ == "__main__":
    unittest.main()
