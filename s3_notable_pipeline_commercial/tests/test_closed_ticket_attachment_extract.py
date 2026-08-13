"""Tests for closed-ticket attachment Textract/OCR extraction."""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.closed_ticket_attachment_extract import (
    STATUS_BYTE_LIMIT_EXCEEDED,
    STATUS_EXTRACTED_TEXTRACT,
    STATUS_VISION_DISABLED,
    extract_closed_ticket_attachment,
    load_closed_ticket_attachments,
)
from s3_notable_pipeline.closed_ticket_embed import embed_closed_ticket
from s3_notable_pipeline.closed_ticket_render import (
    ClosedTicketAttachmentRecord,
    build_closed_ticket_chunks,
)
from s3_notable_pipeline.config import Config
from s3_notable_pipeline.servicenow_closed_ticket_sync import _to_ddb_item

TICKET_SYS_ID = "a1b2c3d4e5f6789012345678abcdef01"
ATTACHMENT_SYS_ID = "b2c3d4e5f6789012345678abcdef0123"
CONTENT_HASH = "abc123def456"


def _vision_config(**overrides: Any) -> Config:
    values = {
        "CLOSED_TICKET_VISION_ENABLED": True,
        "CLOSED_TICKET_ATTACHMENT_MAX_BYTES": 1024 * 1024,
        "KB_EXTRACT_MAX_OUTPUT_CHARS": 500,
        "KB_EXTRACT_MAX_PDF_PAGES": 5,
        "CLOSED_TICKET_REGISTRY_TABLE": "closed-ticket-registry",
    }
    values.update(overrides)
    return Config(**values)


class FakeTextractClient:
    def __init__(self, *, lines: list[str] | None = None, error: Exception | None = None) -> None:
        self.lines = lines or ["LOGIN PAGE", "User: admin"]
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def detect_document_text(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {
            "Blocks": [
                {"BlockType": "LINE", "Text": line}
                for line in self.lines
            ]
        }


class FakeS3AttachmentClient:
    def __init__(self, *, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        key = kwargs["Key"]
        if key not in self.objects:
            raise KeyError(key)
        return {"Body": io.BytesIO(self.objects[key])}


class FakeDynamoAttachmentClient:
    def __init__(self, registry: dict[str, dict[str, Any]] | None = None) -> None:
        self.registry = registry or {}

    def scan(self, **kwargs: Any) -> dict[str, Any]:
        ticket_id = kwargs["ExpressionAttributeValues"][":ticket_id"]["S"]
        items = []
        for row in self.registry.values():
            if row.get("record_type") != "attachment":
                continue
            if str(row.get("ticket_id") or "") != ticket_id:
                continue
            items.append(_to_ddb_item(row))
        return {"Items": items}


class ClosedTicketAttachmentExtractTests(unittest.TestCase):
    def test_vision_disabled_skips_extraction(self) -> None:
        result = extract_closed_ticket_attachment(
            b"png-bytes",
            filename="screen.png",
            content_type="image/png",
            config=Config(CLOSED_TICKET_VISION_ENABLED=False),
            textract_client=FakeTextractClient(),
        )

        self.assertIsNone(result.semantic_text)
        self.assertEqual(result.extraction_status, STATUS_VISION_DISABLED)

    def test_image_extraction_uses_textract_with_provenance(self) -> None:
        result = extract_closed_ticket_attachment(
            b"png-bytes",
            filename="screen.png",
            content_type="image/png",
            config=_vision_config(),
            textract_client=FakeTextractClient(lines=["Suspicious login form"]),
        )

        self.assertIsNotNone(result.semantic_text)
        assert result.semantic_text is not None
        self.assertIn("filename=screen.png", result.semantic_text)
        self.assertIn("Suspicious login form", result.semantic_text)
        self.assertEqual(result.extraction_status, STATUS_EXTRACTED_TEXTRACT)

    def test_byte_limit_is_fail_soft(self) -> None:
        result = extract_closed_ticket_attachment(
            b"x" * 20,
            filename="screen.png",
            content_type="image/png",
            config=_vision_config(CLOSED_TICKET_ATTACHMENT_MAX_BYTES=10),
            textract_client=FakeTextractClient(),
        )

        self.assertIsNone(result.semantic_text)
        self.assertEqual(result.extraction_status, STATUS_BYTE_LIMIT_EXCEEDED)

    def test_unsupported_type_is_skipped(self) -> None:
        result = extract_closed_ticket_attachment(
            b"zip-bytes",
            filename="archive.zip",
            content_type="application/zip",
            config=_vision_config(),
            textract_client=FakeTextractClient(),
        )

        self.assertIsNone(result.semantic_text)
        self.assertEqual(result.extraction_status, "unsupported_content_type")

    def test_textract_failure_returns_metadata_only(self) -> None:
        result = extract_closed_ticket_attachment(
            b"png-bytes",
            filename="screen.png",
            content_type="image/png",
            config=_vision_config(),
            textract_client=FakeTextractClient(error=RuntimeError("textract unavailable")),
        )

        self.assertIsNotNone(result.semantic_text)
        assert result.semantic_text is not None
        self.assertIn("attachment_metadata_only", result.semantic_text)
        self.assertEqual(result.extraction_status, "image_textract_failed")

    def test_load_closed_ticket_attachments_from_registry(self) -> None:
        storage_key = (
            f"closed_tickets/attachments/{TICKET_SYS_ID}/{ATTACHMENT_SYS_ID}/screen.png"
        )
        attachments = load_closed_ticket_attachments(
            ticket_id=TICKET_SYS_ID,
            config=_vision_config(),
            s3_client=FakeS3AttachmentClient(objects={storage_key: b"png-bytes"}),
            dynamodb_client=FakeDynamoAttachmentClient(
                registry={
                    ATTACHMENT_SYS_ID: {
                        "record_type": "attachment",
                        "attachment_id": ATTACHMENT_SYS_ID,
                        "ticket_id": TICKET_SYS_ID,
                        "file_name": "screen.png",
                        "content_type": "image/png",
                        "download_status": "downloaded",
                        "storage_key": storage_key,
                    }
                }
            ),
            bucket="pipeline-bucket",
            textract_client=FakeTextractClient(lines=["Known admin script activity."]),
        )

        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].attachment_id, ATTACHMENT_SYS_ID)
        self.assertIn("Known admin script activity.", attachments[0].semantic_text or "")

    def test_attachment_semantic_chunk_has_provenance_metadata(self) -> None:
        from s3_notable_pipeline.closed_ticket_render import ClosedTicketRecord
        from datetime import UTC, datetime, timedelta

        record = ClosedTicketRecord(
            ticket_id=TICKET_SYS_ID,
            ticket_number="INC001",
            source_table="sn_si_incident",
            source_url=None,
            state="3",
            is_active=True,
            closed_at=datetime(2026, 6, 1, 11, 0, tzinfo=UTC),
            source_updated_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            raw_payload={"number": "INC001"},
            journals_payload=[],
            expires_at=datetime.now(UTC) + timedelta(days=30),
            content_hash=CONTENT_HASH,
        )
        attachment = ClosedTicketAttachmentRecord(
            attachment_id=ATTACHMENT_SYS_ID,
            ticket_id=TICKET_SYS_ID,
            filename="screen.png",
            content_type="image/png",
            metadata={"storage_key": "closed_tickets/attachments/x/y/screen.png"},
            semantic_text="attachment filename=screen.png\n---\nLOGIN PAGE",
            extraction_status=STATUS_EXTRACTED_TEXTRACT,
        )

        chunks = build_closed_ticket_chunks(
            record,
            Config(CLOSED_TICKET_MAX_INDEX_CHUNKS_PER_TICKET=120),
            attachments=[attachment],
        )

        attachment_chunks = [chunk for chunk in chunks if chunk.section == "attachment.semantic"]
        self.assertEqual(len(attachment_chunks), 1)
        self.assertEqual(attachment_chunks[0].metadata["attachment_id"], ATTACHMENT_SYS_ID)
        self.assertIn("LOGIN PAGE", attachment_chunks[0].search_text)


