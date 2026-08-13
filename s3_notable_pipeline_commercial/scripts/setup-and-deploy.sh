#!/usr/bin/env bash
# Setup and Deploy Script for Notable Analyzer Pipeline
# Prerequisites: AWS CLI, SAM CLI, Docker must be installed
#
# Readiness: publish the image to commercial us-east-1 ECR and capture its immutable digest first.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SAM_TEMPLATE="deploy/aws/template-sam.yaml"
SAM_BUILT_TEMPLATE=".aws-sam/build/template.yaml"
cd "$PROJECT_DIR"

echo "=== Notable Analyzer Pipeline - Setup and Deploy ==="

echo
echo "Checking prerequisites..."

missing=()

check_cmd() {
  local cmd="$1"
  local label="$2"
  local install_hint="$3"

  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "  ${label} not found"
    missing+=("$install_hint")
    return
  fi

  echo "  ${label} found"
  "$cmd" --version
}

check_cmd "aws" "AWS CLI" "AWS CLI (https://aws.amazon.com/cli/)"
check_cmd "sam" "SAM CLI" "SAM CLI (https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)"
check_cmd "docker" "Docker" "Docker (https://www.docker.com/products/docker-desktop)"

if [ "${#missing[@]}" -gt 0 ]; then
  echo
  echo "Missing prerequisites:"
  for item in "${missing[@]}"; do
    echo "  - ${item}"
  done
  echo
  echo "Please install the missing tools and run this script again."
  exit 1
fi

region="us-east-1"

echo
echo "Checking commercial AWS deployment boundary..."
if [ -n "${AWS_REGION:-}" ] && [ -n "${AWS_DEFAULT_REGION:-}" ] && [ "$AWS_REGION" != "$AWS_DEFAULT_REGION" ]; then
  echo "  AWS_REGION and AWS_DEFAULT_REGION disagree; both must be $region."
  exit 1
fi

configured_region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
if [ -z "$configured_region" ]; then
  configured_region="$(aws configure get region 2>/dev/null || true)"
fi
if [ "$configured_region" != "$region" ]; then
  echo "  Configured AWS region must be $region; found: ${configured_region:-<unset>}"
  exit 1
fi

expected_account_id="${COMMERCIAL_AWS_ACCOUNT_ID:-}"
if [[ ! "$expected_account_id" =~ ^[0-9]{12}$ ]]; then
  echo "  Set COMMERCIAL_AWS_ACCOUNT_ID to the approved 12-digit commercial AWS account."
  exit 1
fi

if ! caller_account="$(aws sts get-caller-identity --region "$region" --query Account --output text 2>/dev/null)"; then
  echo "  AWS credentials are unavailable or STS caller identity failed."
  exit 1
fi
if ! caller_arn="$(aws sts get-caller-identity --region "$region" --query Arn --output text 2>/dev/null)"; then
  echo "  Unable to resolve the AWS caller ARN."
  exit 1
fi
if [[ ! "$caller_account" =~ ^[0-9]{12}$ ]]; then
  echo "  STS returned an invalid AWS account ID."
  exit 1
fi
if [ "$caller_account" != "$expected_account_id" ]; then
  echo "  AWS caller account $caller_account does not match approved account $expected_account_id."
  exit 1
fi
case "$caller_arn" in
  arn:aws:*) ;;
  *)
    echo "  AWS caller ARN is not in the commercial aws partition: $caller_arn"
    exit 1
    ;;
esac

credential_source="${AWS_PROFILE:-default credential chain}"
echo "  Account: $caller_account"
echo "  Caller: $caller_arn"
echo "  Partition: aws"
echo "  Region: $region"
echo "  Credential source: $credential_source"

echo
echo "Checking Bedrock access..."
nova_models=""
claude_profiles=""
nova_available=0
claude_available=0

if nova_models="$(aws bedrock list-foundation-models --region "$region" --query "modelSummaries[?contains(modelId, 'nova-pro')].modelId" --output text 2>/dev/null)"; then
  if [ -n "$nova_models" ] && [ "$nova_models" != "None" ]; then
    nova_available=1
  fi
fi

if claude_profiles="$(aws bedrock list-inference-profiles --region "$region" --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'claude-sonnet-4-6')].inferenceProfileId" --output text 2>/dev/null)"; then
  if [ -n "$claude_profiles" ] && [ "$claude_profiles" != "None" ]; then
    claude_available=1
  fi
fi

