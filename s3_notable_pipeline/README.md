# S3 Notable Pipeline

Minimal guide for new readers.

This service processes security notables uploaded to S3, runs LLM-based ATT&CK analysis, and sends results to one of three sinks:

- `s3` (test mode): write markdown reports back to S3
- `hec`: post analysis events to Splunk HEC
- `notable_rest`: update Splunk notable comments via REST

## 1) What You Need

- AWS account with Bedrock model access
- AWS CLI configured (`aws configure`)
- AWS SAM CLI
- Docker running (required for Lambda image build)

Quick checks:

```bash
aws sts get-caller-identity
sam --version
docker --version
```

## 2) Deploy (Fast Path)

From this directory:

```powershell
.\setup-and-deploy.ps1
```

What it does:

1. Validates local prerequisites.
2. Runs `sam build -t template-sam.yaml`.
3. Runs `sam deploy` (or `sam deploy --guided` first time).

If using guided deploy, start with:

- `SplunkSinkMode=s3`
- globally unique values for `InputBucketName` and `OutputBucketName`
- if prompted for `ImageUri`, provide a valid ECR image URI for this Lambda image

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
- In `notable_rest` mode, `finding_id` is derived from the filename stem:
  - `incoming/abc-123.json` -> `finding_id=abc-123`

## 5) Sink Modes

### `s3` (default test mode)

- Required: `OUTPUT_BUCKET_NAME`
- Output path: `s3://<output-bucket>/reports/<input-file-stem>.md`

### `hec`

- Required: `SPLUNK_HEC_URL`, `SPLUNK_HEC_TOKEN`
- Sends an event payload to Splunk HEC (`sourcetype=notable:analysis`)

### `notable_rest`

- Required: `SPLUNK_BASE_URL`, `SPLUNK_API_TOKEN`
- Optional: `SPLUNK_NOTABLE_UPDATE_PATH` (default `/services/notable_update`)
- Sends markdown as notable comment with `finding_id`

## 6) Key Files

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
- **Splunk REST update fails:** verify the target endpoint accepts your identifier mapping (`finding_id` vs customer-specific IDs).

## 8) Cleanup

Delete stack:

```bash
sam delete --stack-name notable-analyzer-stack
```

Then empty/delete any retained S3 buckets if needed.
