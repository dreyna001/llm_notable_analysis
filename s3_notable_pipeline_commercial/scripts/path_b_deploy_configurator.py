"""Generate Path B customer-default deployment artifacts from guided answers.

Path B only. Does not run terraform apply, sam deploy, or live AWS mutations.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = PROJECT_ROOT / "customer-default.env"
DEFAULT_TFVARS_PATH = PROJECT_ROOT / "deploy" / "terraform" / "opensearch" / "terraform.tfvars"
DEFAULT_CHECKLIST_PATH = PROJECT_ROOT / "path-b-remaining-steps.md"

CmkMode = Literal["skip", "existing", "create"]
VpcMode = Literal["existing", "create"]
OpenSearchMode = Literal["create", "existing"]

_ACCOUNT_RE = re.compile(r"^[0-9]{12}$")
_VPC_RE = re.compile(r"^vpc-[0-9a-f]+$")
_SUBNET_RE = re.compile(r"^subnet-[0-9a-f]+$")
_SG_RE = re.compile(r"^sg-[0-9a-f]+$")
_DOMAIN_RE = re.compile(r"^[a-z][a-z0-9-]{2,27}$")
_IAM_ROLE_ARN_RE = re.compile(r"^arn:aws:iam::[0-9]{12}:role/.+$")
_OPENSEARCH_ARN_RE = re.compile(r"^arn:aws:es:us-east-1:[0-9]{12}:domain/[a-z0-9-]+$")
_HTTPS_URL_RE = re.compile(r"^https://[a-zA-Z0-9.-]+$")
_KMS_ARN_RE = re.compile(r"^arn:aws:kms:us-east-1:[0-9]{12}:key/[0-9a-f-]+$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass
class PathBConfig:
    aws_account_id: str = ""
    commercial_aws_account_id: str = ""

    cmk_mode: CmkMode = "skip"
    customer_kms_key_arn: str = ""

    vpc_mode: VpcMode = "existing"
    vpc_id: str = ""
    subnet_ids: list[str] = field(default_factory=list)
    lambda_security_group_ids: list[str] = field(default_factory=list)

    opensearch_mode: OpenSearchMode = "create"
    domain_name: str = ""
    opensearch_endpoint: str = ""
    opensearch_domain_arn: str = ""
    admin_principal_arns: list[str] = field(default_factory=list)
    engine_version: str = "OpenSearch_2.11"
    instance_type: str = "t3.small.search"
    instance_count: int = 2
    volume_size_gib: int = 50

    rag_tenant_id: str = ""

    bedrock_analysis_model_id: str = ""
    bedrock_analysis_model_arn: str = ""
    bedrock_analysis_inference_profile_foundation_model_arns: str = ""

    portal_jwt_issuer: str = ""
    portal_jwt_audience: str = ""
    portal_jwt_tenant_id: str = ""
    portal_required_analyst_role: str = ""
    portal_required_analyst_scope: str = ""
    portal_cors_allowed_origins: str = ""

    ecr_repository_uri: str = ""
    image_digest: str = ""

    input_bucket_name: str = ""
    output_bucket_name: str = ""
    case_index_table_name: str = "notable-case-index"
    portal_ui_bucket_name: str = ""

    opensearch_soc_index: str = "soc_knowledge"
    opensearch_splunk_index: str = "splunk_dictionary"
    opensearch_case_index: str = "case_chunks"


def _hint(text: str) -> None:
    print(f"  hint: {text}")


def _prompt(text: str, default: str = "", *, hint: str | None = None) -> str:
    if hint:
        _hint(hint)
    suffix = f" [{default}]" if default else ""
    value = input(f"{text}{suffix}: ").strip()
    return value or default


def _prompt_list(text: str, *, hint: str | None = None) -> list[str]:
    raw = _prompt(text, hint=hint)
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _prompt_yes_no(text: str, default: bool = False) -> bool:
    default_label = "Y/n" if default else "y/N"
    while True:
        value = input(f"{text} ({default_label}): ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Enter y or n.")


def _prompt_choice(text: str, choices: dict[str, str]) -> str:
    print(text)
    keys = list(choices.keys())
    for key in keys:
        print(f"  {key}. {choices[key]}")
    valid = set(keys)
    while True:
        value = input("Choice: ").strip().lower()
        if value in valid:
            return value
        print(f"Choose one of: {', '.join(sorted(valid))}")


def _comma(values: list[str]) -> str:
    return ",".join(values)


def collect_interactive() -> PathBConfig:
    print("Commercial AWS Path B setup (customer-default).")
    print("This script writes local config files only. It does not deploy anything.\n")

    config = PathBConfig()
    config.aws_account_id = _prompt(
        "Commercial AWS account ID (12 digits)",
        hint="Example: 123456789012",
    )
    config.commercial_aws_account_id = _prompt(
        "COMMERCIAL_AWS_ACCOUNT_ID (leave blank to match AWS account ID)",
        config.aws_account_id,
        hint="Must match AWS_ACCOUNT_ID for setup-and-deploy scripts",
    )

    cmk_mode = _prompt_choice(
        "Customer-managed KMS (CMK)?",
        {
            "skip": "Skip — use AWS owned keys",
            "existing": "Use an existing CMK ARN",
            "create": "Create CMK later (manual runbook first)",
        },
    )
    config.cmk_mode = cmk_mode  # type: ignore[assignment]
    if cmk_mode == "existing":
        config.customer_kms_key_arn = _prompt(
            "CMK ARN (us-east-1)",
            hint="Example: arn:aws:kms:us-east-1:123456789012:key/11111111-2222-3333-4444-555555555555",
        )
    elif cmk_mode == "create":
        _hint("Leave CUSTOMER_KMS_KEY_ARN empty until the key exists; see KMS_CUSTOMER_KEY.md")

    vpc_mode = _prompt_choice(
        "VPC and Lambda networking for Path B?",
        {
            "existing": "Use existing VPC, private subnets, and Lambda security group",
            "create": "Provision network later (manual runbook first)",
        },
    )
    config.vpc_mode = vpc_mode  # type: ignore[assignment]
    if vpc_mode == "existing":
        config.vpc_id = _prompt("VPC ID", hint="Example: vpc-0abc123def4567890")
        config.subnet_ids = _prompt_list(
            "Private subnet IDs (comma-separated, no spaces)",
            hint="Example: subnet-aaa111,subnet-bbb222 (1 for dev, 2+ AZs for prod)",
        )
        config.lambda_security_group_ids = _prompt_list(
            "Lambda security group IDs (comma-separated, no spaces)",
            hint="Example: sg-0abc123def4567890",
        )
    else:
        _hint("Finish VPC_NETWORK_PREREQUISITES.md first, then re-run with existing network IDs")

    opensearch_mode = _prompt_choice(
        "OpenSearch domain?",
        {
            "create": "Create with product Terraform (Phase A before SAM)",
            "existing": "Use an existing VPC-only domain",
        },
    )
    config.opensearch_mode = opensearch_mode  # type: ignore[assignment]
    if opensearch_mode == "create":
        config.domain_name = _prompt(
            "OpenSearch domain name",
            "notable-rag-staging",
            hint="Lowercase letters, digits, hyphens; 3-28 chars; unique in account",
        )
        config.admin_principal_arns = _prompt_list(
            "Admin IAM role ARNs for Phase A (comma-separated)",
            hint="Example: arn:aws:iam::123456789012:role/ApprovedOpenSearchAdministrator",
        )
        if _prompt_yes_no("Use default OpenSearch sizing (t3.small.search x2, 50 GiB)?", True):
            pass
        else:
            config.instance_type = _prompt(
                "Instance type",
                config.instance_type,
                hint="Example: t3.small.search",
            )
            config.instance_count = int(
                _prompt("Instance count", str(config.instance_count), hint="1-3")
            )
            config.volume_size_gib = int(
                _prompt("Volume size GiB", str(config.volume_size_gib), hint="Example: 50")
            )
    else:
        config.opensearch_endpoint = _prompt(
            "OpenSearch HTTPS endpoint",
            hint="Example: https://vpc-notable-rag-staging-xxxxx.us-east-1.es.amazonaws.com",
        )
        config.opensearch_domain_arn = _prompt(
            "OpenSearch domain ARN",
            hint="Example: arn:aws:es:us-east-1:123456789012:domain/notable-rag-staging",
        )

    config.rag_tenant_id = _prompt(
        "RAG tenant ID (stable per deployment)",
        hint="Example: customer-acme-prod (same value on every OpenSearch document)",
    )

    print("\nBedrock analysis model (enable in account before SAM deploy).")
    config.bedrock_analysis_model_id = _prompt(
        "BedrockAnalysisModelId",
        hint="Example: amazon.nova-pro-v1:0 or us.anthropic.claude-sonnet-4-20250514-v1:0",
    )
    config.bedrock_analysis_model_arn = _prompt(
        "BedrockAnalysisModelArn",
        hint="Example: arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-pro-v1:0",
    )
    config.bedrock_analysis_inference_profile_foundation_model_arns = _prompt(
        "Geographic inference profile foundation model ARNs (comma-separated, or leave blank)",
        "",
        hint="Required only for geographic inference profiles; from get-inference-profile",
    )

    print("\nPortal JWT (Path B requires portal JWT mode).")
    _hint("Set at least one of role or scope; SAM fails if both are empty")
    config.portal_jwt_issuer = _prompt(
        "Portal JWT issuer URL",
        hint="Example: https://login.microsoftonline.com/<tenant-id>/v2.0",
    )
    config.portal_jwt_audience = _prompt(
        "Portal JWT audience",
        hint="Example: api://<api-app-client-id> or app client ID",
    )
    config.portal_jwt_tenant_id = _prompt(
        "Portal JWT tenant ID (optional Entra tid)",
        "",
        hint="Example: Entra directory tenant GUID; leave blank if unused",
    )
    config.portal_required_analyst_role = _prompt(
        "Required analyst role claim (optional)",
        "",
        hint="Example: Analyst",
    )
    config.portal_required_analyst_scope = _prompt(
        "Required analyst scope claim (optional)",
        "",
        hint="Example: api://<api-app-id>/portal.analyst",
    )
    config.portal_cors_allowed_origins = _prompt(
        "Portal CORS allowed origins",
        hint="Example: https://portal.customer.example (scheme + host + port, no path)",
    )

    print("\nECR image (build and push before SAM deploy).")
    config.ecr_repository_uri = _prompt(
        "ECR repository URI (no tag or digest)",
        hint="Example: 123456789012.dkr.ecr.us-east-1.amazonaws.com/notable-analyzer-s3",
    )
    config.image_digest = _prompt(
        "Image digest (sha256:...)",
        "",
        hint="Example: sha256:abc... from ecr describe-images; leave blank until image is pushed",
    )

    config.input_bucket_name = _prompt(
        "Input S3 bucket name",
        hint="Globally unique; notables land under incoming/",
    )
    config.output_bucket_name = _prompt(
        "Output S3 bucket name",
        hint="Globally unique; reports and JSON output",
    )
    config.portal_ui_bucket_name = _prompt(
        "Portal UI S3 bucket name",
        hint="Globally unique; upload analyst-portal dist/ after SAM deploy",
    )

    return config


def load_config_from_json(path: Path) -> PathBConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("answers file must contain a JSON object")
    allowed = PathBConfig().__dict__.keys()
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise ValueError(f"unknown answer keys: {', '.join(unknown)}")
    return PathBConfig(**data)


def validate_config(config: PathBConfig) -> list[str]:
    errors: list[str] = []

    if not _ACCOUNT_RE.fullmatch(config.aws_account_id):
        errors.append("aws_account_id must be a 12-digit commercial AWS account ID")
    if not _ACCOUNT_RE.fullmatch(config.commercial_aws_account_id):
        errors.append("commercial_aws_account_id must be a 12-digit commercial AWS account ID")
    if config.aws_account_id and config.commercial_aws_account_id != config.aws_account_id:
        errors.append("commercial_aws_account_id must match aws_account_id for deploy scripts")

    if config.cmk_mode == "existing":
        if not config.customer_kms_key_arn:
            errors.append("customer_kms_key_arn is required when cmk_mode is existing")
        elif not _KMS_ARN_RE.fullmatch(config.customer_kms_key_arn):
            errors.append("customer_kms_key_arn must be a us-east-1 KMS key ARN")
    elif config.cmk_mode == "skip" and config.customer_kms_key_arn:
        errors.append("customer_kms_key_arn must be empty when cmk_mode is skip")

    if config.vpc_mode == "existing":
        if not _VPC_RE.fullmatch(config.vpc_id):
            errors.append("vpc_id is required and must look like vpc-xxxxxxxx")
        if not config.subnet_ids or not all(_SUBNET_RE.fullmatch(v) for v in config.subnet_ids):
            errors.append("subnet_ids must contain one or more subnet-xxxxxxxx values")
        if not config.lambda_security_group_ids or not all(
            _SG_RE.fullmatch(v) for v in config.lambda_security_group_ids
        ):
            errors.append(
                "lambda_security_group_ids must contain one or more sg-xxxxxxxx values"
            )
    elif config.vpc_mode == "create":
        errors.append(
            "vpc_mode create is not supported for file generation; provision network first, "
            "then re-run with vpc_mode existing"
        )

    if config.opensearch_mode == "create":
        if not _DOMAIN_RE.fullmatch(config.domain_name):
            errors.append("domain_name is required for OpenSearch create mode")
        if not config.admin_principal_arns or not all(
            _IAM_ROLE_ARN_RE.fullmatch(v) for v in config.admin_principal_arns
        ):
            errors.append("admin_principal_arns must contain at least one IAM role ARN")
        if config.instance_count < 1 or config.instance_count > 3:
            errors.append("instance_count must be between 1 and 3")
        if config.volume_size_gib < 10:
            errors.append("volume_size_gib must be at least 10")
    else:
        if not config.opensearch_endpoint or not _HTTPS_URL_RE.fullmatch(config.opensearch_endpoint):
            errors.append("opensearch_endpoint must be an HTTPS URL without credentials")
        if not config.opensearch_domain_arn or not _OPENSEARCH_ARN_RE.fullmatch(
            config.opensearch_domain_arn
        ):
            errors.append("opensearch_domain_arn must be a us-east-1 OpenSearch domain ARN")

    if not config.rag_tenant_id.strip():
        errors.append("rag_tenant_id is required")

    if not config.bedrock_analysis_model_id.strip():
        errors.append("bedrock_analysis_model_id is required")
    if not config.bedrock_analysis_model_arn.strip():
        errors.append("bedrock_analysis_model_arn is required")

    if not config.portal_jwt_issuer.startswith("https://"):
        errors.append("portal_jwt_issuer must be an HTTPS issuer URL")
    if not config.portal_jwt_audience.strip():
        errors.append("portal_jwt_audience is required")
    if not config.portal_required_analyst_role.strip() and not config.portal_required_analyst_scope.strip():
        errors.append("set portal_required_analyst_role and/or portal_required_analyst_scope")
    if not config.portal_cors_allowed_origins.strip():
        errors.append("portal_cors_allowed_origins is required")

    if not config.ecr_repository_uri.startswith(
        f"{config.aws_account_id}.dkr.ecr.us-east-1.amazonaws.com/"
    ):
        errors.append("ecr_repository_uri must be in the target us-east-1 ECR account")
    if config.image_digest and not _DIGEST_RE.fullmatch(config.image_digest):
        errors.append("image_digest must look like sha256:64-hex-chars when set")

    for name, value in (
        ("input_bucket_name", config.input_bucket_name),
        ("output_bucket_name", config.output_bucket_name),
        ("portal_ui_bucket_name", config.portal_ui_bucket_name),
    ):
        if not value.strip():
            errors.append(f"{name} is required")

    return errors


def render_customer_default_env(config: PathBConfig) -> str:
    lines = [
        "# Generated by scripts/configure_path_b.py — review before sam deploy",
        f"AWS_ACCOUNT_ID={config.aws_account_id}",
        f"COMMERCIAL_AWS_ACCOUNT_ID={config.commercial_aws_account_id}",
        f"ECR_REPOSITORY_URI={config.ecr_repository_uri}",
        f"IMAGE_DIGEST={config.image_digest}",
        "",
        f"BEDROCK_ANALYSIS_MODEL_ID={config.bedrock_analysis_model_id}",
        f"BEDROCK_ANALYSIS_MODEL_ARN={config.bedrock_analysis_model_arn}",
        "BEDROCK_ANALYSIS_INFERENCE_PROFILE_FOUNDATION_MODEL_ARNS="
        f"{config.bedrock_analysis_inference_profile_foundation_model_arns}",
        "",
        f"INPUT_BUCKET_NAME={config.input_bucket_name}",
        f"OUTPUT_BUCKET_NAME={config.output_bucket_name}",
        "",
        f"CASE_INDEX_TABLE_NAME={config.case_index_table_name}",
        f"PORTAL_UI_BUCKET_NAME={config.portal_ui_bucket_name}",
        f"PORTAL_JWT_ISSUER={config.portal_jwt_issuer}",
        f"PORTAL_JWT_AUDIENCE={config.portal_jwt_audience}",
        f"PORTAL_JWT_TENANT_ID={config.portal_jwt_tenant_id}",
        f"PORTAL_REQUIRED_ANALYST_ROLE={config.portal_required_analyst_role}",
        f"PORTAL_REQUIRED_ANALYST_SCOPE={config.portal_required_analyst_scope}",
        f"PORTAL_CORS_ALLOWED_ORIGINS={config.portal_cors_allowed_origins}",
        "",
        f"OPENSEARCH_ENDPOINT={config.opensearch_endpoint}",
        f"OPENSEARCH_DOMAIN_ARN={config.opensearch_domain_arn}",
        f"RAG_TENANT_ID={config.rag_tenant_id}",
        "",
        f"CUSTOMER_VPC_SUBNET_IDS={_comma(config.subnet_ids)}",
        f"CUSTOMER_SECURITY_GROUP_IDS={_comma(config.lambda_security_group_ids)}",
        "",
        f"OPENSEARCH_SOC_INDEX={config.opensearch_soc_index}",
        f"OPENSEARCH_SPLUNK_INDEX={config.opensearch_splunk_index}",
        f"OPENSEARCH_CASE_INDEX={config.opensearch_case_index}",
        "",
        f"CUSTOMER_KMS_KEY_ARN={config.customer_kms_key_arn if config.cmk_mode != 'skip' else ''}",
    ]
    return "\n".join(lines) + "\n"


def _hcl_string(value: str) -> str:
    return json.dumps(value)


def _hcl_list(values: list[str], indent: str = "  ") -> str:
    if not values:
        return "[]"
    inner = ",\n".join(f'{indent}  {_hcl_string(v)}' for v in values)
    return f"[\n{inner},\n{indent}]"


def render_opensearch_tfvars(config: PathBConfig) -> str | None:
    if config.opensearch_mode != "create":
        return None

    kms_value = "null" if config.cmk_mode != "existing" else _hcl_string(config.customer_kms_key_arn)
    lines = [
        f"aws_account_id = {_hcl_string(config.aws_account_id)}",
        f"domain_name    = {_hcl_string(config.domain_name)}",
        f"vpc_id         = {_hcl_string(config.vpc_id)}",
        "",
        f"subnet_ids = {_hcl_list(config.subnet_ids)}",
        "",
        f"lambda_security_group_ids = {_hcl_list(config.lambda_security_group_ids)}",
        "",
        f"admin_principal_arns = {_hcl_list(config.admin_principal_arns)}",
        "",
        "# Phase B: add physical Lambda role ARNs after the first SAM deploy.",
        "read_role_arns = []",
        "",
        "write_role_arns = []",
        "",
        f"engine_version  = {_hcl_string(config.engine_version)}",
        f"instance_type   = {_hcl_string(config.instance_type)}",
        f"instance_count  = {config.instance_count}",
        f"volume_size_gib = {config.volume_size_gib}",
        "",
        f"kms_key_arn = {kms_value}",
        "",
        "tags = {",
        '  Environment = "staging"',
        '  Owner       = "security-platform"',
        "}",
        "",
    ]
    return "\n".join(lines)


def render_remaining_steps(config: PathBConfig) -> str:
    steps: list[str] = [
        "# Path B remaining manual steps",
        "",
        "Generated by `scripts/configure_path_b.py`. Complete in order.",
        "",
    ]

    if config.cmk_mode == "create":
        steps.extend(
            [
                "## CMK (optional)",
                "- Terraform: `deploy/terraform/kms/` (or `enable_kms=true` in `deploy/terraform/foundation/`).",
                "- Manual alternative: `docs/operations/deployment/KMS_CUSTOMER_KEY.md`",
                "- Record `CUSTOMER_KMS_KEY_ARN` from `terraform output sam_environment`.",
                "",
            ]
        )
    if config.vpc_mode == "create":
        steps.extend(
            [
                "## VPC/network (required)",
                "- Provision VPC, private subnets, routing, NAT or VPC endpoints (customer-owned).",
                "- Re-run `scripts/configure_path_b.py` with existing network IDs.",
                "",
            ]
        )
    else:
        steps.extend(
            [
                "## Network (Lambda SG)",
                "- Terraform: `deploy/terraform/network/` for Lambda SG + optional VPC endpoints.",
                "- Or foundation stack: `deploy/terraform/foundation/` with `enable_network=true`.",
                "- Runbook: `docs/operations/deployment/VPC_NETWORK_PREREQUISITES.md`",
                "",
            ]
        )
    if config.opensearch_mode == "create":
        steps.extend(
            [
                "## OpenSearch Phase A",
                "- **Standalone:** configure remote state, then `deploy/terraform/opensearch/` (`terraform init`, `plan`, `apply` after approval).",
                "- **Unified:** `deploy/terraform/foundation/` with `enable_opensearch=true` (see `deploy/terraform/README.md`).",
                "- Copy outputs into `customer-default.env` via `terraform output sam_environment`.",
                "- Runbook: `docs/operations/deployment/OPENSEARCH_PROVISIONING.md`",
                "",
            ]
        )
    else:
        steps.extend(
            [
                "## OpenSearch existing domain",
                "- Confirm the domain is VPC-only and Phase B Lambda role ARNs are in the domain policy.",
                "- Runbook: `docs/operations/deployment/OPENSEARCH_PROVISIONING.md`",
                "",
            ]
        )

    steps.extend(
        [
            "## Bedrock",
            "- Confirm approved models are enabled in the commercial account.",
            "- Runbook: `docs/operations/deployment/BEDROCK_ACCOUNT_ENABLEMENT.md`",
            "",
            "## Portal JWT / IdP",
            "- Complete customer IdP setup and verify issuer, audience, and analyst grants.",
            "- Runbook: `docs/operations/deployment/PORTAL_JWT_IDENTITY.md`",
            "",
            "## ECR image",
            "- Terraform (repo only): `deploy/terraform/ecr/` or foundation `enable_ecr=true`.",
            "- Build, push, and record an immutable `IMAGE_DIGEST` before SAM deploy.",
            "- Runbook: `docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md`",
            "",
            "## SAM deploy (Path B step 7)",
            "- `sam build -t deploy/aws/template-sam.yaml`",
            "- Source `customer-default.env`, then deploy with the preset runbook.",
            "- Runbook: `docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`",
            "",
            "## Post-SAM",
            "- OpenSearch Phase B: add deployed Lambda physical role ARNs to the domain policy.",
            "- CMK Phase B (if used): add Lambda role ARNs to the key policy.",
            "- Ingest SOC and Splunk dictionary corpora.",
            "- Build and upload the analyst portal SPA.",
            "- Run smoke tests in `docs/testing/TESTING.md`.",
            "",
        ]
    )
    return "\n".join(steps)


@dataclass
class GeneratedOutputs:
    env_path: Path
    env_content: str
    tfvars_path: Path | None
    tfvars_content: str | None
    checklist_path: Path
    checklist_content: str


def build_outputs(
    config: PathBConfig,
    *,
    env_path: Path = DEFAULT_ENV_PATH,
    tfvars_path: Path = DEFAULT_TFVARS_PATH,
    checklist_path: Path = DEFAULT_CHECKLIST_PATH,
) -> GeneratedOutputs:
    errors = validate_config(config)
    if errors:
        raise ValueError("configuration invalid:\n- " + "\n- ".join(errors))

    return GeneratedOutputs(
        env_path=env_path,
        env_content=render_customer_default_env(config),
        tfvars_path=tfvars_path if config.opensearch_mode == "create" else None,
        tfvars_content=render_opensearch_tfvars(config),
        checklist_path=checklist_path,
        checklist_content=render_remaining_steps(config),
    )


def write_outputs(outputs: GeneratedOutputs) -> None:
    outputs.env_path.write_text(outputs.env_content, encoding="utf-8")
    if outputs.tfvars_path and outputs.tfvars_content is not None:
        outputs.tfvars_path.parent.mkdir(parents=True, exist_ok=True)
        outputs.tfvars_path.write_text(outputs.tfvars_content, encoding="utf-8")
    outputs.checklist_path.write_text(outputs.checklist_content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate Path B customer-default.env, OpenSearch tfvars, and checklist."
    )
    parser.add_argument(
        "--answers-file",
        type=Path,
        help="Load answers from JSON instead of interactive prompts (for CI/tests).",
    )
    parser.add_argument(
        "--env-out",
        type=Path,
        default=DEFAULT_ENV_PATH,
        help=f"Output env file path (default: {DEFAULT_ENV_PATH.name})",
    )
    parser.add_argument(
        "--tfvars-out",
        type=Path,
        default=DEFAULT_TFVARS_PATH,
        help="Output OpenSearch terraform.tfvars path",
    )
    parser.add_argument(
        "--checklist-out",
        type=Path,
        default=DEFAULT_CHECKLIST_PATH,
        help=f"Output checklist path (default: {DEFAULT_CHECKLIST_PATH.name})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print paths only; do not write files.",
    )
    args = parser.parse_args(argv)

    if args.answers_file:
        config = load_config_from_json(args.answers_file)
    else:
        config = collect_interactive()

    try:
        outputs = build_outputs(
            config,
            env_path=args.env_out,
            tfvars_path=args.tfvars_out,
            checklist_path=args.checklist_out,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.dry_run:
        print("Validation passed.")
        print(f"Would write: {outputs.env_path}")
        if outputs.tfvars_path:
            print(f"Would write: {outputs.tfvars_path}")
        print(f"Would write: {outputs.checklist_path}")
        return 0

    write_outputs(outputs)
    print(f"Wrote {outputs.env_path}")
    if outputs.tfvars_path:
        print(f"Wrote {outputs.tfvars_path}")
    print(f"Wrote {outputs.checklist_path}")
    print("Next: follow path-b-remaining-steps.md and the Path B runbooks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
