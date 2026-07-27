import json
import tempfile
import unittest
from pathlib import Path

# pylint: disable=import-error,no-name-in-module

from llm_notable_analysis_onprem_systemd.onprem_service.closed_ticket_attachment_processing import (
    ClosedTicketAttachmentInput,
    build_attachment_semantic_metadata,
    decode_text_attachment,
    describe_image_with_vision_model,
    extract_attachment_semantic_text,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config


class _FakeHttpClient:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = []

    def __call__(self, url, payload, headers, timeout):
        self.calls.append((url, payload, headers, timeout))
        return json.dumps(self.payload).encode("utf-8")


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

    def test_pdf_remains_metadata_only(self) -> None:
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
        self.assertEqual(result.extraction_status, "pdf_unsupported_metadata_only")
        self.assertIn("pdf_ocr_unsupported", result.semantic_text or "")

    def test_vision_model_returns_description_when_enabled(self) -> None:
        config = Config()
        object.__setattr__(config, "CLOSED_TICKET_VISION_ENABLED", True)
        object.__setattr__(
            config,
            "CLOSED_TICKET_VISION_API_BASE",
            "https://vision.example/v1",
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
