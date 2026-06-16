# Executive AWS Workflow Overview

## Purpose

This document explains the AWS notable-analysis workflow end to end for executive and program stakeholders. It describes what the workflow does, how information moves through the system, what AWS services are involved, and what operational controls are built into the current Wave 1 implementation.

The workflow turns security notables into analyst-ready ATT&CK-oriented reports. A notable is sent to S3, processed by an AWS Lambda function, analyzed through Amazon Bedrock (with optional Knowledge Base retrieval and read-only investigation), validated against a local MITRE ATT&CK technique set, and written back as markdown, JSON, and optionally HTML reports in S3. Optional profiles add Splunk or Elasticsearch read-only queries, ServiceNow incident drafts or approval-gated creates, and Splunk notable comment writeback when explicitly enabled.

## Executive Summary

The AWS workflow provides a bounded, serverless analysis path for security notables:

1. A SOAR playbook or operator uploads one notable payload to an S3 input bucket.
2. S3 automatically triggers a Lambda function when a new object appears under `incoming/`.
3. Lambda reads and normalizes the notable as JSON or text.
4. Lambda optionally retrieves advisory context from Bedrock Knowledge Bases (SOC RAG, SPL or Elastic grounding).
5. Lambda calls Amazon Bedrock with a constrained cybersecurity analysis prompt.
6. When enabled, Lambda generates policy-validated read-only Splunk SPL or Elasticsearch Query DSL, executes bounded queries, and feeds normalized results back into interpretation.
7. The model response is parsed, repaired when possible, and validated before use.
8. MITRE ATT&CK technique IDs are filtered against the local approved ATT&CK v17.1 ID list.
9. Markdown, JSON, and optionally HTML reports are generated for analyst review.
10. Reports are written to the S3 output bucket. Splunk notable comment writeback remains supported through `SplunkSinkMode=notable_rest`; production rollouts should prefer `action_gated` so external writes use DynamoDB side-effect idempotency. ServiceNow incident creates run only through explicit approval gates.

Operators choose capability profiles at deploy time (`CapabilityProfiles` / `CAPABILITY_PROFILES`). Start with `core` and `SplunkSinkMode=s3`; add profiles one at a time after non-production validation. See `docs/operations/CAPABILITY_PROFILES.md` for the operator workflow.

The design is intentionally narrow: one notable upload produces one analysis run and one report set. This keeps the workflow simple to deploy, review, monitor, and validate before broader automation is added.

## Business Outcome

The workflow is intended to reduce the time analysts spend turning raw notable context into a structured first-pass assessment. It produces:

- A direct alert reconciliation verdict with confidence.
- Evidence and inference separated for reviewability.
- Candidate ATT&CK techniques with confidence scores and supporting fields.
- Extracted indicators of compromise.
- Competing benign and adversary hypotheses.
- Recommended pivots and follow-up actions.
- Optional read-only investigation results and ServiceNow draft payloads when those profiles are enabled.

The system supports analyst decision-making. It does not make containment, suppression, escalation, closure, or remediation decisions on its own.

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

### 4. Optional Advisory RAG and Grounding

When the `rag` profile is enabled, Lambda retrieves snippets from a configured Bedrock Knowledge Base and injects them as advisory context in the main analysis prompt. Retrieved material supports pivot ideas and procedure fit; it is not treated as observed case evidence.

When `spl_readonly` or `elastic_readonly` is enabled, optional dedicated Knowledge Bases can ground generated Splunk SPL or Elasticsearch Query DSL. Only one read-only investigation backend is active per deployment.

### 5. Bedrock Analysis

The Lambda function calls Amazon Bedrock using the configured `BEDROCK_MODEL_ID`. The current SAM template configures a Claude Sonnet 4.6 inference profile in `us-east-1`.

The prompt is designed for bounded cybersecurity analysis. It instructs the model to:

- Use only facts present in the notable (plus explicitly labeled advisory RAG context).
- Separate evidence from inference.
- Return a structured output contract.
- Use MITRE ATT&CK v17 technique identifiers.
- State uncertainty instead of inventing missing context.
- Provide competing hypotheses and recommended analyst pivots.

The model is used for synthesis and explanation. Deterministic code still handles parsing, validation, filtering, query policy checks, report generation, sink routing, idempotency, and deployment configuration.

### 6. Optional Read-Only Investigation

When `spl_readonly` is enabled, Lambda generates SPL, validates it against allowlists (indexes, commands, fields, time range, row limits), and executes read-only Splunk REST or MCP queries. When `elastic_readonly` is enabled, Lambda generates Elasticsearch Query DSL with similar bounds and executes read-only `_search` calls. Normalized results can feed a follow-on interpretation step. These paths do not write to Splunk or Elasticsearch.

### 7. Validation and Guardrails

After Bedrock returns a response, the workflow validates the result before rendering reports. The validation path includes:

