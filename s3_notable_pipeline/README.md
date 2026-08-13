# S3 Notable Pipeline

Minimal guide for new readers. **Documentation hub:** [`docs/README.md`](docs/README.md) (deploy paths A/B/C). Customer tuning: [`docs/operations/README.md`](docs/operations/README.md). On-prem mirror: [`../llm_notable_analysis_onprem_systemd/docs/`](../llm_notable_analysis_onprem_systemd/docs/).

This service processes security notables uploaded to S3, runs LLM-based ATT&CK analysis (Bedrock), and sends results to one of two sinks:

- `s3` (test mode): write markdown reports and Bedrock JSON (`llm_response`) back to S3
- `notable_rest`: write the markdown and JSON to S3 and update the Splunk notable comment via REST

## 1) What You Need

- AWS GovCloud account in `us-gov-east-1` with customer-approved Bedrock model access
- AWS CLI configured (`aws configure`)
- AWS SAM CLI
- Docker running (required for Lambda image build)
- A Lambda image published to customer GovCloud ECR and its immutable digest. Deployments pass `EcrRepositoryUri` and `ImageDigest` separately.

Quick checks:

```bash
aws sts get-caller-identity
sam --version
docker --version
```

## 2) Deploy

**Navigation hub:** [`docs/README.md`](docs/README.md) lists deploy paths (core,
RAG + portal, custom profiles). Start there if you are unsure which flow to follow.

### Choose your path

| Path | Doc trail |
| --- | --- |
| **A — Core only** (below) | This section + section 3 smoke test |
| **B — RAG + portal** | [`docs/README.md`](docs/README.md) Path B: [`OPENSEARCH_PROVISIONING.md`](docs/operations/deployment/OPENSEARCH_PROVISIONING.md) -> [`CAPABILITY_PROFILES.md`](docs/operations/platform/CAPABILITY_PROFILES.md) |
| **C — Custom profiles** | [`docs/operations/platform/CAPABILITY_PROFILES.md`](docs/operations/platform/CAPABILITY_PROFILES.md) + [`docs/operations/README.md`](docs/operations/README.md) |

Every path requires an ECR image first: [`docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md`](docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md).

### Path A — Core only (fast path)

**Packaging readiness:** Build with the default Lambda Python 3.12 base for development or override `LAMBDA_BASE_IMAGE` with the customer's approved digest-pinned mirror. Push the result to GovCloud ECR before deployment.

From this directory:

```powershell
.\scripts\setup-and-deploy.ps1
```

```bash
chmod +x ./scripts/setup-and-deploy.sh
./scripts/setup-and-deploy.sh
```

What it does:

1. Validates local prerequisites (AWS CLI, SAM CLI, Docker, credentials; optional Bedrock list check).
2. Runs `sam build -t deploy/aws/template-sam.yaml`.
3. Runs `sam deploy --template-file .aws-sam/build/template.yaml` (or guided mode first time).

Manual equivalent (same core deploy steps both scripts run):

```bash
sam build -t deploy/aws/template-sam.yaml
# If samconfig.toml exists:
sam deploy --template-file .aws-sam/build/template.yaml
# First deploy (no samconfig.toml):
sam deploy --guided --template-file .aws-sam/build/template.yaml
```

If using guided deploy, start with:

- Stack name (default in test script: `notable-analyzer-stack`)
- `SplunkSinkMode=s3`
- globally unique values for `InputBucketName` and `OutputBucketName`
- `AwsAccountId`: your 12-digit AWS account ID (Bedrock inference profile ARN)
- `EcrRepositoryUri`: customer GovCloud ECR repository URI without a tag or digest
- `ImageDigest`: immutable `sha256:...` digest returned by ECR
- `BedrockAnalysisModelId`: customer-approved model or inference-profile ID/ARN
- `CapabilityProfiles=core` unless you are enabling optional bundles (Path B or C; see [`docs/README.md`](docs/README.md))
- `MaxDecompressedInputBytes`: keep the default `1048576` unless expected gzip notable payloads need a larger decompressed size
- if using `notable_rest`, provide:
  - `SplunkBaseUrl`
  - `SplunkApiTokenSecretArn` (Secrets Manager ARN)
  - optional `SplunkApiTokenSecretField` (default `token`)
  - optional `SplunkNotableUpdatePath` (default `/services/notable_update`)

