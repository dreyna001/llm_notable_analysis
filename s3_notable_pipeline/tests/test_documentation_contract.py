"""GovCloud operator documentation contract tests."""

from __future__ import annotations

import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DocumentationContractTests(unittest.TestCase):
    """Operator docs must reference GovCloud provisioning runbooks."""

    def test_prerequisite_runbooks_exist(self) -> None:
        expected = (
            "docs/operations/deployment/OPENSEARCH_PROVISIONING.md",
            "docs/operations/deployment/VPC_NETWORK_PREREQUISITES.md",
            "docs/operations/deployment/BEDROCK_ACCOUNT_ENABLEMENT.md",
            "docs/operations/deployment/KMS_CUSTOMER_KEY.md",
            "docs/operations/deployment/PORTAL_JWT_IDENTITY.md",
            "docs/operations/deployment/CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md",
            "docs/operations/deployment/GOVCLOUD_CUSTOMER_DEFAULT_DEPLOYMENT.md",
        )
        for relative_path in expected:
            self.assertTrue((PROJECT_ROOT / relative_path).is_file(), relative_path)

    def test_opensearch_provisioning_doc_exists(self) -> None:
        path = PROJECT_ROOT / "docs/operations/deployment/OPENSEARCH_PROVISIONING.md"
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        for snippet in (
            "us-gov-east-1",
            "aws-us-gov",
            "OpenSearchDomainArn",
            "ensure_vector_index",
        ):
            self.assertIn(snippet, text)

    def test_deploy_and_rag_docs_link_opensearch_provisioning(self) -> None:
        linked_paths = (
            PROJECT_ROOT / "docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md",
            PROJECT_ROOT / "docs/operations/rag/RAG_OPERATIONS.md",
            PROJECT_ROOT / "docs/operations/rag/KNOWLEDGE_BASE_OPERATIONS.md",
        )
        for path in linked_paths:
            self.assertIn(
                "OPENSEARCH_PROVISIONING.md",
                path.read_text(encoding="utf-8"),
                msg=str(path.relative_to(PROJECT_ROOT)),
            )

    def test_root_readme_owns_deploy_paths_and_docs_readme_indexes_runbooks(
        self,
    ) -> None:
        hub = (PROJECT_ROOT / "docs/README.md").read_text(encoding="utf-8")
        for snippet in (
            "Deploy journey (Path A/B/C)",
            "GOVCLOUD_CUSTOMER_DEFAULT_DEPLOYMENT.md",
            "VPC_NETWORK_PREREQUISITES.md",
            "OPENSEARCH_PROVISIONING.md",
            "BEDROCK_ACCOUNT_ENABLEMENT.md",
            "PORTAL_JWT_IDENTITY.md",
            "KMS_CUSTOMER_KEY.md",
            "CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md",
            "us-gov-east-1",
        ):
            self.assertIn(snippet, hub)

        root_readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/README.md", root_readme)
        self.assertIn("Deploy — pick one path", root_readme)
        self.assertIn("aws-us-gov", root_readme)
        for path_heading in (
            "Path A — Core only",
            "Path B — Customer-default",
            "Path C — Custom profiles",
        ):
            self.assertIn(path_heading, root_readme)
        for path_b_step in (
            "KMS_CUSTOMER_KEY.md",
            "VPC_NETWORK_PREREQUISITES.md",
            "OPENSEARCH_PROVISIONING.md",
            "PORTAL_JWT_IDENTITY.md",
            "GOVCLOUD_CUSTOMER_DEFAULT_DEPLOYMENT.md",
            "KNOWLEDGE_BASE_OPERATIONS.md",
            "ANALYST_PORTAL_OPERATIONS.md",
            "docs/testing/TESTING.md",
        ):
            self.assertIn(path_b_step, root_readme)

        deployment_docs = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (PROJECT_ROOT / "docs/operations/deployment").glob("*.md")
        )
        self.assertNotIn("#path-a--", deployment_docs)
        self.assertNotIn("#path-b--", deployment_docs)
        self.assertNotIn("#path-c--", deployment_docs)


if __name__ == "__main__":
    unittest.main()
