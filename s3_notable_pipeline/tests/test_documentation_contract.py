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

    def test_docs_readme_lists_deploy_paths(self) -> None:
        hub = (PROJECT_ROOT / "docs/README.md").read_text(encoding="utf-8")
        for snippet in (
            "Choose your deploy path",
            "Path A",
            "Path B",
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
        self.assertIn("Choose your path", root_readme)


if __name__ == "__main__":
    unittest.main()
