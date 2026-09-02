#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "$script_dir/.." && pwd)"
terraform_root="$project_root/deploy/terraform"

command -v terraform >/dev/null 2>&1 || {
  echo "terraform is required (version 1.15.9)" >&2
  exit 1
}
command -v checkov >/dev/null 2>&1 || {
  echo "checkov is required; install requirements-terraform.txt" >&2
  exit 1
}

terraform fmt -check -recursive "$terraform_root"

while IFS= read -r module_dir; do
  terraform -chdir="$module_dir" init -backend=false -input=false
  terraform -chdir="$module_dir" validate
done < <(find "$terraform_root" -mindepth 1 -maxdepth 1 -type d \
  -exec find "{}" -maxdepth 1 -type f -name '*.tf' -printf '%h\n' \; | sort -u)

(
  cd "$project_root/.."
  python3 -m unittest \
    s3_notable_pipeline_commercial.tests.test_terraform_modules \
    s3_notable_pipeline_commercial.tests.test_opensearch_terraform \
    s3_notable_pipeline_commercial.tests.test_path_b_deploy_configurator \
    s3_notable_pipeline_commercial.tests.test_deploy_scripts \
    s3_notable_pipeline_commercial.tests.test_documentation_contract \
    s3_notable_pipeline_commercial.tests.test_terraform_ci
)

checkov \
  --directory "$terraform_root" \
  --framework terraform \
  --download-external-modules false \
  --skip-download \
  --quiet \
  --compact
