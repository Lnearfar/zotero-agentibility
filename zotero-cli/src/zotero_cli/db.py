"""Immutable Zotero catalog access.

Modified implementation derived in part from cli-anything-zotero at
f621952f3645546573d622440cbf707320f7a35f. All writable connections, backup
helpers, generated keys, and mutation SQL were removed; queries are limited to
this component's read-only My Library slice.
"""

from __future__ import annotations

import posixpath
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .errors import CliError

_REQUIRED = {
    "libraries": {"libraryID", "type"},
    "items": {"itemID", "key", "libraryID", "itemTypeID"},
    "itemTypes": {"itemTypeID", "typeName"},
    "collections": {"collectionID", "key", "collectionName", "parentCollectionID", "libraryID"},
    "collectionItems": {"collectionID", "itemID"},
    "deletedItems": {"itemID"},
    "deletedCollections": {"collectionID"},
    "itemAttachments": {"itemID", "parentItemID", "linkMode", "contentType", "path"},
    "itemData": {"itemID", "fieldID", "valueID"},
    "fields": {"fieldID", "fieldName"},
    "baseFieldMappings": {"itemTypeID", "baseFieldID", "fieldID"},
    "itemDataValues": {"valueID", "value"},
    "itemTags": {"itemID", "tagID"},
    "tags": {"tagID", "name"},
    "itemCreators": {"itemID", "creatorID", "orderIndex"},
    "creators": {"creatorID", "firstName", "lastName"},
}

_TITLE = """
COALESCE((
  SELECT v.value FROM itemData d
  JOIN fields f ON f.fieldID=d.fieldID
  JOIN itemDataValues v ON v.valueID=d.valueID
  WHERE d.itemID=i.itemID AND (
    f.fieldName='title' OR d.fieldID IN (
      SELECT m.fieldID FROM baseFieldMappings m
      JOIN fields base ON base.fieldID=m.baseFieldID
      WHERE m.itemTypeID=i.itemTypeID AND base.fieldName='title'
    )
  )
  ORDER BY CASE WHEN f.fieldName='title' THEN 0 ELSE 1 END LIMIT 1
), '')
"""


