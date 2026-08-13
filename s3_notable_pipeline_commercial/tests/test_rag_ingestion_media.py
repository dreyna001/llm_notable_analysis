"""Tests for rich KB media extraction in RAG manifest ingest."""

from __future__ import annotations

import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.kb_document_extract import (
    STATUS_EXTRACTED,
    STATUS_NO_TEXT,
    STATUS_OUTPUT_TRUNCATED,
    STATUS_PAGE_LIMIT_EXCEEDED,
    STATUS_TEXTRACT_FAILED,
    extract_kb_document,
)
from s3_notable_pipeline.rag_ingestion import ingest_manifest, parse_s3_document


MINIMAL_PDF_BYTES = b"""%PDF-1.1
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj
4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
5 0 obj<</Length 44>>stream
BT /F1 12 Tf 100 700 Td (Hello PDF) Tj ET
endstream
endobj
xref
0 6
0000000000 65535 f
trailer<</Size 6/Root 1 0 R>>
startxref
0
%%EOF
"""

EMPTY_PDF_BYTES = b"""%PDF-1.1
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj
xref
0 4
0000000000 65535 f
trailer<</Size 4/Root 1 0 R>>
startxref
0
%%EOF
"""


def _minimal_docx_bytes(*, paragraph_text: str = "Hello DOCX") -> bytes:
    body = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        "<w:p><w:r><w:t>"
        f"{paragraph_text}"
        "</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", body)
    return buffer.getvalue()


class FakeBedrockClient:
    def invoke_model(self, **_kwargs):
        return {"body": io.BytesIO(json.dumps({"embedding": [0.01] * 1024}).encode())}


class FakeMediaS3:
    def __init__(self, manifest, payloads: dict[str, bytes]):
        self.manifest = manifest
        self.payloads = payloads
        self.calls: list[dict[str, str]] = []

    def get_object(self, **kwargs):
        self.calls.append(kwargs)
        key = kwargs["Key"]
        if key.endswith("manifest.json"):
            body = json.dumps(self.manifest).encode("utf-8")
        else:
            body = self.payloads[key]
        return {
            "Body": io.BytesIO(body),
            "VersionId": kwargs.get("VersionId", "v1"),
            "ETag": '"etag-1"',
            "ContentLength": len(body),
        }


class FakeIngestionAdapter:
    def __init__(self):
        self.bulks: list[dict[str, object]] = []
        self.searches: list[dict[str, object]] = []

    def ensure_vector_index(self, **_kwargs):
        return None

    def search(self, **_kwargs):
        self.searches.append(_kwargs)
        return {"hits": {"hits": []}}

    def bulk(self, **kwargs):
        self.bulks.append(kwargs)
        return {"errors": False}


