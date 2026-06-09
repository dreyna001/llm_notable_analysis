# Executive AWS Workflow Overview

## Purpose

This document explains the AWS notable-analysis workflow end to end for executive and program stakeholders. It describes what the workflow does, how information moves through the system, what AWS services are involved, and what operational controls are already built into the current implementation.

The workflow turns security notables into analyst-ready ATT&CK-oriented reports. A notable is sent to S3, processed by an AWS Lambda function, analyzed through Amazon Bedrock, validated against a local MITRE ATT&CK technique set, and written back as a markdown report. In the default mode, the report is stored in S3. In the optional Splunk REST mode, the report is also written back to the originating Splunk notable as a comment.

## Executive Summary

The AWS workflow provides a bounded, serverless analysis path for security notables:

1. A SOAR playbook or operator uploads one notable payload to an S3 input bucket.
2. S3 automatically triggers a Lambda function when a new object appears under `incoming/`.
3. Lambda reads and normalizes the notable as JSON or text.
4. Lambda calls Amazon Bedrock with a constrained cybersecurity analysis prompt.
5. The model response is parsed, repaired when possible, and validated before use.
6. MITRE ATT&CK technique IDs are filtered against the local approved ATT&CK v17.1 ID list.
7. A markdown report is generated for analyst review.
8. The report is written to the S3 output bucket and, when enabled, posted back to Splunk via REST.

The current design is intentionally narrow: one notable upload produces one analysis run and one report. This keeps the workflow simple to deploy, review, monitor, and validate before broader automation is added.

## Business Outcome

The workflow is intended to reduce the time analysts spend turning raw notable context into a structured first-pass assessment. It produces:

- A direct alert reconciliation verdict with confidence.
- Evidence and inference separated for reviewability.
- Candidate ATT&CK techniques with confidence scores and supporting fields.
- Extracted indicators of compromise.
- Competing benign and adversary hypotheses.
- Recommended pivots and follow-up actions.

The system supports analyst decision-making. It does not make containment, suppression, escalation, or closure decisions on its own.

## End-to-End Workflow

### 1. Notable Intake

The workflow starts when a notable is prepared for analysis. The recommended integration pattern is a Splunk SOAR / Phantom playbook that selects newly created notables, gathers relevant container and artifact context, builds one JSON payload, and uploads it to:

```text
s3://<input-bucket>/incoming/<finding_id>.json
```

Manual testing uses the same contract: upload a test notable file to the `incoming/` prefix of the input bucket.

### 2. S3 Event Trigger

The input S3 bucket is configured to trigger Lambda on object creation events under `incoming/`. This makes S3 the handoff point between the source system and the AWS processing workflow.

The Lambda handler skips folder markers, empty objects, and common placeholder files so that deployment artifacts and placeholder keys do not create false analysis runs.

### 3. Lambda Processing

The Lambda function reads the uploaded object, decodes it as UTF-8, and normalizes it as either JSON or raw text. Valid JSON remains JSON. Plain text remains plain text.

This keeps the intake contract flexible enough for early deployments while still preserving the original alert content that the model will analyze.

### 4. Bedrock Analysis

The Lambda function calls Amazon Bedrock using the configured `BEDROCK_MODEL_ID`. The current SAM template configures a Claude Sonnet 4.6 inference profile in `us-east-1`.

The prompt is designed for bounded cybersecurity analysis. It instructs the model to:

- Use only facts present in the notable.
- Separate evidence from inference.
- Return a structured output contract.
- Use MITRE ATT&CK v17 technique identifiers.
- State uncertainty instead of inventing missing context.
- Provide competing hypotheses and recommended analyst pivots.

The model is used for synthesis and explanation. Deterministic code still handles parsing, validation, filtering, report generation, sink routing, and deployment configuration.

### 5. Validation and Guardrails

After Bedrock returns a response, the workflow validates the result before rendering the report. The validation path includes:

- Parsing structured tool output when available.
- Falling back to raw JSON mode when tool use fails.
- Attempting one repair call when parsing or validation fails.
- Enforcing required top-level response keys.
- Enforcing content policies such as URL placement rules and placeholder-token rejection.
- Filtering returned ATT&CK technique IDs against `src/s3_notable_pipeline/enterprise_attack_v17.1_ids.json`.

If structured validation cannot be completed, the workflow preserves the raw model output in a proof-of-concept review section instead of silently treating it as validated analysis.

### 6. Report Generation

The report generator converts the validated analysis into markdown. The report includes:

- Alert reconciliation.
- Competing hypotheses and pivots.
- Evidence versus inference.
- Indicators of compromise.
- Scored ATT&CK techniques grouped by confidence.
- Raw model output only when structured validation failed and human review is needed.

Reports are written to:

```text
s3://<output-bucket>/reports/<input-file-stem>.md
```

For example:

```text
s3://notable-output-bucket/reports/abc-123.md
```

### 7. Output Sink

The workflow supports two sink modes.

`s3` is the default and safest first deployment mode. It writes the markdown report to the output bucket only.

`notable_rest` writes the same markdown report to S3 first, then posts it to a Splunk REST endpoint as a notable comment. In this mode, the `finding_id` is derived from the uploaded file name:

```text
incoming/abc-123.json -> finding_id=abc-123
```

