"""Local semantic indexing for Literature Item sources.

Passage splitting, snippets, Chroma grouping, and update behavior are derived
in part from zotero-mcp 0.6.2 (MIT) and rewritten for complete canonical-
Markdown-first indexing with exact source provenance.
"""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import sources
from .errors import CliError

CHUNK_SIZE = 1500
OVERLAP = 200
SNIPPET_WIDTH = 320
COLLECTION_NAME = "passages"
_BATCH_SIZE = 100


def default_index_path(data_dir: Path) -> Path:
    """Return the profile-specific local index directory without creating it."""
    resolved = Path(data_dir).expanduser().resolve()
    profile_id = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:16]
    return Path.home() / ".local" / "share" / "zotero-agent-library" / "index" / profile_id


def split_into_passages(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = OVERLAP) -> list[tuple[str, int, int]]:
    """Split text on natural boundaries, retaining exact source offsets."""
    if not text or not text.strip():
        return []
    if overlap >= chunk_size:
        overlap = chunk_size // 4
    passages: list[tuple[str, int, int]] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        if end < len(text):
            window = text[start:end]
            for separator in ("\n\n", ". ", ".\n", "\n", " "):
                index = window.rfind(separator)
                if index >= int(chunk_size * 0.5):
                    end = start + index + len(separator)
                    break
        if end <= start:
            end = min(len(text), start + chunk_size)
        passages.append((text[start:end], start, end))
        if end >= len(text):
            break
        next_start = end - overlap
        start = next_start if next_start > start else end
    return passages


