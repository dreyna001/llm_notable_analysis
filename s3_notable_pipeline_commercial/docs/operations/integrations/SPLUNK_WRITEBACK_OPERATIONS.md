# Splunk Writeback Operations

This guide covers optional Splunk Enterprise Security notable comment writeback
on AWS. It is separate from read-only SPL investigation in
[`SPL_OPERATIONS.md`](../investigation/SPL_OPERATIONS.md).

## What This Controls

When `SPLUNK_SINK_MODE=notable_rest` (SAM/CloudFormation parameter
`SplunkSinkMode=notable_rest`), the Lambda handler routes each completed analysis
to `write_to_notable_rest_sink()` in `lambda_handler.py`:

1. Write markdown, JSON, and optional HTML reports to the output S3 bucket under
   `OUTPUT_PREFIX` (default `reports/`).
2. POST the full markdown report to Splunk as a notable comment when step 1
   succeeds.

The Splunk REST call uses form fields `finding_id`, `comment`, and `status=2`
(In Progress). It uses HTTPS (`SPLUNK_BASE_URL`), Bearer auth from Secrets
Manager (or legacy `SPLUNK_API_TOKEN`), `Content-Type:
application/x-www-form-urlencoded`, and a 30-second timeout with TLS verification
enabled.

Writeback is a side effect and should be approved separately from read-only
Splunk search execution.

On AWS, writeback is selected by sink mode, not by `SPLUNK_SINK_ENABLED`. That
flag is set by the `action_gated` profile for parity with on-prem naming but is
not checked by the Lambda handler today.

## Recommended Starting Posture

- Deploy with `SplunkSinkMode=s3` / `SPLUNK_SINK_MODE=s3` until report quality
  and identifier mapping are validated.
- Add `CAPABILITY_PROFILES=core,action_gated` before production writeback so
  DynamoDB side-effect idempotency is enabled by default.
- Enable `SplunkSinkMode=notable_rest` only after the Splunk owner approves
  notable comment updates in a lab stack.
- Use a dedicated Secrets Manager secret with minimum writeback scope; avoid
  plain `SPLUNK_API_TOKEN` in Lambda env except for short lab tests.
- Keep `ALLOW_PRIVATE_OUTBOUND_ENDPOINTS=false` unless private Splunk endpoints
  are explicitly approved.

The legacy `notable_rest` sink path remains supported for existing deployments.
New production rollouts should pair it with `action_gated` so duplicate S3
event deliveries do not create duplicate Splunk comments.

## Customer Decisions

### Which sink mode and profile?

**Deploy:** `SplunkSinkMode` (maps to `SPLUNK_SINK_MODE`)

- `s3` — reports only; no Splunk POST.
- `notable_rest` — S3 reports plus Splunk notable comment writeback.

**Profile:** `action_gated` (sets `SIDE_EFFECT_IDEMPOTENCY_ENABLED=true`)

- Preferred for production writeback so replayed Lambda invocations skip
  completed Splunk updates.
- Idempotency can also be enabled explicitly with
  `SIDE_EFFECT_IDEMPOTENCY_ENABLED=true` when `SIDE_EFFECT_IDEMPOTENCY_TABLE`
  is configured.

### Which Splunk endpoint and secret?

**Lambda env / SAM parameters:** `SPLUNK_BASE_URL` / `SplunkBaseUrl`,
`SPLUNK_NOTABLE_UPDATE_PATH` / `SplunkNotableUpdatePath`,
`SPLUNK_API_TOKEN_SECRET_ARN` / `SplunkApiTokenSecretArn`,
`SPLUNK_API_TOKEN_SECRET_FIELD` / `SplunkApiTokenSecretField`

- Confirm the notable update path with the Splunk ES owner; default is
  `/services/notable_update`.
- Secret may be a plain string or JSON object; default JSON field name is
  `token`.
- Lambda IAM must allow `secretsmanager:GetSecretValue` on the Splunk token
  secret ARN.

### How is the notable matched?

`finding_id` is resolved by `resolve_finding_id_for_writeback()`:

- Default: S3 object filename stem after stripping one gzip suffix, for example
  `incoming/abc-123.json` or `incoming/abc-123.json.gz` -> `abc-123`.
- Optional payload override: first present field among `finding_id`,
  `notable_id`, or `sid` in the decoded alert JSON. When both payload and key
  supply a value, they must match or writeback fails closed.
- Values must match `^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$`.

Set `SPLUNK_REQUIRE_PAYLOAD_FINDING_ID=true` / `SplunkRequirePayloadFindingId=true`
when the SOAR handoff must include an explicit payload identifier.

