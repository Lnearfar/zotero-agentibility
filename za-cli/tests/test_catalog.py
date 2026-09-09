import unittest

from za_cli.catalog import LiveCatalog
from za_cli.errors import CliError


def item(key="ABCD1234"):
    return {
        "key": key, "itemID": 1, "dateModified": "2026-01-01", "typeName": "journalArticle", "title": "Paper",
        "creators": ["Ada Lovelace"], "year": "2026", "doi": "10.1/example", "attachments": [{
            "key": "EFGH5678", "itemID": 2, "typeName": "attachment", "title": "Paper PDF", "linkMode": 0,
            "contentType": "application/pdf", "attachmentPath": "storage:paper.pdf", "dateModified": "2026-01-01", "tags": [],
        }],
    }


class Bridge:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def index_catalog(self, keys):
        self.calls.append(keys)
        return self.responses.pop(0)


class LiveCatalogTests(unittest.TestCase):
    def test_full_inventory_caches_normalized_native_item(self):
        bridge = Bridge([{"items": [item()]}])
        catalog = LiveCatalog(bridge)
        self.assertEqual(catalog.index_inventory(), [item()])
        self.assertEqual(bridge.calls, [None])
        cached = catalog.lookup("ABCD1234")
        self.assertEqual(cached["fields"], {"date": "2026", "doi": "10.1/example"})
        self.assertEqual(cached["attachments"][0]["key"], "EFGH5678")

    def test_scoped_inventory_batches_native_reads_at_100(self):
        keys = [f"A{i:07d}" for i in range(101)]
        bridge = Bridge([{"items": []}, {"items": []}])
        LiveCatalog(bridge).index_inventory(keys)
        self.assertEqual([len(batch) for batch in bridge.calls], [100, 1])

    def test_missing_scoped_item_is_safe_for_semantic_removal(self):
        bridge = Bridge([{"items": []}])
        self.assertEqual(LiveCatalog(bridge).index_inventory(["ABCD1234"]), [])

    def test_malformed_or_out_of_scope_catalog_is_rejected(self):
        with self.assertRaisesRegex(CliError, "invalid result"):
            LiveCatalog(Bridge([{}])).index_inventory()
        malformed = item()
        malformed.pop("doi")
        with self.assertRaisesRegex(CliError, "invalid shape"):
            LiveCatalog(Bridge([{"items": [malformed]}])).index_inventory()
        with self.assertRaisesRegex(CliError, "outside"):
            LiveCatalog(Bridge([{"items": [item("EFGH5678")]}])).index_inventory(["ABCD1234"])


if __name__ == "__main__":
    unittest.main()
