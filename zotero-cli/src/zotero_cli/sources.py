"""Preferred-source and attachment reading helpers.

Modified implementation derived in part from cli-anything-zotero at
f621952f3645546573d622440cbf707320f7a35f. Attachment path handling was
retained and narrowed; source selection is replaced with Markdown-first,
tag-driven read-only behavior that excludes Notes and Annotations.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path, PureWindowsPath
from urllib.parse import unquote, urlparse

from .db import Database
from .errors import CliError
from .poppler import extract_pdf

FULLTEXT_TAG = "zotero-cli:fulltext"
SOURCE_TAG = "zotero-cli:source"


def resolve_attachment_path(attachment: dict, data_dir: Path) -> Path | None:
    raw = attachment.get("attachmentPath")
    if not raw:
        return None
    raw = str(raw)
    if raw.startswith("storage:"):
        return (data_dir / "storage" / attachment["key"] / raw.split(":", 1)[1]).resolve()
    if raw.startswith("file://"):
        parsed = urlparse(raw)
        if parsed.netloc not in {"", "localhost"}:
            return Path(str(PureWindowsPath(f"//{parsed.netloc}{unquote(parsed.path)}")))
        return Path(unquote(parsed.path))
    path = Path(raw)
    return path if path.is_absolute() else (data_dir / path).resolve()


def preferred_source(attachments: list[dict], data_dir: Path) -> dict:
    attachments = [a for a in attachments if a.get("typeName") == "attachment"]
    markdown = [a for a in attachments if FULLTEXT_TAG in a.get("tags", [])]
    if len(markdown) > 1:
        raise CliError(
            "MULTIPLE_FULLTEXT",
            "Literature Item has multiple attachments tagged zotero-cli:fulltext",
            details={"keys": [a["key"] for a in markdown]},
        )
    if markdown:
        selected = markdown[0]
        path = resolve_attachment_path(selected, data_dir)
        filename = path.name if path else Path(str(selected.get("attachmentPath") or "")).name
        problems = []
        if filename != "fulltext.md":
            problems.append("filename must be fulltext.md")
        if selected.get("linkMode") != 0:
            problems.append("attachment must be a Zotero stored file")
        if selected.get("title") != "Markdown Full Text":
            problems.append("title must be Markdown Full Text")
        if str(selected.get("contentType") or "").lower() == "application/pdf":
            problems.append("attachment content type cannot be PDF")
        if problems:
            raise CliError(
                "INVALID_FULLTEXT",
                "The tagged Markdown Full Text attachment is not canonical",
                details={"key": selected["key"], "filename": filename, "problems": problems},
            )
        kind = "markdown"
    else:
        pdfs = [
            a for a in attachments
            if str(a.get("contentType") or "").lower() == "application/pdf"
            or str(a.get("attachmentPath") or "").lower().endswith(".pdf")
        ]
        tagged = [a for a in pdfs if SOURCE_TAG in a.get("tags", [])]
        if len(tagged) > 1:
            raise CliError(
                "AMBIGUOUS_SOURCE",
                "Multiple PDFs are tagged zotero-cli:source",
                details={"keys": [a["key"] for a in tagged]},
            )
        if tagged:
            selected = tagged[0]
        elif len(pdfs) == 1:
            selected = pdfs[0]
        elif len(pdfs) > 1:
            raise CliError(
                "AMBIGUOUS_SOURCE",
                "Multiple PDFs require one attachment tagged zotero-cli:source",
                details={"keys": [a["key"] for a in pdfs]},
            )
        else:
            raise CliError("SOURCE_NOT_FOUND", "No Markdown Full Text or Source Document PDF was found")
        kind = "pdf"
    path = resolve_attachment_path(selected, data_dir)
    return {
        "kind": kind,
        "attachmentKey": selected["key"],
        "title": selected.get("title") or ("Markdown Full Text" if kind == "markdown" else "PDF"),
        "path": str(path) if path else None,
        "exists": bool(path and path.is_file()),
    }


def resolve_for_item(db: Database, item_key: str, data_dir: Path) -> dict:
    source = preferred_source(db.attachments(item_key), data_dir)
    source["itemKey"] = item_key
    return source


def _require_file(source: dict) -> Path:
    if not source.get("path") or not source.get("exists"):
        raise CliError("SOURCE_MISSING", f"Preferred source file is missing: {source.get('attachmentKey')}")
    return Path(source["path"])


def segment_markdown(text: str, *, start: int, limit: int, all_text: bool) -> dict:
    if not all_text and (start < 1 or limit < 1):
        raise CliError("INVALID_RANGE", "--start and --limit must be positive")
    lines = text.splitlines(keepends=True)
    total = len(lines)
    if not total:
        if not all_text and start != 1:
            raise CliError("RANGE_OUT_OF_BOUNDS", "Markdown is empty")
        return {"content": "", "start": 0, "end": 0, "total": 0, "nextStart": None, "location": "lines 0-0"}
    if not all_text and start > total:
        raise CliError("RANGE_OUT_OF_BOUNDS", f"Markdown has {total} lines")
    first = 1 if all_text else start
    end = total if all_text else min(total, start + limit - 1)
    content = text if all_text else "".join(lines[start - 1 : end])
    return {
        "content": content,
        "start": first,
        "end": end,
        "total": total,
        "nextStart": end + 1 if end < total else None,
        "location": f"lines {first}-{end}",
    }


def read_source(source: dict, *, start: int, limit: int, all_text: bool) -> dict:
    path = _require_file(source)
    if source["kind"] == "markdown":
        segment = segment_markdown(path.read_text(encoding="utf-8", errors="replace"), start=start, limit=limit, all_text=all_text)
    else:
        segment = extract_pdf(path, start=start, limit=limit, all_text=all_text)
    return {**source, **segment}


def lexical_find(source: dict, query: str, *, limit: int, context: int = 0) -> dict:
    query = query.strip()
    if not query:
        raise CliError("EMPTY_QUERY", "Find query must not be empty")
    if limit < 1 or context < 0:
        raise CliError("INVALID_PAGINATION", "--limit must be positive and --context nonnegative")
    path = _require_file(source)
    matches = []
    if source["kind"] == "markdown":
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for index, line in enumerate(lines):
            if query.casefold() not in line.casefold():
                continue
            start = max(0, index - context)
            end = min(len(lines), index + context + 1)
            matches.append({
                "location": f"lines {start + 1}-{end}",
                "line": index + 1,
                "start": start + 1,
                "end": end,
                "text": "\n".join(lines[start:end]),
            })
    else:
        extracted = extract_pdf(path, all_text=True)
        global_offset = 0
        for page, page_text in enumerate(extracted["content"].split("\f"), 1):
            lines = page_text.splitlines()
            for index, line in enumerate(lines):
                if query.casefold() not in line.casefold():
                    continue
                start = max(0, index - context)
                end = min(len(lines), index + context + 1)
                matches.append({
                    "location": f"lines {global_offset + start + 1}-{global_offset + end} (PDF page {page})",
                    "page": page,
                    "pageLine": index + 1,
                    "line": global_offset + index + 1,
                    "start": global_offset + start + 1,
                    "end": global_offset + end,
                    "text": "\n".join(lines[start:end]),
                })
            global_offset += len(lines)
    return {
        **source,
        "query": query,
        "matches": matches[:limit],
        "total": len(matches),
        "limit": limit,
        "context": context,
    }


def _normalized_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _title_like(filename: str, title: str) -> bool:
    title_name = _normalized_name(title)
    stem = Path(filename).stem
    stem_name = _normalized_name(stem)
    if len(title_name) < 24 or len(stem_name) < 24:
        return False
    if title_name in stem_name or stem_name in title_name:
        return True
    match = re.search(r"(?:\s-\s|_)\d{4}[a-z]?(?:\s-\s|_)(.+)$", stem, re.IGNORECASE)
    if not match:
        return False
    paper_name = _normalized_name(match.group(1))
    return len(paper_name) >= 24 and (title_name.startswith(paper_name) or paper_name.startswith(title_name))


def fulltext_manifest(db: Database, data_dir: Path) -> dict:
    entries = []
    # ponytail: per-item immutable queries are simple; batch only if large-library audits become slow.
    for item_key in db.all_literature_keys():
        parent_title = db.lookup(item_key)["title"]
        normalized_title = _normalized_name(parent_title)
        candidates = []
        tagged_keys = []
        item_entries = []
        attachments = db.attachments(item_key)
        pdfs = [
            attachment
            for attachment in attachments
            if str(attachment.get("contentType") or "").lower() == "application/pdf"
            or str(attachment.get("attachmentPath") or "").lower().endswith(".pdf")
        ]
        marked_sources = [attachment for attachment in pdfs if SOURCE_TAG in attachment.get("tags", [])]
        ambiguous_pdf_keys = {
            attachment["key"] for attachment in pdfs
        } if len(pdfs) > 1 and len(marked_sources) != 1 else set()
        for attachment in attachments:
            path = resolve_attachment_path(attachment, data_dir)
            filename = path.name if path else Path(str(attachment.get("attachmentPath") or "")).name
            content_type = str(attachment.get("contentType") or "").lower()
            looks_markdown = filename.lower().endswith(".md") or content_type in {"text/markdown", "text/x-markdown"}
            tags = attachment.get("tags", [])
            marked_fulltext = FULLTEXT_TAG in tags
            ambiguous_pdf = attachment["key"] in ambiguous_pdf_keys
            if not (looks_markdown or marked_fulltext or ambiguous_pdf):
                continue
            exists = bool(path and path.is_file())
            if marked_fulltext:
                tagged_keys.append(attachment["key"])
            lower = filename.lower()
            stored = attachment.get("linkMode") == 0
            canonical = (
                exists
                and stored
                and marked_fulltext
                and filename == "fulltext.md"
                and attachment.get("title") == "Markdown Full Text"
                and content_type != "application/pdf"
            )
            if not exists:
                candidate_class, reason = "unresolved", "attachment file is missing"
            elif canonical:
                candidate_class, reason = "canonical", "stored and tagged canonical fulltext.md"
            elif marked_fulltext:
                candidate_class, reason = "unresolved", "tagged Full Text is not canonical"
            elif ambiguous_pdf:
                candidate_class, reason = "unresolved", "multiple PDFs have no unique marked Source Document"
            elif not stored:
                candidate_class, reason = "unresolved", "linked Markdown must be imported as a stored attachment"
            elif lower in {"distill.md", "probe_distill.md"}:
                candidate_class, reason = "excluded", "derived distillation is not full text"
            elif lower == "source.md":
                candidate_class, reason = "candidate", "source.md candidate"
                candidates.append(attachment["key"])
            elif normalized_title and _title_like(filename, parent_title):
                candidate_class, reason = "candidate", "title-like Markdown candidate"
                candidates.append(attachment["key"])
            else:
                candidate_class, reason = "unresolved", "not a deterministic source.md or title-like candidate"
            digest = None
            if exists:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            entry = {
                "parentItemKey": item_key,
                "parentTitle": parent_title,
                "attachmentKey": attachment["key"],
                "path": str(path) if path else None,
                "linkMode": attachment.get("linkMode"),
                "exists": exists,
                "filename": filename,
                "contentType": attachment.get("contentType"),
                "attachmentTitle": attachment.get("title"),
                "sha256": digest,
                "markedFullText": marked_fulltext,
                "candidateClass": candidate_class,
                "reason": reason,
            }
            item_entries.append(entry)
        canonical_entries = [entry for entry in item_entries if entry["candidateClass"] == "canonical"]
        if tagged_keys and (len(tagged_keys) != 1 or len(canonical_entries) != 1):
            affected = set(tagged_keys + candidates)
            for entry in item_entries:
                if entry["attachmentKey"] in affected:
                    entry["candidateClass"] = "unresolved"
                    entry["reason"] = "invalid or conflicting marked Full Text requires review"
        elif canonical_entries:
            for entry in item_entries:
                if entry["attachmentKey"] in candidates:
                    entry["candidateClass"] = "excluded"
                    entry["reason"] = "canonical Full Text already exists"
        elif len(candidates) > 1:
            for entry in item_entries:
                if entry["attachmentKey"] in candidates:
                    entry["candidateClass"] = "unresolved"
                    entry["reason"] = "multiple plausible Markdown candidates"
        entries.extend(item_entries)
    return {
        "protocol": 1,
        "readOnly": True,
        "entries": entries,
        "summary": {
            "attachments": len(entries),
            "canonical": sum(e["candidateClass"] == "canonical" for e in entries),
            "candidates": sum(e["candidateClass"] == "candidate" for e in entries),
            "unresolved": sum(e["candidateClass"] == "unresolved" for e in entries),
            "excluded": sum(e["candidateClass"] == "excluded" for e in entries),
        },
    }


def write_manifest(path: Path, manifest: dict) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