### How long should idempotency rows be retained?

**Lambda env / SAM parameters:** `SIDE_EFFECT_IDEMPOTENCY_TABLE` /
`SideEffectIdempotencyTableName`, `SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS` /
`SideEffectIdempotencyRetentionDays`, `SIDE_EFFECT_IDEMPOTENCY_LOCK_SECONDS` /
`SideEffectIdempotencyLockSeconds`

- When idempotency is enabled, the DynamoDB table name is required at writeback
  time.
- TTL on stored rows follows `SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS` (default
  30).
- Stale in-progress locks expire after `SIDE_EFFECT_IDEMPOTENCY_LOCK_SECONDS`
  (default 900) so failed POSTs can be retried safely.

## Idempotency Behavior

When `SIDE_EFFECT_IDEMPOTENCY_ENABLED=true`, `write_to_splunk_rest()` reserves
DynamoDB key `splunk_notable_update` + `finding_id` before POSTing:

- **Completed marker** — second delivery skips the POST with
  `rest_result.status=skipped`; the combined sink still reports `success`.
- **Failed POST** — the in-progress lock is released; retry is safe.
- **S3 report writes** — not deduplicated by idempotency; treat the output
  object key as the natural boundary for one analysis run.

ServiceNow create uses the same table with a different operation key; see
[`SERVICENOW_OPERATIONS.md`](SERVICENOW_OPERATIONS.md).

## Config Quick Reference

| Area | Lambda env | SAM / CloudFormation parameter |
|------|------------|--------------------------------|
| Sink mode | `SPLUNK_SINK_MODE` | `SplunkSinkMode` |
| Profile bundle | `CAPABILITY_PROFILES` | `CapabilityProfiles` |
| Splunk base URL | `SPLUNK_BASE_URL` | `SplunkBaseUrl` |
| Notable update path | `SPLUNK_NOTABLE_UPDATE_PATH` | `SplunkNotableUpdatePath` |
| Token secret | `SPLUNK_API_TOKEN_SECRET_ARN`, `SPLUNK_API_TOKEN_SECRET_FIELD` | `SplunkApiTokenSecretArn`, `SplunkApiTokenSecretField` |
| Payload ID requirement | `SPLUNK_REQUIRE_PAYLOAD_FINDING_ID` | `SplunkRequirePayloadFindingId` |
| Idempotency | `SIDE_EFFECT_IDEMPOTENCY_ENABLED`, `SIDE_EFFECT_IDEMPOTENCY_TABLE`, `SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS`, `SIDE_EFFECT_IDEMPOTENCY_LOCK_SECONDS` | `SideEffectIdempotencyTableName`, `SideEffectIdempotencyRetentionDays`, `SideEffectIdempotencyLockSeconds` |
| Output location | `OUTPUT_BUCKET_NAME`, `OUTPUT_PREFIX` | `OutputBucketName`, `OutputPrefix` |

## Validation And Rollout

1. Deploy with `SplunkSinkMode=s3` and confirm markdown/JSON (and optional HTML)
   artifacts under the output prefix.
2. Switch to `SplunkSinkMode=notable_rest` in a lab stack with Splunk REST
   credentials and confirmed `finding_id` mapping.
3. Upload the same notable twice (or replay the S3 event) and confirm the second
   Splunk POST is skipped when idempotency is enabled.
4. Confirm CloudWatch logs do not contain tokens, secret ARNs, or raw
   Authorization headers.
5. Document token rotation, endpoint ownership, and rollback (`SplunkSinkMode=s3`)
   before production promotion.

Unit tests from the commercial project root:

```bash
python -m pytest tests/test_idempotency.py tests/test_lambda_handler.py -v
```

## Related Docs

- [`SPL_OPERATIONS.md`](../investigation/SPL_OPERATIONS.md) — read-only SPL
  generation and Splunk query execution (separate credentials path).
- [`SERVICENOW_OPERATIONS.md`](SERVICENOW_OPERATIONS.md) — ServiceNow draft/create
  and shared DynamoDB idempotency.
- [`CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md) — profile
  bundles including `action_gated`.
- [`RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](../platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md)
  — S3 event retries, side-effect replay, and operator ownership.
- [`SECURITY_OPERATIONS.md`](../security/SECURITY_OPERATIONS.md) — IAM, Secrets
  Manager, and outbound endpoint validation.
- [`../../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`](../../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md)
  — parity design for writeback and idempotency.
- [`../../testing/TESTING.md`](../../testing/TESTING.md) — full unit and staging
  validation matrix.