def extraction_config(**overrides):
    values = {
        "RAG_SOURCE_BUCKET": "docs",
        "RAG_SOURCE_PREFIX": "rag-sources",
        "RAG_TENANT_ID": "tenant-a",
        "RAG_INGEST_MAX_DOCUMENT_BYTES": 10_485_760,
        "KB_EXTRACT_MAX_BYTES": 10_485_760,
        "KB_EXTRACT_MAX_PDF_PAGES": 50,
        "KB_EXTRACT_MAX_OUTPUT_CHARS": 12000,
        "OPENSEARCH_SOC_INDEX": "soc-knowledge",
        "OPENSEARCH_BULK_BATCH_SIZE": 1,
        "CASE_QA_EMBEDDING_MODEL": "amazon.titan-embed-text-v2:0",
        "CASE_QA_VECTOR_DIMENSIONS": 1024,
        "CASE_QA_EMBED_NORMALIZE": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class KbDocumentExtractTests(unittest.TestCase):
    def test_pdf_extraction_returns_text(self):
        config = extraction_config()
        result = extract_kb_document(MINIMAL_PDF_BYTES, suffix="pdf", config=config)
        self.assertEqual(result.extraction_status, STATUS_EXTRACTED)
        self.assertIn("Hello PDF", result.text)

    def test_pdf_without_text_raises_clear_error(self):
        config = extraction_config()
        with self.assertRaisesRegex(ValueError, "no extractable text"):
            extract_kb_document(EMPTY_PDF_BYTES, suffix="pdf", config=config)

    def test_pdf_page_limit_marks_status_but_keeps_text(self):
        config = extraction_config(KB_EXTRACT_MAX_PDF_PAGES=1)
        with patch("pypdf.PdfReader") as reader_cls:
            page = SimpleNamespace(extract_text=lambda: "page text")
            reader = reader_cls.return_value
            reader.pages = [page, page]
            result = extract_kb_document(MINIMAL_PDF_BYTES, suffix="pdf", config=config)
        self.assertEqual(result.extraction_status, STATUS_PAGE_LIMIT_EXCEEDED)
        self.assertIn("page text", result.text)

    def test_docx_extraction_returns_paragraph_text(self):
        config = extraction_config()
        result = extract_kb_document(
            _minimal_docx_bytes(paragraph_text="Policy escalation steps"),
            suffix="docx",
            config=config,
        )
        self.assertEqual(result.extraction_status, STATUS_EXTRACTED)
        self.assertIn("Policy escalation steps", result.text)

    def test_output_truncation_sets_status(self):
        config = extraction_config(KB_EXTRACT_MAX_OUTPUT_CHARS=8)
        result = extract_kb_document(MINIMAL_PDF_BYTES, suffix="pdf", config=config)
        self.assertEqual(result.extraction_status, STATUS_OUTPUT_TRUNCATED)
        self.assertLessEqual(len(result.text), 8)

    def test_image_textract_success(self):
        textract = SimpleNamespace(
            detect_document_text=lambda **_kwargs: {
                "Blocks": [
                    {"BlockType": "LINE", "Text": "Suspicious login"},
                    {"BlockType": "WORD", "Text": "ignored"},
                ]
            }
        )
        result = extract_kb_document(
            b"\x89PNG\r\n\x1a\n",
            suffix="png",
            config=extraction_config(),
            textract_client=textract,
        )
        self.assertEqual(result.extraction_status, STATUS_EXTRACTED)
        self.assertEqual(result.text, "Suspicious login")

    def test_image_textract_failure_is_fail_soft(self):
        def _raise(**_kwargs):
            raise RuntimeError("Textract unavailable")

        textract = SimpleNamespace(detect_document_text=_raise)
        result = extract_kb_document(
            b"\x89PNG\r\n\x1a\n",
            suffix="png",
            config=extraction_config(),
            textract_client=textract,
        )
        self.assertEqual(result.extraction_status, STATUS_TEXTRACT_FAILED)
        self.assertEqual(result.text, "")

    def test_image_without_detected_text_is_fail_soft(self):
        textract = SimpleNamespace(detect_document_text=lambda **_kwargs: {"Blocks": []})
        result = extract_kb_document(
            b"\x89PNG\r\n\x1a\n",
            suffix="png",
            config=extraction_config(),
            textract_client=textract,
        )
        self.assertEqual(result.extraction_status, STATUS_NO_TEXT)
        self.assertEqual(result.text, "")


class RagIngestionMediaTests(unittest.TestCase):
    def test_parse_s3_document_pdf(self):
        s3 = FakeMediaS3({}, {"rag-sources/guide.pdf": MINIMAL_PDF_BYTES})
        parsed = parse_s3_document(
            bucket="docs",
            key="rag-sources/guide.pdf",
            s3_client=s3,
            version_id="v1",
            config=extraction_config(),
        )
        self.assertIn("Hello PDF", parsed.text)
        self.assertEqual(parsed.extraction_status, STATUS_EXTRACTED)

    def test_manifest_ingest_indexes_pdf_with_provenance(self):
        manifest = {
            "manifest_schema_version": 1,
            "manifest_id": "manifest-pdf",
            "manifest_version": "v1",
            "tenant_id": "tenant-a",
            "corpus_id": "soc",
            "documents": [
                {
                    "bucket": "docs",
                    "key": "rag-sources/guide.pdf",
                    "version_id": "v1",
                    "source_file": "guide.pdf",
                }
            ],
        }
        s3 = FakeMediaS3(manifest, {"rag-sources/guide.pdf": MINIMAL_PDF_BYTES})
        adapter = FakeIngestionAdapter()
        result = ingest_manifest(
            manifest_bucket="docs",
            manifest_key="rag-sources/manifest.json",
            manifest_version_id="manifest-v1",
            manifest_etag="",
            config=extraction_config(),
            s3_client=s3,
            bedrock_client=FakeBedrockClient(),
            adapter=adapter,
            textract_client=SimpleNamespace(),
        )
        self.assertEqual(result.indexed_count, 1)
        self.assertEqual(result.extraction_reports[0]["extraction_status"], STATUS_EXTRACTED)
        document = adapter.bulks[0]["actions"][0]["document"]
        self.assertEqual(document["source_file"], "guide.pdf")
        self.assertEqual(document["extraction_metadata"]["source_suffix"], "pdf")

    def test_manifest_ingest_skips_failed_image_with_report(self):
        manifest = {
            "manifest_schema_version": 1,
            "manifest_id": "manifest-image",
            "manifest_version": "v1",
            "tenant_id": "tenant-a",
            "corpus_id": "soc",
            "documents": [
                {
                    "bucket": "docs",
                    "key": "rag-sources/diagram.png",
                    "version_id": "v1",
                    "source_file": "diagram.png",
                }
            ],
        }
        s3 = FakeMediaS3(manifest, {"rag-sources/diagram.png": b"\x89PNG\r\n\x1a\n"})
        adapter = FakeIngestionAdapter()
        textract = SimpleNamespace(
            detect_document_text=lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("Textract unavailable")
            )
        )
        result = ingest_manifest(
            manifest_bucket="docs",
            manifest_key="rag-sources/manifest.json",
            manifest_version_id="manifest-v1",
            manifest_etag="",
            config=extraction_config(),
            s3_client=s3,
            bedrock_client=FakeBedrockClient(),
            adapter=adapter,
            textract_client=textract,
        )
        self.assertEqual(result.indexed_count, 0)
        self.assertEqual(result.extraction_reports[0]["extraction_status"], STATUS_TEXTRACT_FAILED)
        self.assertFalse(result.extraction_reports[0]["indexed"])
        self.assertEqual(adapter.bulks, [])


if __name__ == "__main__":
    unittest.main()
