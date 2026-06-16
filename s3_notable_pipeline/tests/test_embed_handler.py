"""Tests for the post-archive embed Lambda handler."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.case_embed import EmbedResult
from s3_notable_pipeline.config import Config
from s3_notable_pipeline import embed_handler


class EmbedHandlerTests(unittest.TestCase):
    """Behavior tests for embed_handler.handler."""

    def test_handler_embeds_case_from_event(self) -> None:
        """Handler should pass event envelope pointers to the embed workflow."""
        s3_client = object()
        bedrock_client = object()
        dynamodb_client = object()
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


if __name__ == "__main__":
    unittest.main()
