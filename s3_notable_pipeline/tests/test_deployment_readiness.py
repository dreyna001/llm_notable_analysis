"""Contract tests for the GovCloud deployment readiness report."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "deployment_readiness.py"
SPEC = importlib.util.spec_from_file_location("deployment_readiness", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DeploymentReadinessTests(unittest.TestCase):
    def valid_values(self) -> dict[str, str]:
        values = {key: "value" for key in MODULE.REQUIRED_KEYS}
        values.update(
            AWS_ACCOUNT_ID="123456789012",
            IMAGE_DIGEST="sha256:" + "a" * 64,
            PORTAL_JWT_ISSUER="https://idp.example.test/",
        )
        return values

    def test_valid_values_pass_and_placeholders_fail(self) -> None:
        values = self.valid_values()
        self.assertEqual([], MODULE.validate_values(values))
        values["RAG_TENANT_ID"] = "<tenant-id>"
        self.assertIn("placeholder remains: RAG_TENANT_ID", MODULE.validate_values(values))

    def test_main_writes_machine_readable_blocked_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_path = root / "customer-default.env"
            env_path.write_text("AWS_ACCOUNT_ID=bad\n", encoding="utf-8")
            report_path = root / "report.json"
            code = MODULE.main([
                "--env-file", str(env_path), "--report-out", str(report_path),
                "--skip-sam-validation",
            ])
            report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(1, code)
        self.assertEqual("blocked", report["status"])
        self.assertEqual("aws-us-gov", report["target"]["partition"])


if __name__ == "__main__":
    unittest.main()
