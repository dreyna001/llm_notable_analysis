"""Tests for the vendored portal OpenAPI contract."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = PROJECT_ROOT / "docs" / "contracts" / "portal.openapi.json"


class PortalOpenApiContractTests(unittest.TestCase):
    """OpenAPI contract shape tests."""

    def test_required_paths_are_present(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

        self.assertEqual(contract["openapi"], "3.0.3")
        for path in (
            "/health",
            "/ready",
            "/api/capabilities",
            "/api/cases",
            "/api/cases/{case_id}",
            "/api/cases/{case_id}/raw/{section}",
            "/api/chat",
        ):
            self.assertIn(path, contract["paths"])


if __name__ == "__main__":
    unittest.main()
