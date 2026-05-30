# Recovery Behavior And Responsibilities

This document defines restart and recovery expectations for the AWS S3-triggered
notable pipeline. It clarifies which reliability behavior is implemented in
Lambda, S3, DynamoDB idempotency, and external integrations.

## What This Controls

This guide sets operational expectations when processing is interrupted:
Lambda retries, duplicate processing risk, report and writeback ordering, and
who owns recovery tasks. It does not change runtime behavior.

## Recommended Starting Posture

- Keep `CAPABILITY_PROFILES=core` and `SplunkSinkMode=s3` until the base path is
  stable and observable.
- Enable `action_gated` only after owners accept external write/action risk.
- Validate restart and retry behavior with a known-good S3 upload before
  production.
- Document who decides whether to re-upload, replay, or archive a failed input.

## Customer Decisions

- Who owns CloudWatch log review, failed invocation triage, and redeploy rollback?
- Which artifacts are authoritative after partial failure: S3 report, Splunk
  comment, ServiceNow incident, or original S3 input object?
- What duplicate-processing risk is acceptable when S3 events are retried?
- Who approves manual re-upload of the same notable from `incoming/`?

## Scope

- Deployment model: S3 event -> Lambda container function.
- Input location: `s3://<input-bucket>/incoming/...`
- Output location: `s3://<output-bucket>/reports/...`
- Side-effect ledger: DynamoDB table configured by `SIDE_EFFECT_IDEMPOTENCY_TABLE`
- Core implementation: `src/s3_notable_pipeline/lambda_handler.py`,
  `src/s3_notable_pipeline/ttp_analyzer.py`, `src/s3_notable_pipeline/idempotency.py`

## Facts From Current Code

- One S3 object creation event starts one Lambda invocation for that object.
- Placeholder, empty, and oversize inputs fail before analysis begins.
- Successful processing writes markdown and JSON reports to the output bucket.
- When `SPLUNK_SINK_MODE=notable_rest`, S3 reports are written first; Splunk
  writeback is skipped if the S3 sink fails.
- When any record in the invocation fails, the handler raises an error so the
  Lambda invocation is marked failed.
- Input objects remain in the input bucket; there is no processed/quarantine move.
- Side-effect idempotency applies only to Splunk notable update and ServiceNow
  incident create when `action_gated` is enabled.
- Stale `in_progress` idempotency markers can be reclaimed after
  `SIDE_EFFECT_IDEMPOTENCY_LOCK_SECONDS`.

## Restart And Retry Behavior Matrix

### 1) Normal successful run

- Input object stays in `incoming/`.
- Reports appear under `reports/`.
- No side effects occur unless `action_gated` and configured sinks are enabled.

### 2) Lambda failure before reports are written

- No new report objects are expected.
- S3 may retry the event depending on customer retry configuration.
- Reprocessing the same input object may repeat Bedrock calls.

### 3) Lambda failure after reports are written but before external writeback completes

- S3 report artifacts may already exist.
- Splunk or ServiceNow side effects may not have occurred.
- A retry may regenerate reports and attempt side effects again unless
  idempotency blocks duplicate external actions.

### 4) Lambda failure after Splunk writeback succeeds

- Splunk comment may already exist.
- Input object remains in `incoming/`.
- A retry may attempt writeback again; DynamoDB idempotency should skip a
  duplicate successful write when the same `finding_id` marker is completed.

### 5) Lambda timeout during long Bedrock or investigation chains

- In-flight Bedrock calls are not resumed mid-request.
- Partial JSON in memory is lost; the invocation fails.
- Retry behavior depends on S3/Lambda event configuration.

### 6) Duplicate S3 notifications for the same object

- The pipeline does not maintain a durable per-object processing ledger for S3
  reports or Bedrock calls.
- Duplicate events can produce duplicate reports and duplicate Bedrock usage.
- External side effects are protected by DynamoDB idempotency when enabled.

## What AWS Provides

- **S3 event delivery:** can retry failed asynchronous invocations depending on
  configuration.
- **Lambda failure signaling:** failed invocations surface in CloudWatch and
  can trigger alarms.
- **DynamoDB idempotency table:** conditional writes for external side effects
  only.
- **Secrets Manager:** credential rotation without code changes.

AWS does not provide exactly-once analysis for every S3 upload unless the
customer adds an additional deduplication layer.

## What The Application Provides

Implemented in `s3_notable_pipeline`:

- **Input validation and size bounds:** reject malformed, placeholder, and
  oversize payloads early.
- **Bounded external query policy:** deny unsafe Splunk or Elastic queries before
  network calls.
- **Signed ServiceNow approval checks:** deny unsigned create attempts.
- **Side-effect idempotency:** skip duplicate Splunk writeback and ServiceNow
  create when markers are completed.
- **Stale lock reclaim:** allow retry after abandoned in-progress idempotency
  reservations.

The application does **not** implement durable checkpointing for multi-step
Bedrock analysis or mid-request resume.

## Practical Implications

- The pipeline is resumable at **object/event level**, not at **mid-analysis
  checkpoint level**.
- Duplicate reports and duplicate Bedrock usage are possible when the same S3
  object is processed more than once.
- External side effects are much safer when `action_gated` idempotency is
  enabled and keys are specific (`finding_id`, ServiceNow correlation id).
- Exactly-once semantics across report generation plus external writeback still
  require customer-level controls beyond this application.

## Recommendations

- Use atomic upload patterns (temporary key, then final `incoming/` key).
- Keep `LambdaReservedConcurrentExecutions` low until downstream capacity is
  known.
- Monitor CloudWatch for failed invocations and rising Bedrock latency.
- For writeback-heavy deployments, keep idempotency enabled and review skipped
  versus completed marker states in logs.
- If strict exactly-once report generation is required, add an external
  deduplication key or workflow outside this Lambda.

## Related Docs

- [`FILE_DROP_AND_RETENTION_OPERATIONS.md`](FILE_DROP_AND_RETENTION_OPERATIONS.md)
- [`CAPABILITY_PROFILES.md`](CAPABILITY_PROFILES.md)
- [`SPLUNK_WRITEBACK_OPERATIONS.md`](SPLUNK_WRITEBACK_OPERATIONS.md)
- [`SERVICENOW_OPERATIONS.md`](SERVICENOW_OPERATIONS.md)
- [`SECURITY_OPERATIONS.md`](SECURITY_OPERATIONS.md)
