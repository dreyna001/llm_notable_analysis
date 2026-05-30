#!/usr/bin/env bash
set -euo pipefail

export AWS_ENDPOINT_URL="${AWS_ENDPOINT_URL:-http://localhost:4566}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"

INPUT_BUCKET_NAME="${INPUT_BUCKET_NAME:-notable-local-input}"
OUTPUT_BUCKET_NAME="${OUTPUT_BUCKET_NAME:-notable-local-output}"
SIDE_EFFECT_IDEMPOTENCY_TABLE="${SIDE_EFFECT_IDEMPOTENCY_TABLE:-notable-local-side-effects}"

aws_local() {
  aws --endpoint-url "$AWS_ENDPOINT_URL" "$@"
}

ensure_bucket() {
  local bucket="$1"
  aws_local s3api head-bucket --bucket "$bucket" >/dev/null 2>&1 \
    || aws_local s3 mb "s3://$bucket" >/dev/null
}

ensure_secret() {
  local name="$1"
  local value="$2"
  if aws_local secretsmanager describe-secret --secret-id "$name" >/dev/null 2>&1; then
    aws_local secretsmanager put-secret-value \
      --secret-id "$name" \
      --secret-string "$value" >/dev/null
  else
    aws_local secretsmanager create-secret \
      --name "$name" \
      --secret-string "$value" >/dev/null
  fi
}

ensure_table() {
  if aws_local dynamodb describe-table --table-name "$SIDE_EFFECT_IDEMPOTENCY_TABLE" >/dev/null 2>&1; then
    return
  fi

  aws_local dynamodb create-table \
    --table-name "$SIDE_EFFECT_IDEMPOTENCY_TABLE" \
    --attribute-definitions AttributeName=id,AttributeType=S \
    --key-schema AttributeName=id,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST >/dev/null

  aws_local dynamodb wait table-exists --table-name "$SIDE_EFFECT_IDEMPOTENCY_TABLE"
  aws_local dynamodb update-time-to-live \
    --table-name "$SIDE_EFFECT_IDEMPOTENCY_TABLE" \
    --time-to-live-specification "Enabled=true,AttributeName=expires_at" >/dev/null
}

ensure_bucket "$INPUT_BUCKET_NAME"
ensure_bucket "$OUTPUT_BUCKET_NAME"
ensure_table
ensure_secret "local/splunk/api-token" '{"token":"local-splunk-token"}'
ensure_secret "local/servicenow/api-token" '{"token":"local-servicenow-token"}'
ensure_secret "local/servicenow/approval-hmac" '{"hmac_key":"local-approval-hmac"}'
ensure_secret "local/elasticsearch/api-key" '{"api_key":"local-elasticsearch-key"}'

printf 'LocalStack bootstrap complete at %s\n' "$AWS_ENDPOINT_URL"
