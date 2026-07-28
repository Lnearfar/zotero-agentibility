"""Local semantic indexing for Literature Item sources."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from . import sources
from .errors import CliError

chunk_size = 1500
overlap = 200
snippet_width = 320
CHUNK_SIZE = chunk_size
OVERLAP = overlap
SNIPPET_WIDTH = snippet_width
COLLECTION_NAME = "passages"
_BATCH_SIZE = 100


def default_index_path(data_dir: Path) -> Path:
    """Return the profile-specific local index directory without creating it."""
    resolved = Path(data_dir).expanduser().resolve()
    profile_id = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:16]
    return Path.home() / ".local" / "share" / "zotero-agent-library" / "index" / profile_id


def split_into_passages(text: str, chunk_size: int = chunk_size, overlap: int = overlap) -> list[tuple[str, int, int]]:
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


def best_snippet(query: str, text: str, width: int = snippet_width) -> tuple[str, int]:
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
    return {
        "title": _scalar(item.get("title", "")),
        "item_type": _scalar(item.get("typeName", item.get("itemType", item.get("type", "")))),
        "creators": _scalar(", ".join(map(str, creators)) if isinstance(creators, (list, tuple)) else creators),
        "date": _scalar(fields.get("date", item.get("date", ""))),
        "date_added": _scalar(item.get("dateAdded", item.get("date_added", ""))),
        "date_modified": _scalar(item.get("dateModified", item.get("date_modified", ""))),
        "doi": _scalar(fields.get("DOI", fields.get("doi", item.get("DOI", "")))),
        "publication": _scalar(fields.get("publicationTitle", fields.get("publication", item.get("publication", "")))),
        "tags": _scalar(", ".join(map(str, tags)) if isinstance(tags, (list, tuple)) else tags),
    }


def _embedding_text(item: dict[str, Any], passage: str) -> str:
    metadata = _item_metadata(item)
    header = "\n".join(f"{key}: {value}" for key, value in metadata.items())
    return f"{header}\n\n{passage}"


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
        if self.collection is None:
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
            self.collection = self.client.get_or_create_collection(
                name=COLLECTION_NAME, embedding_function=self.embedding_function
            )

    def _count(self) -> int:
        return int(self.collection.count())

    def _rows(self) -> list[dict[str, Any]]:
        try:
            result = self.collection.get(include=["metadatas"])
        except TypeError:
            result = self.collection.get()
        ids = result.get("ids", []) or []
        metadatas = result.get("metadatas", []) or []
        return [{"id": item_id, "metadata": metadata or {}} for item_id, metadata in zip(ids, metadatas)]

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

    def _prepare(self, item_key: str, item: dict[str, Any], data_dir: Path) -> tuple[list[dict[str, Any]], str, bool]:
        source = sources.resolve_for_item(item.get("_db", item), item_key, data_dir)
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
        fingerprint = hashlib.sha256(json.dumps(fingerprint_input, sort_keys=True).encode()).hexdigest()
        passages = split_into_passages(text)
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
                "embedding_text": _embedding_text(item, passage),
            })
        return records, fingerprint, bool(read.get("partial", False))

    def update(self, db, data_dir: Path, *, force: bool = False, item_keys: Iterable[str] | None = None) -> dict[str, Any]:
        keys = list(item_keys) if item_keys is not None else list(db.all_literature_keys())
        scoped = item_keys is not None
        with _update_lock(self.index_path / "update.lock"):
            existing = self._rows()
            by_item: dict[str, list[dict[str, Any]]] = {}
            for row in existing:
                key = row["metadata"].get("item_key")
                if key:
                    by_item.setdefault(str(key), []).append(row)
            report = {"total": len(keys), "indexed": 0, "updated": 0, "unchanged": 0,
                      "removed": 0, "errors": [], "partial": False}
            prepared: list[tuple[str, list[dict[str, Any]], bool, bool]] = []
            for key in keys:
                try:
                    item = dict(db.lookup(key))
                    item["_db"] = db
                    records, fingerprint, partial = self._prepare(key, item, Path(data_dir))
                    old = by_item.get(key, [])
                    old_fingerprints = {row["metadata"].get("fingerprint") for row in old}
                    old_hashes = {row["metadata"].get("content_sha256") for row in old}
                    unchanged = bool(old) and not force and len(old) == len(records) and (
                        fingerprint in old_fingerprints or (None in old_fingerprints and records and records[0]["metadata"]["content_sha256"] in old_hashes)
                    )
                    if unchanged:
                        report["unchanged"] += 1
                        continue
                    embeddings = []
                    for offset in range(0, len(records), _BATCH_SIZE):
                        embeddings.extend(self._embed([record["embedding_text"] for record in records[offset : offset + _BATCH_SIZE]]) or [])
                    for record, embedding in zip(records, embeddings):
                        record["embedding"] = embedding
                    prepared.append((key, records, bool(old), partial))
                except Exception as exc:
                    report["errors"].append({"item_key": key, "code": getattr(exc, "code", "INTERNAL_ERROR"), "error": str(exc)})
                    report["partial"] = True
            if not scoped:
                current = set(keys)
                for key in set(by_item) - current:
                    report["removed"] += self._delete_item(key, by_item[key])
            for key, records, had_old, partial in prepared:
                report["removed"] += self._delete_item(key, by_item.get(key, []))
                if had_old:
                    report["updated"] += 1
                else:
                    report["indexed"] += 1
                report["partial"] = report["partial"] or partial
                for offset in range(0, len(records), _BATCH_SIZE):
                    batch = records[offset : offset + _BATCH_SIZE]
                    kwargs = {
                        "ids": [record["id"] for record in batch],
                        "documents": [record["document"] for record in batch],
                        "metadatas": [record["metadata"] for record in batch],
                    }
                    if all("embedding" in record for record in batch):
                        kwargs["embeddings"] = [record["embedding"] for record in batch]
                    self.collection.upsert(**kwargs)
            return report

    def search(self, query: str, *, limit: int = 10, filters: dict[str, Any] | None = None,
               item_keys: Iterable[str] | None = None, item_scope: bool = False) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip():
            raise CliError("EMPTY_QUERY", "Search query must not be empty")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise CliError("INVALID_LIMIT", "Search limit must be a positive integer")
        if self._count() == 0:
            raise CliError("INDEX_UNINITIALIZED", "Semantic index is not initialized")
        where = _where(filters, item_keys)
        kwargs = {"query_texts": [query.strip()], "n_results": limit if item_scope else limit * 4,
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
                                        if key in {"source_kind", "attachment_key", "location", "location_start", "location_end", "page", "page_end"}},
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
        return hits[:limit]

    def status(self) -> dict[str, Any]:
        count = self._count()
        info = {"name": COLLECTION_NAME, "count": count, "embedding_model": "default",
                "persist_directory": str(self.index_path)}
        return {"collection_info": info, **info, "path": str(self.index_path), "initialized": bool(count)}

    def inspect(self, *, limit: int = 20, filter_text: str | None = None,
                show_documents: bool = False, stats: bool = False) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise CliError("INVALID_LIMIT", "Inspect limit must be a positive integer")
        include = ["metadatas"] + (["documents"] if show_documents else [])
        try:
            result = self.collection.get(limit=limit, include=include)
        except TypeError:
            result = self.collection.get(include=include)
        ids = result.get("ids", []) or []
        metadatas = result.get("metadatas", []) or []
        documents = result.get("documents", []) or []
        rows = []
        needle = filter_text.casefold() if filter_text else None
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
        output: dict[str, Any] = {"count": self._count(), "items": rows[:limit]}
        if stats:
            output["stats"] = {"items": len({row["metadata"].get("item_key") for row in self._rows() if row["metadata"].get("item_key")}),
                               "passages": self._count()}
        return output
