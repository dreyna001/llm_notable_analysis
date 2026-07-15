"""Deployment template contract tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode, SequenceNode

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


class CfnLoader(yaml.SafeLoader):
    """Loader that tolerates CloudFormation intrinsic tags."""


def _construct_intrinsic(loader: CfnLoader, _suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, MappingNode):
        return loader.construct_mapping(node)
    if isinstance(node, SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_scalar(node)


CfnLoader.add_multi_constructor("!", _construct_intrinsic)


def load_template(path: str) -> dict[str, Any]:
    """Load a CloudFormation/SAM template."""

    source = (PROJECT_ROOT / path).read_text(encoding="utf-8")
    node = yaml.compose(source, Loader=CfnLoader)
    _assert_no_duplicate_mapping_keys(node, path=path)
    template = yaml.load(source, Loader=CfnLoader)
    if not isinstance(template, dict):
        raise AssertionError(f"{path} did not parse as a mapping")
    return template


def _assert_no_duplicate_mapping_keys(node: yaml.Node | None, *, path: str) -> None:
    if isinstance(node, MappingNode):
        seen: set[str] = set()
        for key_node, value_node in node.value:
            key = str(getattr(key_node, "value", ""))
            if key in seen:
                raise AssertionError(f"{path} contains duplicate mapping key: {key}")
            seen.add(key)
            _assert_no_duplicate_mapping_keys(value_node, path=path)
    elif isinstance(node, SequenceNode):
        for child in node.value:
            _assert_no_duplicate_mapping_keys(child, path=path)


class DeployTemplateTests(unittest.TestCase):
    """Template synchronization tests."""

    def test_portal_ui_uses_private_s3_behind_regional_api(self) -> None:
        for path in (
            "deploy/aws/template-sam.yaml",
            "deploy/aws/template-cfn.yaml",
        ):
            with self.subTest(path=path):
                template = load_template(path)
                self.assertIn("PortalUiBucketName", template["Parameters"])
                self.assertIn("HasPortalUiDeployment", template["Conditions"])
                self.assertIn("PortalUiBucket", template["Resources"])
                self.assertIn("PortalHttpApiStaticRoute", template["Resources"])
                self.assertIn("PortalHttpApiStaticRootRoute", template["Resources"])
                self.assertIn("PortalUiBucketName", template["Outputs"])
                self.assertNotIn("PortalUiDistribution", template["Resources"])
                self.assertNotIn("PortalHttpApiStaticIntegration", template["Resources"])
                self.assertNotIn("S3-GetObject", (PROJECT_ROOT / path).read_text(encoding="utf-8"))

    def test_portal_front_door_resources_are_present(self) -> None:
        for path in (
            "deploy/aws/template-sam.yaml",
            "deploy/aws/template-cfn.yaml",
        ):
            with self.subTest(path=path):
                template = load_template(path)
                self.assertIn("HasPortalJwtAuthorizer", template["Conditions"])
                self.assertIn("IsPortalIamAuth", template["Conditions"])
                self.assertIn("PortalHttpApi", template["Resources"])
                self.assertIn("PortalHttpApiIntegration", template["Resources"])
                self.assertIn("PortalHttpApiDefaultRoute", template["Resources"])
                self.assertIn("PortalHttpApiStage", template["Resources"])
                self.assertIn("PortalHttpApiInvokePermission", template["Resources"])
                self.assertIn("PortalApiUrl", template["Outputs"])
                self.assertIn("PortalBrowserApiBaseUrl", template["Outputs"])
                self.assertNotIn("PortalApiFunctionUrl", template["Resources"])
                self.assertNotIn("PortalChatFunctionUrl", template["Outputs"])
                self.assertEqual(template["Parameters"]["PortalChatTimeoutSec"]["Default"], 29)
                self.assertEqual(template["Parameters"]["PortalChatTimeoutSec"]["MaxValue"], 29)
                self.assertEqual(
                    template["Resources"]["PortalHttpApiIntegration"]["Properties"]["TimeoutInMillis"],
                    29000,
                )

    def test_govcloud_queues_and_opensearch_contracts_are_wired(self) -> None:
        for path in (
            "deploy/aws/template-sam.yaml",
            "deploy/aws/template-cfn.yaml",
        ):
            with self.subTest(path=path):
                template = load_template(path)
                parameters = template["Parameters"]
                resources = template["Resources"]
                self.assertEqual(parameters["DeploymentRegion"]["Default"], "us-gov-east-1")
                self.assertIn("OpenSearchEndpoint", parameters)
                self.assertIn("OpenSearchDomainArn", parameters)
                self.assertIn("RagTenantId", parameters)
                for resource in (
                    "AnalyzerQueue",
                    "AnalyzerDeadLetterQueue",
                    "AnalyzerOldestMessageAlarm",
                    "AnalyzerErrorAlarm",
                    "EmbedQueue",
                    "EmbedDeadLetterQueue",
                    "EmbedDlqAlarm",
                    "EmbedErrorAlarm",
                    "RagIngestionQueue",
                    "RagIngestionDeadLetterQueue",
                    "RagIngestionOldestMessageAlarm",
                    "RagIngestionFunction",
                    "PortalErrorAlarm",
                ):
                    self.assertIn(resource, resources)

                expected_types = {
                    "AnalyzerQueue": "AWS::SQS::Queue",
                    "EmbedQueue": "AWS::SQS::Queue",
                    "RagIngestionQueue": "AWS::SQS::Queue",
                    "RagIngestionFunction": (
                        "AWS::Serverless::Function"
                        if path.endswith("template-sam.yaml")
                        else "AWS::Lambda::Function"
                    ),
                }
                if path.endswith("template-cfn.yaml"):
                    expected_types["RagIngestionEventSource"] = "AWS::Lambda::EventSourceMapping"
                for resource, expected_type in expected_types.items():
                    self.assertEqual(resources[resource]["Type"], expected_type)

                source = (PROJECT_ROOT / path).read_text(encoding="utf-8")
                for setting in (
                    "RAG_RETRIEVAL_BACKEND",
                    "RAG_TENANT_ID",
                    "OPENSEARCH_CASE_INDEX",
                    "OPENSEARCH_SOC_INDEX",
                    "OPENSEARCH_SPLUNK_INDEX",
                    "OPENSEARCH_ELASTIC_INDEX",
                    "CASE_EMBED_QUEUE_URL",
                    "PORTAL_REQUIRED_ANALYST_ROLE",
                    "PORTAL_REQUIRED_ANALYST_SCOPE",
                    "ReportBatchItemFailures",
                ):
                    self.assertIn(setting, source)

    def test_chat_history_resources_are_present(self) -> None:
        for path in (
            "deploy/aws/template-sam.yaml",
            "deploy/aws/template-cfn.yaml",
        ):
            with self.subTest(path=path):
                template = load_template(path)
                self.assertIn("HasChatHistory", template["Conditions"])
                self.assertIn("HasManagedChatSessionsTable", template["Conditions"])
                self.assertIn("ChatSessionsTable", template["Resources"])
                self.assertIn("ChatMessagesTable", template["Resources"])


if __name__ == "__main__":
    unittest.main()
