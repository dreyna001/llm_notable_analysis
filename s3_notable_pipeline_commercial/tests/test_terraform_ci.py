"""Static contracts for the repository Terraform CI gate."""

from __future__ import annotations

import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPOSITORY_ROOT / "s3_notable_pipeline_commercial"


class TerraformCiTests(unittest.TestCase):
    def test_tool_versions_are_pinned(self) -> None:
        requirements = (PROJECT_ROOT / "requirements-terraform.txt").read_text(
            encoding="utf-8"
        )
        workflow = (REPOSITORY_ROOT / ".github/workflows/terraform.yml").read_text(
            encoding="utf-8"
        )

        self.assertEqual(requirements.strip(), "checkov==3.3.16")
        self.assertIn("terraform_version: 1.15.9", workflow)

    def test_local_gate_checks_every_required_layer(self) -> None:
        script = (PROJECT_ROOT / "scripts/check-terraform.sh").read_text(
            encoding="utf-8"
        )
        for required in (
            "terraform fmt -check -recursive",
            "init -backend=false -input=false",
            "validate",
            "test_terraform_modules",
            "test_opensearch_terraform",
            "test_path_b_deploy_configurator",
            "test_deploy_scripts",
            "test_documentation_contract",
            "checkov",
            "--framework terraform",
            "--skip-download",
            "--quiet",
        ):
            self.assertIn(required, script)
        self.assertNotIn("--soft-fail", script)

    def test_pull_requests_run_the_reusable_gate(self) -> None:
        workflow = (REPOSITORY_ROOT / ".github/workflows/terraform.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("pull_request:", workflow)
        self.assertNotIn("paths:", workflow)
        self.assertIn("terraform_wrapper: false", workflow)
        self.assertIn(
            "bash s3_notable_pipeline_commercial/scripts/check-terraform.sh", workflow
        )


if __name__ == "__main__":
    unittest.main()
