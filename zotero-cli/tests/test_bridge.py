from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from zotero_cli.bridge import BridgeClient, token_status


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def getcode(self):
        return 200

    def read(self):
        return b'{"ok":true,"protocol":1,"extension_version":"0.1.1"}'


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
        self.assertEqual(request.full_url, "http://127.0.0.1:23119/zotero-agent-library/v1/operation")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + "a" * 64)
        self.assertEqual(
            request.data,
            b'{"protocol":1,"operation":"health","arguments":{}}',
        )
        self.assertTrue(result["ok"])

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
