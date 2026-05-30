# File Drop And Retention Operations

This guide helps customers tune S3 intake, report outputs, lifecycle retention,
input size limits, and Lambda concurrency without changing code.

## What This Controls

The pipeline triggers on new objects under `incoming/` in the input bucket.
Each supported object runs one Lambda analysis. Reports are written under
`reports/` in the output bucket as markdown and JSON. When the `html_reports`
profile is enabled, a third HTML object is also written.

S3 lifecycle rules delete old input objects under `incoming/` and old report
objects under `reports/` after configured retention periods.

## Recommended Starting Posture

- Keep `SplunkSinkMode=s3` until the base S3 report path is validated.
- Keep `CAPABILITY_PROFILES=core` for the first rollout.
- Use globally unique bucket names per environment.
- Keep `InputRetentionDays=2` and `OutputRetentionDays=7` until audit needs are
  agreed.
- Keep `MaxDecompressedInputBytes=1048576` unless representative gzip notables
  require a larger bound.
- Keep `LambdaReservedConcurrentExecutions=5` until downstream Bedrock and SIEM
  load is measured.

## Customer Decisions

### What should SOAR or operators upload?

The Lambda processes objects created under `incoming/` in the input bucket.

Supported payloads:

- UTF-8 plain text (`.txt`, or other non-gzip keys treated as text)
- UTF-8 JSON (`.json`)
- Single-payload gzip (`.gz` suffix or S3 `ContentEncoding: gzip`)

Not supported:

- ZIP archives or multi-file compressed uploads
- Empty objects, folder markers, and placeholder files (`.keep`, `_success`, etc.)

For JSON payloads, include at least a clear alert summary in the object body.
Strongly preferred fields for correlation and writeback are `finding_id`,
`notable_id`, `sid`, `event_id`, `search_name`, `alert_time`, `risk_score`,
`threat_category`, and any raw event context the customer is allowed to send.

If Splunk writeback is enabled (`notable_rest` + `action_gated`), confirm the
object key stem maps to the intended Splunk `finding_id`, or set
`SPLUNK_REQUIRE_PAYLOAD_FINDING_ID=true` and include a matching payload
`finding_id`.

Recommended delivery behavior: upload to a temporary key outside `incoming/`,
then copy or move to the final `incoming/<name>.json` key after upload
completes. This avoids partial reads on in-progress uploads.

### Where do inputs and reports live?

**Settings:** `INPUT_BUCKET_NAME`, `OUTPUT_BUCKET_NAME`, `OUTPUT_PREFIX`

- Input trigger prefix: `incoming/`
- Report prefix: `reports/` (default `OUTPUT_PREFIX`)
- Output object names use the input file stem, stripping gzip and inner data
  extensions (for example `incoming/abc-123.json.gz` -> `reports/abc-123.md`)

### How long should inputs and reports stay?

**SAM/CloudFormation parameters:** `InputRetentionDays`, `OutputRetentionDays`

- Input lifecycle deletes objects under `incoming/` after `InputRetentionDays`
- Output lifecycle deletes objects under `reports/` after `OutputRetentionDays`
- Align retention with incident evidence, privacy, and storage policies
- Export reports elsewhere before lowering retention if long-term storage is required

### How large can one notable be?

**Setting:** `MAX_DECOMPRESSED_INPUT_BYTES`

- Applies to uncompressed objects and to decompressed gzip payloads
- Oversized input fails before Bedrock analysis starts
- Increase only after measuring representative alert sizes

### How much parallel processing is allowed?

**Parameter:** `LambdaReservedConcurrentExecutions`

- Caps concurrent Lambda invocations for the function
- S3 can fan out many events; reserved concurrency limits downstream Bedrock,
  Splunk, Elastic, and ServiceNow load
- Increase only after measuring latency, cost, and external system capacity

## Config Quick Reference

| Area | Primary settings |
|------|-------------------|
| Intake trigger | S3 `incoming/` prefix, `INPUT_BUCKET_NAME` |
| Report outputs | `OUTPUT_BUCKET_NAME`, `OUTPUT_PREFIX`, `CAPABILITY_PROFILES` |
| Retention | `InputRetentionDays`, `OutputRetentionDays` |
| Input size bound | `MaxDecompressedInputBytes` |
| Concurrency cap | `LambdaReservedConcurrentExecutions` |
| Payload correlation | S3 object key stem, JSON `finding_id` / `notable_id` / `sid` |

Runtime environment variables mirror the SAM/CloudFormation parameters above.

## Validation And Rollout

1. Deploy the stack and confirm bucket names from stack outputs.
2. Upload a small representative notable to `s3://<input-bucket>/incoming/test-notable.json`.
3. Confirm `reports/test-notable.md` and `reports/test-notable.json` appear in
   the output bucket.
4. If `html_reports` is enabled, confirm `reports/test-notable.html`.
5. Upload an oversized or malformed object and confirm the invocation fails
   with a clear error in CloudWatch logs.
6. Confirm lifecycle rules match expected retention before production cutover.

Smoke script:

```powershell
.\scripts\test-pipeline.ps1
```

## Related Docs

- [`CAPABILITY_PROFILES.md`](CAPABILITY_PROFILES.md)
- [`../integrations/SOAR_PLAYBOOK_PHANTOM.md`](../integrations/SOAR_PLAYBOOK_PHANTOM.md)
- [`RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md)
- [`SECURITY_OPERATIONS.md`](SECURITY_OPERATIONS.md)
- [`DEPLOYMENT_IMAGE_STEPS.md`](DEPLOYMENT_IMAGE_STEPS.md)
- [`../testing/TESTING.md`](../testing/TESTING.md)
