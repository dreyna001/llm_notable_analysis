# S3 Notable Pipeline

Minimal guide for new readers.

This service processes security notables uploaded to S3, runs LLM-based ATT&CK analysis, and sends results to one of two sinks:

- `s3` (test mode): write markdown reports back to S3
- `notable_rest`: write the markdown report to S3 and update the Splunk notable comment via REST

## 1) What You Need

- AWS account with Bedrock model access
- AWS CLI configured (`aws configure`)
- AWS SAM CLI
- Docker running (required for Lambda image build)
- An **ECR image URI** for this Lambda: SAM’s `ImageUri` must reference an image **already pushed to ECR** in your account/region. You are not ready to deploy until you can build that image (see `Dockerfile`) and publish it, or you use an image your org already ships.

Quick checks:

```bash
aws sts get-caller-identity
sam --version
docker --version
```

## 2) Deploy (Fast Path)

**Packaging readiness:** Deploy passes `ImageUri` into the stack. That URI must be a real Lambda container image in ECR **before** `sam deploy` succeeds. The `Dockerfile` `FROM` is a placeholder/org-specific base—if you cannot pull and build it as written, you still need an agreed way to produce the same handler code inside **some** approved base image and push it to ECR. Until that exists, “ready to deploy” really means “ready to build and publish the Lambda image.”

From this directory:

```powershell
.\setup-and-deploy.ps1
```

```bash
chmod +x ./setup-and-deploy.sh
./setup-and-deploy.sh
```

What it does:

1. Validates local prerequisites.
2. Runs `sam build -t template-sam.yaml`.
3. Runs `sam deploy` (or `sam deploy --guided` first time).

Manual equivalent (same core deploy steps both scripts run):

```bash
sam build -t template-sam.yaml
# If samconfig.toml exists:
sam deploy
# First deploy (no samconfig.toml):
sam deploy --guided
```

If using guided deploy, start with:

- `SplunkSinkMode=s3`
- globally unique values for `InputBucketName` and `OutputBucketName`
- `AwsAccountId`: your 12-digit AWS account ID (Bedrock inference profile ARN)
- if prompted for `ImageUri`, provide the **existing** ECR URI for this Lambda image (build + `docker push` first if you do not have one yet)
- if using `notable_rest`, provide:
  - `SplunkBaseUrl`
  - `SplunkApiTokenSecretArn` (Secrets Manager ARN)
  - optional `SplunkApiTokenSecretField` (default `token`)
  - optional `SplunkNotableUpdatePath` (default `/services/notable_update`)

## 3) Test End-to-End

```powershell
.\test-pipeline.ps1
```

This script:

1. Reads bucket names from CloudFormation outputs.
2. Uploads `test-notable.txt` to `incoming/`.
3. Waits for processing.
4. Pulls generated markdown from `reports/`.

## 4) Runtime Contract (Important)

- Lambda triggers on `s3:ObjectCreated:*` under `incoming/` in the input bucket.
- One uploaded object -> one analysis run.
- Empty objects, folder markers, and placeholders are skipped.
- In `s3` and `notable_rest` modes, markdown output is written to `s3://<output-bucket>/reports/<input-file-stem>.md`.
- In `notable_rest` mode, `finding_id` is derived from the filename stem:
  - `incoming/abc-123.json` -> `finding_id=abc-123`

## 5) Sink Modes

### `s3` (default test mode)

- Required: `OUTPUT_BUCKET_NAME`
- Output path: `s3://<output-bucket>/reports/<input-file-stem>.md`

### `notable_rest`

- Required parameters: `OUTPUT_BUCKET_NAME`, `SplunkBaseUrl`, `SplunkApiTokenSecretArn`
- Optional parameters: `SplunkApiTokenSecretField` (default `token`), `SplunkNotableUpdatePath` (default `/services/notable_update`)
- Runtime env vars populated from template: `SPLUNK_BASE_URL`, `SPLUNK_API_TOKEN_SECRET_ARN`, `SPLUNK_API_TOKEN_SECRET_FIELD`, `SPLUNK_NOTABLE_UPDATE_PATH`
- Output path: `s3://<output-bucket>/reports/<input-file-stem>.md`
- Sends the same markdown to Splunk as a notable comment with `finding_id`

Example secret creation (JSON field style):

```bash
aws secretsmanager create-secret \
  --name notable-rest-token \
  --secret-string '{"token":"<splunk-api-token>"}'
```

## 6) Key Files

- `Dockerfile` - Lambda image build; `FROM` is not portable until you substitute your approved base registry/image
- `lambda_handler.py` - S3 event handling and sink routing
- `ttp_analyzer.py` - Bedrock call, schema validation, TTP filtering
- `markdown_generator.py` - report formatting
- `template-sam.yaml` - deployable infrastructure
- `SOAR_PLAYBOOK_PHANTOM.md` - SOAR upload pattern
- `ATTACK_LLM_ANALYSIS.md` - ATT&CK grounding and validation approach

## 7) Common Issues

- **No Lambda trigger:** verify object key is under `incoming/`.
- **No output report:** check `OUTPUT_BUCKET_NAME` and CloudWatch logs.
- **Bedrock permission errors:** verify `bedrock:InvokeModel` and model access.
- **Secrets access errors in notable_rest:** verify Lambda can call `secretsmanager:GetSecretValue` on `SplunkApiTokenSecretArn`.
- **Splunk REST update fails:** verify the target endpoint accepts your identifier mapping (`finding_id` vs customer-specific IDs).
- **`notable_rest` produced no report in S3:** check `OUTPUT_BUCKET_NAME` and CloudWatch logs; this mode now writes to S3 before calling Splunk REST.

## 8) Cleanup

Delete stack:

```bash
sam delete --stack-name notable-analyzer-stack
```

Then empty/delete any retained S3 buckets if needed.
