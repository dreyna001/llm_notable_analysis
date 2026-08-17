"""On-prem operator documentation contract tests."""

from __future__ import annotations

import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DocumentationContractTests(unittest.TestCase):
    """Operator docs must expose on-prem deploy journeys."""

    def test_prerequisite_runbooks_exist(self) -> None:
        expected = (
            "docs/operations/deployment/INSTALL.md",
            "docs/operations/deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md",
            "docs/operations/deployment/HOST_LAYOUT_AND_UPDATES.md",
            "docs/operations/deployment/OFFLINE_PRESTAGE_GUIDE.md",
            "docs/operations/deployment/AIRGAPPED_DEPLOYMENT.md",
            "docs/operations/integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md",
            "docs/testing/TESTING.md",
        )
        for relative_path in expected:
            self.assertTrue((PROJECT_ROOT / relative_path).is_file(), relative_path)

    def test_root_readme_owns_deploy_paths_and_docs_readme_indexes_runbooks(
        self,
    ) -> None:
        hub = (PROJECT_ROOT / "docs/README.md").read_text(encoding="utf-8")
        for snippet in (
            "Deploy journey (Path A/B/C)",
            "CUSTOMER_DEFAULT_DEPLOYMENT.md",
            "HOST_LAYOUT_AND_UPDATES.md",
            "INSTALL.md",
            "OFFLINE_PRESTAGE_GUIDE.md",
            "SERVICENOW_CLOSED_TICKET_OPERATIONS.md",
            "TESTING.md",
        ):
            self.assertIn(snippet, hub)

        root_readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/README.md", root_readme)
        self.assertIn("Deploy — pick one path", root_readme)
        self.assertIn("onprem-llm-sdk", root_readme)
        for path_heading in (
            "Path A — Core only",
            "Path B — Customer-default",
            "Path C — Custom profiles",
        ):
            self.assertIn(path_heading, root_readme)
        for path_b_step in (
            "HOST_LAYOUT_AND_UPDATES.md",
            "OFFLINE_PRESTAGE_GUIDE.md",
            "INSTALL.md",
            "CUSTOMER_DEFAULT_DEPLOYMENT.md",
            "KNOWLEDGE_BASE_OPERATIONS.md",
            "SERVICENOW_CLOSED_TICKET_OPERATIONS.md",
            "ANALYST_PORTAL_NETWORK_DEPLOYMENT.md",
            "deployment_profiles/README.md",
            "docs/testing/TESTING.md",
        ):
            self.assertIn(path_b_step, root_readme)

        for bad_heading in (
            "Path A -- Core",
            "Path B -- Customer",
            "Path C -- Custom",
        ):
            self.assertNotIn(bad_heading, root_readme)

    def test_customer_default_links_testing_terminus(self) -> None:
        preset = (
            PROJECT_ROOT
            / "docs/operations/deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md"
        ).read_text(encoding="utf-8")
        self.assertIn("TESTING.md", preset)
        self.assertIn("## Next", preset)


if __name__ == "__main__":
    unittest.main()