Infrastructure template: [`deploy/aws/template-sam.yaml`](deploy/aws/template-sam.yaml). Runtime env reference: [`config.env.example`](config.env.example).

## 3) Test End-to-End

```powershell
.\scripts\test-pipeline.ps1
```

Optional Wave 1 profile checks against a live stack (requires deployed AWS resources):

```powershell
.\scripts\test-pipeline.ps1 -Wave1Smoke
.\scripts\test-pipeline.ps1 my-stack-name -Wave1Smoke -ExpectCapabilityProfiles "core,rag"
```

Core smoke (default):

1. Reads bucket names from CloudFormation outputs.
2. Uploads `data/test-notable.txt` to `incoming/`.
3. Waits for processing.
4. Pulls generated markdown from `reports/`.

Unit and integration tests: [`docs/testing/TESTING.md`](docs/testing/TESTING.md).

## 4) Capability Profiles

Profiles are the preferred way to enable optional behavior. Set SAM parameter `CapabilityProfiles` at deploy (maps to Lambda env `CAPABILITY_PROFILES`). Default: `core`. Profiles are additive; `core` is always included. `spl_readonly` and `elastic_readonly` are mutually exclusive.

| Profile | Enables |
|---------|---------|
| `core` | S3-triggered ingest, Bedrock analysis, markdown + JSON under `reports/` |
| `html_reports` | Optional HTML companion report in S3 |
| `rag` | Tenant-scoped OpenSearch advisory context in the main analysis prompt |
| `spl_readonly` | SPL generation and bounded read-only Splunk investigation (REST or MCP) |
| `elastic_readonly` | Query DSL generation and bounded read-only Elasticsearch `_search` |
| `ticket_draft` | ServiceNow incident draft payloads in JSON reports (no POST) |
| `action_gated` | Splunk notable writeback (with `notable_rest`), ServiceNow draft/create, approval HMAC, DynamoDB side-effect idempotency |
| `analyst_portal` | S3 case archive, DynamoDB CaseIndex, case-chunk embed Lambda, JWT/IAM portal API, static SPA, pinned-case Q&A |

Full operator guide: [`docs/operations/platform/CAPABILITY_PROFILES.md`](docs/operations/platform/CAPABILITY_PROFILES.md). Authoritative flag mapping: `src/s3_notable_pipeline/config.py`.

**RAG or portal on GovCloud:** follow Path B in [`docs/README.md`](docs/README.md)
(`OPENSEARCH_PROVISIONING.md` first, then capability profiles and SAM parameters).

## 5) Runtime Contract (Important)

- Lambda `notable-analyzer-s3` triggers on `s3:ObjectCreated:*` under `incoming/` in the input bucket.
- One uploaded object -> one analysis run.
- Empty objects, folder markers, and placeholders are skipped.
- Supported input payloads are UTF-8 text/JSON and single-payload gzip files such as `.json.gz` or `.txt.gz`. ZIP archives and multi-file compressed uploads are not supported.
- Gzip input is decompressed before analysis and rejected if the decompressed payload exceeds `MAX_DECOMPRESSED_INPUT_BYTES` (SAM `MaxDecompressedInputBytes`, default `1048576`).
- In `s3` and `notable_rest` modes, outputs are written under `s3://<output-bucket>/reports/`: `<input-file-stem>.md` (report) and `<input-file-stem>.json` (parsed Bedrock structured payload as `llm_response`). With `html_reports`, a `.html` artifact is also written.
- For gzip input, the report stem strips both extensions, for example `incoming/abc-123.json.gz` -> `reports/abc-123.md` and `reports/abc-123.json`.
- In `notable_rest` mode, `finding_id` is derived from the filename stem:
  - `incoming/abc-123.json` -> `finding_id=abc-123`
  - `incoming/abc-123.json.gz` -> `finding_id=abc-123`
- Optional profiles add RAG retrieval, read-only investigation results, ServiceNow drafts/actions, and analyst portal archive/API behavior per section 4.

## 6) Sink Modes

`SplunkSinkMode` / `SPLUNK_SINK_MODE` is separate from capability profiles. Production Splunk writeback should use `SplunkSinkMode=notable_rest` together with the `action_gated` profile.

### `s3` (default test mode)

