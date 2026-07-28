from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from zotero_cli.errors import CliError
from zotero_cli.sources import (
    adoption_snapshot,
    fulltext_manifest,
    lexical_find,
    load_migration_candidates,
    preferred_source,
    segment_markdown,
)


def attachment(
    key: str,
    path: str,
    *,
    tags=(),
    content_type="application/pdf",
    type_name="attachment",
    link_mode=0,
    title=None,
) -> dict:
    return {
        "key": key,
        "attachmentPath": path,
        "contentType": content_type,
        "tags": list(tags),
        "typeName": type_name,
        "linkMode": link_mode,
        "title": title if title is not None else ("Markdown Full Text" if "zotero-cli:fulltext" in tags else ""),
    }


class FakeDatabase:
    def __init__(self, attachments):
        self._attachments = attachments

    def all_literature_keys(self):
        return list(self._attachments)

    def lookup(self, key):
        return {"title": "Great Paper"}

    def attachments(self, key):
        return self._attachments[key]


class PreferredSourceTests(unittest.TestCase):
    def test_markdown_remains_preferred_after_pdfs_change(self):
        selected = preferred_source(
            [
                attachment("OLDPDF", "storage:old.pdf"),
                attachment("NEWPDF", "storage:new.pdf"),
                attachment("MARKDOWN", "storage:fulltext.md", tags=("zotero-cli:fulltext",), content_type="text/markdown"),
            ],
            Path("/tmp/zotero"),
        )
        self.assertEqual(selected["kind"], "markdown")
        self.assertEqual(selected["attachmentKey"], "MARKDOWN")

    def test_tagged_fulltext_must_use_canonical_filename(self):
        with self.assertRaises(CliError) as caught:
            preferred_source(
                [attachment("MARKDOWN", "storage:source.md", tags=("zotero-cli:fulltext",), content_type="text/markdown")],
                Path("/tmp/zotero"),
            )
        self.assertEqual(caught.exception.code, "INVALID_FULLTEXT")

    def test_note_and_annotation_are_never_candidates(self):
        selected = preferred_source(
            [
                attachment("NOTE", "storage:note.md", tags=("zotero-cli:fulltext",), content_type="text/markdown", type_name="note"),
                attachment("ANNOT", "storage:annotation.md", tags=("zotero-cli:fulltext",), content_type="text/markdown", type_name="annotation"),
                attachment("PDF", "storage:paper.pdf"),
            ],
            Path("/tmp/zotero"),
        )
        self.assertEqual(selected["attachmentKey"], "PDF")

    def test_ambiguous_pdfs_fail(self):
        with self.assertRaises(CliError) as caught:
            preferred_source(
                [attachment("PDFONE", "storage:one.pdf"), attachment("PDFTWO", "storage:two.pdf")],
                Path("/tmp/zotero"),
            )
        self.assertEqual(caught.exception.code, "AMBIGUOUS_SOURCE")

    def test_fulltext_audit_classifies_only_deterministic_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("source.md", "distill.md", "Great Paper.md", "summary.md"):
                (root / name).write_text(name, encoding="utf-8")
            records = []
            for index, name in enumerate(("source.md", "distill.md", "Great Paper.md", "summary.md")):
                records.append(attachment(f"KEY{index}", str(root / name), content_type="text/markdown"))
            manifest = fulltext_manifest(FakeDatabase({"ITEMKEY1": records}), root)
        classes = {entry["filename"]: entry["candidateClass"] for entry in manifest["entries"]}
        self.assertEqual(classes["distill.md"], "excluded")
        self.assertEqual(classes["summary.md"], "unresolved")
        self.assertEqual(classes["source.md"], "candidate")
        self.assertEqual(classes["Great Paper.md"], "unresolved")
        self.assertEqual(manifest["entries"][0]["parentTitle"], "Great Paper")

    def test_audit_canonical_suppresses_old_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical_dir = root / "canonical"
            canonical_dir.mkdir()
            canonical = canonical_dir / "fulltext.md"
            old = root / "source.md"
            canonical.write_text("new", encoding="utf-8")
            old.write_text("old", encoding="utf-8")
            records = [
                attachment("CANONICAL", str(canonical), tags=("zotero-cli:fulltext",), content_type="text/plain"),
                attachment("OLD", str(old), content_type="text/plain"),
            ]
            manifest = fulltext_manifest(FakeDatabase({"ITEMKEY1": records}), root)
        classes = {entry["attachmentKey"]: entry["candidateClass"] for entry in manifest["entries"]}
        self.assertEqual(classes, {"CANONICAL": "canonical", "OLD": "excluded"})

    def test_audit_multiple_marked_fulltexts_are_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = []
            for key in ("FIRST", "SECOND"):
                directory = root / key
                directory.mkdir()
                path = directory / "fulltext.md"
                path.write_text(key, encoding="utf-8")
                records.append(attachment(key, str(path), tags=("zotero-cli:fulltext",), content_type="text/plain"))
            manifest = fulltext_manifest(FakeDatabase({"ITEMKEY1": records}), root)
        self.assertEqual({entry["candidateClass"] for entry in manifest["entries"]}, {"unresolved"})

    def test_audit_existing_linked_markdown_requires_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.md"
            path.write_text("paper", encoding="utf-8")
            manifest = fulltext_manifest(
                FakeDatabase({"ITEMKEY1": [attachment("LINKED", str(path), content_type="text/plain", link_mode=2)]}),
                Path(tmp),
            )
        self.assertEqual(manifest["entries"][0]["candidateClass"], "unresolved")

    def test_audit_includes_malformed_marked_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.pdf"
            path.write_bytes(b"pdf")
            manifest = fulltext_manifest(
                FakeDatabase({"ITEMKEY1": [attachment("BADMARK", str(path), tags=("zotero-cli:fulltext",))]}),
                Path(tmp),
            )
        self.assertEqual(manifest["entries"][0]["attachmentKey"], "BADMARK")
        self.assertEqual(manifest["entries"][0]["candidateClass"], "unresolved")

    def test_audit_reports_ambiguous_source_pdfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = []
            for key in ("PDFONE", "PDFTWO"):
                path = root / f"{key}.pdf"
                path.write_bytes(key.encode())
                records.append(attachment(key, str(path)))
            manifest = fulltext_manifest(FakeDatabase({"ITEMKEY1": records}), root)
        self.assertEqual({entry["attachmentKey"] for entry in manifest["entries"]}, {"PDFONE", "PDFTWO"})
        self.assertEqual({entry["candidateClass"] for entry in manifest["entries"]}, {"unresolved"})

    def test_audit_accepts_truncated_author_year_title_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            filename = "Smith et al. - 2025 - A Very Long Paper Title About Reliable Data Driven Control Meth.md"
            (root / filename).write_text("paper", encoding="utf-8")
            db = FakeDatabase({"ITEMKEY1": [attachment("MARKDOWN", str(root / filename), content_type="text/plain")]})
            db.lookup = lambda key: {"title": "A Very Long Paper Title About Reliable Data Driven Control Methods and Applications"}
            manifest = fulltext_manifest(db, root)
        self.assertEqual(manifest["entries"][0]["candidateClass"], "candidate")

    def test_lexical_find_returns_requested_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fulltext.md"
            path.write_text("alpha\nbeta target\ngamma\ndelta\n", encoding="utf-8")
            result = lexical_find(
                {"kind": "markdown", "path": str(path), "exists": True, "attachmentKey": "MARKDOWN"},
                "target",
                limit=5,
                context=1,
            )
        self.assertEqual(result["matches"][0]["location"], "lines 1-3")
        self.assertEqual(result["matches"][0]["text"], "alpha\nbeta target\ngamma")

    def test_empty_markdown_has_defined_location(self):
        result = segment_markdown("", start=1, limit=20, all_text=False)
        self.assertEqual((result["start"], result["end"], result["total"]), (0, 0, 0))
        with self.assertRaises(CliError):
            segment_markdown("", start=2, limit=20, all_text=False)

    @mock.patch("zotero_cli.sources.extract_pdf")
    def test_pdf_find_reports_global_line_for_read(self, extract_pdf):
        extract_pdf.return_value = {"content": "one\ntwo\fthree target\nfour\n"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.pdf"
            path.write_bytes(b"pdf")
            result = lexical_find(
                {"kind": "pdf", "path": str(path), "exists": True, "attachmentKey": "PDF"},
                "target",
                limit=5,
                context=0,
            )
        self.assertEqual(result["matches"][0]["line"], 3)
        self.assertEqual(result["matches"][0]["location"], "lines 3-3 (PDF page 2)")

    def test_adoption_snapshot_requires_explicit_marked_replacements(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.md"
            old = root / "fulltext.md"
            source.write_text("paper", encoding="utf-8")
            old.write_text("old", encoding="utf-8")
            db = FakeDatabase({
                "ABCD2345": [
                    attachment("EFGH6789", str(source), content_type="text/plain"),
                    attachment("JKLM2345", str(old), tags=("zotero-cli:fulltext",), content_type="text/plain"),
                ]
            })
            with self.assertRaises(CliError) as caught:
                adoption_snapshot(db, "ABCD2345", "EFGH6789", root)
            self.assertEqual(caught.exception.code, "FULLTEXT_CONFLICT")
            snapshot = adoption_snapshot(db, "ABCD2345", "EFGH6789", root, ["JKLM2345"])
        self.assertEqual(snapshot["replaceAttachmentKeys"], ["JKLM2345"])
        self.assertEqual(len(snapshot["expectedSha256"]), 64)

    def test_migration_plan_revalidates_selected_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.md"
            source.write_text("paper", encoding="utf-8")
            db = FakeDatabase({
                "ABCD2345": [attachment("EFGH6789", str(source), content_type="text/plain")]
            })
            snapshot = adoption_snapshot(db, "ABCD2345", "EFGH6789", root)
            plan = root / "plan.json"
            plan.write_text(json.dumps({
                "protocol": 1,
                "entries": [{
                    "parentItemKey": "ABCD2345",
                    "attachmentKey": "EFGH6789",
                    "path": snapshot["expectedPath"],
                    "sha256": snapshot["expectedSha256"],
                    "candidateClass": "candidate",
                }],
            }), encoding="utf-8")
            resolved, candidates = load_migration_candidates(plan, db, root)
            self.assertEqual(resolved, plan.resolve())
            self.assertEqual(candidates, [snapshot])
            source.write_text("changed", encoding="utf-8")
            with self.assertRaises(CliError) as caught:
                load_migration_candidates(plan, db, root)
        self.assertEqual(caught.exception.code, "STALE_MIGRATION_PLAN")

    def test_tagged_source_disambiguates_pdfs(self):
        selected = preferred_source(
            [
                attachment("PDFONE", "storage:one.pdf"),
                attachment("PDFTWO", "storage:two.pdf", tags=("zotero-cli:source",)),
            ],
            Path("/tmp/zotero"),
        )
        self.assertEqual(selected["attachmentKey"], "PDFTWO")


if __name__ == "__main__":
    unittest.main()
