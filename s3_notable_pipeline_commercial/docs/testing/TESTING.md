# Testing

Canonical commands for unit, smoke, integration, and staging validation on
commercial AWS. **Deploy path terminus:** all paths in
[`../../README.md`](../../README.md) section 5 end here.

## Golden Eval

Offline disposition rubric tests for the fixed `data/golden_eval/` corpus. See
[`GOLDEN_EVAL.md`](GOLDEN_EVAL.md) for corpus details, live Bedrock opt-in, and
how to add cases.

## Unit Tests

Unit tests must not call live AWS, Bedrock, Splunk, Elasticsearch, ServiceNow,
or MCP endpoints. Mock AWS clients and HTTP calls, and keep fixtures bounded.

### Python environment (local or CI)

From the commercial project root with Python **3.12+**:

```bash
python -m venv .venv
```

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

Bash:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
```

Runtime pins match `requirements.txt` (Lambda image). `boto3` is listed in
`pyproject.toml` for local runs and tests because the Lambda base image provides
it at deploy time. Test-only packages (`pytest`, `PyYAML`) install via the
`test` extra.

Run the full Python test suite from the commercial project root (with the venv active):

```bash
python -m pytest tests
```

This command includes LocalStack integration tests, but they skip unless
`RUN_LOCALSTACK_INTEGRATION=true` and `AWS_ENDPOINT_URL` points to a local
endpoint.

Focused parity slices:

```bash
python -m pytest tests/test_golden_eval.py -v
python -m pytest tests/test_config.py
python -m pytest tests/test_bedrock_kb_retrieval.py
python -m pytest tests/test_spl_query_generation.py tests/test_splunk_investigation.py
python -m pytest tests/test_query_result_enrichment.py tests/test_query_result_interpretation.py
python -m pytest tests/test_idempotency.py tests/test_servicenow.py
python -m pytest tests/test_elastic_query_generation.py tests/test_elasticsearch_investigation.py
```

Portal handler unit tests (from commercial project root):

```bash
python -m pytest tests/test_portal_handler.py tests/test_portal_jwt.py tests/test_case_index.py tests/test_case_chat_history.py -q
python -m pytest tests/test_case_chat.py tests/test_portal_chat.py -q
```

Portal frontend checks do not call real AWS:

```bash
npm ci --prefix frontend/analyst-portal
npm --prefix frontend/analyst-portal test
npm --prefix frontend/analyst-portal run build
```

## Smoke Validation

For a deployed non-production stack (see also Wave 1 **core** row below):

1. Upload a small representative notable to `incoming/`.
2. Confirm JSON and markdown reports under `reports/`; HTML when `html_reports` enabled.
3. Confirm CloudWatch logs show bounded status metadata without secrets.
4. For read-only investigation profiles: denied generated queries do not outbound;
   successful calls produce `investigation_query_results`.
5. For writeback or ServiceNow create: duplicate events do not duplicate side
   effects when idempotency is enabled.
6. For `analyst_portal`: case archive objects, CaseIndex rows, and retrieval
   chunks present before opening the SPA.

## LocalStack Integration Tests

Use LocalStack to exercise AWS SDK integration and local data flow without real
AWS credentials.

The compose file pins the LocalStack image tag because current `latest` images
require a LocalStack auth token even for local community-style usage.

Start LocalStack from the commercial project root:

```bash
docker compose up -d
```

Set local AWS emulator env vars, bootstrap local resources, then run integration
tests (they skip unless `RUN_LOCALSTACK_INTEGRATION=true` and
`AWS_ENDPOINT_URL` points at LocalStack):

PowerShell:

```powershell
$env:AWS_ENDPOINT_URL = "http://localhost:4566"
$env:AWS_ACCESS_KEY_ID = "test"
$env:AWS_SECRET_ACCESS_KEY = "test"
$env:AWS_REGION = "us-east-1"
$env:RUN_LOCALSTACK_INTEGRATION = "true"
.\scripts\localstack_bootstrap.ps1
python -m pytest tests/integration -m integration -v
```

Bash:

```bash
export AWS_ENDPOINT_URL=http://localhost:4566
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_REGION=us-east-1
export RUN_LOCALSTACK_INTEGRATION=true
bash scripts/localstack_bootstrap.sh
python -m pytest tests/integration -m integration -v
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
  --parameter-overrides \
    AwsAccountId=000000000000 \
    BedrockAnalysisModelId=amazon.nova-pro-v1:0 \
    BedrockAnalysisModelArn=arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-pro-v1:0 \
    EcrRepositoryUri=000000000000.dkr.ecr.us-east-1.amazonaws.com/notable-analyzer-s3 \
    ImageDigest=sha256:0000000000000000000000000000000000000000000000000000000000000000
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
| **core** | Default SAM parameters; Bedrock model ID and ARN; Bedrock model access | Upload `data/test-notable.txt` to `incoming/`; confirm markdown + JSON under `reports/`; review CloudWatch logs for bounded metadata without secrets |
| **html_reports** | `CapabilityProfiles=core,html_reports`, `HtmlReportEnabled=true` | Confirm sibling `.html` object beside markdown/JSON |
| **rag** | `CapabilityProfiles=core,rag`, `RagEnabled=true`, private OpenSearch settings and an ingested SOC corpus | JSON `metadata.rag_status` is `success` or `no_match`; analysis completes when `RagFailureMode=suppress` |
| **spl_readonly** | `CapabilityProfiles=core,rag,spl_readonly`; Splunk URL + token secret; `SplQueryRagEnabled=true` after dictionary ingestion | JSON includes SPL generation metadata and/or `investigation_query_results`; denied SPL commands do not outbound; Splunk allowlists enforced |
| **elastic_readonly** | `CapabilityProfiles=core,rag,elastic_readonly` (not with `spl_readonly`); Elastic URL + API key secret + index allowlist; optional `ElasticsearchGroundingEnabled=true` | JSON `metadata.investigation_query_backend=elasticsearch` with bounded `investigation_query_results` |
| **ticket_draft** | `CapabilityProfiles=core,ticket_draft`, `ServiceNowAssignmentGroup` | JSON `servicenow_section.draft` present; no ServiceNow POST unless create is separately enabled |
| **action_gated** | `CapabilityProfiles=core,action_gated`; Splunk writeback and/or ServiceNow secrets as needed; `SideEffectIdempotencyTableName` | DynamoDB idempotency table exists; replay duplicate side-effect keys and confirm no duplicate Splunk/ServiceNow writes |

