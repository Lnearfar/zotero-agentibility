from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest import mock

from za_cli.errors import CliError
from za_cli.poppler import extract_pdf, parse_pdfinfo


class PopplerTests(unittest.TestCase):
    def test_pdfinfo_parser(self):
        self.assertEqual(parse_pdfinfo("Title: Paper\nPages: 12\n")["pages"], 12)

    @mock.patch("za_cli.poppler.subprocess.run")
    def test_extract_uses_global_text_lines_and_reports_pages(self, run):
        run.side_effect = [
            subprocess.CompletedProcess(["pdfinfo"], 0, b"Pages: 2\n", b""),
            subprocess.CompletedProcess(["pdftotext"], 0, b"page one line one\npage one line two\n\fpage two line one\n", b""),
        ]
        result = extract_pdf(Path("/tmp/paper.pdf"), start=2, limit=2)
        self.assertEqual(result["content"], "page one line two\n\fpage two line one\n")
        self.assertEqual(result["startPage"], 1)
        self.assertEqual(result["endPage"], 2)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["location"], "lines 2-3 (PDF pages 1-2)")
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["pdftotext", "-layout", "/tmp/paper.pdf", "-"],
        )

    @mock.patch("za_cli.poppler.subprocess.run")
    def test_image_only_pdf_requires_ocr(self, run):
        run.side_effect = [
            subprocess.CompletedProcess(["pdfinfo"], 0, b"Pages: 1\n", b""),
            subprocess.CompletedProcess(["pdftotext"], 0, b"\f", b""),
        ]
        with self.assertRaises(CliError) as caught:
            extract_pdf(Path("/tmp/scan.pdf"))
        self.assertEqual(caught.exception.code, "OCR_REQUIRED")


if __name__ == "__main__":
    unittest.main()
