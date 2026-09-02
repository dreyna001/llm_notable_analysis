#!/usr/bin/env python3
"""Validate GovCloud customer-default inputs and write a deployment report."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARTITION = "aws-us-gov"
REGION = "us-gov-east-1"
PRODUCT = "llm-notable-analysis-govcloud"

REQUIRED_KEYS = (
    "AWS_ACCOUNT_ID",
    "ECR_REPOSITORY_URI",
    "IMAGE_DIGEST",
    "BEDROCK_ANALYSIS_MODEL_ID",
    "BEDROCK_ANALYSIS_MODEL_ARN",
    "INPUT_BUCKET_NAME",
    "OUTPUT_BUCKET_NAME",
    "CASE_INDEX_TABLE_NAME",
    "PORTAL_UI_BUCKET_NAME",
    "PORTAL_JWT_ISSUER",
    "PORTAL_JWT_AUDIENCE",
    "PORTAL_CORS_ALLOWED_ORIGINS",
    "OPENSEARCH_ENDPOINT",
    "OPENSEARCH_DOMAIN_ARN",
    "RAG_TENANT_ID",
    "CUSTOMER_VPC_SUBNET_IDS",
    "CUSTOMER_SECURITY_GROUP_IDS",
)
PLACEHOLDER = re.compile(r"<[^>]+>|REPLACE_ME|CHANGEME", re.IGNORECASE)
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def validate_values(values: dict[str, str]) -> list[str]:
    errors = [key for key in REQUIRED_KEYS if not values.get(key, "").strip()]
    messages = [f"missing required value: {key}" for key in errors]
    for key, value in values.items():
        if value and PLACEHOLDER.search(value):
            messages.append(f"placeholder remains: {key}")
    account_id = values.get("AWS_ACCOUNT_ID", "")
    if account_id and not re.fullmatch(r"[0-9]{12}", account_id):
        messages.append("AWS_ACCOUNT_ID must be 12 digits")
    digest = values.get("IMAGE_DIGEST", "")
    if digest and not DIGEST.fullmatch(digest):
        messages.append("IMAGE_DIGEST must be an immutable sha256 digest")
    if values.get("PORTAL_JWT_ISSUER") and not values["PORTAL_JWT_ISSUER"].startswith("https://"):
        messages.append("PORTAL_JWT_ISSUER must use HTTPS")
    return messages


def run_sam_validation() -> tuple[bool, str]:
    if not shutil.which("sam"):
        return False, "SAM CLI is not installed"
    result = subprocess.run(
        ["sam", "validate", "--lint", "--template-file", "deploy/aws/template-sam.yaml"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    detail = (result.stdout or result.stderr).strip()
    return result.returncode == 0, detail[-1000:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / "customer-default.env")
    parser.add_argument("--report-out", type=Path, default=PROJECT_ROOT / "deployment-readiness-report.json")
    parser.add_argument("--skip-sam-validation", action="store_true", help="Only for deterministic local contract tests")
    args = parser.parse_args(argv)

    checks: list[dict[str, object]] = []
    errors: list[str] = []
    try:
        values = load_env(args.env_file)
        errors = validate_values(values)
        checks.append({"name": "customer_inputs", "passed": not errors, "details": errors})
    except (OSError, ValueError) as exc:
        values = {}
        errors = [str(exc)]
        checks.append({"name": "customer_inputs", "passed": False, "details": errors})

    if not args.skip_sam_validation:
        passed, detail = run_sam_validation()
        checks.append({"name": "sam_validate_lint", "passed": passed, "details": detail})
        if not passed:
            errors.append(detail)

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "product": PRODUCT,
        "target": {"partition": PARTITION, "region": REGION, "account_id": values.get("AWS_ACCOUNT_ID", "")},
        "status": "ready" if not errors else "blocked",
        "checks": checks,
        "customer_actions_after_deploy": [
            "Update OpenSearch and optional KMS policies with deployed Lambda role ARNs",
            "Ingest approved knowledge corpora",
            "Upload the analyst portal build",
            "Run the live-cloud acceptance checklist",
        ],
    }
    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Deployment readiness: {report['status']}")
    print(f"Report: {args.report_out}")
    for error in errors:
        print(f"- {error}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
