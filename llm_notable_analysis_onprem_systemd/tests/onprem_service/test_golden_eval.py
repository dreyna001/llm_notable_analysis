"""Golden eval tests for analyzer disposition on easy baseline alerts."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from llm_notable_analysis_onprem_systemd.onprem_service.config import load_config
from llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client import (
    LocalLLMClient,
)
from llm_notable_analysis_onprem_systemd.onprem_service.verdicts import normalize_verdict

from golden_eval_rubric import (
    evaluate_analysis_rubric,
    load_json,
    load_manifest,
)


class _DummyValidator:
    def filter_valid_ttps(self, scored_ttps):
        return scored_ttps


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

    def test_preview_beaconing_bundle_matches_golden_rubric(self) -> None:
        """Guard preview case-1 stored bundle against golden beaconing expectations."""
        bundle_path = (
            Path(__file__).resolve().parents[2]
            / "data"
            / "preview_scenarios"
            / "bundles"
            / "case-1.json"
        )
        bundle = load_json(bundle_path)
        analysis = bundle["analysis"]
        case = next(item for item in load_manifest() if item.id == "beaconing-tp")
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
    """Live LLM evals; opt-in only."""

    @classmethod
    def setUpClass(cls) -> None:
        if not os.environ.get("LLM_API_URL"):
            raise unittest.SkipTest("LLM_API_URL is required for live golden evals")

    def test_live_analyzer_meets_golden_rubric(self) -> None:
        client = LocalLLMClient(
            config=load_config(), ttp_validator=_DummyValidator()
        )

        for case in load_manifest():
            with self.subTest(case_id=case.id):
                alert = load_json(case.alert_path)
                alert_text = json.dumps(alert, ensure_ascii=True, separators=(",", ":"))
                result = client.analyze_alert(
                    alert_text, alert_time=str(alert.get("event_time") or "")
                )
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
