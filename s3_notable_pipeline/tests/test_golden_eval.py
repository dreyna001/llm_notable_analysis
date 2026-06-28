"""Golden eval tests for analyzer disposition on easy baseline alerts."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.ttp_analyzer import BedrockAnalyzer  # pylint: disable=import-error
from s3_notable_pipeline.verdicts import normalize_verdict  # pylint: disable=import-error

from golden_eval_rubric import (
    evaluate_analysis_rubric,
    load_json,
    load_manifest,
)


class TestGoldenEvalRubric(unittest.TestCase):
    """Offline rubric checks against committed reference analyses."""

    def test_manifest_loads_baseline_cases(self) -> None:
        cases = load_manifest()
        self.assertGreaterEqual(len(cases), 3)
        self.assertEqual(
            {case.id for case in cases},
            {"beaconing-tp", "patch-admin-fp", "sparse-unknown"},
        )
        for case in cases:
            self.assertTrue(case.alert_path.is_file(), msg=case.id)
            self.assertTrue(case.reference_analysis_path.is_file(), msg=case.id)

    def test_reference_analyses_pass_rubric(self) -> None:
        for case in load_manifest():
            with self.subTest(case_id=case.id):
                analysis = load_json(case.reference_analysis_path)
                failures = evaluate_analysis_rubric(
                    analysis,
                    expected_verdict=case.expected_verdict,
                    evidence_any=case.evidence_any,
                )
                self.assertEqual(failures, [])


@unittest.skipUnless(
    os.environ.get("GOLDEN_EVAL_LIVE") == "1",
    "Set GOLDEN_EVAL_LIVE=1 to run live analyzer golden evals",
)
class TestGoldenEvalLive(unittest.TestCase):
    """Live Bedrock evals; opt-in only."""

    @classmethod
    def setUpClass(cls) -> None:
        if not os.environ.get("BEDROCK_MODEL_ID"):
            raise unittest.SkipTest("BEDROCK_MODEL_ID is required for live golden evals")

    def test_live_analyzer_meets_golden_rubric(self) -> None:
        analyzer = BedrockAnalyzer(model_id=os.environ["BEDROCK_MODEL_ID"])

        for case in load_manifest():
            with self.subTest(case_id=case.id):
                alert = load_json(case.alert_path)
                alert_text = json.dumps(alert, ensure_ascii=True, separators=(",", ":"))
                analyzer.analyze_ttp(
                    alert_text, alert_time=str(alert.get("event_time") or "")
                )
                result = analyzer.last_llm_response or {}
                self.assertNotIn("error", result, msg=result.get("error"))

                analysis = {
                    key: result[key]
                    for key in (
                        "alert_reconciliation",
                        "competing_hypotheses",
                        "evidence_vs_inference",
                        "ioc_extraction",
                        "ttp_analysis",
                    )
                    if key in result
                }
                failures = evaluate_analysis_rubric(
                    analysis,
                    expected_verdict=case.expected_verdict,
                    evidence_any=case.evidence_any,
                )
                verdict = normalize_verdict(
                    str(analysis.get("alert_reconciliation", {}).get("verdict", ""))
                )
                self.assertEqual(
                    failures,
                    [],
                    msg=f"{case.id} verdict={verdict} failures={failures}",
                )


if __name__ == "__main__":
    unittest.main()