- Parsing structured tool output when available.
- Falling back to raw JSON mode when tool use fails.
- Attempting one repair call when parsing or validation fails.
- Enforcing required top-level response keys.
- Enforcing content policies such as URL placement rules and placeholder-token rejection.
- Filtering returned ATT&CK technique IDs against `src/s3_notable_pipeline/enterprise_attack_v17.1_ids.json`.
- Validating generated SPL or Elastic queries before any read-only execution.

If structured validation cannot be completed, the workflow preserves the raw model output in a proof-of-concept review section instead of silently treating it as validated analysis.

### 8. Report Generation

The report generator converts the validated analysis into markdown and JSON. When `html_reports` is enabled, a static HTML report is also written. Reports include:

- Alert reconciliation.
- Competing hypotheses and pivots.
- Evidence versus inference.
- Indicators of compromise.
- Scored ATT&CK techniques grouped by confidence.
- Optional investigation summaries and ServiceNow draft payloads when those profiles are enabled.
- Raw model output only when structured validation failed and human review is needed.

Reports are written to:

```text
s3://<output-bucket>/reports/<input-file-stem>.md
s3://<output-bucket>/reports/<input-file-stem>.json
```

With `html_reports`:

```text
s3://<output-bucket>/reports/<input-file-stem>.html
```

### 9. Output and Optional Side Effects

**Default (`core`, `SplunkSinkMode=s3`):** Reports land in the output bucket only. No external writes.

**`ticket_draft`:** ServiceNow incident draft payloads appear in JSON reports. No ServiceNow POST.

**`action_gated` (preferred production posture for external writes):**

- Splunk notable comment writeback with DynamoDB side-effect idempotency when `SplunkSinkMode=notable_rest`. The legacy `notable_rest` path remains supported, but new production rollouts should use `action_gated`.
- ServiceNow incident create only when a signed `servicenow_create_approval` object is present in the incoming payload.
- DynamoDB side-effect idempotency for Splunk notable updates and ServiceNow creates (not for S3 writes, read-only queries, or Bedrock calls).

Splunk and ServiceNow credentials are read from AWS Secrets Manager. The template requires the relevant base URLs and secret ARNs when those features are enabled.

### 10. Analyst Review

Analysts review generated reports in S3, and when enabled, Splunk notable comments or ServiceNow incidents. The output is intended to accelerate triage by organizing available evidence, showing model confidence, surfacing optional investigation results, and identifying practical next pivots.

Human approval remains required for consequential actions such as closing, escalating, suppressing, containing, or creating tickets outside the configured approval gates.

## Wave 1 Capability Profiles

Profiles are additive. `core` is included automatically when omitted. Operators set `CapabilityProfiles` at deploy time.

- `core` — S3 ingest, Bedrock analysis, markdown + JSON reports (S3 + Bedrock).
- `html_reports` — static HTML report artifact (additional S3 output only).
- `rag` — advisory SOC context from a Bedrock Knowledge Base (read-only KB retrieval).
- `spl_readonly` — SPL generation and bounded read-only Splunk REST or MCP execution.
- `elastic_readonly` — Elasticsearch DSL generation and bounded read-only `_search` (mutually exclusive with `spl_readonly`).
- `ticket_draft` — ServiceNow incident drafts in JSON reports (no ServiceNow POST).
- `action_gated` — preferred profile for Splunk writeback idempotency when `notable_rest`, approval-gated ServiceNow create, and DynamoDB side-effect idempotency.

Recommended rollout: `core` with `SplunkSinkMode=s3`, then add one profile at a time in a non-production stack. Full operator detail is in `docs/operations/CAPABILITY_PROFILES.md`.

## AWS Architecture

The SAM deployment provisions the core serverless resources:

- Input S3 bucket for notable payloads.
- Output S3 bucket for generated reports.
- S3 event notification from `incoming/` to Lambda.
- Lambda function packaged as a container image.
- Lambda invoke permission for S3.
- Lambda execution permissions for S3, Bedrock (invoke and optional retrieve), CloudWatch Logs, and conditionally Secrets Manager, DynamoDB, and HTTPS egress to customer endpoints.
- Lifecycle rules for automatic retention management.
- Optional DynamoDB table for side-effect idempotency when `action_gated` is enabled.

The Lambda container image must already exist in Amazon ECR before deploying with the current `deploy/aws/template-sam.yaml`. The deployment passes `ImageUri` into SAM; it does not build, tag, push, or create the ECR image by itself.

## Deployment Flow

The deployment workflow is:

1. Confirm AWS CLI, SAM CLI, Docker, and AWS credentials are available.
2. Confirm Bedrock model or inference profile access in the target account.
3. Choose capability profiles and sink mode for the target environment.
4. Build and push the Lambda container image to ECR.
5. Run `sam build -t deploy/aws/template-sam.yaml`.
6. Run `sam deploy --guided --template-file .aws-sam/build/template.yaml` for first-time deployment, or `sam deploy --template-file .aws-sam/build/template.yaml` when `samconfig.toml` already exists.
7. Provide environment-specific parameters such as input bucket, output bucket, account ID, image URI, capability profiles, and optional integration settings.
8. Validate the deployment by uploading a test notable and confirming reports appear under `reports/`.

