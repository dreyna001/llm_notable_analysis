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
            "PortalAuthMode=jwt",
            "PortalRequiredAnalystRole",
            "deploy/aws/presets/customer-default.env.example",
            "VPC_NETWORK_PREREQUISITES.md",
            "OPENSEARCH_PROVISIONING.md",
            "PORTAL_JWT_IDENTITY.md",
            "BEDROCK_ACCOUNT_ENABLEMENT.md",
            "spl_readonly",
            "OpenSearchSocIndex",
            "soc_knowledge",
            "splunk_dictionary",
            "case_chunks",
        ):
            self.assertIn(snippet, preset_doc)

        env_example = (
            PROJECT_ROOT / "deploy/aws/presets/customer-default.env.example"
        ).read_text(encoding="utf-8")
        self.assertIn("RagIngestionEnabled=true", env_example)
        self.assertIn("PortalEnabled=true", env_example)
        self.assertIn("PortalRequiredAnalystRole", env_example)
        self.assertIn("COMMERCIAL_AWS_ACCOUNT_ID", env_example)
        self.assertIn("AwsAccountId=\"$AWS_ACCOUNT_ID\"", env_example)

        samconfig = (
            PROJECT_ROOT / "deploy/aws/presets/samconfig.customer-default.toml.example"
        ).read_text(encoding="utf-8")
        self.assertIn("PortalRequiredAnalystRole", samconfig)
        self.assertIn("PortalAuthMode=jwt", samconfig)

    def test_customer_default_account_variables_are_consistent(self) -> None:
        preset_doc = (
            PROJECT_ROOT
            / "docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md"
        ).read_text(encoding="utf-8")
        env_example = (
            PROJECT_ROOT / "deploy/aws/presets/customer-default.env.example"
        ).read_text(encoding="utf-8")

        self.assertIn("AWS_ACCOUNT_ID", preset_doc)
        self.assertIn("COMMERCIAL_AWS_ACCOUNT_ID", preset_doc)
        self.assertNotIn(
            "AwsAccountId=\"$COMMERCIAL_AWS_ACCOUNT_ID\"",
            preset_doc,
        )
        self.assertIn("AwsAccountId=\"$AWS_ACCOUNT_ID\"", preset_doc)
        self.assertIn("AWS_ACCOUNT_ID=", env_example)
        self.assertIn("COMMERCIAL_AWS_ACCOUNT_ID=", env_example)

    def test_customer_default_jwt_grant_is_wired_in_preset_workflow(self) -> None:
        preset_doc = (
            PROJECT_ROOT
            / "docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md"
        ).read_text(encoding="utf-8")
        env_example = (
            PROJECT_ROOT / "deploy/aws/presets/customer-default.env.example"
        ).read_text(encoding="utf-8")
        samconfig = (
            PROJECT_ROOT / "deploy/aws/presets/samconfig.customer-default.toml.example"
        ).read_text(encoding="utf-8")

        self.assertIn("PortalRequiredAnalystRole=\"$PORTAL_REQUIRED_ANALYST_ROLE\"", preset_doc)
        self.assertIn("PortalRequiredAnalystScope=\"$PORTAL_REQUIRED_ANALYST_SCOPE\"", preset_doc)
        self.assertIn("PortalRequiredAnalystRole", env_example)
        self.assertIn("PORTAL_REQUIRED_ANALYST_SCOPE=", env_example)
        self.assertIn("PortalRequiredAnalystRole", samconfig)
        self.assertIn("PortalAuthMode=jwt", samconfig)

    def test_customer_default_optional_kms_is_wired_in_env_workflow(self) -> None:
        preset_doc = (
            PROJECT_ROOT
            / "docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md"
        ).read_text(encoding="utf-8")
        env_example = (
            PROJECT_ROOT / "deploy/aws/presets/customer-default.env.example"
        ).read_text(encoding="utf-8")

        self.assertIn("CustomerKmsKeyArn=\"$CUSTOMER_KMS_KEY_ARN\"", preset_doc)
        self.assertIn("CUSTOMER_KMS_KEY_ARN=", env_example)
        self.assertIn("OpenSearch Phase B", preset_doc)

    def test_shipped_capability_status_is_not_stale_in_scope_doc(self) -> None:
        scope_doc = (
            PROJECT_ROOT
            / "docs/operations/deployment/CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md"
        ).read_text(encoding="utf-8")
        stale_claims = (
            "Closed-ticket ServiceNow sync + closed-ticket RAG | Not shipped",
            "RAG_RERANK_ENABLED` not wired",
            "AWS backlog",
            "text/json/md/txt/csv only",
        )
        for claim in stale_claims:
            self.assertNotIn(claim, scope_doc)

        for shipped_marker in (
            "P1–P8 parity code is **shipped**",
            "Bedrock rerank",
            "Rich KB ingest",
            "Closed-ticket ServiceNow sync",
            "Portal chat image uploads",
        ):
            self.assertIn(shipped_marker, scope_doc)

    def test_opensearch_index_defaults_match_across_contracts(self) -> None:
        index_defaults = {
            "soc_knowledge": ("OPENSEARCH_SOC_INDEX", "OpenSearchSocIndex"),
            "splunk_dictionary": ("OPENSEARCH_SPLUNK_INDEX", "OpenSearchSplunkIndex"),
            "case_chunks": ("OPENSEARCH_CASE_INDEX", "OpenSearchCaseIndex"),
        }
        config_env = (PROJECT_ROOT / "config.env.example").read_text(encoding="utf-8")
        preset_env = (
            PROJECT_ROOT / "deploy/aws/presets/customer-default.env.example"
        ).read_text(encoding="utf-8")
        samconfig = (
            PROJECT_ROOT / "deploy/aws/presets/samconfig.customer-default.toml.example"
        ).read_text(encoding="utf-8")

        for index_name, (env_key, sam_key) in index_defaults.items():
            self.assertIn(f"{env_key}={index_name}", config_env)
            self.assertIn(f"{env_key}={index_name}", preset_env)
            self.assertIn(f"{sam_key}={index_name}", samconfig)

        stale_indexes = (
            "notable-case-chunks",
            "notable-soc-knowledge",
            "notable-splunk-dictionary",
        )
        for stale in stale_indexes:
            self.assertNotIn(stale, config_env)
            self.assertNotIn(stale, preset_env)

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

    def test_root_readme_owns_deploy_paths_and_docs_readme_indexes_runbooks(
        self,
    ) -> None:
        hub = (PROJECT_ROOT / "docs/README.md").read_text(encoding="utf-8")
        for snippet in (
            "Deploy journey (Path A/B/C)",
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
        self.assertIn("Deploy — pick one path", root_readme)
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
            "COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md",
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
