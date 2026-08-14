"""Tests for rich KB document extraction and ingest parsing."""

from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from azure_notable_pipeline.kb_document_extract import extract_document_text, image_ingest_enabled
from azure_notable_pipeline.rag_ingestion import ManifestDocument, parse_blob_document

MINIMAL_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6300010000050001000d0a2db40000000049454e44ae426082"
)

MINIMAL_PDF = (
    b"%PDF-1.1\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 200 200]/Parent 2 0 R/Resources"
    b"<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
    b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"5 0 obj<</Length 44>>stream\n"
    b"BT /F1 12 Tf 50 100 Td (KB ingest test) Tj ET\n"
    b"endstream endobj\n"
    b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n"
    b"0000000101 00000 n \n0000000202 00000 n \n0000000256 00000 n \n"
    b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n356\n%%EOF\n"
)


def media_config(**overrides):
    values = {
        "IMAGE_INGEST_ENABLED": True,
        "IMAGE_INGEST_ALLOWED_MIME_TYPES": (
            "application/pdf,"
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
            "image/gif,image/jpeg,image/jpg,image/png,image/webp"
        ),
        "IMAGE_INGEST_MAX_BYTES": 1_048_576,
        "IMAGE_INGEST_MAX_PIXELS": 25_000_000,
        "IMAGE_INGEST_MAX_WIDTH": 8192,
        "IMAGE_INGEST_MAX_HEIGHT": 8192,
        "IMAGE_INGEST_MAX_PDF_PAGES": 50,
        "IMAGE_INGEST_MAX_EMBEDDED_IMAGES": 20,
        "IMAGE_INGEST_MAX_OUTPUT_CHARS": 12000,
        "IMAGE_INGEST_USE_DOCUMENT_INTELLIGENCE": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def minimal_docx_bytes(text: str = "Hello KB ingest") -> bytes:
    document_xml = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
        "<w:body><w:p><w:r><w:t>"
        f"{text}"
        "</w:t></w:r></w:p></w:body></w:document>"
    )
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def pdf_library_available() -> bool:
    return (
        importlib.util.find_spec("pypdf") is not None
        or importlib.util.find_spec("PyPDF2") is not None
        or importlib.util.find_spec("pdfminer") is not None
    )


class KbDocumentExtractTests(unittest.TestCase):
    def test_image_ingest_enabled_flag(self):
        self.assertFalse(image_ingest_enabled(SimpleNamespace(IMAGE_INGEST_ENABLED=False)))
        self.assertTrue(image_ingest_enabled(SimpleNamespace(IMAGE_INGEST_ENABLED=True)))

    def test_extract_png_placeholder_without_document_intelligence(self):
        text = extract_document_text(MINIMAL_PNG, "png", media_config())
        self.assertIn("OCR disabled", text)
        self.assertIn("1x1", text)

    def test_extract_docx_via_zip_xml(self):
        text = extract_document_text(minimal_docx_bytes("Runbook excerpt"), "docx", media_config())
        self.assertIn("Runbook excerpt", text)

    def test_extract_truncates_output_chars(self):
        config = media_config(IMAGE_INGEST_MAX_OUTPUT_CHARS=20)
        text = extract_document_text(minimal_docx_bytes("abcdefghijklmnopqrstuvwxyz"), "docx", config)
        self.assertTrue(text.endswith("[truncated]"))
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", text)

    @unittest.skipUnless(pdf_library_available(), "pypdf, PyPDF2, or pdfminer is not installed")
    def test_extract_pdf_text_when_library_available(self):
        text = extract_document_text(MINIMAL_PDF, "pdf", media_config())
        self.assertIn("KB ingest test", text)

    def test_extract_rejects_oversized_payload(self):
        config = media_config(IMAGE_INGEST_MAX_BYTES=16)
        with self.assertRaisesRegex(ValueError, "IMAGE_INGEST_MAX_BYTES"):
            extract_document_text(MINIMAL_PNG, "png", config)


class ParseBlobDocumentMediaTests(unittest.TestCase):
    @patch("azure_notable_pipeline.rag_ingestion._read_blob")
    def test_parse_png_when_image_ingest_enabled(self, read_blob_mock):
        read_blob_mock.return_value = MINIMAL_PNG
        source = ManifestDocument(
            container="docs",
            blob_name="rag-sources/soc/diagram.png",
            version_id="v1",
        )
        text = parse_blob_document(
            source=source,
            config=media_config(),
            max_bytes=1_048_576,
        )
        self.assertIn("OCR disabled", text)

    @patch("azure_notable_pipeline.rag_ingestion._read_blob")
    def test_parse_png_rejected_when_image_ingest_disabled(self, read_blob_mock):
        read_blob_mock.return_value = MINIMAL_PNG
        source = ManifestDocument(
            container="docs",
            blob_name="rag-sources/soc/diagram.png",
            version_id="v1",
        )
        with self.assertRaisesRegex(ValueError, "unsupported RAG document type"):
            parse_blob_document(
                source=source,
                config=media_config(IMAGE_INGEST_ENABLED=False),
                max_bytes=1_048_576,
            )


if __name__ == "__main__":
    unittest.main()
