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
    render_opensearch_tfvars,
    validate_config,
)

FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "path_b_answers_create_opensearch.json"


class PathBDeployConfiguratorTests(unittest.TestCase):
    def test_fixture_loads_and_validates(self) -> None:
        config = load_config_from_json(FIXTURE)
        self.assertEqual([], validate_config(config))

    def test_build_outputs_writes_expected_env_and_tfvars_fields(self) -> None:
        config = load_config_from_json(FIXTURE)
        outputs = build_outputs(config)

        self.assertIn("AWS_ACCOUNT_ID=123456789012", outputs.env_content)
        self.assertIn("RAG_TENANT_ID=customer-acme-staging", outputs.env_content)
        self.assertIn("CUSTOMER_KMS_KEY_ARN=arn:aws:kms:", outputs.env_content)
        self.assertIsNotNone(outputs.tfvars_content)
        assert outputs.tfvars_content is not None
        self.assertIn('domain_name    = "notable-rag-staging"', outputs.tfvars_content)
        self.assertIn("kms_key_arn = ", outputs.tfvars_content)
        self.assertIn("OpenSearch Phase A", outputs.checklist_content)

    def test_existing_opensearch_skips_tfvars(self) -> None:
        config = load_config_from_json(FIXTURE)
        config.opensearch_mode = "existing"
        config.opensearch_endpoint = "https://vpc-notable.example.es.amazonaws.com"
        config.opensearch_domain_arn = "arn:aws:es:us-east-1:123456789012:domain/notable-rag-staging"
        outputs = build_outputs(config)
        self.assertIsNone(outputs.tfvars_path)
        self.assertIsNone(render_opensearch_tfvars(config))

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
            env_out = temp_path / "customer-default.env"
            tfvars_out = temp_path / "terraform.tfvars"
            checklist_out = temp_path / "steps.md"
            exit_code = main(
                [
                    "--answers-file",
                    str(FIXTURE),
                    "--env-out",
                    str(env_out),
                    "--tfvars-out",
                    str(tfvars_out),
                    "--checklist-out",
                    str(checklist_out),
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(env_out.is_file())
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
