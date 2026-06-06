"""Tests for preview portal proxy-auth verification helpers."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from preview_portal_ui import (  # noqa: E402
    verify_preview_portal_auth,
)


class PreviewPortalAuthVerificationTests(unittest.TestCase):
    def test_verify_preview_portal_auth_passes(self) -> None:
        checks = verify_preview_portal_auth()
        self.assertGreaterEqual(len(checks), 5)
        failures = [name for name, passed, _detail in checks if not passed]
        self.assertEqual(failures, [], f"auth checks failed: {failures}")


if __name__ == "__main__":
    unittest.main()
