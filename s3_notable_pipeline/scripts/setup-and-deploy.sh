#!/usr/bin/env bash
# Setup and Deploy Script for Notable Analyzer Pipeline
# Prerequisites: AWS CLI, SAM CLI, Docker must be installed
#
# Readiness: publish the image to GovCloud ECR and capture its immutable digest first.

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

echo
echo "Checking AWS credentials..."
if identity="$(aws sts get-caller-identity 2>&1)"; then
  echo "  AWS credentials configured"
  echo "$identity"
else
  echo "  AWS credentials not configured"
  echo "  Run: aws configure"
  exit 1
fi

echo
echo "Checking Bedrock access..."
region="us-gov-east-1"
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
echo "Before deploy: ensure EcrRepositoryUri and ImageDigest identify the approved image in us-gov-east-1."
echo "Before RAG/portal: complete docs/operations/deployment/OPENSEARCH_PROVISIONING.md"
echo
echo "=== Step 1: Building application ==="
echo "Running: sam validate --lint --template-file $SAM_TEMPLATE"
if ! sam validate --lint --template-file "$SAM_TEMPLATE"; then
  echo "SAM template validation failed"
  exit 1
fi
echo "Running: sam build -t $SAM_TEMPLATE"
if ! sam build -t "$SAM_TEMPLATE"; then
  echo "Build failed"
  exit 1
fi

echo
echo "=== Step 2: Deploying to AWS ==="
if [ -f "samconfig.toml" ]; then
  echo "Found samconfig.toml - using existing configuration"
  echo "Running: sam deploy --template-file $SAM_BUILT_TEMPLATE"
  if ! sam deploy --template-file "$SAM_BUILT_TEMPLATE"; then
    echo "Deployment failed"
    exit 1
  fi
else
  echo "No samconfig.toml found - running guided deployment"
  echo "Running: sam deploy --guided --template-file $SAM_BUILT_TEMPLATE"
  echo
  echo "You'll be prompted for:"
  echo "  - Stack name (e.g., notable-analyzer-stack)"
  echo "  - AWS Region (us-gov-east-1)"
  echo "  - Input bucket name (must be globally unique)"
  echo "  - Output bucket name (must be globally unique)"
  echo "  - Splunk sink mode ('s3' or 'notable_rest'; use 's3' for testing)"
  echo "  - AwsAccountId, EcrRepositoryUri, ImageDigest, and BedrockAnalysisModelId"
  echo "  - If notable_rest: SplunkBaseUrl + SplunkApiTokenSecretArn (Secrets Manager ARN)"
  echo "  - Optional: SplunkApiTokenSecretField (default 'token') and SplunkNotableUpdatePath"
  if ! sam deploy --guided --template-file "$SAM_BUILT_TEMPLATE"; then
    echo "Deployment failed"
    exit 1
  fi
fi

echo
echo "Deployment complete!"
echo
echo "Next steps:"
echo "  1. Run scripts/test-pipeline.ps1 from PowerShell, or follow the manual test flow in README."