Helper script (live AWS, optional; requires **PowerShell 5.1+** or **pwsh**):

```powershell
$env:COMMERCIAL_AWS_ACCOUNT_ID = "<approved-12-digit-account>"
$env:AWS_REGION = "us-east-1"

# Core smoke (default behavior unchanged)
.\scripts\test-pipeline.ps1

# Auto-detect deployed profiles and run matching Wave 1 checks
.\scripts\test-pipeline.ps1 -Wave1Smoke

# Assert a specific profile bundle in staging
.\scripts\test-pipeline.ps1 -Wave1Smoke -ExpectCapabilityProfiles "core,rag,spl_readonly"
```

Without PowerShell, run the same core smoke manually from the commercial project
root (replace bucket names from stack outputs; use `--region us-east-1` on every
AWS CLI call):

```bash
export AWS_REGION=us-east-1
export COMMERCIAL_AWS_ACCOUNT_ID=<approved-12-digit-account>
# Confirm caller account/partition before mutating (see setup-and-deploy.sh preflight)
INPUT_BUCKET=$(aws cloudformation describe-stacks --region us-east-1 --stack-name <stack> \
  --query 'Stacks[0].Outputs[?OutputKey==`InputBucketName`].OutputValue' --output text)
OUTPUT_BUCKET=$(aws cloudformation describe-stacks --region us-east-1 --stack-name <stack> \
  --query 'Stacks[0].Outputs[?OutputKey==`OutputBucketName`].OutputValue' --output text)
STAMP=$(date -u +%Y%m%d-%H%M%S)
BASE="test-notable-$STAMP"
aws s3 cp data/test-notable.txt "s3://$INPUT_BUCKET/incoming/$BASE.txt" --region us-east-1
PREFIX="reports/incoming/$BASE--"
REPORT_KEY=None
for _ in {1..12}; do
  REPORT_KEY=$(aws s3api list-objects-v2 --bucket "$OUTPUT_BUCKET" \
    --prefix "$PREFIX" --region us-east-1 \
    --query "Contents[?ends_with(Key, '.md')].Key | [0]" --output text)
  [[ "$REPORT_KEY" != "None" && -n "$REPORT_KEY" ]] && break
  sleep 5
done
[[ "$REPORT_KEY" != "None" && -n "$REPORT_KEY" ]] || {
  echo "Versioned markdown report not found under $PREFIX" >&2
  exit 1
}
aws s3 cp "s3://$OUTPUT_BUCKET/$REPORT_KEY" "./$BASE.md" --region us-east-1
```

