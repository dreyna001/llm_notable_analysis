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

Wave 2 portal slices use the stdlib test runner in this repository layout:

```bash
python -m unittest discover -s s3_notable_pipeline/tests -p "test_portal_handler.py" -v
python -m unittest discover -s s3_notable_pipeline/tests -p "test_case_chat.py" -v
python -m unittest discover -s s3_notable_pipeline/tests -p "test_portal_chat.py" -v
```

Portal frontend checks do not call real AWS:

```bash
npm --prefix s3_notable_pipeline/frontend/analyst-portal test
npm --prefix s3_notable_pipeline/frontend/analyst-portal run build
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
7. For `analyst_portal`, confirm case archive objects, CaseIndex rows, and
   retrieval chunks are present before opening the static SPA.

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

These checks require configured AWS credentials, a deployed non-production stack,
and any external integrations that profile enables. They are **not** run by
`python -m pytest tests`.

### Wave 1 staging checklist

Run profile slices incrementally. Start with `CapabilityProfiles=core` and
`SplunkSinkMode=s3`, then enable one parity profile at a time.

| Profile slice | Deploy prerequisites | Staging validation |
| --- | --- | --- |
| **core** | Default SAM parameters; Bedrock model access | Upload `data/test-notable.txt` to `incoming/`; confirm markdown + JSON under `reports/`; review CloudWatch logs for bounded metadata without secrets |
| **html_reports** | `CapabilityProfiles=core,html_reports`, `HtmlReportEnabled=true` | Confirm sibling `.html` object beside markdown/JSON |
| **rag** | `CapabilityProfiles=core,rag`, `RagEnabled=true`, `RagBedrockKbId` | JSON `metadata.rag_status` is `success` or `no_match`; analysis completes when `RagFailureMode=suppress` |
| **spl_readonly** | `CapabilityProfiles=core,rag,spl_readonly`; Splunk URL + token secret; optional `SplQueryRagBedrockKbId` | JSON includes SPL generation metadata and/or `investigation_query_results`; denied SPL commands do not outbound; Splunk allowlists enforced |
| **elastic_readonly** | `CapabilityProfiles=core,rag,elastic_readonly` (not with `spl_readonly`); Elastic URL + API key secret + index allowlist; optional `ElasticsearchGroundingBedrockKbId` | JSON `metadata.investigation_query_backend=elasticsearch` with bounded `investigation_query_results` |
| **ticket_draft** | `CapabilityProfiles=core,ticket_draft`, `ServiceNowAssignmentGroup` | JSON `servicenow_section.draft` present; no ServiceNow POST unless create is separately enabled |
| **action_gated** | `CapabilityProfiles=core,action_gated`; Splunk writeback and/or ServiceNow secrets as needed; `SideEffectIdempotencyTableName` | DynamoDB idempotency table exists; replay duplicate side-effect keys and confirm no duplicate Splunk/ServiceNow writes |

Helper script (live AWS, optional):

```powershell
# Core smoke (default behavior unchanged)
.\scripts\test-pipeline.ps1

# Auto-detect deployed profiles and run matching Wave 1 checks
.\scripts\test-pipeline.ps1 -Wave1Smoke

# Assert a specific profile bundle in staging
.\scripts\test-pipeline.ps1 -Wave1Smoke -ExpectCapabilityProfiles "core,rag,spl_readonly"
```

Manual follow-ups still required for **action_gated** idempotency replay, signed
ServiceNow create approval, and Splunk `notable_rest` writeback. See
`docs/operations/CAPABILITY_PROFILES.md`, `SERVICENOW_OPERATIONS.md`, and
`SPLUNK_WRITEBACK_OPERATIONS.md`.

### Wave 2 portal staging checklist

This checklist is optional real AWS validation and must run only in an approved
dev/staging/prod account.

| Profile slice | Deploy prerequisites | Staging validation |
| --- | --- | --- |
| **analyst_portal** | `CapabilityProfiles=core,analyst_portal`; `CaseArchiveBucketName`; `CaseIndexTableName`; JWT issuer/audience; portal CORS origin; optional `PortalUiBucketName` | After deploy, record `PortalBrowserApiBaseUrl`, `PortalApiUrl`, and `PortalChatFunctionUrl`; upload a representative notable; confirm archive envelope, chunks, and CaseIndex `retrieval_status=ready`; load `/`, `/cases`, and `/cases/{case_id}` through the SPA; ask a selected-case question and confirm cited answer |

See [`../operations/ANALYST_PORTAL_OPERATIONS.md`](../operations/ANALYST_PORTAL_OPERATIONS.md).
