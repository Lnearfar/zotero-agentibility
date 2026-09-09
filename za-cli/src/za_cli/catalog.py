from __future__ import annotations

import re
from typing import Any, Iterable

from .errors import CliError

_ITEM_KEY = re.compile(r"^[A-Z0-9]{8}$")
_BATCH_SIZE = 100


def _validate_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise CliError("INVALID_CATALOG_RESPONSE", "Index catalog item must be an object")
    required = {"key": str, "itemID": int, "dateModified": str, "typeName": str, "title": str,
                "creators": list, "year": str, "doi": str, "attachments": list}
    if not set(required) <= set(item) or set(item) - set(required) - {"fields", "tags", "dateAdded"}:
        raise CliError("INVALID_CATALOG_RESPONSE", "Index catalog item has an invalid shape")
    if any(not isinstance(item[name], kind) for name, kind in required.items()):
        raise CliError("INVALID_CATALOG_RESPONSE", "Index catalog item has invalid fields")
    if not _ITEM_KEY.fullmatch(item["key"]) or any(not isinstance(value, str) for value in item["creators"]):
        raise CliError("INVALID_CATALOG_RESPONSE", "Index catalog item has invalid identifiers")
    if (not isinstance(item.get("fields", {}), dict)
            or any(not isinstance(value, str) for value in item.get("fields", {}).values())
            or not isinstance(item.get("tags", []), list)
            or any(not isinstance(tag, str) for tag in item.get("tags", []))
            or not isinstance(item.get("dateAdded", ""), str)):
        raise CliError("INVALID_CATALOG_RESPONSE", "Index catalog metadata has invalid fields")
    attachments = []
    required_attachment = {"key": str, "itemID": int, "typeName": str, "title": str, "linkMode": int,
                           "contentType": str, "attachmentPath": str, "dateModified": str, "tags": list}
    for attachment in item["attachments"]:
        if not isinstance(attachment, dict) or set(attachment) != set(required_attachment):
            raise CliError("INVALID_CATALOG_RESPONSE", "Index catalog attachment has an invalid shape")
        if any(not isinstance(attachment[name], kind) for name, kind in required_attachment.items()):
            raise CliError("INVALID_CATALOG_RESPONSE", "Index catalog attachment has invalid fields")
        if not _ITEM_KEY.fullmatch(attachment["key"]) or attachment["typeName"] != "attachment" \
                or any(not isinstance(tag, str) for tag in attachment["tags"]):
            raise CliError("INVALID_CATALOG_RESPONSE", "Index catalog attachment has invalid fields")
        attachments.append(dict(attachment))
    return {**item, "attachments": attachments}


class LiveCatalog:
    """Native Zotero catalog snapshot used by every semantic update."""

    def __init__(self, bridge):
        self.bridge = bridge
        self._items: dict[str, dict[str, Any]] = {}

    def index_inventory(self, item_keys: Iterable[str] | None = None) -> list[dict[str, Any]]:
        requested = None if item_keys is None else list(dict.fromkeys(item_keys))
        if requested is not None:
            invalid = [key for key in requested if not isinstance(key, str) or not _ITEM_KEY.fullmatch(key)]
            if invalid:
                raise CliError("INVALID_ITEM_KEY", f"Invalid Zotero Item Key: {invalid[0]}")
        batches = [None] if requested is None else [requested[offset:offset + _BATCH_SIZE]
                                                    for offset in range(0, len(requested), _BATCH_SIZE)]
        items: list[dict[str, Any]] = []
        for batch in batches:
            result = self.bridge.index_catalog(batch)
            if not isinstance(result, dict) or set(result) != {"items"} or not isinstance(result["items"], list):
                raise CliError("INVALID_CATALOG_RESPONSE", "Index catalog returned an invalid result")
            parsed = [_validate_item(item) for item in result["items"]]
            if len({item["key"] for item in parsed}) != len(parsed):
                raise CliError("INVALID_CATALOG_RESPONSE", "Index catalog returned duplicate item keys")
            if batch is not None and (len(parsed) > len(batch) or any(item["key"] not in batch for item in parsed)):
                raise CliError("INVALID_CATALOG_RESPONSE", "Index catalog returned items outside the requested scope")
            self._items.update({item["key"]: item for item in parsed})
            items.extend(parsed)
        return items

    def lookup(self, key: str) -> dict[str, Any]:
        try:
            item = self._items[key]
        except KeyError as exc:
            raise CliError("INVALID_CATALOG_RESPONSE", f"Index catalog omitted item: {key}") from exc
        # The native read contract is intentionally small; normalize it to the
        # existing semantic metadata shape without consulting Zotero SQLite.
        return {**item, "fields": item.get("fields", {"date": item["year"], "DOI": item["doi"]}),
                "tags": item.get("tags", [])}
