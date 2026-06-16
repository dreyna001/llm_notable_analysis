"""Tests for portal answer validation."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.portal_chat import validate_answer_payload


class PortalChatTests(unittest.TestCase):
    """Answer schema tests."""

    def test_answered_response_requires_citations(self) -> None:
        result = validate_answer_payload(
            {"answer": "This was suspicious.", "answer_status": "answered", "citations": []}
        )

        self.assertEqual(result.answer_status, "insufficient_context")

    def test_cited_answer_is_accepted(self) -> None:
        result = validate_answer_payload(
            {
                "answer": "This was suspicious.",
                "answer_status": "answered",
                "citations": ["chunk-1"],
            }
        )

        self.assertEqual(result.answer_status, "answered")
        self.assertEqual(result.citations, ["chunk-1"])

    def test_answered_response_rejects_unknown_citations(self) -> None:
        result = validate_answer_payload(
            {
                "answer": "This was suspicious.",
                "answer_status": "answered",
                "citations": ["other-case-chunk"],
            },
            allowed_citations={"chunk-1"},
        )

        self.assertEqual(result.answer_status, "insufficient_context")


if __name__ == "__main__":
    unittest.main()
