"""Static contracts for the native commercial Path B Terraform deployment."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_ROOT = PROJECT_ROOT / "deploy" / "terraform"
PATH_B_ROOT = TERRAFORM_ROOT / "customer_default"


def module_text(name: str) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((TERRAFORM_ROOT / name).glob("*.tf"))
    )


class TerraformModulesTests(unittest.TestCase):
    def test_path_b_has_one_native_root_and_application_modules(self) -> None:
        for relative in (
            "customer_default/main.tf",
            "customer_default/variables.tf",
            "customer_default/outputs.tf",
            "customer_default/provider.tf",
            "customer_default/versions.tf",
            "customer_default/terraform.tfvars.example",
            "customer_default/README.md",
            "application_core/iam.tf",
            "application_core/lambda.tf",
            "application_core/queues.tf",
            "application_core/storage.tf",
            "application_core/alarms.tf",
            "application_core/outputs.tf",
            "application_portal/main.tf",
            "application_portal/outputs.tf",
        ):
            self.assertTrue((TERRAFORM_ROOT / relative).is_file(), relative)

        root = module_text("customer_default")
        for snippet in (
            'module "network"',
            'module "kms"',
            'module "ecr"',
            'module "opensearch"',
            'module "application_core"',
            'module "application_portal"',
            'source = "../application_core"',
            'source = "../application_portal"',
        ):
            self.assertIn(snippet, root)

    def test_path_b_uses_digest_pinned_image_and_commercial_boundary(self) -> None:
        root = module_text("customer_default")
        modules = root + module_text("application_core") + module_text("application_portal")
        for snippet in (
            "sha256:",
            "image_digest",
            "@${var.image_digest}",
            'aws_region == "us-east-1"',
            "aws_account_id",
        ):
            self.assertIn(snippet, modules)
        self.assertNotRegex(modules, re.compile(r"image_uri\s*=.*:latest", re.IGNORECASE))

    def test_path_b_baseline_has_required_compute_queues_auth_and_operations(self) -> None:
        core = module_text("application_core")
        portal = module_text("application_portal")
        for snippet in (
            'resource "aws_lambda_function" "analyzer"',
            'resource "aws_lambda_function" "embed"',
            'resource "aws_lambda_function" "rag"',
            'resource "aws_sqs_queue" "analyzer"',
            'resource "aws_sqs_queue" "analyzer_dlq"',
            'resource "aws_sqs_queue" "embed"',
            'resource "aws_sqs_queue" "embed_dlq"',
            'resource "aws_sqs_queue" "rag"',
            'resource "aws_sqs_queue" "rag_dlq"',
            'redrive_policy',
            'resource "aws_cloudwatch_metric_alarm"',
            'resource "aws_cloudwatch_log_group"',
        ):
            self.assertIn(snippet, core)
        for snippet in (
            'resource "aws_lambda_function" "portal"',
            'resource "aws_apigatewayv2_authorizer"',
            "portal_required_analyst_role",
            "portal_required_analyst_scope",
            'resource "aws_s3_bucket" "portal_ui"',
        ):
            self.assertIn(snippet, portal)
        self.assertRegex(portal, re.compile(r'authorizer_type\s*=\s*"JWT"'))

    def test_path_b_excludes_disabled_optional_profile_resources(self) -> None:
        application = module_text("application_core") + module_text("application_portal")
        for excluded in (
            "disposition_sync",
            "closed_ticket_sync",
            "closed_ticket_embed",
            "side_effect_idempotency",
        ):
            self.assertNotIn(excluded, application.lower())
        portal_variables = (TERRAFORM_ROOT / "application_portal/variables.tf").read_text(
            encoding="utf-8"
        )
        self.assertRegex(
            portal_variables,
            re.compile(r'variable "chat_history_enabled"\s*\{.*?default\s*=\s*false', re.DOTALL),
        )

    def test_root_wires_application_roles_directly_into_search_and_kms(self) -> None:
        root = module_text("customer_default")
        for snippet in (
            "module.application_core",
            "module.application_portal",
            "read_role_arns",
            "write_role_arns",
            "lambda_role_arns",
        ):
            self.assertIn(snippet, root)
        self.assertNotIn("terraform_remote_state", root)

    def test_root_validates_and_reports_customer_deployment(self) -> None:
        root = module_text("customer_default")
        outputs = (PATH_B_ROOT / "outputs.tf").read_text(encoding="utf-8")
        for snippet in (
            'resource "terraform_data"',
            "precondition",
            'output "deployment"',
            'output "ecr_repository_uri"',
            "portal_api_url",
            "application_role_arns",
            "analyzer_queue_url",
        ):
            self.assertIn(snippet, root + outputs)

    def test_path_b_security_and_state_contracts(self) -> None:
        root = module_text("customer_default")
        kms = module_text("kms")
        core = module_text("application_core")
        for snippet in (
            'backend "s3"',
            "use_lockfile = true",
            "existing_kms_policy_ready",
            "replace_existing_opensearch_access_policy",
        ):
            self.assertIn(snippet, root)
        for snippet in (
            "AllowS3NotificationQueueEncryption",
            'identifiers = ["s3.amazonaws.com"]',
            'variable = "aws:SourceAccount"',
            'variable = "aws:SourceArn"',
        ):
            self.assertIn(snippet, kms)
        self.assertIn('data "aws_iam_policy_document" "analyzer_queue_notification"', core)
        self.assertIn('data "aws_iam_policy_document" "rag_queue_notification"', core)
        self.assertIn("analyzer_maximum_concurrency >= 2", core)
        self.assertIn("contains([1, 3, 5, 7, 14, 30", core)


if __name__ == "__main__":
    unittest.main()
