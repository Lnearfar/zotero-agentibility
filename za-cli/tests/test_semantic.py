import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from za_cli.errors import CliError
from za_cli.semantic import SemanticIndex, default_index_path


class Embedding:
    def __init__(self):
        self.calls = []

    def __call__(self, texts):
        self.calls.append(list(texts))
        return [[float(len(text))] for text in texts]


class Collection:
    def __init__(self):
        self.rows = {}
        self.queries = 0

    def count(self):
        return len(self.rows)

    def get(self, limit=None, offset=0, include=None, where=None):
        values = list(self.rows.values())
        if where:
            values = [row for row in values if row["metadata"].get("item_key") == where["item_key"]]
        values = values[offset : offset + limit] if limit else values[offset:]
        result = {"ids": [v["id"] for v in values], "metadatas": [v["metadata"] for v in values]}
        if include and "documents" in include:
            result["documents"] = [v["document"] for v in values]
        return result

    def upsert(self, ids, documents, metadatas, embeddings=None):
        for index, item_id in enumerate(ids):
            self.rows[item_id] = {"id": item_id, "document": documents[index], "metadata": metadatas[index]}

    def delete(self, ids=None, where=None):
        if ids is None:
            ids = [item_id for item_id, row in self.rows.items() if row["metadata"].get("item_key") == where["item_key"]]
        for item_id in ids:
            self.rows.pop(item_id, None)

    def query(self, query_texts, n_results, include, where=None):
        self.queries += 1
        rows = list(self.rows.values())
        if where and "item_key" in where:
            keys = where["item_key"]["$in"]
            rows = [row for row in rows if row["metadata"].get("item_key") in keys]
        rows = rows[:n_results]
        return {
            "documents": [[row["document"] for row in rows]],
            "metadatas": [[row["metadata"] for row in rows]],
            "distances": [[0.1 + i / 100 for i in range(len(rows))]],
        }


