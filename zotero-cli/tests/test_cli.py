from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from zotero_cli.cli import cli, main


class CliShapeTests(unittest.TestCase):
    def test_help_summarizes_every_command(self):
        result = CliRunner().invoke(cli, ["--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        for summary in (
            "app       Inspect Zotero and required local tools.",
            "cd        Change this session's current Collection.",
            "find      Find exact text in the selected Full Text source.",
            "fulltext  Inspect existing Markdown attachments without mutation.",
            "lookup    Show metadata for a Literature Item.",
            "ls        List child Collections and Literature Items.",
            "pwd       Show this session's current Collection path.",
            "read      Read bounded lines from the selected Full Text source.",
            "session   Create and inspect independent Browsing Sessions.",
            "source    Show the selected Markdown Full Text or fallback PDF.",
        ):
            self.assertIn(summary, result.output)
        self.assertIn("zotero-cli COMMAND --help", result.output)

    def test_json_error_is_compact_and_stable(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            "os.environ", {"ZOTERO_CLI_CONFIG_DIR": tmp}, clear=False
        ):
            result = CliRunner().invoke(cli, ["--json", "--session", "bad/id", "session", "status"])
        self.assertNotEqual(result.exit_code, 0)
        payload = json.loads(result.stderr)
        self.assertEqual(payload["ok"], False)
        self.assertEqual(payload["code"], "INVALID_SESSION_ID")
        self.assertEqual(result.stderr.strip(), json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    def test_main_returns_nonzero_for_domain_error(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            "os.environ", {"ZOTERO_CLI_CONFIG_DIR": tmp}, clear=False
        ), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--json", "--session", "bad/id", "session", "status"]), 1)

    def test_doctor_rejects_mismatched_extension_release(self):
        app = {"ready": True, "running": True, "ping": {"ok": True}, "localApi": {"ok": True}}
        with mock.patch("zotero_cli.cli.probes", return_value=app), \
             mock.patch("zotero_cli.cli.token_status", return_value={"ok": True}), \
             mock.patch("zotero_cli.cli.BridgeClient") as bridge, \
             mock.patch("zotero_cli.cli.Database") as database, \
             mock.patch("zotero_cli.cli.shutil.which", return_value="/usr/bin/tool"):
            bridge.return_value.health.return_value = {
                "ok": True,
                "protocol": 1,
                "extension_version": "0.0.9",
            }
            database.return_value.schema_check.return_value = {"ok": True}
            result = CliRunner().invoke(cli, ["--json", "app", "doctor"])
        self.assertEqual(result.exit_code, 1)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["data"]["checks"]["bridge"]["ok"])

    def test_json_success_envelope(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            "os.environ", {"ZOTERO_CLI_CONFIG_DIR": tmp}, clear=False
        ):
            result = CliRunner().invoke(cli, ["--json", "session", "create", "agent-1"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["id"], "agent-1")


if __name__ == "__main__":
    unittest.main()
