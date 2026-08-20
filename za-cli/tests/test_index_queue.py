import json
import tempfile
import unittest
from pathlib import Path

from za_cli.index_queue import IndexQueue


class SemanticIndex:
    def __init__(self, report=None, on_update=None):
        self.report = report or {"errors": []}
        self.on_update = on_update
        self.calls = []

    def update(self, db, data_dir, *, item_keys):
        self.calls.append(list(item_keys))
        if self.on_update:
            self.on_update()
        return self.report


class IndexQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.queue = IndexQueue(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_enqueue_is_durable_and_worker_coalesces_duplicate_keys(self):
        self.queue.enqueue(["ABCD1234", "ABCD1234", "EFGH5678"], reason="test")
        status = self.queue.status()
        self.assertEqual(status["pending_events"], 2)
        self.assertEqual(status["pending_items"], 2)

        semantic = SemanticIndex()
        result = self.queue.work_once(semantic, object(), self.root)
        self.assertEqual(semantic.calls, [["ABCD1234", "EFGH5678"]])
        self.assertEqual(result["processed_items"], 2)
        self.assertEqual(self.queue.status()["pending_events"], 0)

    def test_failed_item_remains_pending_while_success_is_acknowledged(self):
        self.queue.enqueue(["ABCD1234", "EFGH5678"])
        semantic = SemanticIndex({"errors": [{"item_key": "EFGH5678", "error": "failed"}]})
        result = self.queue.work_once(semantic, object(), self.root)
        self.assertEqual(result["acknowledged_items"], 1)
        status = self.queue.status()
        self.assertEqual((status["pending_events"], status["pending_items"]), (1, 1))

    def test_event_enqueued_during_update_is_not_acknowledged(self):
        self.queue.enqueue(["ABCD1234"])
        semantic = SemanticIndex(on_update=lambda: self.queue.enqueue(["ABCD1234"], reason="changed-again"))
        self.queue.work_once(semantic, object(), self.root)
        self.assertEqual(self.queue.status()["pending_events"], 1)

    def test_refreshing_is_true_only_during_an_active_batch(self):
        states = []
        self.queue.enqueue(["ABCD1234"])
        semantic = SemanticIndex(on_update=lambda: states.append(self.queue.runtime_status()))
        with self.queue.worker():
            self.assertFalse(self.queue.runtime_status()["refreshing"])
            self.queue.work_once(semantic, object(), self.root)
            self.assertFalse(self.queue.runtime_status()["refreshing"])
        self.assertEqual(states, [{"worker_running": True, "refreshing": True}])

    def test_malformed_event_is_quarantined(self):
        self.queue.pending.mkdir(parents=True)
        (self.queue.pending / "broken.json").write_text("{", encoding="utf-8")
        result = self.queue.work_once(SemanticIndex(), object(), self.root)
        self.assertEqual(result["quarantined_events"], 1)
        self.assertEqual(self.queue.status()["failed_events"], 1)

    def test_failed_update_leaves_snapshot_pending(self):
        self.queue.enqueue(["ABCD1234"])
        semantic = SemanticIndex()
        semantic.update = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("busy"))
        with self.assertRaisesRegex(RuntimeError, "busy"):
            self.queue.work_once(semantic, object(), self.root)
        self.assertEqual(self.queue.status()["pending_events"], 1)

    def test_worker_lock_reports_running_and_rejects_second_worker(self):
        with self.queue.worker():
            self.assertTrue(self.queue.status()["worker_running"])
            with self.assertRaisesRegex(Exception, "Another index worker"):
                with self.queue.worker():
                    pass
        self.assertFalse(self.queue.status()["worker_running"])

    def test_enqueue_rejects_invalid_item_key(self):
        with self.assertRaisesRegex(Exception, "Invalid Zotero Item Key"):
            self.queue.enqueue(["bad/key"])


if __name__ == "__main__":
    unittest.main()