def best_snippet(query: str, text: str, width: int = SNIPPET_WIDTH) -> tuple[str, int]:
    """Return the fixed-width window richest in lexical query terms."""
    text = text or ""
    if not text.strip():
        return "", 0
    if len(text) <= width:
        return text.strip(), 0
    terms = [term for term in re.findall(r"\w+", (query or "").lower()) if len(term) > 2]
    if not terms:
        return text[:width].strip(), 0
    lowered = text.lower()
    best_start, best_score = 0, -1
    for match in re.finditer(r"\w+", lowered):
        if match.group(0) not in terms:
            continue
        start = max(0, match.start() - width // 3)
        score = sum(lowered[start : start + width].count(term) for term in terms)
        if score > best_score:
            best_start, best_score = start, score
    return text[best_start : best_start + width].strip(), best_start


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _line_range(text: str, start: int, end: int) -> tuple[int, int]:
    start_line = text.count("\n", 0, start) + 1
    end_line = text.count("\n", 0, end)
    if end > start and text[end - 1] != "\n":
        end_line += 1
    return start_line, max(start_line, end_line)


def _page_range(text: str, start: int, end: int) -> tuple[int, int] | None:
    if "\f" not in text:
        return None
    start_page = text.count("\f", 0, start) + 1
    end_offset = end - 1 if end > start and text[end - 1] == "\f" else end
    end_page = text.count("\f", 0, end_offset) + 1
    return start_page, max(start_page, end_page)


def _scalar(value: Any) -> str | int | float | bool:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _item_metadata(item: dict[str, Any]) -> dict[str, Any]:
    fields = item.get("fields") or {}
    creators = item.get("creators") or []
    tags = item.get("tags") or []
    extra = str(fields.get("extra", ""))
    citation_key = next((line.split(":", 1)[1].strip() for line in extra.splitlines()
                         if line.lower().startswith(("citation key:", "citationkey:"))), "")
    return {
        "title": _scalar(item.get("title", "")),
        "item_type": _scalar(item.get("typeName", item.get("itemType", item.get("type", "")))),
        "creators": _scalar(", ".join(map(str, creators)) if isinstance(creators, (list, tuple)) else creators),
        "abstract": "",  # overwrite metadata from pre-v0.3 development indexes; abstract is embedding-only
        "date": _scalar(fields.get("date", item.get("date", ""))),
        "date_added": _scalar(item.get("dateAdded", item.get("date_added", ""))),
        "date_modified": _scalar(item.get("dateModified", item.get("date_modified", ""))),
        "doi": _scalar(fields.get("DOI", fields.get("doi", item.get("DOI", "")))),
        "publication": _scalar(fields.get("publicationTitle", fields.get("publication", item.get("publication", "")))),
        "url": _scalar(fields.get("url", item.get("url", ""))),
        "tags": _scalar(", ".join(map(str, tags)) if isinstance(tags, (list, tuple)) else tags),
        "citation_key": citation_key,
    }


def _embedding_text(item: dict[str, Any], passage: str, *, include_metadata: bool) -> str:
    if not include_metadata:
        return passage
    fields = item.get("fields") or {}
    metadata = _item_metadata(item)
    structured = " ".join(str(value) for value in (
        metadata["title"],
        metadata["creators"],
        fields.get("abstractNote", ""),
        metadata["publication"],
        metadata["tags"],
    ) if value)
    return f"{structured}\n\n{passage}" if structured else passage


def _where(filters: dict[str, Any] | None, item_keys: Iterable[str] | None) -> dict[str, Any] | None:
    scope = list(item_keys) if item_keys is not None else None
    clauses = []
    if filters:
        clauses.append(filters)
    if scope is not None:
        clauses.append({"item_key": {"$in": scope}})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


@contextmanager
def _update_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        try:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CliError("CONCURRENT_UPDATE", "Another semantic index update is already running") from exc
        yield
    finally:
        try:
            if "fcntl" in locals():
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


class SemanticIndex:
    def __init__(self, index_path: Path, *, client=None, collection=None, embedding_function=None):
        self.index_path = Path(index_path).expanduser().resolve()
        self.embedding_function = embedding_function
        self.client = client
        self.collection = collection

    def _open(self, *, create: bool = False):
        if self.collection is not None:
            return self.collection
        if not create and not self.index_path.exists():
            return None
        if self.client is None:
            import chromadb
            from chromadb.config import Settings

            self.client = chromadb.PersistentClient(
                path=str(self.index_path),
                settings=Settings(anonymized_telemetry=False),
            )
        if self.embedding_function is None:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

            self.embedding_function = DefaultEmbeddingFunction()
        from chromadb.errors import NotFoundError

        try:
            self.collection = self.client.get_collection(
                name=COLLECTION_NAME, embedding_function=self.embedding_function
            )
        except NotFoundError:
            if not create:
                return None
            self.collection = self.client.create_collection(
                name=COLLECTION_NAME, embedding_function=self.embedding_function
            )
        return self.collection

    def _count(self) -> int:
        collection = self._open()
        return int(collection.count()) if collection is not None else 0

    def _rows(self) -> list[dict[str, Any]]:
        collection = self._open()
        if collection is None:
            return []
        try:
            result = collection.get(include=["metadatas"])
        except TypeError:
            result = collection.get()
        ids = result.get("ids", []) or []
        metadatas = result.get("metadatas", []) or []
        return [{"id": item_id, "metadata": metadata or {}} for item_id, metadata in zip(ids, metadatas)]

    def _state(self) -> dict[str, Any]:
        try:
            return json.loads((self.index_path / "state.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}

    def _save_state(self, report: dict[str, Any]) -> None:
        state = self._state()
        state.update({
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "complete": not bool(report["errors"]),
            "scope": report.get("scope"),
            "report": {key: value for key, value in report.items() if key != "errors"},
        })
        if report.get("scope") == "library" or int(report.get("total", 0)) > 1:
            state["last_bulk_update"] = {
                "updated_at": state["updated_at"],
                "complete": state["complete"],
                "scope": state["scope"],
                "total": report.get("total", 0),
                "errors": len(report["errors"]),
            }
        target = self.index_path / "state.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary.replace(target)

    def _embed(self, texts: list[str]) -> list[Any] | None:
        function = self.embedding_function or getattr(self.collection, "_embedding_function", None)
        if function is None:
            return None
        if hasattr(function, "embed_documents"):
            return list(function.embed_documents(texts))
        return list(function(texts))

    def _delete_item(self, item_key: str, rows: list[dict[str, Any]] | None = None) -> int:
        ids = [row["id"] for row in (rows or self._rows()) if row["metadata"].get("item_key") == item_key]
        if not ids:
            return 0
        try:
            self.collection.delete(ids=ids)
        except (TypeError, ValueError):
            self.collection.delete(where={"item_key": item_key})
        return len(ids)

    def _prepare(self, db, item_key: str, item: dict[str, Any], data_dir: Path) -> tuple[list[dict[str, Any]], str, bool]:
        source = sources.resolve_for_item(db, item_key, data_dir)
        path = Path(source["path"])
        content_sha256 = _sha256_file(path)
        read = sources.read_source(source, start=1, limit=10**9, all_text=True)
        text = read.get("content", "") or ""
        source_meta = _item_metadata(item)
        source_meta.update({
            "item_key": item_key,
            "source_kind": _scalar(source.get("kind", "")),
            "attachment_key": _scalar(source.get("attachmentKey", source.get("attachment_key", ""))),
            "content_sha256": content_sha256,
            "partial": bool(read.get("partial", False)),
        })
        fingerprint_input = {key: value for key, value in source_meta.items() if key != "partial"}
        fingerprint_input["structured_text"] = _embedding_text(item, "", include_metadata=True)
        fingerprint = hashlib.sha256(json.dumps(fingerprint_input, sort_keys=True).encode()).hexdigest()
        passages = split_into_passages(text)
        if not passages:
            raise CliError("EMPTY_SOURCE", "Preferred Full Text source is empty")
        records = []
        for index, (passage, start, end) in enumerate(passages):
            line_start, line_end = _line_range(text, start, end)
            page_range = _page_range(text, start, end) if source.get("kind") == "pdf" else None
            metadata = {
                **source_meta,
                "fingerprint": fingerprint,
                "chunk_index": index,
                "n_chunks": len(passages),
                "char_start": start,
                "char_end": end,
                "location_start": line_start,
                "location_end": line_end,
                "location": (f"PDF pages {page_range[0]}-{page_range[1]}; lines {line_start}-{line_end}" if page_range
                             else f"lines {line_start}-{line_end}"),
            }
            if page_range:
                metadata.update(page=page_range[0], page_end=page_range[1])
            records.append({
                "id": f"{item_key}#{index}",
                "document": passage,
                "metadata": {key: _scalar(value) for key, value in metadata.items()},
                "embedding_text": _embedding_text(item, passage, include_metadata=index == 0),
            })
        return records, fingerprint, bool(read.get("partial", False))

    def update(self, db, data_dir: Path, *, force: bool = False, item_keys: Iterable[str] | None = None) -> dict[str, Any]:
        keys = list(item_keys) if item_keys is not None else list(db.all_literature_keys())
        scoped = item_keys is not None
        with _update_lock(self.index_path / "update.lock"):
            self._open(create=True)
            existing = self._rows()
            by_item: dict[str, list[dict[str, Any]]] = {}
            for row in existing:
                key = row["metadata"].get("item_key")
                if key:
                    by_item.setdefault(str(key), []).append(row)
            report = {"scope": "items" if scoped else "library", "total": len(keys),
                      "indexed": 0, "updated": 0, "unchanged": 0, "removed": 0,
                      "removed_passages": 0, "errors": [], "partial": False}
            for key in keys:
                try:
                    item = dict(db.lookup(key))
                    records, fingerprint, partial = self._prepare(db, key, item, Path(data_dir))
                    old = by_item.get(key, [])
                    old_fingerprints = {row["metadata"].get("fingerprint") for row in old}
                    old_hashes = {row["metadata"].get("content_sha256") for row in old}
                    unchanged = bool(old) and not force and len(old) == len(records) and (
                        fingerprint in old_fingerprints or (
                            None in old_fingerprints
                            and records[0]["metadata"]["content_sha256"] in old_hashes
                        )
                    )
                    if unchanged:
                        report["unchanged"] += 1
                        continue

                    embeddings = []
                    for offset in range(0, len(records), _BATCH_SIZE):
                        batch_embeddings = self._embed([
                            record["embedding_text"] for record in records[offset : offset + _BATCH_SIZE]
                        ])
                        if batch_embeddings is None:
                            raise CliError("EMBEDDING_UNAVAILABLE", "Local ONNX embedding function is unavailable")
                        embeddings.extend(batch_embeddings)
                    if len(embeddings) != len(records):
                        raise CliError("EMBEDDING_FAILED", "Embedding model returned an incomplete batch")
                    for record, embedding in zip(records, embeddings):
                        record["embedding"] = embedding

                    for offset in range(0, len(records), _BATCH_SIZE):
                        batch = records[offset : offset + _BATCH_SIZE]
                        self.collection.upsert(
                            ids=[record["id"] for record in batch],
                            documents=[record["document"] for record in batch],
                            metadatas=[record["metadata"] for record in batch],
                            embeddings=[record["embedding"] for record in batch],
                        )
                    new_ids = {record["id"] for record in records}
                    stale_ids = [row["id"] for row in old if row["id"] not in new_ids]
                    if stale_ids:
                        self.collection.delete(ids=stale_ids)
                        report["removed_passages"] += len(stale_ids)
                    report["updated" if old else "indexed"] += 1
                    report["partial"] = report["partial"] or partial
                except Exception as exc:
                    report["errors"].append({
                        "item_key": key,
                        "code": getattr(exc, "code", "INDEX_WRITE_FAILED"),
                        "error": str(exc),
                    })
                    report["partial"] = True
            if not scoped:
                current = set(keys)
                for key in set(by_item) - current:
                    removed = self._delete_item(key, by_item[key])
                    report["removed"] += 1
                    report["removed_passages"] += removed
            self._save_state(report)
            return report

    def search(self, query: str, *, limit: int = 10, filters: dict[str, Any] | None = None,
               item_keys: Iterable[str] | None = None, item_scope: bool = False) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            raise CliError("EMPTY_QUERY", "Search query must not be empty")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise CliError("INVALID_LIMIT", "Search limit must be a positive integer")
        count = self._count()
        if count == 0:
            raise CliError("INDEX_UNINITIALIZED", "Semantic index is not initialized")
        if filters is not None and not isinstance(filters, dict):
            raise CliError("INVALID_FILTERS", "Semantic filters must be an object")
        scope = list(item_keys) if item_keys is not None else None
        if scope == []:
            return {"query": query.strip(), "limit": limit, "filters": filters, "results": [], "total_found": 0}
        where = _where(filters, scope)
        kwargs = {"query_texts": [query.strip()], "n_results": min(count, limit if item_scope else limit * 4),
                  "include": ["documents", "metadatas", "distances"]}
        if where is not None:
            kwargs["where"] = where
        try:
            result = self.collection.query(**kwargs)
        except TypeError:
            kwargs.pop("include", None)
            result = self.collection.query(**kwargs)
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        hits = []
        for document, metadata, distance in zip(documents, metadatas, distances):
            metadata = metadata or {}
            document = document or ""
            score = 1 - float(distance)
            hit = {"item_key": metadata.get("item_key"), "score": score, "similarity_score": score,
                         "matched_text": document, "matched_passage": best_snippet(query, document)[0],
                         "provenance": {key: value for key, value in metadata.items()
                                        if key in {"source_kind", "attachment_key", "content_sha256", "fingerprint",
                                                   "chunk_index", "n_chunks", "char_start", "char_end", "location",
                                                   "location_start", "location_end", "page", "page_end", "partial"}},
                         "metadata": metadata}
            for key in ("chunk_index", "n_chunks", "char_start", "char_end", "page", "page_end"):
                if key in metadata:
                    hit[key] = metadata[key]
            hits.append(hit)
        if not item_scope:
            best: dict[str, dict[str, Any]] = {}
            for hit in hits:
                key = hit["item_key"]
                if key not in best or hit["score"] > best[key]["score"]:
                    best[key] = hit
            hits = sorted(best.values(), key=lambda hit: hit["score"], reverse=True)
        hits = hits[:limit]
        return {
            "query": query.strip(),
            "limit": limit,
            "filters": filters,
            "results": hits,
            "total_found": len(hits),
        }

    def status(self) -> dict[str, Any]:
        rows = self._rows()
        count = len(rows)
        item_keys = {row["metadata"].get("item_key") for row in rows if row["metadata"].get("item_key")}
        source_counts: dict[str, int] = {}
        partial_items = set()
        for row in rows:
            metadata = row["metadata"]
            source = str(metadata.get("source_kind") or "unknown")
            source_counts[source] = source_counts.get(source, 0) + 1
            if metadata.get("partial"):
                partial_items.add(metadata.get("item_key"))
        state = self._state()
        info = {
            "name": COLLECTION_NAME,
            "count": count,
            "item_count": len(item_keys),
            "embedding_model": "all-MiniLM-L6-v2",
            "persist_directory": str(self.index_path),
            "source_counts": source_counts,
            "partial_items": len(partial_items - {None}),
            "last_update": state.get("updated_at"),
            "last_update_complete": state.get("complete"),
            "last_update_scope": state.get("scope"),
            "last_bulk_update": state.get("last_bulk_update"),
        }
        return {"collection_info": info, **info, "path": str(self.index_path), "initialized": bool(count)}

    def inspect(self, *, limit: int = 20, filter_text: str | None = None,
                show_documents: bool = False, stats: bool = False) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise CliError("INVALID_LIMIT", "Inspect limit must be a positive integer")
        collection = self._open()
        if collection is None or not self._count():
            raise CliError("INDEX_UNINITIALIZED", "Semantic index is not initialized")
        include = ["metadatas"] + (["documents"] if show_documents else [])
        rows = []
        needle = filter_text.casefold() if filter_text else None
        offset = 0
        while len(rows) < limit:
            paged = True
            try:
                result = collection.get(limit=limit if needle is None else 500, offset=offset, include=include)
            except TypeError:
                paged = False
                result = collection.get(include=include)
            ids = result.get("ids", []) or []
            metadatas = result.get("metadatas", []) or []
            documents = result.get("documents", []) or []
            for index, (item_id, metadata) in enumerate(zip(ids, metadatas)):
                document = documents[index] if index < len(documents) else None
                haystack = json.dumps(metadata or {}, ensure_ascii=False)
                if document is not None:
                    haystack += "\n" + document
                if needle and needle not in haystack.casefold():
                    continue
                row = {"id": item_id, "metadata": metadata or {}}
                if show_documents:
                    row["document"] = document or ""
                rows.append(row)
                if len(rows) >= limit:
                    break
            if not paged or needle is None or len(ids) < 500:
                break
            offset += len(ids)
        output: dict[str, Any] = {"count": self._count(), "items": rows[:limit]}
        if stats:
            all_rows = self._rows()
            item_types: dict[str, int] = {}
            source_kinds: dict[str, int] = {}
            item_keys = set()
            fulltext_items = set()
            for row in all_rows:
                metadata = row["metadata"]
                item_key = metadata.get("item_key")
                if item_key:
                    item_keys.add(item_key)
                    fulltext_items.add(item_key)
                item_type = str(metadata.get("item_type") or "unknown")
                source_kind = str(metadata.get("source_kind") or "unknown")
                item_types[item_type] = item_types.get(item_type, 0) + 1
                source_kinds[source_kind] = source_kinds.get(source_kind, 0) + 1
            output["stats"] = {
                "items": len(item_keys),
                "passages": len(all_rows),
                "with_fulltext": len(fulltext_items),
                "item_types": item_types,
                "source_kinds": source_kinds,
            }
        return output
