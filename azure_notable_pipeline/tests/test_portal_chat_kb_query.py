"""Tests for case-aware Knowledge Base query construction."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from azure_notable_pipeline.portal_chat_kb_query import build_case_aware_kb_query  # noqa: E402


class PortalCaseAwareKbQueryTests(unittest.TestCase):
    def test_empty_case_chunks_returns_raw_question(self) -> None:
        query = build_case_aware_kb_query(
            "Summarize this case.",
            case_chunks=[],
            selected_case_id=None,
        )
        self.assertEqual(query, "Summarize this case.")

    def test_appends_selected_case_id_and_extracted_entities(self) -> None:
        query = build_case_aware_kb_query(
            "Summarize this case in a few sentences.",
            case_chunks=[
                {
                    "source_lane": "current_case",
                    "section": "alert.summary",
                    "text": (
                        "dest_host=db-prod-01.corp.local src_host=jump-01.corp.local "
                        "user=corp\\svc-backup"
                    ),
                }
            ],
            selected_case_id="case-5",
        )
        self.assertIn("Summarize this case in a few sentences.", query)
        self.assertIn("selected_case_id=case-5", query)
        self.assertIn("db-prod-01.corp.local", query)


if __name__ == "__main__":
    unittest.main()
