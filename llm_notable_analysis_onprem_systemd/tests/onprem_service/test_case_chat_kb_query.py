"""Tests for case-aware Knowledge Base query construction."""

from __future__ import annotations

import unittest

from llm_notable_analysis_onprem_systemd.onprem_service.case_chat import RetrievedSource
from llm_notable_analysis_onprem_systemd.onprem_service.case_chat_kb_query import (
    build_case_aware_kb_query,
)


class CaseAwareKbQueryTests(unittest.TestCase):
    def test_empty_case_sources_returns_raw_question(self) -> None:
        query = build_case_aware_kb_query(
            "Summarize this case.",
            case_sources=[],
            selected_case_id=None,
        )
        self.assertEqual(query, "Summarize this case.")

    def test_appends_selected_case_id_and_extracted_entities(self) -> None:
        query = build_case_aware_kb_query(
            "Summarize this case in a few sentences.",
            case_sources=[
                RetrievedSource(
                    source_lane="current_case",
                    section="alert.summary",
                    text=(
                        "dest_host=db-prod-01.corp.local src_host=jump-01.corp.local "
                        "user=corp\\svc-backup alert_type=Suspicious RDP Lateral Movement"
                    ),
                )
            ],
            selected_case_id="case-5",
        )
        self.assertIn("Summarize this case in a few sentences.", query)
        self.assertIn("selected_case_id=case-5", query)
        self.assertIn("dest_host=db-prod-01.corp.local", query)
        self.assertIn("db-prod-01.corp.local", query)
        self.assertIn("db-prod-01", query)
        self.assertIn("corp\\svc-backup", query)

    def test_ignores_non_current_case_sources(self) -> None:
        query = build_case_aware_kb_query(
            "What happened?",
            case_sources=[
                RetrievedSource(
                    source_lane="knowledge_base",
                    section="knowledge_base.hva_registry",
                    text="db-prod-99.corp.local",
                )
            ],
        )
        self.assertEqual(query, "What happened?")

    def test_context_budget_is_bounded(self) -> None:
        long_text = "dest_host=" + ("x" * 2000) + ".corp.local"
        query = build_case_aware_kb_query(
            "Summarize.",
            case_sources=[
                RetrievedSource(
                    source_lane="current_case",
                    section="alert.summary",
                    text=long_text,
                )
            ],
            max_context_chars=100,
        )
        self.assertLessEqual(len(query), len("Summarize.") + 1 + 100)


if __name__ == "__main__":
    unittest.main()
