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
            "docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md",
            "docs/operations/deployment/OPENSEARCH_PROVISIONING.md",
            "docs/operations/deployment/VPC_NETWORK_PREREQUISITES.md",
            "docs/operations/deployment/BEDROCK_ACCOUNT_ENABLEMENT.md",
            "docs/operations/deployment/KMS_CUSTOMER_KEY.md",
            "docs/operations/deployment/PORTAL_JWT_IDENTITY.md",
            "docs/operations/deployment/CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md",
            "docs/planning/AWS_COMMERCIAL_READINESS_PLAN.md",
            "docs/internal/AWS_COMMERCIAL_DEFERRED_GAPS.md",
            "deploy/aws/presets/customer-default.env.example",
            "deploy/aws/presets/samconfig.customer-default.toml.example",
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

    def test_deploy_docs_use_ecr_digest_contract(self) -> None:
        deploy_docs = (
            PROJECT_ROOT / "README.md",
            PROJECT_ROOT / "docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md",
            PROJECT_ROOT / "docs/delivery_package/AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md",
            PROJECT_ROOT / "docs/delivery_package/AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_OVERVIEW.md",
            PROJECT_ROOT / "docs/delivery_package/end_to_end_diagrams/END_TO_END_DIAGRAMS.md",
        )
        forbidden = re.compile(r"\bImageUri\b")
        findings: list[str] = []
        for path in deploy_docs:
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                if forbidden.search(line):
                    findings.append(f"{path.relative_to(PROJECT_ROOT)}:{line_number}")
        self.assertEqual(findings, [])

        required_snippets = (
            "EcrRepositoryUri",
            "ImageDigest",
            "BedrockAnalysisModelArn",
        )
        steps = (PROJECT_ROOT / "docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md").read_text(
            encoding="utf-8"
        )
        for snippet in required_snippets:
            self.assertIn(snippet, steps)

    def test_customer_default_preset_documents_core_bundle(self) -> None:
        preset_doc = (
            PROJECT_ROOT
            / "docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md"
        ).read_text(encoding="utf-8")
        for snippet in (
            "CapabilityProfiles=core,rag,analyst_portal",
            "SplQueryRagEnabled=true",
            "deploy/aws/presets/customer-default.env.example",
            "VPC_NETWORK_PREREQUISITES.md",
            "OPENSEARCH_PROVISIONING.md",
            "PORTAL_JWT_IDENTITY.md",
            "BEDROCK_ACCOUNT_ENABLEMENT.md",
            "spl_readonly",
        ):
            self.assertIn(snippet, preset_doc)

        env_example = (
            PROJECT_ROOT / "deploy/aws/presets/customer-default.env.example"
        ).read_text(encoding="utf-8")
        self.assertIn("RagIngestionEnabled=true", env_example)
        self.assertIn("PortalEnabled=true", env_example)

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

    def test_docs_readme_lists_deploy_paths(self) -> None:
        hub = (PROJECT_ROOT / "docs/README.md").read_text(encoding="utf-8")
        for snippet in (
            "Choose your deploy path",
            "Path A",
            "Path B",
            "Path C",
            "VPC_NETWORK_PREREQUISITES.md",
            "OPENSEARCH_PROVISIONING.md",
            "BEDROCK_ACCOUNT_ENABLEMENT.md",
            "PORTAL_JWT_IDENTITY.md",
            "KMS_CUSTOMER_KEY.md",
            "CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md",
            "COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md",
        ):
            self.assertIn(snippet, hub)

        root_readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/README.md", root_readme)
        self.assertIn("Choose your path", root_readme)


if __name__ == "__main__":
    unittest.main()
