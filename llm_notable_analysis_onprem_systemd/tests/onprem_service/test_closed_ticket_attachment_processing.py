import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# pylint: disable=import-error,no-name-in-module

from llm_notable_analysis_onprem_systemd.onprem_service.closed_ticket_attachment_processing import (
    ClosedTicketAttachmentInput,
    build_attachment_semantic_metadata,
    decode_text_attachment,
    describe_image_with_vision_model,
    extract_attachment_semantic_text,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from onprem_rag_notable_analysis.future.image_extraction import (
    STATUS_EXTRACTED,
    STATUS_OCR_EMPTY,
    STATUS_PREREQUISITE_MISSING,
    ImageExtractionResult,
)
from onprem_rag_notable_analysis.future.image_extraction_config import (
    ImageExtractionConfig,
)

_MODULE = "llm_notable_analysis_onprem_systemd.onprem_service.closed_ticket_attachment_processing"


class _FakeHttpClient:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = []

    def __call__(self, url, payload, headers, timeout):
        self.calls.append((url, payload, headers, timeout))
        return json.dumps(self.payload).encode("utf-8")


def _ocr_result(**kwargs) -> ImageExtractionResult:
    defaults = {
        "status": STATUS_EXTRACTED,
        "text": None,
        "source_mime": "image/png",
    }
    defaults.update(kwargs)
    return ImageExtractionResult(**defaults)


class TestClosedTicketAttachmentProcessing(unittest.TestCase):
    def test_decode_text_attachment_bounds_output(self) -> None:
        config = Config()
        text, status = decode_text_attachment(
            b"hello world",
            content_type="text/plain",
            config=config,
        )
        self.assertEqual(status, "text_decoded")
        self.assertEqual(text, "hello world")

    @mock.patch(f"{_MODULE}.extract_image_content")
    def test_pdf_ocr_extracted_when_shared_extractor_succeeds(self, mock_extract) -> None:
        mock_extract.return_value = _ocr_result(
            status=STATUS_EXTRACTED,
            text="Scanned invoice total $500.",
            source_mime="application/pdf",
            decoded_format="PDF",
            page_count=1,
        )
        result = extract_attachment_semantic_text(
            ClosedTicketAttachmentInput(
                attachment_id="a1",
                ticket_id="t1",
                filename="report.pdf",
                content_type="application/pdf",
                metadata={},
                raw_content=b"%PDF-1.4",
            ),
            Config(),
        )
        self.assertEqual(result.extraction_status, "pdf_ocr_extracted")
        self.assertEqual(result.semantic_text, "Scanned invoice total $500.")
        mock_extract.assert_called_once()
        config_arg = mock_extract.call_args.kwargs["config"]
        self.assertIsInstance(config_arg, ImageExtractionConfig)

    @mock.patch(f"{_MODULE}.extract_image_content")
    def test_pdf_prerequisite_missing_is_explicit(self, mock_extract) -> None:
        mock_extract.return_value = _ocr_result(
            status=STATUS_PREREQUISITE_MISSING,
            text=None,
            source_mime="application/pdf",
            error_message="pypdfium2",
        )
        result = extract_attachment_semantic_text(
            ClosedTicketAttachmentInput(
                attachment_id="a1",
                ticket_id="t1",
                filename="report.pdf",
                content_type="application/pdf",
                metadata={},
                raw_content=b"%PDF-1.4",
            ),
            Config(),
        )
        self.assertEqual(result.extraction_status, "pdf_prerequisite_missing")
        self.assertIn("pdf_prerequisite_missing", result.semantic_text or "")

    @mock.patch(f"{_MODULE}.extract_image_content")
    def test_docx_embedded_image_ocr_extracted(self, mock_extract) -> None:
        docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        mock_extract.return_value = _ocr_result(
            status=STATUS_EXTRACTED,
            text="Embedded chart label",
            source_mime=docx_mime,
            decoded_format="DOCX",
            embedded_image_count=1,
        )
        result = extract_attachment_semantic_text(
            ClosedTicketAttachmentInput(
                attachment_id="a1",
                ticket_id="t1",
                filename="brief.docx",
                content_type=docx_mime,
                metadata={},
                raw_content=b"PK\x03\x04",
            ),
            Config(),
        )
        self.assertEqual(result.extraction_status, "docx_ocr_extracted")
        self.assertEqual(result.semantic_text, "Embedded chart label")

    @mock.patch(f"{_MODULE}.extract_image_content")
    def test_shared_image_ocr_used_for_raster(self, mock_extract) -> None:
        mock_extract.return_value = _ocr_result(
            status=STATUS_EXTRACTED,
            text="LOGIN PAGE",
            source_mime="image/png",
            decoded_format="PNG",
        )
        result = extract_attachment_semantic_text(
            ClosedTicketAttachmentInput(
                attachment_id="a1",
                ticket_id="t1",
                filename="screen.png",
                content_type="image/png",
                metadata={},
                raw_content=b"\x89PNG",
            ),
            Config(),
        )
        self.assertEqual(result.extraction_status, "image_ocr_extracted")
        self.assertIn("LOGIN PAGE", result.semantic_text or "")

    @mock.patch(f"{_MODULE}.describe_image_with_vision_model")
    @mock.patch(f"{_MODULE}.extract_image_content")
    def test_image_combines_vision_and_ocr_when_both_available(
        self,
        mock_extract,
        mock_vision,
    ) -> None:
        mock_extract.return_value = _ocr_result(
            status=STATUS_EXTRACTED,
            text=(
                "[Vision description (advisory)]\n"
                "Screenshot shows a login form.\n\n"
                "[OCR text]\n"
                "LOGIN PAGE"
            ),
            source_mime="image/png",
            decoded_format="PNG",
            vision_status="vision_described",
            vision_raster_attempts=1,
            vision_raster_described=1,
        )
        result = extract_attachment_semantic_text(
            ClosedTicketAttachmentInput(
                attachment_id="a1",
                ticket_id="t1",
                filename="screen.png",
                content_type="image/png",
                metadata={},
                raw_content=b"\x89PNG",
            ),
            Config(),
        )
        self.assertEqual(result.extraction_status, "vision_described")
        self.assertIn("Screenshot shows a login form.", result.semantic_text or "")
        self.assertIn("[OCR text]", result.semantic_text or "")
        self.assertIn("LOGIN PAGE", result.semantic_text or "")
        mock_vision.assert_not_called()

    def test_vision_model_returns_description_when_enabled(self) -> None:
        config = Config()
        object.__setattr__(config, "CLOSED_TICKET_VISION_ENABLED", True)
        object.__setattr__(
            config,
            "CLOSED_TICKET_VISION_API_BASE",
            "http://127.0.0.1:4000/v1",
        )
        object.__setattr__(config, "CLOSED_TICKET_VISION_MODEL", "vision-model")
        client = _FakeHttpClient(
            {"choices": [{"message": {"content": "Screenshot shows a login form."}}]}
        )
        description, status = describe_image_with_vision_model(
            image_bytes=b"fake-image-bytes",
            content_type="image/png",
            config=config,
            http_client=client,
        )
        self.assertEqual(status, "vision_described")
        self.assertEqual(description, "Screenshot shows a login form.")
        self.assertEqual(len(client.calls), 1)

    def test_vision_wrapper_rejects_non_loopback_endpoint(self) -> None:
        config = Config()
        object.__setattr__(config, "CLOSED_TICKET_VISION_ENABLED", True)
        object.__setattr__(
            config,
            "CLOSED_TICKET_VISION_API_BASE",
            "https://vision.example/v1",
        )
        object.__setattr__(config, "CLOSED_TICKET_VISION_MODEL", "vision-model")
        description, status = describe_image_with_vision_model(
            image_bytes=b"fake-image-bytes",
            content_type="image/png",
            config=config,
            http_client=_FakeHttpClient({"choices": []}),
        )
        self.assertIsNone(description)
        self.assertEqual(status, "vision_endpoint_not_loopback")

    @mock.patch(f"{_MODULE}.extract_image_content")
    def test_image_prerequisite_missing_is_explicit(self, mock_extract) -> None:
        mock_extract.return_value = _ocr_result(
            status=STATUS_PREREQUISITE_MISSING,
            text=None,
            source_mime="image/png",
            error_message="pillow",
        )
        result = extract_attachment_semantic_text(
            ClosedTicketAttachmentInput(
                attachment_id="a1",
                ticket_id="t1",
                filename="screen.png",
                content_type="image/png",
                metadata={},
                raw_content=b"\x89PNG",
            ),
            Config(),
        )
        self.assertEqual(result.extraction_status, "image_prerequisite_missing")
        self.assertIn("image_prerequisite_missing", result.semantic_text or "")

    @mock.patch(f"{_MODULE}.describe_image_with_vision_model")
    @mock.patch(f"{_MODULE}.extract_image_content")
    def test_image_ocr_empty_without_vision_stays_explicit(
        self,
        mock_extract,
        mock_vision,
    ) -> None:
        mock_extract.return_value = _ocr_result(
            status=STATUS_OCR_EMPTY,
            text=None,
            source_mime="image/png",
            decoded_format="PNG",
            vision_status="vision_disabled",
        )
        result = extract_attachment_semantic_text(
            ClosedTicketAttachmentInput(
                attachment_id="a1",
                ticket_id="t1",
                filename="blank.png",
                content_type="image/png",
                metadata={},
                raw_content=b"\x89PNG",
            ),
            Config(),
        )
        self.assertEqual(result.extraction_status, "image_ocr_empty")
        self.assertIn("image_ocr_empty", result.semantic_text or "")
        mock_vision.assert_not_called()

    @mock.patch(f"{_MODULE}.describe_image_with_vision_model")
    @mock.patch(f"{_MODULE}.extract_image_content")
    def test_standalone_raster_does_not_duplicate_vision_call(
        self,
        mock_extract,
        mock_vision,
    ) -> None:
        mock_extract.return_value = _ocr_result(
            status=STATUS_EXTRACTED,
            text="[OCR text]\nLOGIN PAGE",
            source_mime="image/png",
            vision_status="vision_described",
        )
        config = Config()
        object.__setattr__(config, "CLOSED_TICKET_VISION_ENABLED", True)
        object.__setattr__(
            config,
            "CLOSED_TICKET_VISION_API_BASE",
            "http://127.0.0.1:4000/v1",
        )
        object.__setattr__(config, "CLOSED_TICKET_VISION_MODEL", "vision-model")
        extract_attachment_semantic_text(
            ClosedTicketAttachmentInput(
                attachment_id="a1",
                ticket_id="t1",
                filename="screen.png",
                content_type="image/png",
                metadata={},
                raw_content=b"\x89PNG",
            ),
            config,
        )
        mock_extract.assert_called_once()
        mock_vision.assert_not_called()
        call_kwargs = mock_extract.call_args.kwargs
        self.assertIsNotNone(call_kwargs.get("vision_describer"))

    @mock.patch(f"{_MODULE}.extract_image_content")
    def test_image_extraction_config_uses_shared_image_ingest_bounds(self, mock_extract) -> None:
        mock_extract.return_value = _ocr_result(
            status=STATUS_EXTRACTED,
            text="ok",
            source_mime="image/png",
        )
        config = Config()
        object.__setattr__(config, "IMAGE_INGEST_MAX_PIXELS", 1234)
        object.__setattr__(config, "IMAGE_INGEST_TESSERACT_LANG", "fra")
        extract_attachment_semantic_text(
            ClosedTicketAttachmentInput(
                attachment_id="a1",
                ticket_id="t1",
                filename="screen.png",
                content_type="image/png",
                metadata={},
                raw_content=b"\x89PNG",
            ),
            config,
        )
        extraction_config = mock_extract.call_args.kwargs["config"]
        self.assertEqual(extraction_config.max_pixels, 1234)
        self.assertEqual(extraction_config.tesseract_lang, "fra")

    def test_build_metadata_merges_semantic_fields(self) -> None:
        result = build_attachment_semantic_metadata(
            ClosedTicketAttachmentInput(
                attachment_id="a2",
                ticket_id="t1",
                filename="note.txt",
                content_type="text/plain",
                metadata={"synced_at": "2026-01-01"},
                raw_content="Known admin script activity.",
            ),
            Config(),
        )
        self.assertEqual(result.metadata["semantic_description"], "Known admin script activity.")
        self.assertEqual(result.metadata["semantic_extraction_status"], "text_decoded")
        self.assertEqual(result.metadata["synced_at"], "2026-01-01")

    def test_storage_path_is_used_when_raw_content_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "note.txt"
            path.write_text("From disk path.", encoding="utf-8")
            result = extract_attachment_semantic_text(
                ClosedTicketAttachmentInput(
                    attachment_id="a4",
                    ticket_id="t1",
                    filename="note.txt",
                    content_type="text/plain",
                    metadata={},
                    storage_path=str(path),
                ),
                Config(),
            )
            self.assertEqual(result.semantic_text, "From disk path.")
            self.assertEqual(result.extraction_status, "text_decoded")

    def test_existing_metadata_semantic_is_not_hallucinated(self) -> None:
        result = extract_attachment_semantic_text(
            ClosedTicketAttachmentInput(
                attachment_id="a3",
                ticket_id="t1",
                filename="stored.txt",
                content_type="text/plain",
                metadata={
                    "semantic_description": "Stored semantic text",
                    "semantic_extraction_status": "stored",
                },
                raw_content="different raw",
            ),
            Config(),
        )
        self.assertEqual(result.semantic_text, "Stored semantic text")
        self.assertEqual(result.extraction_status, "stored")

    @mock.patch(f"{_MODULE}.extract_image_content")
    def test_build_metadata_persists_pdf_ocr_status(self, mock_extract) -> None:
        mock_extract.return_value = _ocr_result(
            status=STATUS_EXTRACTED,
            text="Invoice 123",
            source_mime="application/pdf",
            decoded_format="PDF",
        )
        result = build_attachment_semantic_metadata(
            ClosedTicketAttachmentInput(
                attachment_id="a5",
                ticket_id="t1",
                filename="invoice.pdf",
                content_type="application/pdf",
                metadata={"synced_at": "2026-01-02"},
                raw_content=b"%PDF",
            ),
            Config(),
        )
        self.assertEqual(result.metadata["semantic_description"], "Invoice 123")
        self.assertEqual(result.metadata["semantic_extraction_status"], "pdf_ocr_extracted")