- Required: `OUTPUT_BUCKET_NAME`
- Output paths: `s3://<output-bucket>/reports/<input-file-stem>.md` and `.json` (Bedrock `llm_response` only)

### `notable_rest`

- Required parameters: `OUTPUT_BUCKET_NAME`, `SplunkBaseUrl`, `SplunkApiTokenSecretArn`
- Optional parameters: `SplunkApiTokenSecretField` (default `token`), `SplunkNotableUpdatePath` (default `/services/notable_update`)
- Runtime env vars populated from template: `SPLUNK_BASE_URL`, `SPLUNK_API_TOKEN_SECRET_ARN`, `SPLUNK_API_TOKEN_SECRET_FIELD`, `SPLUNK_NOTABLE_UPDATE_PATH`
- Output paths: `s3://<output-bucket>/reports/<input-file-stem>.md` and `.json` (Bedrock `llm_response` only)
- Sends the same markdown to Splunk as a notable comment with `finding_id`

Example secret creation (JSON field style):

```bash
aws secretsmanager create-secret \
  --name notable-rest-token \
  --secret-string '{"token":"<splunk-api-token>"}'
```

Operations: [`docs/operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](docs/operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md).

## 7) Key Files

**Code and deploy**

- `pyproject.toml` - package metadata for the `src/` layout
- `src/s3_notable_pipeline/lambda_handler.py` - S3 event handling and sink routing
- `src/s3_notable_pipeline/ttp_analyzer.py` - Bedrock call, schema validation, TTP filtering
- `src/s3_notable_pipeline/markdown_generator.py` - report formatting
- `src/s3_notable_pipeline/config.py` - runtime config and capability profile mapping
- `src/s3_notable_pipeline/case_archive.py`, `portal_handler.py`, `embed_handler.py` - analyst portal archive, API, and chunk embedding (when `analyst_portal` is enabled)
- `deploy/docker/Dockerfile` - Lambda image build; `FROM` is not portable until you substitute your approved base registry/image
- `deploy/aws/template-sam.yaml` - deployable GovCloud SAM infrastructure (durable queues, Lambdas, regional API Gateway, and private S3 portal assets)
- `tests/test_lambda_handler.py` - focused Lambda sink routing tests
- `scripts/setup-and-deploy.*` - prerequisite checks, `sam build`, `sam deploy`
- `scripts/test-pipeline.ps1` - core and optional Wave 1 stack smoke checks
- `scripts/localstack_bootstrap.*` - LocalStack bootstrap for integration tests
- `frontend/analyst-portal` - vendored AWS analyst portal SPA
- `data/test-notable.txt` - sample notable used by the test helper
- `config.env.example` - AWS runtime contract reference for Lambda environment variables

**Documentation**

- [`docs/README.md`](docs/README.md) — **start here** for deploy paths and topic shortcuts
- [`docs/operations/README.md`](docs/operations/README.md) — operations guides by category
- [`docs/testing/TESTING.md`](docs/testing/TESTING.md) — validation commands

## 8) Common Issues

- **No Lambda trigger:** verify object key is under `incoming/`.
- **No output report:** check `OUTPUT_BUCKET_NAME` and CloudWatch logs for `notable-analyzer-s3`.
- **Bedrock permission errors:** verify `bedrock:InvokeModel` and model/inference-profile access; confirm `AwsAccountId` matches the deployed account.
- **Deploy fails on image resolution:** verify `EcrRepositoryUri` is in `us-gov-east-1`, `ImageDigest` exists in that repository, and Lambda can pull it.
- **Compressed input errors:** only gzip is supported. Verify the object is valid gzip, contains UTF-8 text/JSON after decompression, and does not exceed `MAX_DECOMPRESSED_INPUT_BYTES`.
- **Secrets access errors in notable_rest:** verify Lambda can call `secretsmanager:GetSecretValue` on `SplunkApiTokenSecretArn`.
- **Splunk REST update fails:** verify the target endpoint accepts your identifier mapping (`finding_id` vs customer-specific IDs).
- **`notable_rest` produced no report in S3:** check `OUTPUT_BUCKET_NAME` and CloudWatch logs; this mode writes to S3 before calling Splunk REST.

## 9) Cleanup

Delete stack:

```bash
sam delete --stack-name notable-analyzer-stack
```

Then empty/delete any retained S3 buckets if needed.
