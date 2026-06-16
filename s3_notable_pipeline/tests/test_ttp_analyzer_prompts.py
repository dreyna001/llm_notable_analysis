"""Tests for TTP analyzer prompt contract text."""
# pylint: disable=import-error,no-name-in-module

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from s3_notable_pipeline.ttp_analyzer import (
    BedrockAnalyzer,
    REPAIR_PROMPT_TEMPLATE,
    REPAIR_PROMPT_TEMPLATE_RAW_JSON,
)


class TTPAnalyzerPromptTests(unittest.TestCase):
    """Prompt layout and repair-template contract tests."""

    def setUp(self) -> None:
        with patch("s3_notable_pipeline.ttp_analyzer.boto3.client"):
            self.analyzer = BedrockAnalyzer(model_id="test-model")

    def test_build_prompt_is_contract_first_for_tool_mode(self) -> None:
        prompt = self.analyzer._build_prompt(
            "user=alice index=main",
            "2026-01-01T00:00:00Z",
            use_tool=True,
            advisory_context="Use index main for pivots.",
        )

        self.assertLess(prompt.index("TASK:"), prompt.index("ANALYST DOCTRINE"))
        self.assertLess(prompt.index("OUTPUT CONTRACT:"), prompt.index("ANALYST DOCTRINE"))
        self.assertIn("SOC CONTEXT RULES:", prompt)
        self.assertIn("likely_true_positive", prompt)
        self.assertIn("Direct alert evidence must come only from SECURITY ALERT INPUT", prompt)

    def test_build_prompt_is_contract_first_for_raw_json_mode(self) -> None:
        prompt = self.analyzer._build_prompt(
            "user=alice index=main",
            None,
            use_tool=False,
        )

        self.assertIn("OUTPUT CONTRACT:", prompt)
        self.assertIn("SOC_OPERATIONAL_CONTEXT\n(none)", prompt)
        self.assertIn("likely_false_positive", prompt)

    def test_repair_templates_are_contract_aware(self) -> None:
        self.assertIn("{contract}", REPAIR_PROMPT_TEMPLATE)
        self.assertIn("{contract}", REPAIR_PROMPT_TEMPLATE_RAW_JSON)
        self.assertIn("Do not add facts", REPAIR_PROMPT_TEMPLATE_RAW_JSON)
        self.assertIn("analyze_notable tool", REPAIR_PROMPT_TEMPLATE)


if __name__ == "__main__":
    unittest.main()
