# Recovery Behavior And Responsibilities

This document defines restart and recovery expectations for the AWS S3-triggered
notable pipeline. It clarifies which reliability behavior is implemented in
Lambda, S3, DynamoDB idempotency, and external integrations.

Shared recovery concepts with on-prem (file-level replay, side-effect idempotency
keys, crash windows) are aligned with
[`llm_notable_analysis_onprem_systemd/docs/operations/platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](../../../../llm_notable_analysis_onprem_systemd/docs/operations/platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md).
AWS-specific differences (no input move/quarantine, sink-gated success, S3 report
overwrite) are called out below.

## What This Controls

This guide sets operational expectations when processing is interrupted:
Lambda retries, duplicate processing risk, report and writeback ordering, and
who owns recovery tasks. It does not change runtime behavior.

## Recommended Starting Posture

- Keep `CAPABILITY_PROFILES=core` and `SplunkSinkMode=s3` until the base path is
  stable and observable.
- Enable `action_gated` only after owners accept external write/action risk and
  the DynamoDB idempotency table is deployed.
- Validate restart and retry behavior with a known-good S3 upload before
  production.
- Document who decides whether to re-upload, replay, or archive a failed input.

## Customer Decisions

- Who owns CloudWatch log review, failed invocation triage, and redeploy rollback?
- Which artifacts are authoritative after partial failure: S3 report, Splunk
  comment, ServiceNow incident, or original S3 input object?
- What duplicate-processing risk is acceptable when S3 events are retried?
- Who approves manual re-upload of the same notable to `incoming/`?
- When `analyst_portal` is enabled, is a missing case archive acceptable while
  reports exist (`CASE_ARCHIVE_FAILURE_MODE=suppress`), or should archive failure
  fail the invocation (`fail_closed`)?

## Scope

- Deployment model: S3 event -> Lambda container function (`lambda_handler.handler`).
- Input location: `s3://<input-bucket>/incoming/...`
- Output location: `s3://<output-bucket>/reports/...`
- Side-effect ledger: DynamoDB table configured by `SIDE_EFFECT_IDEMPOTENCY_TABLE`
- Core implementation: `src/s3_notable_pipeline/lambda_handler.py`,
  `src/s3_notable_pipeline/ttp_analyzer.py`, `src/s3_notable_pipeline/idempotency.py`,
  `src/s3_notable_pipeline/case_archive.py`, `src/s3_notable_pipeline/servicenow.py`

## Facts From Current Code

- One S3 object-creation record starts one processing attempt for that object.
  Events may contain multiple records; if any record ends in `status=error`, the
  handler raises `RuntimeError` and the invocation is marked failed.
- Folder markers, placeholder basenames (`.keep`, `.gitkeep`, `_success`,
  `.placeholder`), and 0-byte objects are skipped with `status=skipped` and do
  not fail the invocation.
- Malformed, oversize, or invalid gzip/UTF-8 inputs fail before Bedrock analysis
  begins and mark the record `status=error`.
- **Success boundary:** a record is successful only when the final sink returns
  `status=success`. There is no `move_to_processed()` or quarantine path; input
  objects remain in `incoming/` after success or failure.
- **Processing order (one record):** Bedrock analysis -> optional RAG and
  read-only investigation queries -> optional ServiceNow draft/create (embedded
  in `llm_response`) -> markdown/HTML report generation -> report sink
  (`s3` or `notable_rest`) -> optional case archive when `analyst_portal` is
  enabled.
- When `SPLUNK_SINK_MODE=notable_rest`, S3 reports are written first; Splunk REST
  writeback runs only when the S3 sink succeeds. Splunk `skipped` from
  idempotency still counts as sink success.
- When `SPLUNK_SINK_MODE=s3`, no Splunk writeback occurs regardless of profile.
- ServiceNow draft/create failures are recorded in `llm_response` but do not by
  themselves fail the invocation; report sink failure does.
- Report objects use deterministic keys derived from the input stem
  (`reports/<stem>.md`, `.json`, optional `.html`) and are overwritten on
  reprocess when no S3 processing identity is present. When versioned processing
  identity is available, report keys include a `--<processing_id>` suffix and
  are created with `IfNoneMatch="*"`. Retries reconcile existing artifacts by
  verifying byte-identical content before writing missing siblings; content
  mismatch fails closed.
- Side-effect idempotency is **off by default**; the `action_gated` profile sets
  `SIDE_EFFECT_IDEMPOTENCY_ENABLED=true`. It applies only to Splunk notable
  update and ServiceNow incident create, not Bedrock calls, local S3 reports,
  read-only investigation queries, or case archive writes.
- Case archive replay uses CaseIndex identity checks in `case_archive.py` (separate
  from side-effect idempotency). Claimed runs stuck after partial envelope,
  completion, or embed publication are reconciled on replay: verify the expected
  envelope (or write it when missing), finalize the run, and republish pending
  embed requests without duplicating completed side effects. Envelope content
  mismatch fails closed. With `CASE_ARCHIVE_FAILURE_MODE=suppress`
  (default), archive errors are logged and attached to `sink_result` without
  failing the record; `fail_closed` propagates the error and fails the record.
- Stale `in_progress` side-effect markers can be reclaimed after
  `SIDE_EFFECT_IDEMPOTENCY_LOCK_SECONDS` (default 900).

## Restart And Retry Behavior Matrix

### 1) Normal successful run

- Input object stays in `incoming/`.
- Reports appear under `reports/` (and optional HTML when enabled).
- Optional ServiceNow draft/create metadata is embedded in the JSON report.
- No Splunk writeback unless `SPLUNK_SINK_MODE=notable_rest`.
- Optional case archive runs after a successful report sink.

### 2) Lambda failure before reports are written

- No new report objects are expected (unless a prior attempt partially wrote them).
- Input remains in `incoming/`.
- S3/Lambda may redeliver the event depending on customer retry configuration.
- Reprocessing repeats Bedrock calls and read-only investigation queries.

### 3) Lambda failure after reports are written but before external writeback completes

- Applies mainly to `notable_rest`: S3 markdown/JSON/HTML may already exist while
  Splunk POST has not succeeded.
- When processing identity is present, partial S3 report writes use create-only
  keys; a retry verifies existing artifacts and completes missing markdown/JSON/HTML
  siblings. Content mismatch fails closed.
- ServiceNow create may already have succeeded earlier in the same attempt (before
  report generation); that outcome is not rolled back.
- A retry overwrites report objects at the same keys and may retry Splunk
  writeback unless idempotency blocks it.

### 4) Lambda failure after Splunk writeback succeeds

- Splunk comment may already exist; input remains in `incoming/`.
- A retry overwrites S3 reports and may attempt writeback again; DynamoDB
  idempotency should return `status=skipped` when a completed marker exists for
  the same `finding_id`.
- **Crash window:** Splunk POST succeeded but `complete_side_effect_success()`
  did not persist the marker -> replay may duplicate the comment.

### 5) Lambda timeout during long Bedrock or investigation chains

- In-flight Bedrock or HTTP calls are not resumed mid-request.
- Partial in-memory analysis is lost; the record fails unless already marked
  success (unlikely mid-chain).
- Retry behavior depends on S3/Lambda event configuration.

### 6) Duplicate S3 notifications for the same object

- The pipeline does not maintain a durable per-object processing ledger for S3
  reports, Bedrock usage, or investigation queries.
- Duplicate events can overwrite reports at the same keys and repeat Bedrock and
  SIEM/Elastic query usage.
- External side effects are protected by DynamoDB idempotency when enabled.
- Case archive replay for the same identity returns success without rewriting
  when CaseIndex already matches.

### 7) Report sink succeeds but case archive fails

- **`CASE_ARCHIVE_FAILURE_MODE=suppress` (default):** invocation succeeds;
  `case_archive_result.status=error` is attached for operator review; reports
  remain authoritative.
- **`CASE_ARCHIVE_FAILURE_MODE=fail_closed`:** archive exception fails the
  record and the invocation; S3 reports from that attempt may already exist.

### 8) ServiceNow create error logged, report sink still succeeds

- Create failure is stored under `llm_response.servicenow_section.create` with
  `status=error`; the invocation still succeeds when the report sink succeeds.
- The input will **not** auto-retry ServiceNow unless the S3 event is redelivered
  or the object is uploaded again.

## Side-Effect Idempotency And Replay

Implemented in `idempotency.py`, invoked from `lambda_handler.py` (Splunk) and
`servicenow.py` (create):

| Operation | Key | Replay when marker exists |
| --- | --- | --- |
| `splunk_notable_update` | `finding_id` (payload `finding_id`/`notable_id`/`sid` when present and consistent, else input key stem) | Skip POST; return `status=skipped` |
| `servicenow_incident_create` | draft `correlation_id`, else `correlation_display` | Skip POST; return prior `sys_id`/`number` from marker metadata |

Mechanics:

- `begin_side_effect()` reserves with a conditional DynamoDB put; skips when a
  completed or in-progress marker exists.
- Stale `in_progress` markers older than `SIDE_EFFECT_IDEMPOTENCY_LOCK_SECONDS`
  are deleted and the side effect may run again.
- `complete_side_effect_success()` sets `status=completed` after a successful
  external POST; a failed write returns `idempotency_recorded=false` (ServiceNow
  also surfaces `idempotency_warning`).
- Failed POST calls `release_side_effect_lock()` so a later retry can execute.
- Generic/missing keys raise `ValueError` when idempotency is enabled.
- Items carry TTL via `expires_at` aligned to
  `SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS` (best-effort DynamoDB expiration).

Idempotency does **not** deduplicate Bedrock calls, S3 report writes, case archive
envelope writes (except CaseIndex identity replay), or read-only investigation
queries.

## What AWS Provides

- **S3 event delivery:** can retry failed asynchronous invocations depending on
  configuration.
- **Lambda failure signaling:** failed invocations surface in CloudWatch and
  can trigger alarms.
- **DynamoDB idempotency table:** conditional writes for external side effects
  when enabled; separate CaseIndex conditional semantics for case archive.
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
- **Case archive identity replay:** skip duplicate archive writes when CaseIndex
  identity matches an existing row.

The application does **not** implement durable checkpointing for multi-step
Bedrock analysis or mid-request resume.

## Practical Implications

- Recovery is **object/event level**, not mid-analysis checkpoint level (same
  intent as on-prem file-level recovery).
- Unlike on-prem, there is no quarantine move; failed inputs stay in `incoming/`
  until lifecycle deletion or operator action.
- Unlike on-prem, report sink failure fails the invocation; ServiceNow create
  failure alone does not.
- Duplicate Bedrock usage and report overwrite are possible when the same S3
  object is processed more than once.
- External side effects are much safer when `action_gated` idempotency is enabled
  and keys are specific (`finding_id`, ServiceNow correlation id).
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
- [`../integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](../integrations/SPLUNK_WRITEBACK_OPERATIONS.md)
- [`../integrations/SERVICENOW_OPERATIONS.md`](../integrations/SERVICENOW_OPERATIONS.md)
- [`../security/SECURITY_OPERATIONS.md`](../security/SECURITY_OPERATIONS.md)
