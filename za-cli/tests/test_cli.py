from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from za_cli.cli import cli, main
from za_cli.config import build_config
from za_cli.errors import CliError


class CliShapeTests(unittest.TestCase):
    def test_config_environment_name(self):
        with mock.patch.dict("os.environ", {"ZA_CLI_CONFIG_DIR": "/config"}, clear=False):
            self.assertEqual(build_config(None, False).config_dir, Path("/config"))

    def test_help_summarizes_every_command(self):
        result = CliRunner().invoke(cli, ["--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        for summary in (
            "app       Inspect Zotero and required local tools.",
            "cd        Change this session's current Collection.",
            "find      Find exact text in the selected Full Text source.",
            "fulltext  Audit, import, and safely adopt canonical Markdown Full Text.",
            "index     Update and inspect the local semantic Passage index.",
            "lookup    Show metadata for a Literature Item.",
            "ls        List child Collections and Literature Items.",
            "resolve   Create a verified parent item for a standalone PDF or EPUB.",
            "pwd       Show this session's current Collection path.",
            "read      Read bounded lines from the selected Full Text source.",
            "search    Search indexed Passages by semantic similarity.",
            "session   Create and inspect independent Browsing Sessions.",
            "source    Show the selected Markdown Full Text or fallback PDF.",
        ):
            self.assertIn(summary, result.output)
        self.assertIn("za-cli COMMAND --help", result.output)

    def test_pwd_does_not_report_valid_collection_as_warning(self):
        with mock.patch("za_cli.cli._session", return_value={"id": "agent-1", "collection": "COLL1234"}), \
             mock.patch("za_cli.cli._database") as database:
            database.return_value.collection_by_key.return_value = {
                "key": "COLL1234", "path": "/My Library/Research"
            }
            result = CliRunner().invoke(cli, ["--json", "pwd"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(json.loads(result.output)["data"]["warning"])

    def test_semantic_search_never_updates_implicitly(self):
        search_result = {"query": "stability", "results": [], "total_found": 0}
        with mock.patch("za_cli.cli._database") as database, \
             mock.patch("za_cli.cli._semantic_index") as semantic, \
             mock.patch("za_cli.cli._index_queue") as queue:
            semantic.return_value.search.return_value = search_result
            queue.return_value.runtime_status.return_value = {"worker_running": False, "refreshing": False}
            result = CliRunner().invoke(cli, [
                "--json", "search", "stability", "--item", "ABCD2345",
                "--filters", '{"itemType":"journalArticle"}',
            ])
        self.assertEqual(result.exit_code, 0, result.output)
        database.return_value.lookup.assert_called_once_with("ABCD2345")
        semantic.return_value.search.assert_called_once_with(
            "stability", limit=10, filters={"item_type": "journalArticle"},
            item_keys=["ABCD2345"], item_scope=True,
        )
        semantic.return_value.update.assert_not_called()

    def test_index_status_scans_only_with_deep_flag(self):
        with mock.patch("za_cli.cli._semantic_index") as semantic, \
             mock.patch("za_cli.cli._index_queue") as queue:
            semantic.return_value.status.return_value = {"initialized": True}
            queue.return_value.status.return_value = {"pending_items": 0}
            quick = CliRunner().invoke(cli, ["--json", "index", "status"])
            semantic.return_value.status.assert_called_once_with()
            semantic.return_value.status.reset_mock()
            deep = CliRunner().invoke(cli, ["--json", "index", "status", "--deep"])
            semantic.return_value.status.assert_called_once_with(deep=True)
        self.assertEqual((quick.exit_code, deep.exit_code), (0, 0))
        self.assertEqual(json.loads(quick.stdout)["data"]["queue"]["pending_items"], 0)

    def test_index_refresh_enqueues_without_updating(self):
        with mock.patch("za_cli.cli._database") as database, \
             mock.patch("za_cli.cli._index_queue") as queue, \
             mock.patch("za_cli.cli._semantic_index") as semantic:
            database.return_value.lookup.return_value = {"key": "ABCD2345"}
            queue.return_value.enqueue.return_value = {
                "queued": True, "item_keys": ["ABCD2345"], "events": 1,
            }
            result = CliRunner().invoke(cli, [
                "--json", "index", "refresh", "--item", "ABCD2345",
            ])
        self.assertEqual(result.exit_code, 0, result.output)
        queue.return_value.enqueue.assert_called_once_with(["ABCD2345"], reason="explicit-refresh")
        semantic.return_value.update.assert_not_called()

    def test_index_worker_once_drains_one_batch(self):
        with mock.patch("za_cli.cli._database") as database, \
             mock.patch("za_cli.cli._index_queue") as queue, \
             mock.patch("za_cli.cli._semantic_index") as semantic:
            queue.return_value.work_once.return_value = {"processed_items": 1, "report": {"errors": []}}
            result = CliRunner().invoke(cli, ["--json", "index", "worker", "--once"])
        self.assertEqual(result.exit_code, 0, result.output)
        queue.return_value.work_once.assert_called_once_with(
            semantic.return_value, database.return_value, mock.ANY,
        )

    def test_index_worker_once_returns_nonzero_for_partial_batch(self):
        with mock.patch("za_cli.cli._database"), \
             mock.patch("za_cli.cli._index_queue") as queue, \
             mock.patch("za_cli.cli._semantic_index"):
            queue.return_value.work_once.return_value = {
                "processed_items": 1,
                "report": {"errors": [{"item_key": "ABCD2345", "error": "failed"}]},
            }
            result = CliRunner().invoke(cli, ["--json", "index", "worker", "--once"])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertEqual(json.loads(result.stdout)["code"], "INDEX_PARTIAL")

    @mock.patch("za_cli.cli.BridgeClient")
    def test_metadata_resolve_requires_confirmation_before_bridge(self, bridge):
        result = CliRunner().invoke(cli, [
            "--json", "--session", "agent-1", "resolve", "KUS9YXK3",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(json.loads(result.stderr)["code"], "CONFIRMATION_REQUIRED")
        bridge.assert_not_called()

    def test_confirmed_metadata_resolve_sends_reviewed_snapshot(self):
        snapshot = {
            "attachmentKey": "KUS9YXK3",
            "expectedPath": "/tmp/book.pdf",
            "expectedSha256": "b" * 64,
            "markdownPath": "/tmp/book.md",
            "markdownSha256": "c" * 64,
        }
        with mock.patch("za_cli.cli._session", return_value={"id": "agent-1", "collection": None}), \
             mock.patch("za_cli.cli._database"), \
             mock.patch("za_cli.cli.sources.metadata_resolution_snapshot", return_value=snapshot), \
             mock.patch("za_cli.cli.BridgeClient") as bridge:
            bridge.return_value.metadata_resolve.return_value = {
                "attachment_key": "KUS9YXK3", "parent_item_key": "PARENT44", "resolution": "native"
            }
            result = CliRunner().invoke(cli, [
                "--json", "--session", "agent-1", "resolve", "KUS9YXK3",
                "--markdown", "/tmp/book.md", "--confirm",
            ])
        self.assertEqual(result.exit_code, 0, result.output)
        bridge.return_value.metadata_resolve.assert_called_once_with(
            session_id="agent-1",
            attachment_key="KUS9YXK3",
            expected_path="/tmp/book.pdf",
            expected_sha256="b" * 64,
            markdown_path="/tmp/book.md",
            markdown_sha256="c" * 64,
        )

    @mock.patch("za_cli.cli.BridgeClient")
    def test_fulltext_adopt_requires_confirmation_before_bridge(self, bridge):
        result = CliRunner().invoke(cli, [
            "--json", "--session", "agent-1", "fulltext", "adopt", "ABCD2345", "EFGH6789",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(json.loads(result.stderr)["code"], "CONFIRMATION_REQUIRED")
        bridge.assert_not_called()

    @mock.patch("za_cli.cli.BridgeClient")
    def test_fulltext_import_requires_confirmation_before_bridge(self, bridge):
        result = CliRunner().invoke(cli, [
            "--json", "--session", "agent-1", "fulltext", "import", "ABCD2345", "/tmp/paper.md",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(json.loads(result.stderr)["code"], "CONFIRMATION_REQUIRED")
        bridge.assert_not_called()

    def test_confirmed_fulltext_import_sends_reviewed_snapshot(self):
        snapshot = {
            "itemKey": "ABCD2345",
            "sourcePath": "/tmp/converted.md",
            "expectedSha256": "b" * 64,
            "replaceAttachmentKeys": ["JKLM2345"],
        }
        with mock.patch("za_cli.cli._session", return_value={"id": "agent-1", "collection": None}), \
             mock.patch("za_cli.cli._database"), \
             mock.patch("za_cli.cli.sources.import_snapshot", return_value=snapshot), \
             mock.patch("za_cli.cli._index_queue") as queue, \
             mock.patch("za_cli.cli._semantic_index") as semantic, \
             mock.patch("za_cli.cli.BridgeClient") as bridge:
            queue.return_value.enqueue.return_value = {
                "queued": True, "item_keys": ["ABCD2345"], "events": 1,
            }
            bridge.return_value.fulltext_import.return_value = {"markdown_attachment_key": "NEWW2345"}
            result = CliRunner().invoke(cli, [
                "--json", "--session", "agent-1", "fulltext", "import", "ABCD2345", "/tmp/converted.md",
                "--replace", "JKLM2345", "--confirm",
            ])
        self.assertEqual(result.exit_code, 0, result.output)
        queue.return_value.enqueue.assert_called_once_with(["ABCD2345"], reason="fulltext-mutation")
        semantic.return_value.update.assert_not_called()
        self.assertTrue(json.loads(result.stdout)["data"]["index"]["queued"])
        bridge.return_value.fulltext_import.assert_called_once_with(
            session_id="agent-1",
            item_key="ABCD2345",
            source_path="/tmp/converted.md",
            expected_sha256="b" * 64,
            replace_attachment_keys=["JKLM2345"],
        )

    def test_confirmed_fulltext_adopt_sends_reviewed_snapshot(self):
        snapshot = {
            "itemKey": "ABCD2345",
            "attachmentKey": "EFGH6789",
            "expectedPath": "/tmp/source.md",
            "expectedSha256": "b" * 64,
            "replaceAttachmentKeys": ["JKLM2345"],
        }
        with mock.patch("za_cli.cli._session", return_value={"id": "agent-1", "collection": None}), \
             mock.patch("za_cli.cli._database"), \
             mock.patch("za_cli.cli.sources.adoption_snapshot", return_value=snapshot), \
             mock.patch("za_cli.cli._queue_index_after_mutation", return_value=None), \
             mock.patch("za_cli.cli.BridgeClient") as bridge:
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
        with mock.patch("za_cli.cli._session", return_value={"id": "agent-1", "collection": None}), \
             mock.patch("za_cli.cli._database"), \
             mock.patch("za_cli.cli.sources.adoption_snapshot", return_value=snapshot), \
             mock.patch("za_cli.cli._queue_index_after_mutation", return_value=None), \
             mock.patch("za_cli.cli.BridgeClient") as bridge:
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
        with mock.patch("za_cli.cli._session", return_value={"id": "agent-1", "collection": None}), \
             mock.patch("za_cli.cli._database"), \
             mock.patch("za_cli.cli.sources.load_migration_candidates", return_value=(Path("/plan.json"), candidates)), \
             mock.patch("za_cli.cli._queue_index_after_mutation", return_value=None), \
             mock.patch("za_cli.cli.BridgeClient") as bridge:
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
        with mock.patch("za_cli.cli._session", return_value={"id": "agent-1", "collection": None}), \
             mock.patch("za_cli.cli._database"), \
             mock.patch("za_cli.cli.sources.load_migration_candidates", return_value=(Path("/plan.json"), candidates)), \
             mock.patch("za_cli.cli._queue_index_after_mutation", return_value=None), \
             mock.patch("za_cli.cli.BridgeClient") as bridge:
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
            "os.environ", {"ZA_CLI_CONFIG_DIR": tmp}, clear=False
        ):
            result = CliRunner().invoke(cli, ["--json", "--session", "bad/id", "session", "status"])
        self.assertNotEqual(result.exit_code, 0)
        payload = json.loads(result.stderr)
        self.assertEqual(payload["ok"], False)
        self.assertEqual(payload["code"], "INVALID_SESSION_ID")
        self.assertEqual(result.stderr.strip(), json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    def test_main_returns_nonzero_for_domain_error(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            "os.environ", {"ZA_CLI_CONFIG_DIR": tmp}, clear=False
        ), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--json", "--session", "bad/id", "session", "status"]), 1)

    def test_doctor_accepts_different_compatible_extension_release(self):
        app = {"ready": True, "running": True, "ping": {"ok": True}, "localApi": {"ok": True}}
        with mock.patch("za_cli.cli.probes", return_value=app), \
             mock.patch("za_cli.cli.token_status", return_value={"ok": True}), \
             mock.patch("za_cli.cli.BridgeClient") as bridge, \
             mock.patch("za_cli.cli.Database") as database, \
             mock.patch("za_cli.cli._semantic_index") as semantic_index, \
             mock.patch("za_cli.cli.shutil.which", return_value="/usr/bin/tool"):
            bridge.return_value.health.return_value = {
                "ok": True,
                "protocol": 1,
                "extension_version": "0.0.9",
            }
            database.return_value.schema_check.return_value = {"ok": True}
            semantic_index.return_value.status.return_value = {}
            result = CliRunner().invoke(cli, ["--json", "app", "doctor"])
        self.assertEqual(result.exit_code, 0, result.output)
        semantic_index.return_value.status.assert_called_once_with()
        payload = json.loads(result.stdout)
        self.assertTrue(payload["data"]["checks"]["bridge"]["ok"])

    def test_json_success_envelope(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            "os.environ", {"ZA_CLI_CONFIG_DIR": tmp}, clear=False
        ):
            result = CliRunner().invoke(cli, ["--json", "session", "create", "agent-1"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["id"], "agent-1")


if __name__ == "__main__":
    unittest.main()
