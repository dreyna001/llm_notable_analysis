"""Commercial product identity and documentation contract tests."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DocumentationContractTests(unittest.TestCase):
    """Operator documentation must describe the independent commercial product."""

    def test_commercial_document_renames_and_links_are_complete(self) -> None:
        expected = (
            "docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md",
            "docs/planning/AWS_COMMERCIAL_READINESS_PLAN.md",
            "docs/internal/AWS_COMMERCIAL_DEFERRED_GAPS.md",
        )
        retired = (
            "docs/operations/deployment/GOVCLOUD_CUSTOMER_CONFIGURATION.md",
            "docs/planning/AWS_GOVCLOUD_READINESS_PLAN.md",
            "docs/internal/AWS_GOVCLOUD_DEFERRED_GAPS.md",
        )
        for relative_path in expected:
            self.assertTrue((PROJECT_ROOT / relative_path).is_file(), relative_path)
        for relative_path in retired:
            self.assertFalse((PROJECT_ROOT / relative_path).exists(), relative_path)

        operator_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (PROJECT_ROOT / "docs").rglob("*.md")
            if path.name != "COMMERCIAL_AWS_FORK_PLAN.md"
        )
        for retired_name in (Path(path).name for path in retired):
            self.assertNotIn(retired_name, operator_text)

    def test_operator_surface_has_no_govcloud_runtime_identity(self) -> None:
        paths = (
            PROJECT_ROOT / "README.md",
            PROJECT_ROOT / "config.env.example",
            PROJECT_ROOT / "deploy",
            PROJECT_ROOT / "scripts",
            PROJECT_ROOT / "src",
            PROJECT_ROOT / "docs",
        )
        forbidden = re.compile(r"govcloud|aws-us-gov|us-gov-", re.IGNORECASE)
        findings: list[str] = []
        for root in paths:
            candidates = (root,) if root.is_file() else root.rglob("*")
            for path in candidates:
                if not path.is_file() or path.name == "COMMERCIAL_AWS_FORK_PLAN.md":
                    continue
                if path.suffix.lower() not in {".md", ".py", ".sh", ".ps1", ".yaml", ".yml"}:
                    continue
                for line_number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), start=1
                ):
                    if forbidden.search(line):
                        findings.append(f"{path.relative_to(PROJECT_ROOT)}:{line_number}")
        self.assertEqual(findings, [])

    def test_commercial_service_decisions_are_recorded(self) -> None:
        register = (
            PROJECT_ROOT / "docs/internal/COMMERCIAL_AWS_APPROVED_DIFFERENCES.md"
        ).read_text(encoding="utf-8")
        for decision in (
            "API Gateway",
            "Lambda Function URLs",
            "CloudFront",
            "OpenSearch",
            "Bedrock Knowledge Bases",
            "S3 Vectors",
        ):
            self.assertIn(decision, register)


if __name__ == "__main__":
    unittest.main()