Manual follow-ups still required for **action_gated** idempotency replay, signed
ServiceNow create approval, and Splunk `notable_rest` writeback. See
[`../operations/platform/CAPABILITY_PROFILES.md`](../operations/platform/CAPABILITY_PROFILES.md),
[`../operations/integrations/SERVICENOW_OPERATIONS.md`](../operations/integrations/SERVICENOW_OPERATIONS.md),
and
[`../operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](../operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md).

### OpenSearch preflight (before RAG or customer-default SAM deploy)

Complete [`../operations/deployment/OPENSEARCH_PROVISIONING.md`](../operations/deployment/OPENSEARCH_PROVISIONING.md), then confirm:

| Check | Pass criteria |
| --- | --- |
| Domain active | `aws opensearch describe-domain --region us-east-1` shows `Processing=false`, VPC endpoint present |
| Network | Lambda subnets route to OpenSearch SG on 443; NAT or VPC endpoints cover S3, SQS, DynamoDB, Bedrock, Logs |
| Access policy | Domain policy allows analyzer, portal, case-embed, and rag-ingestion Lambda role ARNs |
| SAM inputs | `OpenSearchEndpoint`, `OpenSearchDomainArn`, `RagTenantId`, `CustomerVpcSubnetIds`, `CustomerSecurityGroupIds` filled in preset |
| Post-ingest | First manifest creates expected index with k-NN mapping; tenant filter rejects wrong `RagTenantId` |

### Portal and customer-default staging checklist

Optional real AWS validation for `analyst_portal` and the customer-default bundle.
Run only in an approved dev/staging/prod account **after** OpenSearch preflight
when RAG is enabled.

| Profile slice | Deploy prerequisites | Staging validation |
| --- | --- | --- |
| **customer-default** | Preset [`COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](../operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md): `CapabilityProfiles=core,rag,analyst_portal`; `RagEnabled=true`; `RagIngestionEnabled=true`; `SplQueryRagEnabled=true`; `PortalEnabled=true`; `CaseArchiveEnabled=true`; `CaseQaEnabled=true`; OpenSearch VPC; portal JWT/CORS; `CaseIndexTableName`; SOC + Splunk dictionary ingested | OpenSearch preflight above; `.\scripts\test-pipeline.ps1 -Wave1Smoke -ExpectCapabilityProfiles "core,rag,analyst_portal"`; SPA uploaded; notable -> archive + CaseIndex ready; portal chat with KB grounding |
| **analyst_portal** | `CapabilityProfiles=core,analyst_portal`; `CaseArchiveBucketName`; `CaseIndexTableName`; JWT issuer/audience; portal CORS; optional `PortalUiBucketName` | Record `PortalBrowserApiBaseUrl` and `PortalApiUrl`; upload notable; archive + chunks + CaseIndex `retrieval_status=ready`; load `/`, `/cases`, `/cases/{case_id}`; cited chat within regional API timeout |

Playwright E2E for the commercial JWT route:
[`../../frontend/analyst-portal/README.md`](../../frontend/analyst-portal/README.md)
(`PORTAL_E2E_BASE_URL`, `PORTAL_E2E_AUTH_MODE=jwt`, `PORTAL_E2E_JWT`).
