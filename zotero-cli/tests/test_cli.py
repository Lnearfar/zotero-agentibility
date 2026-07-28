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
from zotero_cli.errors import CliError


class CliShapeTests(unittest.TestCase):
    def test_help_summarizes_every_command(self):
        result = CliRunner().invoke(cli, ["--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        for summary in (
            "app       Inspect Zotero and required local tools.",
            "cd        Change this session's current Collection.",
            "find      Find exact text in the selected Full Text source.",
            "fulltext  Audit and safely adopt canonical Markdown Full Text.",
            "lookup    Show metadata for a Literature Item.",
            "ls        List child Collections and Literature Items.",
            "pwd       Show this session's current Collection path.",
            "read      Read bounded lines from the selected Full Text source.",
            "session   Create and inspect independent Browsing Sessions.",
            "source    Show the selected Markdown Full Text or fallback PDF.",
        ):
            self.assertIn(summary, result.output)
        self.assertIn("zotero-cli COMMAND --help", result.output)

    @mock.patch("zotero_cli.cli.BridgeClient")
    def test_fulltext_adopt_requires_confirmation_before_bridge(self, bridge):
        result = CliRunner().invoke(cli, [
            "--json", "--session", "agent-1", "fulltext", "adopt", "ABCD2345", "EFGH6789",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(json.loads(result.stderr)["code"], "CONFIRMATION_REQUIRED")
        bridge.assert_not_called()

    def test_confirmed_fulltext_adopt_sends_reviewed_snapshot(self):
        snapshot = {
            "itemKey": "ABCD2345",
            "attachmentKey": "EFGH6789",
            "expectedPath": "/tmp/source.md",
            "expectedSha256": "b" * 64,
            "replaceAttachmentKeys": ["JKLM2345"],
        }
        with mock.patch("zotero_cli.cli._session", return_value={"id": "agent-1", "collection": None}), \
             mock.patch("zotero_cli.cli._database"), \
             mock.patch("zotero_cli.cli.sources.adoption_snapshot", return_value=snapshot), \
             mock.patch("zotero_cli.cli.BridgeClient") as bridge:
            bridge.return_value.fulltext_adopt.return_value = {"markdown_attachment_key": "NEWW2345"}
            result = CliRunner().invoke(cli, [
                "--json", "--session", "agent-1", "fulltext", "adopt", "ABCD2345", "EFGH6789",
                "--replace", "JKLM2345", "--confirm",
            ])
        self.assertEqual(result.exit_code, 0, result.output)
        bridge.return_value.fulltext_adopt.assert_called_once_with(
            session_id="agent-1",
            item_key="ABCD2345",
            attachment_key="EFGH6789",
            expected_path="/tmp/source.md",
            expected_sha256="b" * 64,
            replace_attachment_keys=["JKLM2345"],
        )

    def test_direct_adopt_reports_committed_audit_warning(self):
        snapshot = {
            "itemKey": "ABCD2345", "attachmentKey": "EFGH6789", "expectedPath": "/tmp/source.md",
            "expectedSha256": "b" * 64, "replaceAttachmentKeys": [],
        }
        warning = CliError(
            "AUDIT_LOG_FAILED_AFTER_WRITE",
            "committed",
            details={"markdown_attachment_key": "NEWW2345", "trashed_attachment_keys": ["EFGH6789"]},
        )
        with mock.patch("zotero_cli.cli._session", return_value={"id": "agent-1", "collection": None}), \
             mock.patch("zotero_cli.cli._database"), \
             mock.patch("zotero_cli.cli.sources.adoption_snapshot", return_value=snapshot), \
             mock.patch("zotero_cli.cli.BridgeClient") as bridge:
            bridge.return_value.fulltext_adopt.side_effect = warning
            result = CliRunner().invoke(cli, [
                "--json", "--session", "agent-1", "fulltext", "adopt", "ABCD2345", "EFGH6789", "--confirm",
            ])
        payload = json.loads(result.stdout)
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(payload["code"], "AUDIT_LOG_FAILED_AFTER_WRITE")
        self.assertEqual(payload["data"]["status"], "committed_with_warning")

    def test_migration_reports_partial_failure(self):
        candidates = [
            {"itemKey": "ABCD2345", "attachmentKey": "EFGH6789", "expectedPath": "/a.md",
             "expectedSha256": "a" * 64, "replaceAttachmentKeys": []},
            {"itemKey": "JKLM2345", "attachmentKey": "NPQR2345", "expectedPath": "/b.md",
             "expectedSha256": "b" * 64, "replaceAttachmentKeys": []},
        ]
        with mock.patch("zotero_cli.cli._session", return_value={"id": "agent-1", "collection": None}), \
             mock.patch("zotero_cli.cli._database"), \
             mock.patch("zotero_cli.cli.sources.load_migration_candidates", return_value=(Path("/plan.json"), candidates)), \
             mock.patch("zotero_cli.cli.BridgeClient") as bridge:
            bridge.return_value.fulltext_adopt.side_effect = [
                {"markdown_attachment_key": "STUV2345"},
                CliError("STALE_ATTACHMENT_HASH", "changed"),
            ]
            result = CliRunner().invoke(cli, [
                "--json", "--session", "agent-1", "fulltext", "migrate", "/plan.json", "--confirm",
            ])
        self.assertEqual(result.exit_code, 1, result.output)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["code"], "PARTIAL_FAILURE")
        self.assertEqual((payload["data"]["succeeded"], payload["data"]["failed"]), (1, 1))

    def test_migration_stops_when_write_outcome_is_unknown(self):
        candidates = [
            {"itemKey": "ABCD2345", "attachmentKey": "EFGH6789", "expectedPath": "/a.md",
             "expectedSha256": "a" * 64, "replaceAttachmentKeys": []},
            {"itemKey": "JKLM2345", "attachmentKey": "NPQR2345", "expectedPath": "/b.md",
             "expectedSha256": "b" * 64, "replaceAttachmentKeys": []},
        ]
        with mock.patch("zotero_cli.cli._session", return_value={"id": "agent-1", "collection": None}), \
             mock.patch("zotero_cli.cli._database"), \
             mock.patch("zotero_cli.cli.sources.load_migration_candidates", return_value=(Path("/plan.json"), candidates)), \
             mock.patch("zotero_cli.cli.BridgeClient") as bridge:
            bridge.return_value.fulltext_adopt.side_effect = CliError("WRITE_OUTCOME_UNKNOWN", "inspect first")
            result = CliRunner().invoke(cli, [
                "--json", "--session", "agent-1", "fulltext", "migrate", "/plan.json", "--confirm",
            ])
        payload = json.loads(result.stdout)
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(payload["code"], "OUTCOME_UNKNOWN")
        self.assertEqual((payload["data"]["attempted"], payload["data"]["skipped"]), (1, 1))
        self.assertEqual(bridge.return_value.fulltext_adopt.call_count, 1)

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
