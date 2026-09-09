import io
import json
import tempfile
import time
import unittest
from pathlib import Path

from za_cli.index_queue import IndexQueue


class SemanticIndex:
    def __init__(self, report=None, on_update=None):
        self.report = report or {"errors": []}
        self.on_update = on_update
        self.calls = []

    def update(self, catalog, data_dir, *, item_keys=None):
        self.calls.append(None if item_keys is None else list(item_keys))
        if self.on_update:
            self.on_update()
        return self.report

    def _state(self):
        return {"stats": {"passages": 3, "items": 1}, "item_stats": {"ABCD1234": {"passages": 3}}}


class IndexQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.queue = IndexQueue(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_enqueue_is_durable_and_worker_coalesces_duplicate_keys(self):
        self.queue.enqueue(["ABCD1234", "ABCD1234", "EFGH5678"], reason="test")
        self.assertEqual(self.queue.status()["pending_keys"], 2)
        semantic = SemanticIndex()
        result = self.queue.work_once(semantic, object(), self.root)
        self.assertEqual(semantic.calls, [["ABCD1234", "EFGH5678"]])
        self.assertEqual(result["processed_items"], 2)
        self.assertEqual(self.queue.status()["pending_items"], 0)

    def test_failed_item_moves_to_durable_retry_while_success_is_acknowledged(self):
        self.queue.enqueue(["ABCD1234", "EFGH5678"])
        semantic = SemanticIndex({"errors": [{"item_key": "EFGH5678", "error": "failed"}]})
        result = self.queue.work_once(semantic, object(), self.root)
        self.assertEqual(result["acknowledged_items"], 1)
        self.assertEqual(self.queue.status()["pending_keys"], 1)
        self.assertEqual(self.queue.status()["failed_events"], 1)

    def test_new_work_is_processed_with_a_retrying_failure(self):
        self.queue.enqueue(["ABCD1234"])
        self.queue.work_once(SemanticIndex({"errors": [{"item_key": "ABCD1234", "error": "failed"}]}), object(), self.root)
        self.queue.enqueue(["EFGH5678"])
        semantic = SemanticIndex({"errors": [{"item_key": "ABCD1234", "error": "failed"}]})
        self.queue.work_once(semantic, object(), self.root)
        self.assertIn("EFGH5678", semantic.calls[-1])
        self.assertEqual(self.queue.status()["pending_keys"], 1)

    def test_event_enqueued_during_update_is_not_acknowledged(self):
        self.queue.enqueue(["ABCD1234"])
        semantic = SemanticIndex(on_update=lambda: self.queue.enqueue(["ABCD1234"], reason="changed-again"))
        self.queue.work_once(semantic, object(), self.root)
        self.assertEqual(self.queue.status()["pending_items"], 1)

    def test_malformed_event_is_quarantined_once(self):
        self.queue.pending.mkdir(parents=True)
        (self.queue.pending / "broken.json").write_text("{", encoding="utf-8")
        result = self.queue.work_once(SemanticIndex(), object(), self.root)
        self.assertEqual(result["quarantined_events"], 1)
        self.assertEqual(self.queue.status()["failed_events"], 1)

    def test_managed_pipe_persists_notification_and_stops_on_shutdown(self):
        output = io.StringIO()
        semantic = SemanticIndex()
        class Pipe:
            def __iter__(self):
                yield '{"operation":"enqueue","item_keys":["ABCD1234"]}\n'
                time.sleep(.05)
                yield '{"operation":"shutdown"}\n'

        self.queue.run_managed(semantic, object(), self.root, input_stream=Pipe(), output_stream=output, poll_seconds=.01)
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertTrue(events and all(event["event"] == "status" for event in events))
        self.assertTrue({"phase", "heartbeat", "pending_items", "pending_keys", "active_item_keys", "last_error",
                         "last_report", "last_updated", "last_reconcile", "count", "item_count", "item_stats", "errors"}
                        <= set(events[-1]["state"]))
        self.assertIn(["ABCD1234"], semantic.calls)
        self.assertEqual(self.queue.status()["runtime"]["phase"], "stopped")

    def test_managed_pipe_stops_at_eof(self):
        self.queue.run_managed(SemanticIndex(), object(), self.root, input_stream=io.StringIO(),
                               output_stream=io.StringIO(), poll_seconds=.01)
        self.assertEqual(self.queue.status()["runtime"]["phase"], "stopped")

    def test_worker_lock_reports_running_and_rejects_second_worker(self):
        with self.queue.worker():
            self.assertTrue(self.queue.status()["worker_running"])
            with self.assertRaisesRegex(Exception, "Another index worker"):
                with self.queue.worker():
                    pass

    def test_enqueue_rejects_invalid_item_key(self):
        with self.assertRaisesRegex(Exception, "Invalid Zotero Item Key"):
            self.queue.enqueue(["bad/key"])


if __name__ == "__main__":
    unittest.main()
