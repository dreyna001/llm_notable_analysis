"""Static contracts for commercial Path B Terraform modules."""

from __future__ import annotations

import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MODULES: dict[str, tuple[str, ...]] = {
    "network": (
        "README.md",
        "main.tf",
        "outputs.tf",
        "provider.tf",
        "terraform.tfvars.example",
        "variables.tf",
        "versions.tf",
    ),
    "kms": (
        "README.md",
        "main.tf",
        "outputs.tf",
        "provider.tf",
        "terraform.tfvars.example",
        "variables.tf",
        "versions.tf",
    ),
    "ecr": (
        "README.md",
        ".terraform.lock.hcl",
        "main.tf",
        "outputs.tf",
        "provider.tf",
        "terraform.tfvars.example",
        "variables.tf",
        "versions.tf",
    ),
    "foundation": (
        "README.md",
        "main.tf",
        "outputs.tf",
        "provider.tf",
        "terraform.tfvars.example",
        "variables.tf",
        "versions.tf",
    ),
}


class TerraformModulesTests(unittest.TestCase):
    """Foundation Terraform must preserve commercial Path B contracts."""

    def test_hub_and_module_files_exist(self) -> None:
        hub = PROJECT_ROOT / "deploy/terraform/README.md"
        self.assertTrue(hub.is_file())
        for snippet in (
            "SAM remains required",
            "deploy/terraform/foundation/",
            "deploy/terraform/network/",
            "deploy/terraform/kms/",
            "deploy/terraform/ecr/",
            "deploy/terraform/opensearch/",
        ):
            self.assertIn(snippet, hub.read_text(encoding="utf-8"))

        for module, files in MODULES.items():
            root = PROJECT_ROOT / "deploy/terraform" / module
            with self.subTest(module=module):
                for name in files:
                    self.assertTrue((root / name).is_file(), f"{module}/{name}")

    def test_foundation_composes_child_modules(self) -> None:
        source = (PROJECT_ROOT / "deploy/terraform/foundation/main.tf").read_text(
            encoding="utf-8"
        )
        for snippet in (
            'module "network"',
            'module "kms"',
            'module "ecr"',
            'module "opensearch"',
            'source = "../network"',
            'source = "../kms"',
            'source = "../ecr"',
            'source = "../opensearch"',
            "enable_opensearch_grant = var.enable_opensearch",
            'resource "terraform_data" "foundation_preconditions"',
        ):
            self.assertIn(snippet, source)

    def test_foundation_outputs_merged_sam_environment(self) -> None:
        source = (PROJECT_ROOT / "deploy/terraform/foundation/outputs.tf").read_text(
            encoding="utf-8"
        )
        for snippet in (
            'output "sam_environment"',
            "module.kms[0].sam_environment",
            "module.network[0].sam_environment",
            "module.ecr[0].sam_environment",
            "module.opensearch[0].sam_environment",
        ):
            self.assertIn(snippet, source)

    def test_network_module_creates_lambda_security_group(self) -> None:
        source = (PROJECT_ROOT / "deploy/terraform/network/main.tf").read_text(
            encoding="utf-8"
        )
        for snippet in (
            'resource "aws_security_group" "lambda"',
            "data.aws_caller_identity.current.account_id == var.aws_account_id",
            'data.aws_region.current.region == "us-east-1"',
            'output "sam_environment"',
        ):
            if snippet.startswith("output"):
                outputs = (PROJECT_ROOT / "deploy/terraform/network/outputs.tf").read_text(
                    encoding="utf-8"
                )
                self.assertIn(snippet, outputs)
            else:
                self.assertIn(snippet, source)

    def test_kms_module_grants_opensearch_and_lambda(self) -> None:
        source = (PROJECT_ROOT / "deploy/terraform/kms/main.tf").read_text(encoding="utf-8")
        for snippet in (
            'resource "aws_kms_key" "this"',
            "enable_opensearch_grant",
            "lambda_role_arns",
            "es.amazonaws.com",
        ):
            self.assertIn(snippet, source)

    def test_ecr_module_outputs_repository_uri(self) -> None:
        outputs = (PROJECT_ROOT / "deploy/terraform/ecr/outputs.tf").read_text(
            encoding="utf-8"
        )
        main = (PROJECT_ROOT / "deploy/terraform/ecr/main.tf").read_text(encoding="utf-8")
        self.assertIn('output "ecr_repository_uri"', outputs)
        self.assertIn("ECR_REPOSITORY_URI", outputs)
        self.assertIn('resource "aws_ecr_repository" "this"', main)
        self.assertIn("scan_on_push", main)

    def test_operator_docs_reference_terraform_hub(self) -> None:
        root_readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        for snippet in (
            "deploy/terraform/README.md",
            "deploy/terraform/foundation/",
            "deploy/terraform/network/",
            "deploy/terraform/kms/",
            "deploy/terraform/ecr/",
        ):
            self.assertIn(snippet, root_readme)

        vpc_doc = (
            PROJECT_ROOT / "docs/operations/deployment/VPC_NETWORK_PREREQUISITES.md"
        ).read_text(encoding="utf-8")
        self.assertIn("deploy/terraform/network/", vpc_doc)
        self.assertIn("Terraform workflow", vpc_doc)


if __name__ == "__main__":
    unittest.main()
