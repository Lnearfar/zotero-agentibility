from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from zotero_cli.db import Database, connect_immutable
from zotero_cli.errors import CliError


SCHEMA = """
CREATE TABLE libraries(libraryID INTEGER PRIMARY KEY,type TEXT);
CREATE TABLE items(itemID INTEGER PRIMARY KEY,key TEXT,libraryID INTEGER,itemTypeID INTEGER,dateAdded TEXT,dateModified TEXT);
CREATE TABLE itemTypes(itemTypeID INTEGER PRIMARY KEY,typeName TEXT);
CREATE TABLE collections(collectionID INTEGER PRIMARY KEY,key TEXT,collectionName TEXT,parentCollectionID INTEGER,libraryID INTEGER);
CREATE TABLE collectionItems(collectionID INTEGER,itemID INTEGER);
CREATE TABLE deletedItems(itemID INTEGER);
CREATE TABLE deletedCollections(collectionID INTEGER);
CREATE TABLE itemAttachments(itemID INTEGER,parentItemID INTEGER,linkMode INTEGER,contentType TEXT,path TEXT);
CREATE TABLE itemData(itemID INTEGER,fieldID INTEGER,valueID INTEGER);
CREATE TABLE fields(fieldID INTEGER PRIMARY KEY,fieldName TEXT);
CREATE TABLE baseFieldMappings(itemTypeID INTEGER,baseFieldID INTEGER,fieldID INTEGER);
CREATE TABLE itemDataValues(valueID INTEGER PRIMARY KEY,value TEXT);
CREATE TABLE itemTags(itemID INTEGER,tagID INTEGER);
CREATE TABLE tags(tagID INTEGER PRIMARY KEY,name TEXT);
CREATE TABLE itemCreators(itemID INTEGER,creatorID INTEGER,orderIndex INTEGER);
CREATE TABLE creators(creatorID INTEGER PRIMARY KEY,firstName TEXT,lastName TEXT);
"""


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "zotero.sqlite"
        with sqlite3.connect(self.path) as conn:
            conn.executescript(SCHEMA)
            conn.executemany("INSERT INTO itemTypes VALUES(?,?)", [(1, "journalArticle"), (2, "attachment"), (3, "note"), (4, "annotation"), (5, "case")])
            conn.execute("INSERT INTO libraries VALUES(1,'user')")
            conn.executemany(
                "INSERT INTO items VALUES(?,?,?,?,?,?)",
                [(1, "ITEMONE1", 1, 1, "", ""), (2, "ITEMTWO2", 1, 1, "", ""), (3, "PDFKEY33", 1, 2, "", "")],
            )
            conn.executemany("INSERT INTO fields VALUES(?,?)", [(1, "title"), (2, "caseName")])
            conn.execute("INSERT INTO baseFieldMappings VALUES(5,1,2)")
            conn.executemany("INSERT INTO itemDataValues VALUES(?,?)", [(1, "Filed Paper"), (2, "Unfiled Paper"), (3, "Paper PDF")])
            conn.executemany("INSERT INTO itemData VALUES(?,1,?)", [(1, 1), (2, 2), (3, 3)])
            conn.executemany(
                "INSERT INTO collections VALUES(?,?,?,?,?)",
                [(1, "ROOTCOL1", "Research", None, 1), (2, "CHILDCOL", "Methods", 1, 1)],
            )
            conn.execute("INSERT INTO collectionItems VALUES(1,1)")
            conn.execute("INSERT INTO itemAttachments VALUES(3,1,0,'application/pdf','storage:paper.pdf')")
            conn.execute("INSERT INTO creators VALUES(1,'Ada','Lovelace')")
            conn.execute("INSERT INTO itemCreators VALUES(1,1,0)")
            conn.execute("INSERT INTO tags VALUES(1,'source')")
            conn.execute("INSERT INTO itemTags VALUES(3,1)")
        self.db = Database(self.path)

    def test_root_and_collection_listing_are_direct(self):
        self.db.schema_check()
        root = self.db.list_entries(None, offset=0, limit=50)
        self.assertEqual([(e["kind"], e["key"]) for e in root["entries"]], [("collection", "ROOTCOL1"), ("item", "ITEMTWO2")])
        collection = self.db.list_entries("ROOTCOL1", offset=0, limit=50)
        self.assertEqual([(e["kind"], e["key"]) for e in collection["entries"]], [("collection", "CHILDCOL"), ("item", "ITEMONE1")])

    def test_lookup_uses_item_type_title_mapping(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO items VALUES(4,'CASEKEY4',1,5,'','')")
            conn.execute("INSERT INTO itemDataValues VALUES(4,'Mapped Case Name')")
            conn.execute("INSERT INTO itemData VALUES(4,2,4)")
        self.assertEqual(self.db.lookup("CASEKEY4")["title"], "Mapped Case Name")

    def test_lookup_and_attachment_metadata(self):
        item = self.db.lookup("ITEMONE1")
        self.assertEqual(item["title"], "Filed Paper")
        self.assertEqual(item["creators"], ["Ada Lovelace"])
        self.assertEqual(self.db.attachments("ITEMONE1")[0]["tags"], ["source"])

    def test_deleted_collection_is_hidden(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO deletedCollections VALUES(1)")
        root = self.db.list_entries(None, offset=0, limit=50)
        keys = [entry["key"] for entry in root["entries"]]
        self.assertNotIn("ROOTCOL1", keys)
        self.assertIn("ITEMONE1", keys)
        self.assertIsNone(self.db.collection_by_key("ROOTCOL1"))
        self.assertEqual(self.db.lookup("ITEMONE1")["collections"], [])

    def test_deleted_items_do_not_count_in_collection(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO deletedItems VALUES(1)")
        research = self.db.collection_by_key("ROOTCOL1")
        self.assertEqual(research["itemCount"], 0)

    def test_uri_metacharacters_do_not_change_database_path(self):
        special = Path(self.temp.name) / "with?query#fragment.sqlite"
        with sqlite3.connect(special) as conn:
            conn.execute("CREATE TABLE marker(value TEXT)")
            conn.execute("INSERT INTO marker VALUES('right file')")
        with connect_immutable(special) as conn:
            self.assertEqual(conn.execute("SELECT value FROM marker").fetchone()[0], "right file")

    def test_ambiguous_collection_path_reports_keys(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO collections VALUES(3,'ROOTCOL2','Research',NULL,1)")
        with self.assertRaises(CliError) as caught:
            self.db.resolve_collection("/My Library/Research")
        self.assertEqual(caught.exception.code, "AMBIGUOUS_COLLECTION")
        self.assertEqual(len(caught.exception.details["candidates"]), 2)


if __name__ == "__main__":
    unittest.main()
