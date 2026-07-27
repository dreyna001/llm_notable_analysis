"""Tests for the post-archive embed Lambda handler."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.case_embed import EmbedResult
from s3_notable_pipeline.config import Config
from s3_notable_pipeline import embed_handler


def embed_job(*, bucket: str = "archive-bucket", key: str = "cases/2026/06/15/case-1.json") -> dict[str, str]:
    return {
        "case_id": "case-1",
        "case_envelope_bucket": bucket,
        "case_envelope_key": key,
    }


class EmbedHandlerTests(unittest.TestCase):
    """Behavior tests for embed_handler.handler."""

    def _patch_clients(self) -> tuple[Any, ...]:
        s3_client = object()
        bedrock_client = object()
        dynamodb_client = object()
        return s3_client, bedrock_client, dynamodb_client

    def test_handler_embeds_case_from_direct_event(self) -> None:
        """Handler should pass direct event envelope pointers to the embed workflow."""
        s3_client, bedrock_client, dynamodb_client = self._patch_clients()
        with (
            patch.object(
                embed_handler,
                "load_config",
                return_value=Config(CASE_ARCHIVE_BUCKET="case-bucket"),
            ),
            patch.object(embed_handler, "s3_client", return_value=s3_client),
            patch.object(embed_handler, "bedrock_runtime_client", return_value=bedrock_client),
            patch.object(embed_handler, "dynamodb_client", return_value=dynamodb_client),
            patch.object(
                embed_handler,
                "embed_case_envelope",
                return_value=EmbedResult(
                    status="ready",
                    case_id="case-1",
                    chunk_count=3,
                ),
            ) as mock_embed,
        ):
            response = embed_handler.handler(
                {
                    "case_envelope_bucket": "archive-bucket",
                    "case_envelope_key": "cases/2026/06/15/case-1.json",
                },
                None,
            )

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["chunk_count"], 3)
        mock_embed.assert_called_once()
        self.assertEqual(mock_embed.call_args.kwargs["bucket"], "archive-bucket")
        self.assertEqual(
            mock_embed.call_args.kwargs["key"],
            "cases/2026/06/15/case-1.json",
        )
        self.assertIs(mock_embed.call_args.kwargs["s3_client"], s3_client)
        self.assertIs(mock_embed.call_args.kwargs["bedrock_client"], bedrock_client)
        self.assertIs(mock_embed.call_args.kwargs["dynamodb_client"], dynamodb_client)

    def test_sqs_batch_success_returns_no_failures(self) -> None:
        with (
            patch.object(
                embed_handler,
                "load_config",
                return_value=Config(CASE_ARCHIVE_BUCKET="case-bucket"),
            ),
            patch.object(embed_handler, "s3_client", return_value=object()),
            patch.object(embed_handler, "bedrock_runtime_client", return_value=object()),
            patch.object(embed_handler, "dynamodb_client", return_value=object()),
            patch.object(
                embed_handler,
                "embed_case_envelope",
                return_value=EmbedResult(status="ready", case_id="case-1", chunk_count=2),
            ) as mock_embed,
        ):
            result = embed_handler.handler(
                {
                    "Records": [
                        {
                            "messageId": "msg-1",
                            "body": json.dumps(embed_job(key="cases/a.json")),
                        },
                        {
                            "messageId": "msg-2",
                            "body": json.dumps(embed_job(key="cases/b.json")),
                        },
                    ]
                },
                None,
            )

        self.assertEqual(result, {"batchItemFailures": []})
        self.assertEqual(mock_embed.call_count, 2)

    def test_sqs_partial_failure_reports_only_failed_message(self) -> None:
        def embed_side_effect(*, key: str, **_kwargs: object) -> EmbedResult:
            if key.endswith("bad.json"):
                return EmbedResult(status="failed", case_id="case-bad", message="bedrock error")
            return EmbedResult(status="ready", case_id="case-good", chunk_count=1)

        with (
            patch.object(
                embed_handler,
                "load_config",
                return_value=Config(CASE_ARCHIVE_BUCKET="case-bucket"),
            ),
            patch.object(embed_handler, "s3_client", return_value=object()),
            patch.object(embed_handler, "bedrock_runtime_client", return_value=object()),
            patch.object(embed_handler, "dynamodb_client", return_value=object()),
            patch.object(embed_handler, "embed_case_envelope", side_effect=embed_side_effect),
        ):
            result = embed_handler.handler(
                {
                    "Records": [
                        {
                            "messageId": "good-message",
                            "body": json.dumps(embed_job(key="cases/good.json")),
                        },
                        {
                            "messageId": "bad-message",
                            "body": json.dumps(embed_job(key="cases/bad.json")),
                        },
                    ]
                },
                None,
            )

        self.assertEqual(result["batchItemFailures"], [{"itemIdentifier": "bad-message"}])

    def test_sqs_malformed_body_fails_only_that_message(self) -> None:
        with (
            patch.object(
                embed_handler,
                "load_config",
                return_value=Config(CASE_ARCHIVE_BUCKET="case-bucket"),
            ),
            patch.object(embed_handler, "s3_client", return_value=object()),
            patch.object(embed_handler, "bedrock_runtime_client", return_value=object()),
            patch.object(embed_handler, "dynamodb_client", return_value=object()),
            patch.object(
                embed_handler,
                "embed_case_envelope",
                return_value=EmbedResult(status="ready", case_id="case-1", chunk_count=1),
            ) as mock_embed,
        ):
            result = embed_handler.handler(
                {
                    "Records": [
                        {
                            "messageId": "good-message",
                            "body": json.dumps(embed_job(key="cases/good.json")),
                        },
                        {
                            "messageId": "malformed-message",
                            "body": "not-json",
                        },
                    ]
                },
                None,
            )

        self.assertEqual(result["batchItemFailures"], [{"itemIdentifier": "malformed-message"}])
        mock_embed.assert_called_once()

    def test_sqs_failed_embed_result_signals_retry(self) -> None:
        with (
            patch.object(
                embed_handler,
                "load_config",
                return_value=Config(CASE_ARCHIVE_BUCKET="case-bucket"),
            ),
            patch.object(embed_handler, "s3_client", return_value=object()),
            patch.object(embed_handler, "bedrock_runtime_client", return_value=object()),
            patch.object(embed_handler, "dynamodb_client", return_value=object()),
            patch.object(
                embed_handler,
                "embed_case_envelope",
                return_value=EmbedResult(status="failed", case_id="case-1", message="embed error"),
            ),
        ):
            result = embed_handler.handler(
                {
                    "Records": [
                        {
                            "messageId": "retry-me",
                            "body": json.dumps(embed_job()),
                        }
                    ]
                },
                None,
            )

        self.assertEqual(result["batchItemFailures"], [{"itemIdentifier": "retry-me"}])


if __name__ == "__main__":
    unittest.main()
