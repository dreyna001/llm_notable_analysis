"""Azure Government operator documentation contract tests."""

from __future__ import annotations

import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DocumentationContractTests(unittest.TestCase):
    """Operator docs must expose Azure Government deploy journeys."""

    def test_prerequisite_runbooks_exist(self) -> None:
        expected = (
            "docs/operations/deployment/AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md",
            "docs/operations/deployment/AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md",
            "docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md",
            "docs/operations/deployment/AZURE_UPGRADE_AND_ROLLBACK.md",
            "docs/operations/ANALYST_PORTAL_DEPLOYMENT.md",
            "docs/operations/testing/AZURE_GOVERNMENT_TESTING.md",
        )
        for relative_path in expected:
            self.assertTrue((PROJECT_ROOT / relative_path).is_file(), relative_path)

    def test_root_readme_owns_deploy_paths_and_docs_readme_indexes_runbooks(
        self,
    ) -> None:
        hub = (PROJECT_ROOT / "docs/README.md").read_text(encoding="utf-8")
        for snippet in (
            "Deploy journey (Path A/B/C)",
            "AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md",
            "AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md",
            "DEPLOYMENT_IMAGE_STEPS.md",
            "ANALYST_PORTAL_DEPLOYMENT.md",
            "AZURE_GOVERNMENT_TESTING.md",
            "AZURE_UPGRADE_AND_ROLLBACK.md",
        ):
            self.assertIn(snippet, hub)

        root_readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/README.md", root_readme)
        self.assertIn("Deploy — pick one path", root_readme)
        self.assertIn("usgovvirginia", root_readme)
        for path_heading in (
            "Path A — Core only",
            "Path B — Customer-default",
            "Path C — Custom profiles",
        ):
            self.assertIn(path_heading, root_readme)
        for path_b_step in (
            "AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md",
            "LLM_INFERENCE_OPERATIONS.md",
            "KNOWLEDGE_BASE_OPERATIONS.md",
            "ANALYST_PORTAL_DEPLOYMENT.md",
            "DEPLOYMENT_IMAGE_STEPS.md",
            "AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md",
            "ANALYST_PORTAL_OPERATIONS.md",
            "AZURE_AI_SEARCH_RAG_INGESTION.md",
            "docs/operations/testing/AZURE_GOVERNMENT_TESTING.md",
        ):
            self.assertIn(path_b_step, root_readme)

        deployment_docs = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (PROJECT_ROOT / "docs/operations/deployment").glob("*.md")
        )
        self.assertNotIn("#path-a--", deployment_docs)
        self.assertNotIn("#path-b--", deployment_docs)
        self.assertNotIn("#path-c--", deployment_docs)

    def test_customer_default_smoke_links_government_testing(self) -> None:
        preset = (
            PROJECT_ROOT
            / "docs/operations/deployment/AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md"
        ).read_text(encoding="utf-8")
        self.assertIn("AZURE_GOVERNMENT_TESTING.md", preset)
        self.assertNotIn("testing/TESTING.md", preset)

    def test_customer_deployment_readiness_contract_is_documented(self) -> None:
        preset = (
            PROJECT_ROOT
            / "docs/operations/deployment/AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md"
        ).read_text(encoding="utf-8")
        customer_config = (
            PROJECT_ROOT
            / "docs/operations/deployment/AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md"
        ).read_text(encoding="utf-8")
        upgrade = (
            PROJECT_ROOT
            / "docs/operations/deployment/AZURE_UPGRADE_AND_ROLLBACK.md"
        ).read_text(encoding="utf-8")
        live_gate = (
            PROJECT_ROOT / "docs/operations/testing/AZURE_GOVERNMENT_TESTING.md"
        ).read_text(encoding="utf-8")

        for snippet in (
            "Azure Resource Manager to validate",
            "DEPLOYMENT_REPORT_PATH",
            "sanitized JSON result",
        ):
            self.assertIn(snippet, preset)
        self.assertIn("## Who owns what", customer_config)
        self.assertIn("Customer owns", customer_config)
        self.assertIn("Product deployment owns", customer_config)
        for snippet in (
            "## Before the change",
            "## Upgrade",
            "## Rollback",
            "last qualified",
        ):
            self.assertIn(snippet, upgrade)
        self.assertIn("## Required live-cloud release gate", live_gate)
        for live_boundary in (
            "Managed identity and RBAC",
            "Private networking and DNS",
            "Failure and recovery",
            "Upgrade and rollback",
        ):
            self.assertIn(live_boundary, live_gate)


if __name__ == "__main__":
    unittest.main()