class ClosedTicketEmbedAttachmentIntegrationTests(unittest.TestCase):
    def test_embed_indexes_attachment_semantic_chunk(self) -> None:
        from datetime import UTC, datetime, timedelta

        expires_at = datetime.now(UTC) + timedelta(days=30)
        manifest_key = f"closed_tickets/tickets/{TICKET_SYS_ID}/manifest.json"
        version_key = (
            f"closed_tickets/tickets/{TICKET_SYS_ID}/versions/{CONTENT_HASH}/ticket.json"
        )
        attachment_key = (
            f"closed_tickets/attachments/{TICKET_SYS_ID}/{ATTACHMENT_SYS_ID}/screen.png"
        )
        manifest = {
            "schema_version": 1,
            "ticket_id": TICKET_SYS_ID,
            "ticket_number": "INC001",
            "source_table": "sn_si_incident",
            "source_url": "https://example.service-now.com/nav_to.do",
            "state": "3",
            "content_hash": CONTENT_HASH,
            "version_key": version_key,
            "manifest_key": manifest_key,
            "is_active": True,
            "index_status": "pending",
            "expires_at": expires_at.isoformat(),
        }
        version_payload = {
            "schema_version": 1,
            "ticket_id": TICKET_SYS_ID,
            "ticket_number": "INC001",
            "source_table": "sn_si_incident",
            "source_url": manifest["source_url"],
            "state": "3",
            "closed_at": "2026-06-01T11:00:00+00:00",
            "source_updated_at": "2026-06-01T12:00:00+00:00",
            "content_hash": CONTENT_HASH,
            "raw_payload": {"number": "INC001", "short_description": "Suspicious activity"},
            "journals_payload": [],
        }

        class FakeS3Client:
            def __init__(self) -> None:
                self.objects = {
                    manifest_key: manifest,
                    version_key: version_payload,
                }
                self.binary = {attachment_key: b"png-bytes"}
                self.puts: list[dict[str, Any]] = []

            def get_object(self, **kwargs: Any) -> dict[str, Any]:
                key = kwargs["Key"]
                if key in self.binary:
                    return {"Body": io.BytesIO(self.binary[key])}
                if key not in self.objects:
                    raise KeyError(key)
                return {"Body": io.BytesIO(json.dumps(self.objects[key]).encode("utf-8"))}

            def put_object(self, **kwargs: Any) -> None:
                self.puts.append(kwargs)
                body = kwargs["Body"]
                if isinstance(body, bytes):
                    self.objects[kwargs["Key"]] = json.loads(body.decode("utf-8"))

        class FakeOpenSearchAdapter:
            def __init__(self) -> None:
                self.documents: dict[str, dict[str, Any]] = {}
                self.bulks: list[dict[str, Any]] = []

            def bulk(self, **kwargs: Any) -> dict[str, bool]:
                self.bulks.append(kwargs)
                for action in kwargs.get("actions", []):
                    if action.get("operation") == "index":
                        doc_id = str(action["id"])
                        self.documents[doc_id] = dict(action["document"])
                return {"errors": False}

            def search(self, **_kwargs: Any) -> dict[str, Any]:
                hits = []
                for doc_id, document in self.documents.items():
                    if document.get("active", True):
                        hits.append({"_id": doc_id, "_score": 1.0, "_source": document})
                return {"hits": {"hits": hits}}

        s3 = FakeS3Client()
        adapter = FakeOpenSearchAdapter()
        dynamodb = FakeDynamoAttachmentClient(
            registry={
                TICKET_SYS_ID: {
                    "ticket_id": TICKET_SYS_ID,
                    "record_type": "ticket",
                    "is_active": True,
                    "index_status": "pending",
                    "manifest_key": manifest_key,
                    "version_key": version_key,
                },
                ATTACHMENT_SYS_ID: {
                    "record_type": "attachment",
                    "attachment_id": ATTACHMENT_SYS_ID,
                    "ticket_id": TICKET_SYS_ID,
                    "file_name": "screen.png",
                    "content_type": "image/png",
                    "download_status": "downloaded",
                    "storage_key": attachment_key,
                },
            }
        )

        class FakeBedrockClient:
            def invoke_model(self, **_kwargs: Any) -> dict[str, Any]:
                return {"body": io.BytesIO(json.dumps({"embedding": [0.01] * 1024}).encode())}

        class FakeDynamoForEmbed(FakeDynamoAttachmentClient):
            def get_item(self, **kwargs: Any) -> dict[str, Any]:
                ticket_id = kwargs["Key"]["ticket_id"]["S"]
                row = self.registry.get(ticket_id)
                if not row or row.get("record_type") != "ticket":
                    return {}
                return {"Item": _to_ddb_item(row)}

            def put_item(self, **kwargs: Any) -> None:
                item = kwargs["Item"]
                ticket_id = item["ticket_id"]["S"]
                from s3_notable_pipeline.servicenow_closed_ticket_sync import _from_ddb_item

                self.registry[ticket_id] = _from_ddb_item(item)

        embed_dynamo = FakeDynamoForEmbed(registry=dynamodb.registry)

        textract = FakeTextractClient(lines=["Screenshot shows a login form."])
        import s3_notable_pipeline.closed_ticket_embed as embed_module

        original_factory = embed_module._textract_client_for_attachments
        embed_module._textract_client_for_attachments = lambda _config: textract
        try:
            result = embed_closed_ticket(
                ticket_id=TICKET_SYS_ID,
                config=Config(
                    CLOSED_TICKET_EMBED_ENABLED=True,
                    CLOSED_TICKET_VISION_ENABLED=True,
                    OUTPUT_BUCKET_NAME="pipeline-bucket",
                    CLOSED_TICKET_RAW_PREFIX="closed_tickets",
                    CLOSED_TICKET_REGISTRY_TABLE="closed-ticket-registry",
                    RAG_TENANT_ID="tenant-a",
                    RAG_RETRIEVAL_BACKEND="opensearch",
                    OPENSEARCH_ENDPOINT="https://search.example.com",
                    OPENSEARCH_CLOSED_TICKET_INDEX="closed_tickets",
                ),
                s3_client=s3,
                bedrock_client=FakeBedrockClient(),
                dynamodb_client=embed_dynamo,
                adapter=adapter,
            )
        finally:
            embed_module._textract_client_for_attachments = original_factory

        self.assertEqual(result.status, "ready")
        attachment_docs = [
            doc
            for doc in adapter.documents.values()
            if doc.get("section") == "attachment.semantic"
        ]
        self.assertEqual(len(attachment_docs), 1)
        self.assertIn("Screenshot shows a login form.", attachment_docs[0]["search_text"])


if __name__ == "__main__":
    unittest.main()
