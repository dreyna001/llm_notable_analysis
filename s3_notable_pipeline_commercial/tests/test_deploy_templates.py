"""Deployment template contract tests."""

from __future__ import annotations

import re
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

TEMPLATE_PATHS = (
    "deploy/aws/template-sam.yaml",
    "deploy/aws/template-cfn.yaml",
)


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


def _collect_condition_names(template: dict[str, Any]) -> set[str]:
    conditions = template.get("Conditions")
    if not isinstance(conditions, dict):
        return set()
    return set(conditions.keys())


def _resource_conditions(template: dict[str, Any]) -> dict[str, str]:
    resources = template.get("Resources")
    if not isinstance(resources, dict):
        return {}
    named: dict[str, str] = {}
    for name, spec in resources.items():
        if not isinstance(spec, dict):
            continue
        condition = spec.get("Condition")
        if isinstance(condition, str):
            named[name] = condition
    return named


class DeployTemplateTests(unittest.TestCase):
    """Template synchronization tests."""

    def test_portal_ui_uses_private_s3_behind_regional_api(self) -> None:
        for path in TEMPLATE_PATHS:
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
        for path in TEMPLATE_PATHS:
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

    def test_commercial_queues_and_opensearch_contracts_are_wired(self) -> None:
        for path in TEMPLATE_PATHS:
            with self.subTest(path=path):
                template = load_template(path)
                parameters = template["Parameters"]
                resources = template["Resources"]
                self.assertEqual(parameters["DeploymentRegion"]["Default"], "us-east-1")
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
        for path in TEMPLATE_PATHS:
            with self.subTest(path=path):
                template = load_template(path)
                self.assertIn("HasChatHistory", template["Conditions"])
                self.assertIn("HasManagedChatSessionsTable", template["Conditions"])
                self.assertIn("ChatSessionsTable", template["Resources"])
                self.assertIn("ChatMessagesTable", template["Resources"])

    def test_repaired_commercial_permissions_and_rag_notification_contract(self) -> None:
        for path in TEMPLATE_PATHS:
            with self.subTest(path=path):
                template = load_template(path)
                source = (PROJECT_ROOT / path).read_text(encoding="utf-8")
                self.assertIn("RagIngestionQueueArn", template["Outputs"])
                self.assertIn("RequireDistinctExternalRagSourceBucket", template["Rules"])
                self.assertIn("RagIngestionUsesInputBucket", template["Conditions"])
                self.assertIn("dynamodb:TransactWriteItems", source)
                self.assertIn("s3:prefix", source)
                for spec in template["Resources"].values():
                    if spec.get("Type") == "AWS::IAM::Role":
                        self.assertNotIn("RoleName", spec.get("Properties", {}))
                if path.endswith("template-sam.yaml"):
                    disposition = template["Resources"]["DispositionSyncFunction"]
                else:
                    disposition = template["Resources"]["DispositionSyncLambdaRole"]
                self.assertIn("CustomerKmsReadPolicy", str(disposition))

    def test_embed_resources_use_has_case_qa_condition(self) -> None:
        for path in TEMPLATE_PATHS:
            with self.subTest(path=path):
                template = load_template(path)
                conditions = _collect_condition_names(template)
                self.assertNotIn("HasCaseIndex", conditions)
                self.assertNotIn("HasCaseQaTable", conditions)
                for resource, condition in _resource_conditions(template).items():
                    self.assertNotEqual(
                        condition,
                        "HasCaseIndex",
                        msg=f"{path} resource {resource} references undefined HasCaseIndex",
                    )
                self.assertEqual(
                    template["Resources"]["CaseIndexTable"]["Condition"],
                    "HasCaseIndexTable",
                )
                embed_conditioned = {
                    name
                    for name, condition in _resource_conditions(template).items()
                    if condition == "HasCaseQa"
                }
                self.assertIn("CaseEmbedLogGroup", embed_conditioned)
                self.assertIn("EmbedDlqAlarm", embed_conditioned)
                self.assertIn("EmbedErrorAlarm", embed_conditioned)

    def test_lambda_environment_does_not_set_reserved_aws_region(self) -> None:
        pattern = re.compile(r"^\s*AWS_REGION:\s*!Ref\s+DeploymentRegion\s*$", re.MULTILINE)
        for path in TEMPLATE_PATHS:
            with self.subTest(path=path):
                source = (PROJECT_ROOT / path).read_text(encoding="utf-8")
                self.assertIsNone(
                    pattern.search(source),
                    msg=f"{path} must not set reserved AWS_REGION in Lambda environment",
                )

    def test_input_bucket_does_not_depend_on_conditional_rag_queue_policy(self) -> None:
        for path in TEMPLATE_PATHS:
            with self.subTest(path=path):
                template = load_template(path)
                depends_on = template["Resources"]["InputBucket"].get("DependsOn", [])
                if isinstance(depends_on, str):
                    depends_on = [depends_on]
                self.assertEqual(depends_on, ["AnalyzerQueuePolicy"])
                self.assertNotIn("RagIngestionQueuePolicy", depends_on)
                self.assertNotIn("RagIngestionQueuePolicy", template["Resources"])
                self.assertIn(
                    "AllowRagSourceBucketSend",
                    str(template["Resources"]["AnalyzerQueuePolicy"]),
                )

    def test_portal_readiness_configuration_matches_iam(self) -> None:
        for path in TEMPLATE_PATHS:
            with self.subTest(path=path):
                template = load_template(path)
                portal = template["Resources"]["PortalApiFunction"]
                variables = portal["Properties"]["Environment"]["Variables"]
                self.assertEqual(variables["CASE_ARCHIVE_PREFIX"], "CaseArchivePrefix")
                self.assertEqual(
                    variables["PORTAL_READINESS_TIMEOUT_SECONDS"],
                    "PortalReadinessTimeoutSeconds",
                )
                source = (PROJECT_ROOT / path).read_text(encoding="utf-8")
                self.assertIn("dynamodb:DescribeTable", source)
                self.assertIn("bedrock:CountTokens", source)

    def test_runtime_safety_limits_are_deploy_configurable(self) -> None:
        expected_parameters = {
            "MaxCompressedInputBytes",
            "RagIngestMaxDocumentBytes",
            "RagIngestMaxManifestBytes",
            "RagIngestMaxDocumentsPerManifest",
            "RagIngestMaxTotalSourceBytes",
            "RagIngestMaxEmbeddingsPerManifest",
            "PortalReadinessTimeoutSeconds",
        }
        for path in TEMPLATE_PATHS:
            with self.subTest(path=path):
                template = load_template(path)
                self.assertTrue(expected_parameters.issubset(template["Parameters"]))
                source = (PROJECT_ROOT / path).read_text(encoding="utf-8")
                for setting in (
                    "MAX_COMPRESSED_INPUT_BYTES",
                    "RAG_INGEST_MAX_DOCUMENT_BYTES",
                    "RAG_INGEST_MAX_MANIFEST_BYTES",
                    "RAG_INGEST_MAX_DOCUMENTS_PER_MANIFEST",
                    "RAG_INGEST_MAX_TOTAL_SOURCE_BYTES",
                    "RAG_INGEST_MAX_EMBEDDINGS_PER_MANIFEST",
                    "PORTAL_READINESS_TIMEOUT_SECONDS",
                ):
                    self.assertIn(setting, source)

    def test_cfn_container_lambdas_use_code_image_uri(self) -> None:
        template = load_template("deploy/aws/template-cfn.yaml")
        resources = template["Resources"]
        for name, spec in resources.items():
            if spec.get("Type") != "AWS::Lambda::Function":
                continue
            props = spec.get("Properties", {})
            if props.get("PackageType") != "Image":
                continue
            with self.subTest(function=name):
                self.assertIn("Code", props)
                self.assertIn("ImageUri", props["Code"])
                self.assertNotIn("ImageUri", props)

    def test_dynamodb_sse_uses_kms_type_only_with_customer_cmk(self) -> None:
        for path in TEMPLATE_PATHS:
            with self.subTest(path=path):
                source = (PROJECT_ROOT / path).read_text(encoding="utf-8")
                self.assertNotIn(
                    "KMSMasterKeyId: !If [HasCustomerKmsKey",
                    source,
                    msg=f"{path} must not set DynamoDB KMSMasterKeyId without SSEType: KMS",
                )
                self.assertIn("SSEType: KMS", source)
                self.assertIn(
                    "SSESpecification: !If",
                    source,
                )

    def test_vpc_eni_policy_is_available_for_lambda_roles(self) -> None:
        for path in TEMPLATE_PATHS:
            with self.subTest(path=path):
                template = load_template(path)
                self.assertIn("LambdaVpcEniPolicy", template["Resources"])
                self.assertEqual(
                    template["Resources"]["LambdaVpcEniPolicy"]["Condition"],
                    "HasCustomerVpc",
                )
                source = (PROJECT_ROOT / path).read_text(encoding="utf-8")
                self.assertIn("ec2:CreateNetworkInterface", source)
                self.assertIn("LambdaVpcEniPolicy", source)

    def test_portal_bedrock_iam_uses_configured_model_arn(self) -> None:
        for path in TEMPLATE_PATHS:
            with self.subTest(path=path):
                template = load_template(path)
                self.assertIn("PortalChatBedrockModelArn", template["Parameters"])
                self.assertNotIn("Default", template["Parameters"]["BedrockAnalysisModelArn"])
                self.assertIn("HasPortalChatBedrockModelOverride", template["Conditions"])
                source = (PROJECT_ROOT / path).read_text(encoding="utf-8")
                self.assertNotIn("inference-profile/*", source)
                self.assertIn("PortalChatBedrockModelArn", source)
                self.assertIn("BedrockAnalysisModelArn", source)

    def test_commercial_partition_and_region_are_locked(self) -> None:
        for path in TEMPLATE_PATHS:
            with self.subTest(path=path):
                template = load_template(path)
                parameters = template["Parameters"]
                self.assertEqual(parameters["DeploymentPartition"]["Default"], "aws")
                self.assertEqual(parameters["DeploymentPartition"]["AllowedValues"], ["aws"])
                self.assertNotIn("aws-us-gov", parameters["DeploymentPartition"]["AllowedValues"])
                self.assertEqual(parameters["DeploymentRegion"]["Default"], "us-east-1")
                self.assertEqual(parameters["DeploymentRegion"]["AllowedValues"], ["us-east-1"])
                self.assertNotIn("us-gov-east-1", parameters["DeploymentRegion"]["AllowedValues"])
                self.assertEqual(parameters["OpenSearchRegion"]["Default"], "us-east-1")
                self.assertEqual(parameters["OpenSearchRegion"]["AllowedValues"], ["us-east-1"])
                self.assertIn("RequireCommercialAwsBoundary", template["Rules"])
                self.assertNotIn("RequireGovCloudBoundary", template["Rules"])

    def test_ecr_repository_uri_is_commercial_us_east_1(self) -> None:
        valid = "123456789012.dkr.ecr.us-east-1.amazonaws.com/notable/analyzer"
        invalid = (
            "123456789012.dkr.ecr.us-west-2.amazonaws.com/notable/analyzer",
            "123456789012.dkr.ecr.us-gov-east-1.amazonaws.com/notable/analyzer",
            "arn:aws:ecr:us-east-1:123456789012:repository/notable/analyzer",
        )
        for path in TEMPLATE_PATHS:
            with self.subTest(path=path):
                pattern = load_template(path)["Parameters"]["EcrRepositoryUri"]["AllowedPattern"]
                self.assertIsNotNone(re.fullmatch(pattern, valid))
                for candidate in invalid:
                    self.assertIsNone(re.fullmatch(pattern, candidate))

    def test_bedrock_model_arns_are_commercial_us_east_1(self) -> None:
        valid = (
            "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-pro-v1:0",
            "arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.example-model-v1:0",
        )
        invalid = (
            "arn:aws-us-gov:bedrock:us-gov-east-1::foundation-model/example",
            "arn:aws:bedrock:us-west-2::foundation-model/example",
        )
        for path in TEMPLATE_PATHS:
            with self.subTest(path=path):
                parameters = load_template(path)["Parameters"]
                analysis_pattern = parameters["BedrockAnalysisModelArn"]["AllowedPattern"]
                portal_pattern = parameters["PortalChatBedrockModelArn"]["AllowedPattern"]
                for candidate in valid:
                    self.assertIsNotNone(re.fullmatch(analysis_pattern, candidate))
                    self.assertIsNotNone(re.fullmatch(portal_pattern, candidate))
                self.assertIsNotNone(re.fullmatch(portal_pattern, ""))
                for candidate in invalid:
                    self.assertIsNone(re.fullmatch(analysis_pattern, candidate))
                    self.assertIsNone(re.fullmatch(portal_pattern, candidate))

    def test_regional_resource_arns_are_commercial_us_east_1(self) -> None:
        secret_parameters = (
            "SplunkMcpAuthSecretArn",
            "ServiceNowApiTokenSecretArn",
            "ServiceNowApprovalHmacSecretArn",
            "ServiceNowDispositionSyncTokenSecretArn",
            "ElasticsearchApiKeySecretArn",
            "SplunkApiTokenSecretArn",
        )
        regional_parameters = {
            "OpenSearchDomainArn": "arn:aws:es:us-east-1:123456789012:domain/notable",
            "CustomerKmsKeyArn": (
                "arn:aws:kms:us-east-1:123456789012:key/12345678-abcd-1234-abcd-1234567890ab"
            ),
            "AlarmNotificationTopicArn": "arn:aws:sns:us-east-1:123456789012:notable-alarms",
        }
        for path in TEMPLATE_PATHS:
            with self.subTest(path=path):
                parameters = load_template(path)["Parameters"]
                for parameter in secret_parameters:
                    pattern = parameters[parameter]["AllowedPattern"]
                    valid = "arn:aws:secretsmanager:us-east-1:123456789012:secret:notable-token"
                    self.assertIsNotNone(re.fullmatch(pattern, valid))
                    self.assertIsNotNone(re.fullmatch(pattern, "*"))
                    self.assertIsNone(re.fullmatch(pattern, valid.replace("us-east-1", "us-west-2")))
                    self.assertIsNone(re.fullmatch(pattern, valid.replace("arn:aws:", "arn:aws-us-gov:")))
                for parameter, valid in regional_parameters.items():
                    pattern = parameters[parameter]["AllowedPattern"]
                    self.assertIsNotNone(re.fullmatch(pattern, valid))
                    self.assertIsNotNone(re.fullmatch(pattern, ""))
                    self.assertIsNone(re.fullmatch(pattern, valid.replace("us-east-1", "us-west-2")))
                    self.assertIsNone(re.fullmatch(pattern, valid.replace("arn:aws:", "arn:aws-us-gov:")))
                iam_pattern = parameters["CustomerKmsKeyAdminRoleArn"]["AllowedPattern"]
                self.assertIsNotNone(
                    re.fullmatch(iam_pattern, "arn:aws:iam::123456789012:role/KmsAdmin")
                )
                self.assertIsNone(
                    re.fullmatch(iam_pattern, "arn:aws-us-gov:iam::123456789012:role/KmsAdmin")
                )

    def test_account_and_kms_admin_deployment_values_are_validated_or_recorded(self) -> None:
        for path in TEMPLATE_PATHS:
            with self.subTest(path=path):
                template = load_template(path)
                self.assertIn("AwsAccountId", template["Parameters"])
                self.assertIn("RequireCommercialAwsBoundary", template["Rules"])
                self.assertIn("HasCustomerKmsAdminRole", template["Conditions"])
                self.assertEqual(
                    template["Outputs"]["CustomerKmsKeyAdminRoleArn"]["Condition"],
                    "HasCustomerKmsAdminRole",
                )

    def test_template_rules_guard_portal_and_profile_prerequisites(self) -> None:
        required_rules = (
            "RequireCaseIndexForPortalFeatures",
            "RequireCaseArchiveForPortal",
            "RequireChatHistoryPrerequisites",
            "RequirePortalChatBedrockModelArn",
        )
        for path in TEMPLATE_PATHS:
            with self.subTest(path=path):
                template = load_template(path)
                rules = template.get("Rules", {})
                for rule_name in required_rules:
                    self.assertIn(rule_name, rules, msg=f"{path} missing rule {rule_name}")


if __name__ == "__main__":
    unittest.main()
