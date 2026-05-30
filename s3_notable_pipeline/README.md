# S3 Notable Pipeline

Minimal guide for new readers.

This service processes security notables uploaded to S3, runs LLM-based ATT&CK analysis, and sends results to one of two sinks:

- `s3` (test mode): write markdown reports and Bedrock JSON (`llm_response`) back to S3
- `notable_rest`: write the markdown and JSON to S3 and update the Splunk notable comment via REST

## 1) What You Need

- AWS account with Bedrock model access
- AWS CLI configured (`aws configure`)
- AWS SAM CLI
- Docker running (required for Lambda image build)
- An **ECR image URI** for this Lambda: SAM’s `ImageUri` must reference an image **already pushed to ECR** in your account/region. You are not ready to deploy until you can build that image (see `deploy/docker/Dockerfile`) and publish it, or you use an image your org already ships.

Quick checks:

```bash
aws sts get-caller-identity
sam --version
docker --version
```

## 2) Deploy (Fast Path)

**Packaging readiness:** Deploy passes `ImageUri` into the stack. That URI must be a real Lambda container image in ECR **before** `sam deploy` succeeds. The `deploy/docker/Dockerfile` `FROM` is a placeholder/org-specific base—if you cannot pull and build it as written, you still need an agreed way to produce the same handler code inside **some** approved base image and push it to ECR. Until that exists, “ready to deploy” really means “ready to build and publish the Lambda image.”

From this directory:

```powershell
.\scripts\setup-and-deploy.ps1
```

```bash
chmod +x ./scripts/setup-and-deploy.sh
./scripts/setup-and-deploy.sh
```

What it does:

1. Validates local prerequisites.
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

- `SplunkSinkMode=s3`
- globally unique values for `InputBucketName` and `OutputBucketName`
- `AwsAccountId`: your 12-digit AWS account ID (Bedrock inference profile ARN)
- `MaxDecompressedInputBytes`: keep the default `1048576` unless expected gzip notable payloads need a larger decompressed size
- if prompted for `ImageUri`, provide the **existing** ECR URI for this Lambda image (build + `docker push` first if you do not have one yet)
- if using `notable_rest`, provide:
  - `SplunkBaseUrl`
  - `SplunkApiTokenSecretArn` (Secrets Manager ARN)
  - optional `SplunkApiTokenSecretField` (default `token`)
  - optional `SplunkNotableUpdatePath` (default `/services/notable_update`)

## 3) Test End-to-End

```powershell
.\scripts\test-pipeline.ps1
```

This script:

1. Reads bucket names from CloudFormation outputs.
2. Uploads `data/test-notable.txt` to `incoming/`.
3. Waits for processing.
4. Pulls generated markdown from `reports/`.

## 4) Runtime Contract (Important)

- Lambda triggers on `s3:ObjectCreated:*` under `incoming/` in the input bucket.
- One uploaded object -> one analysis run.
- Empty objects, folder markers, and placeholders are skipped.
- Supported input payloads are UTF-8 text/JSON and single-payload gzip files such as `.json.gz` or `.txt.gz`. ZIP archives and multi-file compressed uploads are not supported.
- Gzip input is decompressed before analysis and rejected if the decompressed payload exceeds `MAX_DECOMPRESSED_INPUT_BYTES` (default `1048576`).
- In `s3` and `notable_rest` modes, outputs are written under `s3://<output-bucket>/reports/`: `<input-file-stem>.md` (report) and `<input-file-stem>.json` (parsed Bedrock structured payload as `llm_response`).
- For gzip input, the report stem strips both extensions, for example `incoming/abc-123.json.gz` -> `reports/abc-123.md` and `reports/abc-123.json`.
- In `notable_rest` mode, `finding_id` is derived from the filename stem:
  - `incoming/abc-123.json` -> `finding_id=abc-123`
  - `incoming/abc-123.json.gz` -> `finding_id=abc-123`
