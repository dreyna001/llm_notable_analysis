"""Tests for Bedrock Knowledge Base retrieval helpers."""
# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.bedrock_kb_retrieval import (
    render_soc_context,
    retrieve_soc_context,
)
from s3_notable_pipeline.config import Config


class BedrockKbRetrievalTests(unittest.TestCase):
    """Validate bounded advisory context retrieval."""

    def test_disabled_rag_skips_retrieval(self) -> None:
        """Disabled RAG should not require a KB id or client."""
        result = retrieve_soc_context("alert", Config(RAG_ENABLED=False))

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.context, "")

    def test_missing_kb_id_suppresses_when_configured(self) -> None:
        """Missing KB id should fail soft by default."""
        result = retrieve_soc_context("alert", Config(RAG_ENABLED=True))

        self.assertEqual(result.status, "failed")
        self.assertIn("RAG_BEDROCK_KB_ID", result.message)

    def test_retrieve_renders_source_labeled_context(self) -> None:
        """Successful retrieval should render bounded source-labeled snippets."""
        client = types.SimpleNamespace(
            retrieve=lambda **_kwargs: {
                "retrievalResults": [
                    {
                        "content": {"text": "Reset password SOP and escalation notes."},
                        "metadata": {"source_file": "sop.md"},
                    }
                ]
            }
        )
        config = Config(
            RAG_ENABLED=True,
            RAG_BEDROCK_KB_ID="KB123",
            RAG_CONTEXT_BUDGET_CHARS=200,
        )

        result = retrieve_soc_context("alert", config, client=client)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.snippet_count, 1)
        self.assertIn("Source: sop.md", result.context)
        self.assertIn("Reset password SOP", result.context)

    def test_render_respects_context_budget(self) -> None:
        """Rendered context should stay within the configured character budget."""
        context = render_soc_context(
            [
                {
                    "content": {"text": "a" * 100},
                    "metadata": {"source_file": "large.txt"},
                }
            ],
            budget_chars=40,
        )

        self.assertLessEqual(len(context), 40)


if __name__ == "__main__":
    unittest.main()
