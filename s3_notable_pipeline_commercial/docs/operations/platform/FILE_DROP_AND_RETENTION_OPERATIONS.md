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

When `analyst_portal` is enabled, case envelopes and retrieval chunks are written
to the case archive bucket (defaults to the output bucket). The CaseIndex DynamoDB
table uses `expires_at_epoch` for TTL. Align S3 lifecycle and TTL with
`CaseRetentionDays`.

## Retention Equivalence (On-Prem vs AWS)

On-prem retention is driven by a **systemd timer** that runs
`retention.py` on a schedule. AWS does **not** port that script; it uses
**S3 lifecycle rules** and **DynamoDB TTL** to achieve the same policy intent.

| On-prem mechanism | AWS equivalent | Primary setting |
| --- | --- | --- |
| Delete or move aged inputs from `INCOMING_DIR` / processed paths | S3 lifecycle expiration on `incoming/` | `InputRetentionDays` |
| Delete aged markdown/JSON/HTML reports | S3 lifecycle expiration on `reports/` | `OutputRetentionDays` |
| Two-stage filesystem archive then delete for processed/quarantine/reports | Not ported literally; S3 lifecycle deletes objects in place | `InputRetentionDays`, `OutputRetentionDays` |
| Delete expired Postgres case rows and chunks | S3 lifecycle on case envelope/chunk prefixes plus DynamoDB TTL on CaseIndex `expires_at_epoch` | `CaseRetentionDays` |
| Delete expired side-effect idempotency markers | DynamoDB TTL on idempotency table `expires_at` | `SideEffectIdempotencyRetentionDays` |
| Scheduled retention timer | S3/DynamoDB automatic expiration (no cron Lambda required for v1) | Lifecycle and TTL only |

### On-prem gzip parity

