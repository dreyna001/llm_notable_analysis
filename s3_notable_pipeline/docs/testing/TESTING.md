# Testing

## Unit Tests

Unit tests must not call live AWS, Bedrock, Splunk, Elasticsearch, ServiceNow,
or MCP endpoints. Mock AWS clients and HTTP calls, and keep fixtures bounded.

Run the full Python test suite from `s3_notable_pipeline`:

```bash
python -m pytest tests
```

This command includes LocalStack integration tests, but they skip unless
`RUN_LOCALSTACK_INTEGRATION=true` and `AWS_ENDPOINT_URL` points to a local
endpoint.

Focused parity slices:

```bash
python -m pytest tests/test_config.py
python -m pytest tests/test_bedrock_kb_retrieval.py
python -m pytest tests/test_spl_query_generation.py tests/test_splunk_investigation.py
python -m pytest tests/test_query_result_enrichment.py tests/test_query_result_interpretation.py
python -m pytest tests/test_idempotency.py tests/test_servicenow.py
python -m pytest tests/test_elastic_query_generation.py tests/test_elasticsearch_investigation.py
```

## Smoke Validation

For a deployed non-production stack:

1. Upload a small representative notable to `incoming/`.
2. Confirm JSON and markdown reports are written under `reports/`.
3. If `html_reports` is enabled, confirm the HTML object is also written.
4. Confirm CloudWatch logs show bounded status metadata without secrets.
5. For read-only investigation profiles, confirm denied generated queries do not
   make outbound calls and successful calls produce `investigation_query_results`.
6. For writeback or ServiceNow create, confirm duplicate events do not duplicate
   side effects when idempotency is enabled.

## LocalStack Integration Tests

Use LocalStack to exercise AWS SDK integration and local data flow without real
AWS credentials.

The compose file pins the LocalStack image tag because current `latest` images
require a LocalStack auth token even for local community-style usage.

Start LocalStack from `s3_notable_pipeline`:

```bash
docker compose up -d
```

Load the local env and bootstrap local resources.

PowerShell:

```powershell
Get-Content .env.local | ForEach-Object {
  if ($_ -and -not $_.StartsWith("#")) {
    $name, $value = $_.Split("=", 2)
    Set-Item -Path "env:$name" -Value $value
  }
}
.\scripts\localstack_bootstrap.ps1
python -m pytest tests/integration -m integration
```

Bash:

```bash
set -a
source .env.local
set +a
bash scripts/localstack_bootstrap.sh
python -m pytest tests/integration -m integration
```

The integration test creates its own S3 bucket, DynamoDB table, and Secrets
Manager secret, then cleans them up. The bootstrap script creates stable local
resources for manual smoke testing.

## SAM Local Smoke

`events/s3-placeholder-event.json` is a safe handler-startup event that points at
`incoming/.keep`, so it should skip before reading S3 or calling Bedrock.
`events/sam-local-env.json` contains local-only fake AWS credentials.

The SAM template uses `PackageType: Image`; build or tag a compatible local
Lambda image before invoking. Then run:

```bash
sam local invoke NotableAnalyzerFunction \
  --template-file deploy/aws/template-sam.yaml \
  --event events/s3-placeholder-event.json \
  --env-vars events/sam-local-env.json \
  --parameter-overrides AwsAccountId=000000000000 ImageUri=notable-analyzer-s3:local
```

This smoke validates local handler startup and S3 event parsing. It does not
replace a real Bedrock or IAM validation pass.

## Real AWS Validation

Real AWS, Splunk, Elasticsearch, ServiceNow, or customer MCP validation must be
explicit dev/staging/prod validation, not a default unit-test dependency.
