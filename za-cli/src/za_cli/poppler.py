from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .errors import CliError


def parse_pdfinfo(text: str) -> dict:
    values = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip().lower()] = value.strip()
    match = re.match(r"\d+", values.get("pages", ""))
    if not match:
        raise CliError("PDFINFO_INVALID", "pdfinfo did not report a page count")
    return {"pages": int(match.group()), "title": values.get("title")}


def pdf_info(path: Path) -> dict:
    try:
        result = subprocess.run(["pdfinfo", str(path)], capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise CliError("POPPLER_MISSING", "pdfinfo is required") from exc
    if result.returncode:
        raise CliError("PDFINFO_FAILED", result.stderr.decode("utf-8", "replace").strip() or "pdfinfo failed")
    return parse_pdfinfo(result.stdout.decode("utf-8", "replace"))


def extract_pdf(path: Path, *, start: int = 1, limit: int = 200, all_text: bool = False) -> dict:
    info = pdf_info(path)
    if not all_text and (start < 1 or limit < 1):
        raise CliError("INVALID_RANGE", "--start and --limit must be positive")
    try:
        result = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise CliError("POPPLER_MISSING", "pdftotext is required") from exc
    if result.returncode:
        raise CliError("PDFTEXT_FAILED", result.stderr.decode("utf-8", "replace").strip() or "pdftotext failed")

    text = result.stdout.decode("utf-8", "replace")
    if not text.strip():
        raise CliError("OCR_REQUIRED", "PDF has no extractable text")

    numbered_lines: list[tuple[int, str]] = []
    for page, page_text in enumerate(text.split("\f"), 1):
        if page > info["pages"]:
            break
        numbered_lines.extend((page, line) for line in page_text.splitlines(keepends=True))
    total_lines = len(numbered_lines)
    if not all_text and start > total_lines:
        raise CliError("RANGE_OUT_OF_BOUNDS", f"PDF text has {total_lines} lines")

    first = 1 if all_text else start
    end = total_lines if all_text else min(total_lines, start + limit - 1)
    selected = numbered_lines if all_text else numbered_lines[start - 1 : end]
    start_page = selected[0][0]
    end_page = selected[-1][0]
    if all_text:
        content = text
    else:
        chunks: list[str] = []
        previous_page = start_page
        for page, line in selected:
            if page != previous_page:
                chunks.append("\f")
                previous_page = page
            chunks.append(line)
        content = "".join(chunks)

    return {
        "content": content,
        "start": first,
        "end": end,
        "total": total_lines,
        "nextStart": end + 1 if end < total_lines else None,
        "startPage": start_page,
        "endPage": end_page,
        "pages": info["pages"],
        "location": f"lines {first}-{end} (PDF pages {start_page}-{end_page})",
    }
