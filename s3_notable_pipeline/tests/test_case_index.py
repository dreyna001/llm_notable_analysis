"""Tests for read-only CaseIndex helpers."""

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

from s3_notable_pipeline.case_index import get_case_detail, get_case_raw_section, list_cases
from s3_notable_pipeline.config import Config


class FakeDynamoDbClient:
    """Fake CaseIndex DynamoDB client."""

    def __init__(self) -> None:
        self.item = ddb_case_item()

    def query(self, **_kwargs: Any) -> dict[str, Any]:
        return {"Items": [self.item]}

    def get_item(self, **_kwargs: Any) -> dict[str, Any]:
        return {"Item": self.item}


class FakeS3Client:
    """Fake S3 envelope client."""

    def get_object(self, **_kwargs: Any) -> dict[str, Any]:
        return {"Body": io.BytesIO(json.dumps(case_envelope()).encode("utf-8"))}


def config() -> Config:
    """Return portal config for read tests."""

    return Config(
        CASE_ARCHIVE_BUCKET="case-bucket",
        CASE_INDEX_TABLE="case-index",
        PORTAL_PAGE_SIZE=50,
    )


def ddb_case_item() -> dict[str, dict[str, Any]]:
    """Return a low-level CaseIndex item."""

    return {
        "case_id": {"S": "case-1"},
        "processed_at": {"S": "2026-06-15T10:30:00Z"},
        "processed_at_case_id": {"S": "2026-06-15T10:30:00Z#case-1"},
        "expires_at": {"S": "2026-07-15T10:30:00Z"},
        "verdict": {"S": "likely_true_positive"},
        "confidence": {"S": "0.8"},
        "search_name": {"S": "Suspicious Login"},
        "retrieval_status": {"S": "pending"},
        "source_completeness": {"S": "complete"},
        "case_envelope_key": {"S": "cases/2026/06/15/case-1.json"},
    }


def case_envelope() -> dict[str, Any]:
    """Return an archived case envelope."""

    return {
        "case_id": "case-1",
        "artifacts": {
            "report_markdown_key": "reports/case-1.md",
            "report_html_key": "reports/case-1.html",
        },
        "archive_metadata": {
            "retrieval_status": "pending",
            "source_completeness": "complete",
        },
        "alert_payload": {"finding_id": "finding-1", "user": "alice"},
        "analysis": {"alert_reconciliation": {"verdict": "likely_true_positive"}},
    }


class CaseIndexTests(unittest.TestCase):
    """CaseIndex helper tests."""

    def test_list_cases_includes_archive_notices(self) -> None:
        result = list_cases(config=config(), dynamodb_client=FakeDynamoDbClient())

        self.assertEqual(result["items"][0]["case_id"], "case-1")
        self.assertEqual(result["items"][0]["confidence"], 0.8)
        self.assertIn("indexing is still pending", result["items"][0]["archive_notices"][0])

    def test_get_case_detail_loads_bounded_envelope(self) -> None:
        result = get_case_detail(
            config=config(),
            dynamodb_client=FakeDynamoDbClient(),
            s3_client=FakeS3Client(),
            case_id="case-1",
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["report_md_path"], "reports/case-1.md")
        self.assertEqual(result["alert_payload"]["user"], "alice")
        self.assertIn("alert_payload", result["content_bounds"]["raw_sections"])

    def test_get_case_raw_section_pages_items(self) -> None:
        result = get_case_raw_section(
            config=config(),
            dynamodb_client=FakeDynamoDbClient(),
            s3_client=FakeS3Client(),
            case_id="case-1",
            section="alert_payload",
            offset=1,
            limit=1,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["total_keys"], 2)
        self.assertEqual(result["limit"], 1)
        self.assertEqual(list(result["items"]), ["user"])


if __name__ == "__main__":
    unittest.main()