if [ "$nova_available" -eq 1 ] || [ "$claude_available" -eq 1 ]; then
  echo "  Bedrock access confirmed"
  if [ "$nova_available" -eq 1 ]; then
    echo "  Available Nova Pro models: $nova_models"
  fi
  if [ "$claude_available" -eq 1 ]; then
    echo "  Available Claude Sonnet 4.6 inference profiles: $claude_profiles"
  fi
  echo "  Validate deploy-time values still match template parameters (AwsAccountId, model/profile, region)."
else
  echo "  Could not verify Nova Pro models or Claude Sonnet 4.6 inference profiles (may need model/profile access request)."
fi

echo
echo "Before deploy: ensure EcrRepositoryUri and ImageDigest identify the approved image in us-east-1."
echo
echo "=== Step 1: Building application ==="
echo "Running: sam build -t $SAM_TEMPLATE"
if ! sam build -t "$SAM_TEMPLATE"; then
  echo "Build failed"
  exit 1
fi

echo
echo "=== Wave 1 Parity Parameters (reference) ==="
echo "Defaults are core-only and safe for first deploy. Enable parity profiles only in dev/staging after prerequisites are ready."
echo "See docs/operations/platform/CAPABILITY_PROFILES.md and config.env.example for full contracts."
echo
echo "  CapabilityProfiles (default: core)"
echo "    core                          - required base analysis path"
echo "    core,html_reports             - add escaped HTML companion reports"
echo "    core,rag                      - private OpenSearch advisory context (set RagEnabled=true)"
echo "    core,rag,spl_readonly         - SPL generation + read-only Splunk investigation (SplunkBaseUrl, token secret)"
echo "    core,rag,elastic_readonly     - Elasticsearch read-only investigation (mutually exclusive with spl_readonly)"
echo "    core,ticket_draft             - ServiceNow draft payloads in JSON reports"
echo "    core,action_gated             - Splunk writeback / ServiceNow create + DynamoDB idempotency"
echo
echo "  OpenSearch grounding"
echo "    OpenSearchEndpoint, OpenSearchDomainArn, RagTenantId, private VPC IDs"
echo "    SplQueryRagEnabled / ElasticsearchGroundingEnabled enable dictionary lanes"
echo
echo "  Safe first deploy: CapabilityProfiles=core, SplunkSinkMode=s3, HtmlReportEnabled=false, RagEnabled=false"
echo ""
echo "  Customer-default preset (core,rag,analyst_portal):"
echo "    docs/operations/deployment/OPENSEARCH_PROVISIONING.md (Step 0)"
echo "    docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md"
echo "    deploy/aws/presets/customer-default.env.example"
echo "    deploy/aws/presets/samconfig.customer-default.toml.example"

echo
echo "=== Step 2: Deploying to AWS ==="
if [ -f "samconfig.toml" ]; then
  echo "Found samconfig.toml - using existing configuration"
  echo "Running: sam deploy --region $region --template-file $SAM_BUILT_TEMPLATE"
  if ! sam deploy --region "$region" --template-file "$SAM_BUILT_TEMPLATE"; then
    echo "Deployment failed"
    exit 1
  fi
else
  echo "No samconfig.toml found - running guided deployment"
  echo "Running: sam deploy --guided --region $region --template-file $SAM_BUILT_TEMPLATE"
  echo
  echo "You'll be prompted for:"
  echo "  - Stack name (e.g., notable-analyzer-stack)"
  echo "  - AWS Region (us-east-1)"
  echo "  - Input bucket name (must be globally unique)"
  echo "  - Output bucket name (must be globally unique)"
  echo "  - Splunk sink mode ('s3' or 'notable_rest'; use 's3' for testing)"
  echo "  - AwsAccountId, EcrRepositoryUri, ImageDigest, BedrockAnalysisModelId, and BedrockAnalysisModelArn"
  echo "  - If notable_rest: SplunkBaseUrl + SplunkApiTokenSecretArn (Secrets Manager ARN)"
  echo "  - Optional: SplunkApiTokenSecretField (default 'token') and SplunkNotableUpdatePath"
  if ! sam deploy --guided --region "$region" --template-file "$SAM_BUILT_TEMPLATE"; then
    echo "Deployment failed"
    exit 1
  fi
fi

echo
echo "Deployment complete!"
echo
echo "Next steps:"
echo "  1. Run scripts/test-pipeline.ps1 from PowerShell, or follow the manual test flow in README."
