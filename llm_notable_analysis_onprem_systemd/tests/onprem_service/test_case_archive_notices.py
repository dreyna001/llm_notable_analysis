"""Tests for deterministic case archive analyst notices."""

from __future__ import annotations

import unittest

from llm_notable_analysis_onprem_systemd.onprem_service.case_archive_notices import (
    build_case_archive_notices,
)


class CaseArchiveNoticesTests(unittest.TestCase):
    def test_ready_complete_case_has_no_notices(self) -> None:
        self.assertEqual(
            build_case_archive_notices(
                retrieval_status="ready",
                source_completeness="complete",
            ),
            [],
        )

    def test_failed_indexing_notice(self) -> None:
        notices = build_case_archive_notices(
            retrieval_status="failed",
            source_completeness="complete",
        )
        self.assertEqual(len(notices), 1)
        self.assertIn("chat indexing failed", notices[0])

    def test_missing_analysis_notice(self) -> None:
        notices = build_case_archive_notices(
            retrieval_status="not_indexed",
            source_completeness="missing_analysis",
        )
        self.assertGreaterEqual(len(notices), 2)
        self.assertTrue(any("Structured analysis was not stored" in item for item in notices))

    def test_markdown_only_backfill_notice(self) -> None:
        notices = build_case_archive_notices(
            retrieval_status="ready",
            source_completeness="markdown_only",
        )
        self.assertEqual(len(notices), 1)
        self.assertIn("legacy markdown report", notices[0])


if __name__ == "__main__":
    unittest.main()