def connect_immutable(path: Path) -> sqlite3.Connection:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise CliError("DATABASE_NOT_FOUND", f"Zotero database not found: {path}")
    connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._library_id: int | None = None

    def schema_check(self) -> dict:
        with closing(connect_immutable(self.path)) as conn:
            missing: dict[str, list[str]] = {}
            for table, required in _REQUIRED.items():
                columns = {row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")')}
                absent = sorted(required - columns)
                if absent:
                    missing[table] = absent
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if missing:
            raise CliError("UNSUPPORTED_SCHEMA", "Unsupported Zotero SQLite schema", details=missing)
        return {"ok": True, "userVersion": version}

    def library_id(self) -> int:
        if self._library_id is None:
            with closing(connect_immutable(self.path)) as conn:
                row = conn.execute("SELECT libraryID FROM libraries WHERE type='user' ORDER BY libraryID LIMIT 1").fetchone()
            if not row:
                raise CliError("MY_LIBRARY_NOT_FOUND", "My Library was not found")
            self._library_id = int(row["libraryID"])
        return self._library_id

    def collections(self) -> list[dict[str, Any]]:
        with closing(connect_immutable(self.path)) as conn:
            rows = conn.execute(
                """SELECT c.collectionID,c.key,c.collectionName,c.parentCollectionID,c.libraryID,
                   COUNT(CASE WHEN di.itemID IS NULL THEN ci.itemID END) AS itemCount
                   FROM collections c LEFT JOIN collectionItems ci ON ci.collectionID=c.collectionID
                   LEFT JOIN deletedItems di ON di.itemID=ci.itemID
                   WHERE c.libraryID=?
                   AND NOT EXISTS (SELECT 1 FROM deletedCollections d WHERE d.collectionID=c.collectionID)
                   GROUP BY c.collectionID ORDER BY c.collectionName COLLATE NOCASE,c.collectionID""",
                (self.library_id(),),
            ).fetchall()
        collections = [dict(row) for row in rows]
        by_id = {row["collectionID"]: row for row in collections}

        def path_for(row: dict, seen: set[int] | None = None) -> str:
            seen = set() if seen is None else seen
            collection_id = int(row["collectionID"])
            if collection_id in seen:
                raise CliError("UNSUPPORTED_SCHEMA", "Collection hierarchy contains a cycle")
            seen.add(collection_id)
            parent = by_id.get(row["parentCollectionID"])
            prefix = path_for(parent, seen) if parent else "/My Library"
            return prefix + "/" + row["collectionName"]

        for row in collections:
            row["path"] = path_for(row)
        return collections

    def collection_by_key(self, key: str) -> dict | None:
        return next((row for row in self.collections() if row["key"] == key), None)

    def resolve_collection(self, target: str, current_key: str | None = None) -> dict | None:
        if target in {"/", "/My Library", "My Library"}:
            return None
        rows = self.collections()
        current = next((row for row in rows if row["key"] == current_key), None)
        if target == ".." and current:
            return next((row for row in rows if row["collectionID"] == current["parentCollectionID"]), None)
        if target.startswith("/"):
            path = posixpath.normpath(target)
        else:
            base = current["path"] if current else "/My Library"
            path = posixpath.normpath(base + "/" + target)
        if path == "/":
            path = "/My Library"
        if path == "/My Library":
            return None
        if not path.startswith("/My Library/"):
            raise CliError("INVALID_COLLECTION_PATH", "Collection path must stay under /My Library")
        matches = [row for row in rows if row["path"] == path]
        if not matches:
            raise CliError("COLLECTION_NOT_FOUND", f"Collection not found: {target}")
        if len(matches) > 1:
            raise CliError(
                "AMBIGUOUS_COLLECTION",
                f"Collection path is ambiguous: {path}",
                details={"candidates": [{"key": row["key"], "path": row["path"]} for row in matches]},
            )
        return matches[0]

    def list_entries(self, collection_key: str | None, *, offset: int, limit: int) -> dict:
        if offset < 0 or limit < 1:
            raise CliError("INVALID_PAGINATION", "--offset must be nonnegative and --limit positive")
        collections = self.collections()
        current = None
        if collection_key:
            current = next((row for row in collections if row["key"] == collection_key), None)
            if not current:
                raise CliError("COLLECTION_NOT_FOUND", f"Collection not found: {collection_key}")
        parent_id = current["collectionID"] if current else None
        child_collections = [
            {"kind": "collection", "key": row["key"], "name": row["collectionName"], "path": row["path"]}
            for row in collections
            if row["parentCollectionID"] == parent_id
        ]
        with closing(connect_immutable(self.path)) as conn:
            if current:
                where = "EXISTS (SELECT 1 FROM collectionItems ci WHERE ci.itemID=i.itemID AND ci.collectionID=?)"
                params = (current["collectionID"], self.library_id())
            else:
                where = """NOT EXISTS (
                    SELECT 1 FROM collectionItems ci WHERE ci.itemID=i.itemID
                    AND NOT EXISTS (
                        SELECT 1 FROM deletedCollections dc WHERE dc.collectionID=ci.collectionID
                    )
                )"""
                params = (self.library_id(),)
            rows = conn.execute(
                f"""SELECT i.key,{_TITLE} AS title,it.typeName
                    FROM items i JOIN itemTypes it ON it.itemTypeID=i.itemTypeID
                    WHERE {where} AND i.libraryID=?
                    AND it.typeName NOT IN ('attachment','note','annotation')
                    AND NOT EXISTS (SELECT 1 FROM deletedItems d WHERE d.itemID=i.itemID)
                    ORDER BY title COLLATE NOCASE,i.itemID""",
                params,
            ).fetchall()
        items = [{"kind": "item", "key": row["key"], "name": row["title"], "itemType": row["typeName"]} for row in rows]
        entries = child_collections + items
        return {
            "path": current["path"] if current else "/My Library",
            "collection": current["key"] if current else None,
            "entries": entries[offset : offset + limit],
            "offset": offset,
            "limit": limit,
            "total": len(entries),
            "hasMore": offset + limit < len(entries),
        }

    def _item_row(self, conn: sqlite3.Connection, key: str) -> sqlite3.Row:
        row = conn.execute(
            f"""SELECT i.itemID,i.key,i.libraryID,it.typeName,{_TITLE} AS title,i.dateAdded,i.dateModified
                FROM items i JOIN itemTypes it ON it.itemTypeID=i.itemTypeID
                WHERE i.key=? AND i.libraryID=?
                AND it.typeName NOT IN ('attachment','note','annotation')
                AND NOT EXISTS (SELECT 1 FROM deletedItems d WHERE d.itemID=i.itemID)""",
            (key, self.library_id()),
        ).fetchone()
        if not row:
            raise CliError("ITEM_NOT_FOUND", f"Literature Item not found: {key}")
        return row

    def lookup(self, key: str) -> dict:
        with closing(connect_immutable(self.path)) as conn:
            row = self._item_row(conn, key)
            item_id = int(row["itemID"])
            fields = {
                value["fieldName"]: value["value"]
                for value in conn.execute(
                    """SELECT f.fieldName,v.value FROM itemData d
                       JOIN fields f ON f.fieldID=d.fieldID JOIN itemDataValues v ON v.valueID=d.valueID
                       WHERE d.itemID=? ORDER BY f.fieldName""",
                    (item_id,),
                )
            }
            creators = [
                " ".join(filter(None, (creator["firstName"], creator["lastName"])))
                for creator in conn.execute(
                    """SELECT c.firstName,c.lastName FROM itemCreators ic
                       JOIN creators c ON c.creatorID=ic.creatorID WHERE ic.itemID=? ORDER BY ic.orderIndex""",
                    (item_id,),
                )
            ]
            tags = [tag["name"] for tag in conn.execute(
                "SELECT t.name FROM itemTags it JOIN tags t ON t.tagID=it.tagID WHERE it.itemID=? ORDER BY t.name", (item_id,)
            )]
            collections = [dict(c) for c in conn.execute(
                """SELECT c.key,c.collectionName FROM collectionItems ci JOIN collections c ON c.collectionID=ci.collectionID
                   WHERE ci.itemID=?
                   AND NOT EXISTS (SELECT 1 FROM deletedCollections dc WHERE dc.collectionID=c.collectionID)
                   ORDER BY c.collectionName""", (item_id,)
            )]
        return {**dict(row), "fields": fields, "creators": creators, "tags": tags, "collections": collections}

    def attachments(self, item_key: str) -> list[dict]:
        with closing(connect_immutable(self.path)) as conn:
            parent = self._item_row(conn, item_key)
            rows = conn.execute(
                f"""SELECT i.itemID,i.key,it.typeName,{_TITLE} AS title,a.linkMode,a.contentType,a.path AS attachmentPath
                    FROM itemAttachments a JOIN items i ON i.itemID=a.itemID
                    JOIN itemTypes it ON it.itemTypeID=i.itemTypeID
                    WHERE a.parentItemID=? AND NOT EXISTS (SELECT 1 FROM deletedItems d WHERE d.itemID=i.itemID)
                    ORDER BY i.itemID""",
                (parent["itemID"],),
            ).fetchall()
            attachments = [dict(row) for row in rows]
            for attachment in attachments:
                attachment["tags"] = [tag["name"] for tag in conn.execute(
                    "SELECT t.name FROM itemTags it JOIN tags t ON t.tagID=it.tagID WHERE it.itemID=? ORDER BY t.name",
                    (attachment["itemID"],),
                )]
        return attachments

    def literature_keys(self, collection_key: str | None = None) -> list[str]:
        with closing(connect_immutable(self.path)) as conn:
            if collection_key is None:
                rows = conn.execute(
                    """SELECT i.key FROM items i JOIN itemTypes it ON it.itemTypeID=i.itemTypeID
                       WHERE i.libraryID=? AND it.typeName NOT IN ('attachment','note','annotation')
                       AND NOT EXISTS (SELECT 1 FROM deletedItems d WHERE d.itemID=i.itemID)
                       ORDER BY i.itemID""",
                    (self.library_id(),),
                ).fetchall()
            else:
                collection = conn.execute(
                    """SELECT collectionID FROM collections WHERE key=? AND libraryID=?
                       AND NOT EXISTS (SELECT 1 FROM deletedCollections d WHERE d.collectionID=collections.collectionID)""",
                    (collection_key, self.library_id()),
                ).fetchone()
                if not collection:
                    raise CliError("COLLECTION_NOT_FOUND", f"Collection not found: {collection_key}")
                rows = conn.execute(
                    """WITH RECURSIVE descendants(collectionID) AS (
                         SELECT ? UNION
                         SELECT c.collectionID FROM collections c JOIN descendants d
                           ON c.parentCollectionID=d.collectionID
                         WHERE NOT EXISTS (SELECT 1 FROM deletedCollections x WHERE x.collectionID=c.collectionID)
                       )
                       SELECT DISTINCT i.key,i.itemID FROM descendants d
                       JOIN collectionItems ci ON ci.collectionID=d.collectionID
                       JOIN items i ON i.itemID=ci.itemID
                       JOIN itemTypes it ON it.itemTypeID=i.itemTypeID
                       WHERE i.libraryID=? AND it.typeName NOT IN ('attachment','note','annotation')
                       AND NOT EXISTS (SELECT 1 FROM deletedItems x WHERE x.itemID=i.itemID)
                       ORDER BY i.itemID""",
                    (collection["collectionID"], self.library_id()),
                ).fetchall()
        return [row["key"] for row in rows]

    def all_literature_keys(self) -> list[str]:
        return self.literature_keys()