The current fast-path scripts perform prerequisite checks and SAM build/deploy steps, but the ECR image must be available before deployment succeeds.

## Operating Modes

### Test / S3 Mode (recommended start)

Use `CAPABILITY_PROFILES=core` and `SplunkSinkMode=s3` for the first deployment and validation. This mode has the smallest blast radius: S3 ingest, Bedrock analysis, and S3 report output only.

### Read-Only Investigation

Add `spl_readonly` or `elastic_readonly` (one per deployment) after Splunk or Elasticsearch owners approve generated queries, allowlists, and secret lifecycle. Investigation results are advisory enrichment; they do not trigger remediation.

### Splunk Writeback and ServiceNow Actions

Enable `action_gated` only after S3 and any read-only paths are reliable and owners approve external writes. Splunk writeback requires `SplunkSinkMode=notable_rest` and validated endpoint, token, and finding ID mapping; `action_gated` is the preferred production profile because it adds idempotency around that write path. ServiceNow create requires signed approval in the incoming payload.

## Security and Control Posture

The Wave 1 workflow includes control points appropriate for a production-shaped deployment:

- S3 prefix filtering limits automatic processing to `incoming/`.
- Placeholder and empty-object skips avoid accidental invocations.
- Capability profiles gate optional features at startup; unknown profile names fail validation.
- Lambda permissions are scoped to configured buckets, Bedrock targets, Knowledge Bases, CloudWatch logs, optional secrets, DynamoDB idempotency, and customer HTTPS endpoints.
- Tokens and approval secrets are stored in Secrets Manager, not hardcoded.
- Bedrock output is parsed and validated before report rendering.
- ATT&CK technique IDs are allowlisted through a local versioned dataset.
- Generated SPL and Elastic queries are policy-validated before read-only execution.
- RAG and query-grounding snippets are advisory; observed case facts come from the ingested notable.
- New production external-write rollouts should use `action_gated`, explicit configuration, and approval boundaries; DynamoDB idempotency limits duplicate side effects. Legacy `notable_rest` writeback remains supported for existing deployments.
- The system does not execute remediation, suppression, or autonomous case closure.
- S3 lifecycle policies limit retention of raw input and generated reports.

## Observability and Validation

Operational validation is straightforward:

- CloudFormation outputs identify the deployed Lambda and bucket names.
- `scripts/test-pipeline.ps1` uploads a test notable to the input bucket and checks for the generated report.
- CloudWatch Logs show Lambda invocation, S3 read activity, Bedrock and optional KB retrieve status, validation outcomes, optional query execution, sink routing, idempotency, and error messages.
- S3 output under `reports/` provides the durable review artifact.
- Profile-specific smoke steps are in `docs/operations/` and `docs/testing/TESTING.md`.

## Key Readiness Constraints

The workflow is ready to explain and demonstrate, but these constraints should be resolved before a customer production rollout:

- The Lambda image must be built and pushed to ECR before SAM deploys the function.
- The `deploy/docker/Dockerfile` base image is currently organization-specific and must be replaced with an approved, pullable Lambda Python 3.12 base image.
- The SAM template currently points Bedrock to a `us-east-1` inference profile, so region changes require template review.
- S3 bucket names must be globally unique per AWS account and region.
- Optional profiles require additional secrets, Knowledge Base IDs, allowlists, and owner approvals before enablement.
- `notable_rest` and ServiceNow create require validated endpoints, Secrets Manager lifecycle, and customer-specific identifier mapping.
- The workflow produces analyst guidance and gated side effects only; remediation or broader automation should go through explicit approval and policy gates outside this pipeline.

## Success Criteria

A successful end-to-end run is complete when:

1. A notable payload lands in `s3://<input-bucket>/incoming/`.
2. Lambda is invoked automatically by the S3 event.
3. Bedrock analysis completes or produces a preserved reviewable fallback.
4. Markdown and JSON reports (and HTML when enabled) are written to `s3://<output-bucket>/reports/`.
5. When `action_gated` and `notable_rest` are enabled, the corresponding Splunk notable receives the report comment without duplicate side effects.
6. When ServiceNow create is enabled and approved in the payload, the incident is created once per correlation ID.
7. Operators can trace the run through CloudWatch logs and S3 output.

## Current Recommended Rollout Path

Start with `core` and `SplunkSinkMode=s3` in a non-production AWS account or controlled customer environment. Validate deployment, Bedrock access, report quality, lifecycle behavior, and CloudWatch logs with representative notables. Add `html_reports`, `rag`, or read-only investigation profiles one at a time after owners approve the supporting Knowledge Bases, allowlists, and secrets. Enable `ticket_draft` when ServiceNow draft content in JSON is useful without creates. Use `action_gated` for new production Splunk writeback or ServiceNow create rollouts after boundaries, idempotency, and rollback expectations are documented and tested. Keep remediation and broader automation outside the workflow until explicit approval gates and policy controls are designed.