On-prem gzip intake is **planned** (not discovered by `ingest.py` today). AWS gzip
intake is **implemented** in `lambda_handler.py` (see [Gzip compressed inputs](#gzip-compressed-inputs)).

| Topic | On-prem today | AWS (this stack) |
| --- | --- | --- |
| Gzip notables | Planned — top-level `*.json`/`.txt` only | Implemented — `.gz`/`.gzip` suffix or S3 `ContentEncoding: gzip` / `x-gzip` |
| Input size cap | `MAX_INPUT_FILE_BYTES` (default `4194304`) on raw files | `MaxDecompressedInputBytes` (default `1048576`) on uncompressed bytes and decompressed gzip payloads |
| Retention | Filesystem archive dirs + Postgres case/chat cleanup | S3 lifecycle + DynamoDB TTL |

On-prem target: single-payload `*.json.gz`, `*.txt.gz`, and `.gzip` suffix
variants with bounded decompression and `MAX_DECOMPRESSED_INPUT_BYTES` default
`1048576`. Until that ships on-prem, do not drop `.gz` files into `INCOMING_DIR`.

On-prem reference:
[`llm_notable_analysis_onprem_systemd/docs/operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../../../../llm_notable_analysis_onprem_systemd/docs/operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md).

Operational notes:

- **Policy alignment, not byte-for-byte parity:** on-prem may move files to an
  archive directory before deletion; AWS deletes S3 objects when lifecycle rules
  expire. Match the customer's evidence window with day counts, not directory
  layout.
- **Case archive:** set `CaseRetentionDays` consistently in stack parameters,
  S3 lifecycle rules for archive prefixes, and DynamoDB CaseIndex TTL. Lowering
  retention deletes analyst-visible cases after the window elapses.
- **Optional extensions:** customers that need custom purge logic (legal hold
  exceptions, cross-bucket copies, audit exports) can add EventBridge-scheduled
  Lambdas or downstream ops jobs. That is outside the default stack contract.
- **Validation:** before production cutover, confirm lifecycle and TTL match the
  agreed retention table and that exported evidence exists elsewhere when
  windows are shortened.

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

The Lambda processes objects created under `incoming/` in the input bucket
(S3 notification filter prefix `incoming/` in `template-sam.yaml`).

Supported payloads:

- UTF-8 plain text (`.txt`, or other non-gzip keys treated as text)
- UTF-8 JSON (`.json`)
- Single-payload gzip (`.gz` or `.gzip` suffix, or S3 `ContentEncoding: gzip`
  or `x-gzip`)

Not supported:

- ZIP archives or multi-file compressed uploads
- Empty objects, folder markers, and placeholder files (`.keep`, `.gitkeep`,
  `_success`, `.placeholder`)

For JSON payloads, include at least a clear alert summary in the object body.
Strongly preferred fields for correlation and writeback are `finding_id`,
`notable_id`, `sid`, `event_id`, `search_name`, `alert_time`, `risk_score`,
`threat_category`, and any raw event context the customer is allowed to send.

### Gzip compressed inputs

Gzip support is **implemented** in `lambda_handler.py`. Scope is **single-payload
gzip only** — not ZIP, nested archives, or multiple notables in one object.

**Detection:** `.gz` or `.gzip` suffix on the S3 key, or S3 object metadata
`ContentEncoding: gzip` or `x-gzip` (works even when the key has no `.gz`
suffix).

**Behavior:**

- Decompress with bounded streaming (`decompress_gzip_bounded`) before UTF-8
  decode and analysis.
- Treat inner type from the filename stem (for example `.json.gz` is JSON).
- Enforce `MAX_DECOMPRESSED_INPUT_BYTES` on decompressed size (SAM parameter
  `MaxDecompressedInputBytes`, default `1048576`); oversized payloads fail
  before Bedrock. The same limit applies to uncompressed object bytes.
- Compressed gzip objects may exceed the limit on the wire; only decompressed
  size is bounded.
- Output report names preserve the source prefix and strip both compression and
  inner data extensions (for example `incoming/abc-123.json.gz` ->
  `reports/incoming/abc-123--<processing_id>.md` for an S3 event).

**Failure modes (CloudWatch):**

- `Invalid gzip content for S3 object ...` — object is not valid gzip.
- `Decompressed input exceeds MAX_DECOMPRESSED_INPUT_BYTES (...)` — raise
  `MaxDecompressedInputBytes` only after measuring representative payloads.
- `S3 object ... exceeds MAX_DECOMPRESSED_INPUT_BYTES (...)` — uncompressed
  object too large.
- `S3 object ... must contain UTF-8 text` — fix source encoding or upload
  uncompressed JSON/text instead.

**Not supported:** ZIP archives, tar/gz multi-file bundles, nested archives.

If Splunk writeback is enabled (`notable_rest` + `action_gated`), confirm the
object key stem maps to the intended Splunk `finding_id`, or set
`SPLUNK_REQUIRE_PAYLOAD_FINDING_ID=true` and include a matching payload
`finding_id`.

Recommended delivery behavior: upload to a temporary key outside `incoming/`,
then copy or move to the final `incoming/<name>.json` key after upload
completes. This avoids partial reads on in-progress uploads.

### Where do inputs and reports live?

**Stack outputs / Lambda env:** `INPUT_BUCKET_NAME`, `OUTPUT_BUCKET_NAME`,
`OUTPUT_PREFIX`

| Location | Prefix / path | Template default |
| --- | --- | --- |
| Input trigger | `incoming/` | S3 event filter on input bucket |
| Markdown/JSON/HTML reports | `{OUTPUT_PREFIX}/` | `reports/` (`OUTPUT_PREFIX` fixed to `reports` in `template-sam.yaml`) |
| Case envelopes (analyst portal) | `{CaseArchivePrefix}/` | `cases/` |
| Case chunks (analyst portal) | `{CaseArchiveChunksPrefix}/` | `case_chunks/` |

Output object names preserve the input prefix and use the input file stem,
stripping gzip and inner data extensions (for example
`incoming/abc-123.json.gz` ->
`reports/incoming/abc-123--<processing_id>.md` for an S3 event).

When `CaseArchiveBucketName` is blank, case archive objects and report outputs
share the output bucket. A non-blank `CaseArchiveBucketName` points writes at an
external bucket the stack does not create.

### How long should inputs and reports stay?

**SAM/CloudFormation parameters:** `InputRetentionDays`, `OutputRetentionDays`,
`CaseRetentionDays`, `SideEffectIdempotencyRetentionDays`

Lifecycle rules in `template-sam.yaml`:

| Bucket | Prefix | Parameter | Default (days) |
| --- | --- | --- | --- |
| Input | `incoming/` | `InputRetentionDays` | 2 |
| Output | `reports/` | `OutputRetentionDays` | 7 |
| Output (when CaseIndex table is created) | `{CaseArchivePrefix}/` | `CaseRetentionDays` | 30 |
| Output (when CaseIndex table is created) | `{CaseArchiveChunksPrefix}/` | `CaseRetentionDays` | 30 |

DynamoDB TTL (automatic, not day-count parameters on the table resource):

- CaseIndex: `expires_at_epoch` aligned with `CaseRetentionDays`
- Side-effect idempotency: `expires_at` aligned with
  `SideEffectIdempotencyRetentionDays` (default 30)

Align retention with incident evidence, privacy, and storage policies. Export
reports elsewhere before lowering retention if long-term storage is required.

### How large can one notable be?

**SAM parameter:** `MaxDecompressedInputBytes`
**Lambda env:** `MAX_DECOMPRESSED_INPUT_BYTES` (default `1048576`)

- Applies to uncompressed object bytes and to decompressed gzip payloads
- Oversized input fails before Bedrock analysis starts
- Increase only after measuring representative alert sizes

Note: the SAM parameter description mentions gzip, but the runtime enforces the
same byte limit for plain text and JSON uploads.

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
| Report outputs | `OUTPUT_BUCKET_NAME`, `OUTPUT_PREFIX` (`reports`), `CAPABILITY_PROFILES` |
| Retention | `InputRetentionDays`, `OutputRetentionDays`, `CaseRetentionDays`, `SideEffectIdempotencyRetentionDays` |
| Case archive prefixes | `CaseArchivePrefix` (`cases`), `CaseArchiveChunksPrefix` (`case_chunks`) |
| Input size bound | `MaxDecompressedInputBytes` / `MAX_DECOMPRESSED_INPUT_BYTES` |
| Concurrency cap | `LambdaReservedConcurrentExecutions` |
| Payload correlation | S3 object key stem, JSON `finding_id` / `notable_id` / `sid` |

Runtime environment variables mirror the SAM/CloudFormation parameters above.

## Validation And Rollout

1. Deploy the stack and confirm bucket names from stack outputs.
2. Upload a small representative notable to `s3://<input-bucket>/incoming/test-notable.json`.
3. Confirm `reports/incoming/test-notable--<processing_id>.md` and
   `reports/incoming/test-notable--<processing_id>.json` appear in the output
   bucket with the same processing ID.
4. If `html_reports` is enabled, confirm the matching
   `reports/incoming/test-notable--<processing_id>.html`.
5. Upload `incoming/test-notable.json.gz` (valid gzip JSON) and confirm
   the new version-suffixed markdown and JSON keys use the source stem without
   `.gz`.
6. Upload an oversized or malformed object and confirm the invocation fails
   with a clear error in CloudWatch logs.
7. If `analyst_portal` is enabled, confirm case envelopes under `cases/`,
   chunks under `case_chunks/`, CaseIndex TTL on `expires_at_epoch`, and S3
   lifecycle rules match `CaseRetentionDays`.
8. Confirm lifecycle rules match expected retention before production cutover.

Smoke script (from the commercial project root):

```powershell
.\scripts\test-pipeline.ps1
```

## Related Docs

- [`CAPABILITY_PROFILES.md`](CAPABILITY_PROFILES.md)
- [`../../integrations/SOAR_PLAYBOOK_PHANTOM.md`](../../integrations/SOAR_PLAYBOOK_PHANTOM.md)
- [`RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md)
- [`../security/SECURITY_OPERATIONS.md`](../security/SECURITY_OPERATIONS.md)
- [`../deployment/DEPLOYMENT_IMAGE_STEPS.md`](../deployment/DEPLOYMENT_IMAGE_STEPS.md)
- [`../../testing/TESTING.md`](../../testing/TESTING.md)
