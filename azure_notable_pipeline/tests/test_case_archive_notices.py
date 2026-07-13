"""Tests for portal archive notices."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from azure_notable_pipeline.case_archive_notices import build_case_archive_notices


class CaseArchiveNoticeTests(unittest.TestCase):
    """Notice generation tests."""

    def test_failed_indexing_and_missing_analysis_generate_notices(self) -> None:
        notices = build_case_archive_notices(
            retrieval_status="failed",
            source_completeness="missing_analysis",
        )

        self.assertEqual(len(notices), 2)
        self.assertIn("indexing failed", notices[0])
        self.assertIn("Structured analysis", notices[1])


if __name__ == "__main__":
    unittest.main()
