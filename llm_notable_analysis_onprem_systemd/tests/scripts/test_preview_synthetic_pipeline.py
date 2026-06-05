"""Tests for preview synthetic pipeline fixtures."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_SRC = Path(__file__).resolve().parents[2] / "src"
for path in (_SCRIPTS, _SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from preview_synthetic_pipeline import (  # noqa: E402
    build_synthetic_preview_record,
    materialize_synthetic_analysis,
    preview_scenario_count,
    _preview_scenarios,
)

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config  # noqa: E402
from llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client import (  # noqa: E402
    validate_response_schema,
)


class TestPreviewSyntheticPipeline(unittest.TestCase):
    def test_all_scenarios_validate_and_include_query_section(self) -> None:
        for index, scenario in enumerate(_preview_scenarios(), start=1):
            analysis = materialize_synthetic_analysis(scenario)
            ok, err = validate_response_schema(analysis)
            self.assertTrue(ok, msg=f"scenario {index}: {err}")
            self.assertEqual(len(analysis["competing_hypotheses"]), 6)
            if scenario.get("query_results"):
                self.assertIn("query_result_section", analysis)
                self.assertGreater(
                    analysis["query_result_section"]["summary"]["attempted"],
                    0,
                )

    def test_build_synthetic_preview_record_uses_archive_builder(self) -> None:
        config = Config()
        record = build_synthetic_preview_record(
            config=config,
            scenario_index=1,
            case_id="case-1",
            finding_id="syn-001",
            source_filename="syn-case-1.json",
            processed_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
        )
        self.assertEqual(record.case_id, "case-1")
        self.assertEqual(record.retrieval_status, "ready")
        self.assertEqual(record.source_completeness, "complete")
        self.assertIsNotNone(record.analysis)
        self.assertEqual(record.search_name, "Suspicious PowerShell")
        self.assertEqual(record.verdict, "likely_malicious")

    def test_preview_scenario_count_is_five(self) -> None:
        self.assertEqual(preview_scenario_count(), 5)


if __name__ == "__main__":
    unittest.main()