- Optional `spl_readonly` parity adds generated SPL and bounded read-only
  Splunk investigation results to the JSON report. It is disabled by default.
- Optional `elastic_readonly` parity adds generated Elasticsearch Query DSL and
  bounded read-only `_search` results to the JSON report. It is disabled by
  default and is mutually exclusive with `spl_readonly`.

## 5) Sink Modes

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

## 6) Key Files

- `pyproject.toml` - package metadata for the `src/` layout
- `src/s3_notable_pipeline/lambda_handler.py` - S3 event handling and sink routing
- `src/s3_notable_pipeline/ttp_analyzer.py` - Bedrock call, schema validation, TTP filtering
- `src/s3_notable_pipeline/markdown_generator.py` - report formatting
- `deploy/docker/Dockerfile` - Lambda image build; `FROM` is not portable until you substitute your approved base registry/image
- `deploy/aws/template-sam.yaml` - deployable SAM infrastructure
- `tests/test_lambda_handler.py` - focused Lambda sink routing tests
- `scripts/` - deployment, test, and maintenance helpers
- `data/test-notable.txt` - sample notable used by the test helper
- `config.env.example` - AWS runtime contract reference for Lambda environment variables
- `docs/operations/README.md` - AWS operations guide index
- `docs/technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md` - AWS/on-prem parity implementation contract
- `docs/planning/AWS_ONPREM_PARITY_PLAN.md` - reviewed parity plan and diff sequence
- `docs/delivery_package/EXECUTIVE_AWS_WORKFLOW.md` - executive end-to-end workflow overview
- `docs/delivery_package/end_to_end_diagrams/END_TO_END_DIAGRAMS.md` - end-to-end Mermaid diagrams (SVG exports in the same folder)
- `docs/delivery_package/AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_OVERVIEW.md` - deployment readiness gateway (executive)
- `docs/delivery_package/AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md` - readiness assessment (technical checklist)
- `docs/operations/DEPLOYMENT_IMAGE_STEPS.md` - Lambda image build and ECR deployment notes
- `docs/operations/SPL_OPERATIONS.md` - SPL generation, grounding, and read-only Splunk investigation operations
- `docs/operations/ELASTICSEARCH_OPERATIONS.md` - Elasticsearch Query DSL generation, grounding, and read-only `_search` operations
- `docs/operations/SPLUNK_WRITEBACK_OPERATIONS.md` - Splunk notable writeback and DynamoDB idempotency operations
- `docs/operations/SERVICENOW_OPERATIONS.md` - ServiceNow incident draft/create operations
- `docs/testing/TESTING.md` - unit, smoke, and optional integration validation commands
- `docs/integrations/SOAR_PLAYBOOK_PHANTOM.md` - SOAR upload pattern
- `docs/security/ATTACK_LLM_ANALYSIS.md` - ATT&CK grounding and validation approach

## 7) Common Issues

- **No Lambda trigger:** verify object key is under `incoming/`.
- **No output report:** check `OUTPUT_BUCKET_NAME` and CloudWatch logs.
- **Bedrock permission errors:** verify `bedrock:InvokeModel` and model access.
- **Compressed input errors:** only gzip is supported. Verify the object is valid gzip, contains UTF-8 text/JSON after decompression, and does not exceed `MAX_DECOMPRESSED_INPUT_BYTES`.
- **Secrets access errors in notable_rest:** verify Lambda can call `secretsmanager:GetSecretValue` on `SplunkApiTokenSecretArn`.
- **Splunk REST update fails:** verify the target endpoint accepts your identifier mapping (`finding_id` vs customer-specific IDs).
- **`notable_rest` produced no report in S3:** check `OUTPUT_BUCKET_NAME` and CloudWatch logs; this mode now writes to S3 before calling Splunk REST.

## 8) Cleanup

Delete stack:

```bash
sam delete --stack-name notable-analyzer-stack
```

Then empty/delete any retained S3 buckets if needed.