class DB:
    def __init__(self, items):
        self.items = items
        self.lookup_calls = []

    def index_inventory(self, item_keys=None):
        keys = list(self.items) if item_keys is None else list(item_keys)
        return [{
            "key": key,
            "dateModified": self.items[key].get("dateModified", ""),
            "attachments": [{"key": "EFGH5678", "dateModified": "", "typeName": "attachment"}],
        } for key in keys if key in self.items]

    def lookup(self, key):
        self.lookup_calls.append(key)
        return self.items[key]


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "fulltext.md"
        self.source.write_text("text", encoding="utf-8")
        self.db = DB({"ABCD1234": {"title": "A paper", "typeName": "journalArticle", "fields": {}, "creators": [], "tags": []}})
        self.collection = Collection()
        self.embedding = Embedding()
        self.index = SemanticIndex(self.root / "index", collection=self.collection, embedding_function=self.embedding)

    def tearDown(self):
        self.temp.cleanup()

    def update(self, *, kind="markdown", item_keys=None):
        source = {"kind": kind, "attachmentKey": "EFGH5678", "path": str(self.source), "exists": True}
        with patch("za_cli.semantic.sources.preferred_source", return_value=source), patch(
            "za_cli.semantic.sources.read_source",
            side_effect=lambda source, **kwargs: {"content": self.source.read_text(encoding="utf-8")},
        ):
            return self.index.update(self.db, self.root, item_keys=item_keys)

    def test_default_path_is_stable_and_profile_specific(self):
        first = default_index_path(self.root)
        second = default_index_path(self.root.resolve())
        self.assertEqual(first, second)
        self.assertIn(".local/share/zotero-agentibility/index", str(first))
        self.assertNotIn("zotero-mcp", str(first))

    def test_more_than_120_chunks_are_indexed(self):
        self.source.write_text("x" * (1500 * 121), encoding="utf-8")
        report = self.update()
        self.assertEqual(report["indexed"], 1)
        self.assertGreater(len(self.collection.rows), 120)
        self.assertIn("ABCD1234#120", self.collection.rows)
        embedded = [text for batch in self.embedding.calls for text in batch]
        self.assertNotEqual(embedded[0], embedded[1])

    def test_line_and_pdf_page_provenance(self):
        self.source.write_text("one\ntwo\nthree\n", encoding="utf-8")
        self.update()
        metadata = next(iter(self.collection.rows.values()))["metadata"]
        self.assertEqual(metadata["location"], "lines 1-3")
        self.assertNotIn("page", metadata)

        self.collection.rows.clear()
        self.source.write_text("page one\n\fpage two\n", encoding="utf-8")
        self.update(kind="pdf")
        metadata = next(iter(self.collection.rows.values()))["metadata"]
        self.assertEqual(metadata["page"], 1)
        self.assertEqual(metadata["page_end"], 2)
        self.assertIn("PDF pages 1-2", metadata["location"])

    def test_unchanged_update_does_not_read_or_embed_source(self):
        source = {"kind": "markdown", "attachmentKey": "EFGH5678", "path": str(self.source), "exists": True}
        with patch("za_cli.semantic.sources.preferred_source", return_value=source), patch(
            "za_cli.semantic.sources.read_source", return_value={"content": "text"}
        ) as read_source:
            self.index.update(self.db, self.root, item_keys=["ABCD1234"])
            self.db.lookup_calls.clear()
            self.embedding.calls.clear()
            report = self.index.update(self.db, self.root, item_keys=["ABCD1234"])
        self.assertEqual(report["unchanged"], 1)
        self.assertEqual(self.db.lookup_calls, [])
        self.assertEqual(self.embedding.calls, [])
        self.assertEqual(read_source.call_count, 1)

    def test_only_changed_item_is_rebuilt(self):
        self.db.items["EFGH5678"] = {
            "title": "B", "typeName": "book", "dateModified": "v1",
            "fields": {}, "creators": [], "tags": [],
        }
        source = {"kind": "markdown", "attachmentKey": "EFGH5678", "path": str(self.source), "exists": True}
        with patch("za_cli.semantic.sources.preferred_source", return_value=source), patch(
            "za_cli.semantic.sources.read_source", return_value={"content": "text"}
        ) as read_source:
            self.index.update(self.db, self.root)
            self.db.lookup_calls.clear()
            self.embedding.calls.clear()
            read_source.reset_mock()
            self.db.items["EFGH5678"]["dateModified"] = "v2"
            report = self.index.update(self.db, self.root)
        self.assertEqual((report["updated"], report["unchanged"]), (1, 1))
        self.assertEqual(self.db.lookup_calls, ["EFGH5678"])
        self.assertEqual(read_source.call_count, 1)
        self.assertEqual(len(self.embedding.calls), 1)

    def test_pdf_passages_are_replaced_when_markdown_becomes_preferred(self):
        current = {"kind": "pdf", "attachmentKey": "PDFKEY33"}

        def source(_attachments, _data_dir):
            return {**current, "path": str(self.source), "exists": True}

        with patch("za_cli.semantic.sources.preferred_source", side_effect=source), patch(
            "za_cli.semantic.sources.read_source",
            side_effect=lambda _source, **_kwargs: {"content": self.source.read_text(encoding="utf-8")},
        ):
            self.source.write_text("pdf " * 600, encoding="utf-8")
            self.index.update(self.db, self.root)
            self.assertGreater(len(self.collection.rows), 1)
            current.update(kind="markdown", attachmentKey="MARKDOWN")
            self.source.write_text("markdown text", encoding="utf-8")
            report = self.index.update(self.db, self.root)
        self.assertEqual(report["updated"], 1)
        self.assertGreater(report["removed_passages"], 0)
        self.assertEqual(set(self.collection.rows), {"ABCD1234#0"})
        metadata = self.collection.rows["ABCD1234#0"]["metadata"]
        self.assertEqual((metadata["source_kind"], metadata["attachment_key"]), ("markdown", "MARKDOWN"))

    def test_failed_rebuild_keeps_old_passages_and_retries(self):
        self.update()
        before = copy.deepcopy(self.collection.rows)
        self.source.write_text("changed text", encoding="utf-8")
        source = {"kind": "markdown", "attachmentKey": "EFGH5678", "path": str(self.source), "exists": True}
        with patch("za_cli.semantic.sources.preferred_source", return_value=source), patch(
            "za_cli.semantic.sources.read_source", side_effect=RuntimeError("extract failed")
        ):
            failed = self.index.update(self.db, self.root)
        self.assertEqual(len(failed["errors"]), 1)
        self.assertEqual(self.collection.rows, before)
        retried = self.update()
        self.assertEqual(retried["updated"], 1)
        self.assertEqual(self.collection.rows["ABCD1234#0"]["document"], "changed text")

    def test_stale_chunks_are_deleted(self):
        self.source.write_text("a" * 2200, encoding="utf-8")
        self.update()
        self.source.write_text("short", encoding="utf-8")
        report = self.update()
        self.assertEqual(report["updated"], 1)
        self.assertEqual(set(self.collection.rows), {"ABCD1234#0"})

    def test_full_update_removes_deleted_literature_item(self):
        self.db.items["EFGH5678"] = {"title": "B", "typeName": "book", "fields": {}, "creators": [], "tags": []}
        self.update()
        self.source.write_text("other", encoding="utf-8")
        self.update()
        self.db.items.pop("EFGH5678")
        report = self.update()
        self.assertGreaterEqual(report["removed"], 1)
        self.assertFalse(any(row["metadata"]["item_key"] == "EFGH5678" for row in self.collection.rows.values()))

    def test_scoped_update_removes_requested_deleted_item(self):
        self.update()
        self.db.items.pop("ABCD1234")
        report = self.update(item_keys=["ABCD1234"])
        self.assertEqual(report["removed"], 1)
        self.assertEqual(self.collection.rows, {})

    def test_global_grouping_and_item_scope(self):
        self.source.write_text("first passage " + "x" * 1700, encoding="utf-8")
        self.update()
        self.db.items["EFGH5678"] = {"title": "B", "typeName": "book", "fields": {}, "creators": [], "tags": []}
        self.source.write_text("second item", encoding="utf-8")
        self.update(item_keys=["EFGH5678"])
        global_hits = self.index.search("passage", limit=10)["results"]
        self.assertEqual(len({hit["item_key"] for hit in global_hits}), 2)
        scoped_hits = self.index.search("passage", limit=10, item_keys=["ABCD1234"], item_scope=True)["results"]
        self.assertGreaterEqual(len(scoped_hits), 2)
        self.assertIn("content_sha256", scoped_hits[0]["provenance"])
        self.assertIn("char_start", scoped_hits[0]["provenance"])

    def test_single_item_update_preserves_last_bulk_status(self):
        self.db.items["EFGH5678"] = {"title": "B", "typeName": "book", "fields": {}, "creators": [], "tags": []}
        self.update()
        reconcile = self.index._state()["last_reconcile"]
        self.update(item_keys=["ABCD1234"])
        self.assertEqual(self.index.status()["last_bulk_update"]["total"], 2)
        self.assertEqual(self.index._state()["last_reconcile"], reconcile)

    def test_status_uses_persisted_stats_without_scanning_passages(self):
        self.update()
        with patch.object(self.collection, "get", side_effect=AssertionError("status scanned passages")):
            status = self.index.status()
        self.assertEqual(status["count"], 1)
        self.assertEqual(status["item_count"], 1)
        self.assertEqual(status["source_counts"], {"markdown": 1})
        self.assertFalse(status["stats_stale"])

    def test_deep_status_scans_passages_on_request(self):
        self.update()
        status = self.index.status(deep=True)
        self.assertEqual(status["count"], 1)
        self.assertEqual(status["item_count"], 1)

    def test_status_reports_corrupt_persisted_state(self):
        self.index.index_path.mkdir()
        (self.index.index_path / "state.json").write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(CliError, "Semantic index state is unreadable"):
            self.index.status()

    def test_search_returns_cached_index_freshness_without_scanning(self):
        self.update()
        with patch.object(self.index, "_rows", side_effect=AssertionError("search scanned passages")):
            result = self.index.search("text")
        self.assertEqual(result["index"]["last_updated"], self.index._state()["updated_at"])
        self.assertFalse(result["index"]["refreshing"])
        self.assertIn("possibly_stale", result["index"])

    def test_search_never_updates(self):
        self.update()
        with patch.object(self.index, "update", side_effect=AssertionError("search updated")):
            self.index.search("text")
        self.assertEqual(self.collection.queries, 1)


if __name__ == "__main__":
    unittest.main()
