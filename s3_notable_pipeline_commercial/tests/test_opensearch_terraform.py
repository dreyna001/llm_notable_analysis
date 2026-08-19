"""Static contracts for the standalone OpenSearch Terraform stack."""

from __future__ import annotations

import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TERRAFORM_ROOT = PROJECT_ROOT / "deploy/terraform/opensearch"


class OpenSearchTerraformTests(unittest.TestCase):
    """Terraform must preserve the commercial Path B security contract."""

    def test_required_terraform_files_exist(self) -> None:
        for name in (
            "README.md",
            ".terraform.lock.hcl",
            "main.tf",
            "outputs.tf",
            "provider.tf",
            "terraform.tfvars.example",
            "variables.tf",
            "versions.tf",
        ):
            with self.subTest(name=name):
                self.assertTrue((TERRAFORM_ROOT / name).is_file(), name)

    def test_domain_is_vpc_only_and_encrypted(self) -> None:
        source = (TERRAFORM_ROOT / "main.tf").read_text(encoding="utf-8")
        for snippet in (
            'resource "aws_opensearch_domain" "this"',
            "vpc_options",
            "subnet_ids",
            "security_group_ids",
            "encrypt_at_rest",
            "node_to_node_encryption",
            "enforce_https       = true",
            'tls_security_policy = "Policy-Min-TLS-1-2-2019-07"',
            'volume_type = "gp3"',
            "zone_awareness_enabled",
        ):
            self.assertIn(snippet, source)

        self.assertNotIn("endpoint_options", source.replace("domain_endpoint_options", ""))
        self.assertNotIn("0.0.0.0/0", source)
        self.assertNotIn('identifiers = ["*"]', source)

    def test_security_group_allows_only_lambda_https_ingress(self) -> None:
        source = (TERRAFORM_ROOT / "main.tf").read_text(encoding="utf-8")
        self.assertIn('resource "aws_vpc_security_group_ingress_rule" "lambda_https"', source)
        self.assertIn("referenced_security_group_id = each.value", source)
        self.assertIn("from_port                    = 443", source)
        self.assertIn("to_port                      = 443", source)
        self.assertIn('ip_protocol                  = "tcp"', source)
        self.assertNotIn("cidr_ipv4", source)
        self.assertNotIn("cidr_ipv6", source)

    def test_account_region_and_network_inputs_fail_closed(self) -> None:
        source = (TERRAFORM_ROOT / "main.tf").read_text(encoding="utf-8")
        variables = (TERRAFORM_ROOT / "variables.tf").read_text(encoding="utf-8")
        for snippet in (
            'data.aws_partition.current.partition == "aws"',
            'data.aws_region.current.region == "us-east-1"',
            "data.aws_caller_identity.current.account_id == var.aws_account_id",
            "subnet.vpc_id == var.vpc_id",
            "group.vpc_id == var.vpc_id",
            "length(local.subnet_azs) == length(var.subnet_ids)",
            "split(\":\", arn)[4] == var.aws_account_id",
            "split(\":\", var.kms_key_arn)[4] == var.aws_account_id",
        ):
            self.assertIn(snippet, source)
        self.assertIn('var.aws_region == "us-east-1"', variables)

    def test_phase_a_and_phase_b_access_are_separate(self) -> None:
        source = (TERRAFORM_ROOT / "main.tf").read_text(encoding="utf-8")
        for snippet in (
            "AllowApprovedAdministrators",
            "AllowProductReadRoles",
            "AllowProductWriteRoles",
            'actions   = ["es:ESHttpGet", "es:ESHttpPost"]',
            '"es:ESHttpDelete"',
            '"es:ESHttpPut"',
            "var.read_role_arns",
            "var.write_role_arns",
        ):
            self.assertIn(snippet, source)

    def test_outputs_match_sam_parameter_contract(self) -> None:
        source = (TERRAFORM_ROOT / "outputs.tf").read_text(encoding="utf-8")
        for snippet in (
            'output "opensearch_endpoint"',
            'output "opensearch_domain_arn"',
            'output "opensearch_security_group_id"',
            "OPENSEARCH_ENDPOINT",
            "OPENSEARCH_DOMAIN_ARN",
            "CUSTOMER_VPC_SUBNET_IDS",
            "CUSTOMER_SECURITY_GROUP_IDS",
            "CUSTOMER_KMS_KEY_ARN",
        ):
            self.assertIn(snippet, source)

    def test_operator_docs_route_path_b_through_terraform(self) -> None:
        root_readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        runbook = (
            PROJECT_ROOT / "docs/operations/deployment/OPENSEARCH_PROVISIONING.md"
        ).read_text(encoding="utf-8")
        self.assertIn("deploy/terraform/opensearch/", root_readme)
        self.assertIn("Terraform workflow (preferred)", runbook)
        self.assertIn("terraform output sam_environment", runbook)


if __name__ == "__main__":
    unittest.main()
