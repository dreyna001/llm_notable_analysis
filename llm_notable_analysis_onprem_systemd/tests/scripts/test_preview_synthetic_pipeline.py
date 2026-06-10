"""Tests for preview synthetic pipeline fixtures."""

from __future__ import annotations

import json
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
    PREVIEW_ALERT_SPECS,
    load_preview_bundle,
    preview_bundle_path,
    preview_scenario_count,
    prepare_preview_analysis,
)

from llm_notable_analysis_onprem_systemd.onprem_service.config import Config  # noqa: E402
from llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client import (  # noqa: E402
    validate_response_schema,
)


class TestPreviewSyntheticPipeline(unittest.TestCase):
    def test_preview_alert_fixtures_exist(self) -> None:
        self.assertEqual(preview_scenario_count(), 5)
        for spec in PREVIEW_ALERT_SPECS:
            self.assertTrue(spec.alert_path.is_file(), msg=str(spec.alert_path))
            payload = json.loads(spec.alert_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["search_name"], spec.search_name)

    def test_cached_bundles_validate_when_present(self) -> None:
        for spec in PREVIEW_ALERT_SPECS:
            bundle_path = preview_bundle_path(spec.index)
            if not bundle_path.is_file():
                self.skipTest(
                    f"bundle missing: {bundle_path}; run generate_preview_scenarios.py"
                )
            bundle = load_preview_bundle(spec.index)
            analysis = bundle["analysis"]
            ok, err = validate_response_schema(analysis)
            self.assertTrue(ok, msg=f"case-{spec.index}: {err}")
            self.assertEqual(len(analysis["competing_hypotheses"]), 6)

    def test_prepare_preview_analysis_tags_metadata(self) -> None:
        if not preview_bundle_path(1).is_file():
            self.skipTest("bundle missing for case-1")
        bundle = json.loads(preview_bundle_path(1).read_text(encoding="utf-8"))
        analysis = prepare_preview_analysis(bundle["analysis"])
        self.assertTrue(analysis["metadata"]["preview_synthetic"])


if __name__ == "__main__":
    unittest.main()
