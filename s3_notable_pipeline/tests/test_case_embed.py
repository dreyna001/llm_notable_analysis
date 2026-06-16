"""Tests for post-archive case chunk embedding."""

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

from s3_notable_pipeline.case_embed import (
    build_case_chunks,
    embed_case_envelope,
    rewrite_case_chunks,
)
from s3_notable_pipeline.config import Config


class FakeS3Client:
    """Fake S3 client for envelope reads and chunk rewrites."""

    def __init__(self, envelope: dict[str, Any] | None = None) -> None:
        self.envelope = envelope or case_envelope()
        self.puts: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []
        self.list_calls: list[dict[str, Any]] = []

    def get_object(self, **_kwargs: Any) -> dict[str, Any]:
        return {"Body": io.BytesIO(json.dumps(self.envelope).encode("utf-8"))}

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        self.list_calls.append(kwargs)
        return {
            "Contents": [
                {"Key": f"{kwargs['Prefix']}old-1.json"},
                {"Key": f"{kwargs['Prefix']}old-2.json"},
            ],
            "IsTruncated": False,
        }

    def delete_objects(self, **kwargs: Any) -> None:
        self.deletes.append(kwargs)

    def put_object(self, **kwargs: Any) -> None:
        self.puts.append(kwargs)


class FakeBedrockClient:
    """Fake Bedrock Runtime client returning deterministic embeddings."""

    def __init__(self, dimensions: int = 1024) -> None:
        self.dimensions = dimensions
        self.requests: list[dict[str, Any]] = []

    def invoke_model(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(kwargs)
        return {
            "body": io.BytesIO(
                json.dumps({"embedding": [0.01] * self.dimensions}).encode("utf-8")
            )
        }


class FakeDynamoDbClient:
    """Capture CaseIndex status updates."""

    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    def update_item(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)


def embed_config(**overrides: Any) -> Config:
    """Return config suitable for embedding tests."""

    values = {
        "CASE_ARCHIVE_BUCKET": "case-bucket",
        "CASE_INDEX_TABLE": "case-index",
        "CASE_ARCHIVE_CHUNKS_PREFIX": "case_chunks",
    }
    values.update(overrides)
    return Config(**values)


def case_envelope(**overrides: Any) -> dict[str, Any]:
    """Return a representative case envelope."""

    envelope = {
        "case_id": "case-1",
        "finding_id": "finding-1",
        "source": {"source_filename": "example.json"},
        "artifacts": {"report_markdown_key": "reports/example.md"},
        "alert_payload": {
            "finding_id": "finding-1",
            "summary": "Suspicious login",
            "user": "alice",
            "src_ip": "192.0.2.10",
        },
        "analysis": {
            "alert_reconciliation": {
                "verdict": "likely_true_positive",
                "confidence": 0.8,
            },
            "ioc_extraction": {"ips": ["192.0.2.10"]},
        },
    }
    envelope.update(overrides)
    return envelope


class CaseEmbedTests(unittest.TestCase):
    """Behavior tests for chunk building and embedding."""

    def test_build_case_chunks_uses_search_text_contract(self) -> None:
        chunks = build_case_chunks(case_envelope(), embed_config())

        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(chunks[0].source_lane, "alert_payload")
        self.assertIn("alert.summary", chunks[0].search_text)
        self.assertIn("$", chunks[0].search_text)
        self.assertIn("Suspicious login", chunks[0].search_text)

    def test_rewrite_case_chunks_deletes_prefix_and_writes_embeddings(self) -> None:
        chunks = build_case_chunks(case_envelope(), embed_config(CASE_QA_MAX_INDEX_CHUNKS_PER_CASE=2))
        s3 = FakeS3Client()
        bedrock = FakeBedrockClient()

        rewrite_case_chunks(
            bucket="case-bucket",
            case_id="case-1",
            chunks=chunks,
            config=embed_config(),
            s3_client=s3,
            bedrock_client=bedrock,
        )

        self.assertEqual(s3.list_calls[0]["Prefix"], "case_chunks/case-1/")
        self.assertEqual(len(s3.deletes), 1)
        self.assertEqual(len(s3.puts), len(chunks))
        chunk_body = json.loads(s3.puts[0]["Body"].decode("utf-8"))
        self.assertEqual(chunk_body["embedding_model"], "amazon.titan-embed-text-v2:0")
        self.assertEqual(len(chunk_body["embedding"]), 1024)
        self.assertIn("search_text", chunk_body)
        self.assertEqual(len(bedrock.requests), len(chunks))

    def test_embed_case_envelope_updates_ready_status(self) -> None:
        s3 = FakeS3Client()
        bedrock = FakeBedrockClient()
        dynamodb = FakeDynamoDbClient()

        result = embed_case_envelope(
            bucket="case-bucket",
            key="cases/2026/06/15/case-1.json",
            config=embed_config(CASE_QA_MAX_INDEX_CHUNKS_PER_CASE=2),
            s3_client=s3,
            bedrock_client=bedrock,
            dynamodb_client=dynamodb,
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.case_id, "case-1")
        self.assertEqual(result.chunk_count, 2)
        self.assertEqual(dynamodb.updates[-1]["Key"], {"case_id": {"S": "case-1"}})
        self.assertEqual(
            dynamodb.updates[-1]["ExpressionAttributeValues"][":status"],
            {"S": "ready"},
        )

    def test_embed_failure_updates_failed_status(self) -> None:
        s3 = FakeS3Client()
        bedrock = FakeBedrockClient(dimensions=2)
        dynamodb = FakeDynamoDbClient()

        result = embed_case_envelope(
            bucket="case-bucket",
            key="cases/2026/06/15/case-1.json",
            config=embed_config(),
            s3_client=s3,
            bedrock_client=bedrock,
            dynamodb_client=dynamodb,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(
            dynamodb.updates[-1]["ExpressionAttributeValues"][":status"],
            {"S": "failed"},
        )


if __name__ == "__main__":
    unittest.main()
