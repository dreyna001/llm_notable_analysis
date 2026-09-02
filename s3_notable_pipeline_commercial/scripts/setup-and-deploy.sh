#!/usr/bin/env bash
set -euo pipefail

# Commercial AWS Path B. Path A and Path C continue to use the legacy SAM runbooks.

usage() {
  echo "Usage: $0 [--apply] [--bootstrap-ecr] [--var-file PATH] [--backend-config PATH]"
  echo "  default          validate and create a saved Terraform plan"
  echo "  --apply          create, show, and apply the saved plan"
  echo "  --bootstrap-ecr  plan/apply only module.ecr[0] before the first image push"
}

apply_plan=0
bootstrap_ecr=0
var_file="terraform.tfvars"
backend_config="backend.hcl"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply) apply_plan=1 ;;
    --bootstrap-ecr) bootstrap_ecr=1 ;;
    --var-file)
      shift
      if [ "$#" -eq 0 ]; then
        echo "--var-file requires a path" >&2
        exit 2
      fi
      var_file="$1"
      ;;
    --backend-config)
      shift
      if [ "$#" -eq 0 ]; then
        echo "--backend-config requires a path" >&2
        exit 2
      fi
      backend_config="$1"
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$script_dir/.." && pwd)"
tf_root="deploy/terraform/customer_default"
cd "$project_dir"

for command_name in aws terraform; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "$command_name is required" >&2
    exit 1
  fi
done

region="us-east-1"
if [ -n "${AWS_REGION:-}" ] && [ -n "${AWS_DEFAULT_REGION:-}" ] && [ "$AWS_REGION" != "$AWS_DEFAULT_REGION" ]; then
  echo "AWS_REGION and AWS_DEFAULT_REGION disagree; both must be $region."
  exit 1
fi
configured_region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
if [ -z "$configured_region" ]; then
  configured_region="$(aws configure get region 2>/dev/null || true)"
fi
if [ "$configured_region" != "$region" ]; then
  echo "Configured AWS region must be $region; found: ${configured_region:-<unset>}"
  exit 1
fi

expected_account_id="${COMMERCIAL_AWS_ACCOUNT_ID:-}"
if [[ ! "$expected_account_id" =~ ^[0-9]{12}$ ]]; then
  echo "Set COMMERCIAL_AWS_ACCOUNT_ID to the approved 12-digit commercial AWS account."
  exit 1
fi
caller_account="$(aws sts get-caller-identity --region "$region" --query Account --output text 2>/dev/null)"
caller_arn="$(aws sts get-caller-identity --region "$region" --query Arn --output text 2>/dev/null)"
if [ "$caller_account" != "$expected_account_id" ]; then
  echo "AWS caller account $caller_account does not match approved account $expected_account_id."
  exit 1
fi
case "$caller_arn" in
  arn:aws:*) ;;
  *) echo "AWS caller ARN is not in the commercial aws partition: $caller_arn"; exit 1 ;;
esac

if [ ! -f "$tf_root/$var_file" ]; then
  echo "Missing $tf_root/$var_file; run python scripts/configure_path_b.py first."
  exit 1
fi
if [ ! -f "$tf_root/$backend_config" ]; then
  echo "Missing $tf_root/$backend_config; copy backend.hcl.example and set the approved remote state location."
  exit 1
fi

echo "Account: $caller_account"
echo "Region: $region"
echo "Terraform root: $tf_root"
terraform "-chdir=$tf_root" fmt -check
terraform "-chdir=$tf_root" init "-backend-config=$backend_config"
terraform "-chdir=$tf_root" validate

plan_name="customer-default.tfplan"
if [ "$bootstrap_ecr" -eq 1 ]; then
  plan_name="bootstrap-ecr.tfplan"
fi

if [ "$apply_plan" -eq 0 ]; then
  plan_args=(plan "-var-file=$var_file" -out="$plan_name")
  if [ "$bootstrap_ecr" -eq 1 ]; then
    plan_args=(plan "-var-file=$var_file" '-var=deploy_application=false' '-target=module.ecr[0]' -out="$plan_name")
  fi
  terraform "-chdir=$tf_root" "${plan_args[@]}"
  terraform "-chdir=$tf_root" show "$plan_name"
  echo "Plan saved at $tf_root/$plan_name. Review it, then rerun with --apply."
  exit 0
fi

if [ ! -f "$tf_root/$plan_name" ]; then
  echo "Missing reviewed plan $tf_root/$plan_name; run the matching plan-only command first."
  exit 1
fi
terraform "-chdir=$tf_root" show "$plan_name"
terraform "-chdir=$tf_root" apply "$plan_name"
terraform "-chdir=$tf_root" output -json
echo "Terraform apply complete. Follow the validation steps in docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md."