Splunk REST credentials are read from AWS Secrets Manager through `SplunkApiTokenSecretArn`. The template requires the Splunk base URL and secret ARN when `notable_rest` mode is enabled.

### 8. Analyst Review

Analysts review the generated markdown report in S3 or directly in the Splunk notable comment, depending on sink mode. The output is intended to accelerate triage by organizing the available evidence, showing model confidence, and identifying practical next pivots.

Human approval remains required for consequential actions such as closing, escalating, suppressing, or containing an alert.

## AWS Architecture

The SAM deployment provisions the core serverless resources:

- Input S3 bucket for notable payloads.
- Output S3 bucket for generated markdown reports.
- S3 event notification from `incoming/` to Lambda.
- Lambda function packaged as a container image.
- Lambda invoke permission for S3.
- Lambda execution permissions for S3, Bedrock, CloudWatch Logs, and conditionally Secrets Manager.
- Lifecycle rules for automatic retention management.

The Lambda container image must already exist in Amazon ECR before deploying with the current `deploy/aws/template-sam.yaml`. The deployment passes `ImageUri` into SAM; it does not build, tag, push, or create the ECR image by itself.

## Deployment Flow

The deployment workflow is:

1. Confirm AWS CLI, SAM CLI, Docker, and AWS credentials are available.
2. Confirm Bedrock model or inference profile access in the target account.
3. Build and push the Lambda container image to ECR.
4. Run `sam build -t deploy/aws/template-sam.yaml`.
5. Run `sam deploy --guided --template-file .aws-sam/build/template.yaml` for first-time deployment, or `sam deploy --template-file .aws-sam/build/template.yaml` when `samconfig.toml` already exists.
6. Provide environment-specific parameters such as input bucket, output bucket, account ID, image URI, and sink mode.
7. Validate the deployment by uploading a test notable and confirming the report appears under `reports/`.

The current fast-path scripts perform prerequisite checks and SAM build/deploy steps, but the ECR image must be available before deployment succeeds.

## Operating Modes

### Test / S3 Mode

Use `SplunkSinkMode=s3` for the first deployment and validation. This mode has the smallest blast radius because it reads from S3, calls Bedrock, and writes the report back to S3 only.

### Splunk Writeback Mode

Use `SplunkSinkMode=notable_rest` only after the S3 mode is working and the customer-specific Splunk REST endpoint, token secret, and finding ID mapping have been validated.

This mode still writes the report to S3 for auditability and troubleshooting before attempting the Splunk REST update.

## Security and Control Posture

The current workflow includes several control points appropriate for an early production-shaped deployment:

- S3 prefix filtering limits automatic processing to `incoming/`.
- Placeholder and empty-object skips avoid accidental invocations.
- Lambda permissions are scoped to the configured input bucket, output bucket, Bedrock inference profile, CloudWatch logs, and optional Splunk token secret.
- Splunk tokens are stored in Secrets Manager, not hardcoded in code or templates.
- Bedrock output is parsed and validated before report rendering.
- ATT&CK technique IDs are allowlisted through a local versioned dataset.
- The system writes analyst-supporting output only; it does not execute response actions.
- S3 lifecycle policies limit retention of raw input and generated reports.

## Observability and Validation

Operational validation is straightforward:

- CloudFormation outputs identify the deployed Lambda and bucket names.
- `scripts/test-pipeline.ps1` uploads a test notable to the input bucket and checks for the generated report.
- CloudWatch Logs show Lambda invocation, S3 read activity, Bedrock call status, validation outcomes, sink routing, and error messages.
- S3 output under `reports/` provides the durable review artifact.
- In `notable_rest` mode, the Splunk notable comment confirms writeback.

## Key Readiness Constraints

The workflow is ready to explain and demonstrate, but these constraints should be resolved before a customer production rollout:

- The Lambda image must be built and pushed to ECR before SAM deploys the function.
- The `deploy/docker/Dockerfile` base image is currently organization-specific and must be replaced with an approved, pullable Lambda Python 3.12 base image.
- The SAM template currently points Bedrock to a `us-east-1` inference profile, so region changes require template review.
- S3 bucket names must be globally unique per AWS account and region.
- `notable_rest` requires a validated Splunk REST endpoint, Secrets Manager token, and customer-specific finding ID mapping.
- The workflow produces analyst guidance; any automated writeback or action beyond comments should go through explicit approval and policy gates.

## Success Criteria

A successful end-to-end run is complete when:

1. A notable payload lands in `s3://<input-bucket>/incoming/`.
2. Lambda is invoked automatically by the S3 event.
3. Bedrock analysis completes or produces a preserved reviewable fallback.
4. A markdown report is written to `s3://<output-bucket>/reports/`.
5. In `notable_rest` mode, the corresponding Splunk notable receives the report comment.
6. Operators can trace the run through CloudWatch logs and S3 output.

## Current Recommended Rollout Path

Start with `s3` mode in a non-production AWS account or controlled customer environment. Validate the deployment, Bedrock access, report quality, lifecycle behavior, and CloudWatch logs with representative notables. After the S3 path is reliable, enable `notable_rest` with a test Splunk notable and confirm the endpoint, token, and finding ID mapping. Keep any further action-taking outside the workflow until explicit approval gates and policy controls are designed.
