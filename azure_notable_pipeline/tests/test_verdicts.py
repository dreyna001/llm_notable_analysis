"""Tests for stable analyzer verdict normalization."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from azure_notable_pipeline.verdicts import normalize_verdict  # pylint: disable=import-error


class VerdictNormalizationTests(unittest.TestCase):
    """Legacy and model verdict strings map to the on-prem enum."""

    def test_normalize_verdict_maps_legacy_values_to_stable_enum(self) -> None:
        self.assertEqual(normalize_verdict("likely malicious"), "likely_malicious")
        self.assertEqual(normalize_verdict("likely_true_positive"), "likely_malicious")
        self.assertEqual(normalize_verdict("false positive"), "likely_benign")
        self.assertEqual(normalize_verdict("likely_false_positive"), "likely_benign")
        self.assertEqual(normalize_verdict("needs review"), "unknown")


if __name__ == "__main__":
    unittest.main()
