"""Tests for the Path B deployment configurator."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from path_b_deploy_configurator import (  # noqa: E402
    build_outputs,
    load_config_from_json,
    main,
    render_terraform_tfvars,
    validate_config,
)

FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "path_b_answers_create_opensearch.json"


class PathBDeployConfiguratorTests(unittest.TestCase):
    def test_fixture_loads_and_validates(self) -> None:
        config = load_config_from_json(FIXTURE)
        self.assertEqual([], validate_config(config))

    def test_build_outputs_writes_single_customer_default_tfvars(self) -> None:
        config = load_config_from_json(FIXTURE)
        outputs = build_outputs(config)

        self.assertIn('aws_account_id = "123456789012"', outputs.tfvars_content)
        self.assertIn('rag_tenant_id          = "customer-acme-staging"', outputs.tfvars_content)
        self.assertIn("existing_kms_key_arn", outputs.tfvars_content)
        self.assertIn('opensearch_domain_name   = "notable-rag-staging"', outputs.tfvars_content)
        self.assertNotIn("read_role_arns", outputs.tfvars_content)
        self.assertNotIn("write_role_arns", outputs.tfvars_content)
        self.assertIn("Terraform deploy", outputs.checklist_content)
        self.assertNotIn("SAM deploy", outputs.checklist_content)

    def test_existing_opensearch_is_wired_in_same_tfvars(self) -> None:
        config = load_config_from_json(FIXTURE)
        config.opensearch_mode = "existing"
        config.opensearch_endpoint = "https://vpc-notable.example.es.amazonaws.com"
        config.opensearch_domain_arn = "arn:aws:es:us-east-1:123456789012:domain/notable-rag-staging"
        tfvars = render_terraform_tfvars(config)
        self.assertIn("create_opensearch_domain = false", tfvars)
        self.assertIn('existing_opensearch_endpoint = "https://vpc-notable.example.es.amazonaws.com"', tfvars)

    def test_greenfield_ecr_can_bootstrap_without_an_image_uri(self) -> None:
        config = load_config_from_json(FIXTURE)
        config.ecr_mode = "create"
        config.ecr_repository_uri = ""
        tfvars = render_terraform_tfvars(config)
        self.assertIn("create_ecr_repository      = true", tfvars)
        self.assertIn('ecr_repository_name         = "notable-analyzer-s3"', tfvars)

    def test_validation_requires_jwt_grant(self) -> None:
        config = load_config_from_json(FIXTURE)
        config.portal_required_analyst_role = ""
        config.portal_required_analyst_scope = ""
        errors = validate_config(config)
        self.assertTrue(any("portal_required_analyst" in err for err in errors))

    def test_validation_rejects_vpc_create_mode(self) -> None:
        config = load_config_from_json(FIXTURE)
        config.vpc_mode = "create"
        config.vpc_id = ""
        errors = validate_config(config)
        self.assertTrue(any("vpc_mode create" in err for err in errors))

    def test_main_dry_run_with_answers_file(self) -> None:
        exit_code = main(
            ["--answers-file", str(FIXTURE), "--dry-run"],
        )
        self.assertEqual(exit_code, 0)

    def test_main_writes_files_from_answers_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            tfvars_out = temp_path / "terraform.tfvars"
            checklist_out = temp_path / "steps.md"
            exit_code = main(
                [
                    "--answers-file",
                    str(FIXTURE),
                    "--tfvars-out",
                    str(tfvars_out),
                    "--checklist-out",
                    str(checklist_out),
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(tfvars_out.is_file())
            self.assertTrue(checklist_out.is_file())

    def test_unknown_json_keys_fail(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            data = json.loads(FIXTURE.read_text(encoding="utf-8"))
            data["unexpected"] = True
            json.dump(data, handle)
            handle.flush()
            temp_path = Path(handle.name)
        try:
            with self.assertRaises(ValueError):
                load_config_from_json(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
