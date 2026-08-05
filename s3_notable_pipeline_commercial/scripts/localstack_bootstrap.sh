#!/usr/bin/env bash
set -euo pipefail

export AWS_ENDPOINT_URL="${AWS_ENDPOINT_URL:-http://localhost:4566}"
case "$AWS_ENDPOINT_URL" in
  http://localhost:4566|http://localhost:4566/|http://127.0.0.1:4566|http://127.0.0.1:4566/) ;;
  *) printf 'AWS_ENDPOINT_URL must be a loopback LocalStack URL on port 4566\n' >&2; exit 2 ;;
esac
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
unset AWS_SESSION_TOKEN AWS_PROFILE
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"

INPUT_BUCKET_NAME="${INPUT_BUCKET_NAME:-notable-local-input}"
OUTPUT_BUCKET_NAME="${OUTPUT_BUCKET_NAME:-notable-local-output}"
SIDE_EFFECT_IDEMPOTENCY_TABLE="${SIDE_EFFECT_IDEMPOTENCY_TABLE:-notable-local-side-effects}"
ANALYZER_QUEUE_NAME="${ANALYZER_QUEUE_NAME:-notable-local-analyzer}"
ANALYZER_DLQ_NAME="${ANALYZER_DLQ_NAME:-notable-local-analyzer-dlq}"
CASE_EMBED_QUEUE_NAME="${CASE_EMBED_QUEUE_NAME:-notable-local-case-embed}"
CASE_EMBED_DLQ_NAME="${CASE_EMBED_DLQ_NAME:-notable-local-case-embed-dlq}"
RAG_INGEST_QUEUE_NAME="${RAG_INGEST_QUEUE_NAME:-notable-local-rag-ingest}"
RAG_INGEST_DLQ_NAME="${RAG_INGEST_DLQ_NAME:-notable-local-rag-ingest-dlq}"

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

ensure_queue_pair() {
  local queue_name="$1"
  local dlq_name="$2"
  local dlq_url dlq_arn

  dlq_url="$(aws_local sqs create-queue --queue-name "$dlq_name" --query QueueUrl --output text)"
  dlq_arn="$(aws_local sqs get-queue-attributes \
    --queue-url "$dlq_url" \
    --attribute-names QueueArn \
    --query Attributes.QueueArn \
    --output text)"
  aws_local sqs create-queue \
    --queue-name "$queue_name" \
    --attributes "RedrivePolicy={\"deadLetterTargetArn\":\"$dlq_arn\",\"maxReceiveCount\":\"5\"},VisibilityTimeout=900" \
    >/dev/null
}

ensure_bucket "$INPUT_BUCKET_NAME"
ensure_bucket "$OUTPUT_BUCKET_NAME"
ensure_table
ensure_queue_pair "$ANALYZER_QUEUE_NAME" "$ANALYZER_DLQ_NAME"
ensure_queue_pair "$CASE_EMBED_QUEUE_NAME" "$CASE_EMBED_DLQ_NAME"
ensure_queue_pair "$RAG_INGEST_QUEUE_NAME" "$RAG_INGEST_DLQ_NAME"
ensure_secret "local/splunk/api-token" '{"token":"local-splunk-token"}'
ensure_secret "local/servicenow/api-token" '{"token":"local-servicenow-token"}'
ensure_secret "local/servicenow/approval-hmac" '{"hmac_key":"local-approval-hmac"}'
ensure_secret "local/elasticsearch/api-key" '{"api_key":"local-elasticsearch-key"}'

printf 'LocalStack bootstrap complete at %s\n' "$AWS_ENDPOINT_URL"
