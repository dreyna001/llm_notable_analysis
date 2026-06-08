"""Tests for bounded portal case detail views and raw JSON paging."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from llm_notable_analysis_onprem_systemd.onprem_service.case_store import (
    build_case_archive_record,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config
from llm_notable_analysis_onprem_systemd.onprem_service.portal_case_detail_view import (
    build_case_detail_view,
    build_case_raw_section_page,
)


def _record(*, alert_payload: dict | None = None, analysis: dict | None = None):
    return build_case_archive_record(
        config=Config(),
        case_id="case-1",
        finding_id="case-1",
        source_filename="case-1.json",
        alert_payload=alert_payload or {"notable_id": "abc-123", "search_name": "Rule"},
        analysis=analysis
        or {
            "alert_reconciliation": {"verdict": "likely_malicious"},
            "raw_response": "secret raw output",
        },
        report_md_path="/reports/case-1.md",
        report_html_path=None,
        processed_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )


class TestPortalCaseDetailView(unittest.TestCase):
    def test_build_case_detail_view_omits_non_view_analysis_sections(self) -> None:
        view = build_case_detail_view(_record())

        self.assertEqual(view["alert_payload"]["notable_id"], "abc-123")
        self.assertIn("alert_reconciliation", view["analysis"])
        self.assertNotIn("raw_response", view["analysis"])
        self.assertIn("analysis", view["content_bounds"]["raw_sections"])

    def test_build_case_detail_view_bounds_large_strings(self) -> None:
        view = build_case_detail_view(
            _record(
                analysis={
                    "alert_reconciliation": {"one_sentence_summary": "x" * 20_000},
                    "raw_response": "y" * 20_000,
                }
            )
        )

        summary = view["analysis"]["alert_reconciliation"]["one_sentence_summary"]
        self.assertLessEqual(len(summary), 8_000)
        self.assertTrue(view["content_bounds"]["analysis_truncated"])

    def test_build_case_raw_section_page_paginates_top_level_keys(self) -> None:
        alert_payload = {f"field_{index}": index for index in range(120)}
        page = build_case_raw_section_page(
            _record(alert_payload=alert_payload),
            section="alert_payload",
            offset=0,
            limit=50,
            key=None,
        )

        self.assertEqual(page["total_keys"], 120)
        self.assertEqual(len(page["items"]), 50)
        self.assertTrue(page["has_more"])

    def test_build_case_raw_section_page_supports_single_key_lookup(self) -> None:
        page = build_case_raw_section_page(
            _record(),
            section="analysis",
            offset=0,
            limit=50,
            key="raw_response",
        )

        self.assertEqual(page["items"]["raw_response"], "secret raw output")
        self.assertFalse(page["has_more"])

    def test_build_case_raw_section_page_rejects_unknown_key(self) -> None:
        with self.assertRaises(LookupError):
            build_case_raw_section_page(
                _record(),
                section="analysis",
                offset=0,
                limit=50,
                key="missing",
            )


if __name__ == "__main__":
    unittest.main()
