# ServiceNow Operations

## What This Controls

This guide covers optional ServiceNow incident draft creation and
approval-gated incident create for AWS notable analysis.

Draft payloads appear under `servicenow_section.draft` in JSON reports. Create
results appear under `servicenow_section.create`. Create reads approval metadata
from the root of the incoming notable JSON (the S3 object body), not from report
output.

## Recommended Starting Posture

Start with `CAPABILITY_PROFILES=core` (no ServiceNow flags). Add
`CAPABILITY_PROFILES=core,ticket_draft` first so analysts can review
`incident_payload` drafts without network side effects. Enable create only with
`CAPABILITY_PROFILES=core,action_gated`, DynamoDB idempotency
(`SideEffectIdempotencyTableName` / `SIDE_EFFECT_IDEMPOTENCY_TABLE`), Secrets
Manager ARNs, and a trusted signed `servicenow_create_approval` object in the
incoming notable JSON.

Direct `SERVICENOW_DRAFT_ENABLED` / `SERVICENOW_CREATE_ENABLED` env overrides
remain for lab use; selected capability profiles take precedence.

## Customer Decisions

- Which assignment group should receive incident drafts?
- Which ServiceNow instance and table path should be used?
- Which trusted system signs `servicenow_create_approval` payloads, and how is
  the HMAC key stored and rotated in Secrets Manager?
- How long should DynamoDB idempotency rows be retained
  (`SideEffectIdempotencyRetentionDays` / `SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS`)?

## Profiles

| Profile | Sets |
|---------|------|
| `ticket_draft` | `SERVICENOW_DRAFT_ENABLED=true` |
| `action_gated` | `SERVICENOW_DRAFT_ENABLED=true`, `SERVICENOW_CREATE_ENABLED=true`, `SERVICENOW_CREATE_REQUIRES_APPROVAL=true`, `SIDE_EFFECT_IDEMPOTENCY_ENABLED=true` (also enables Splunk notable writeback when `SplunkSinkMode=notable_rest`; see [`SPLUNK_WRITEBACK_OPERATIONS.md`](SPLUNK_WRITEBACK_OPERATIONS.md)) |

## Config Quick Reference

Lambda env vars (SAM/CloudFormation parameters in parentheses where they differ):

- `CAPABILITY_PROFILES` (`CapabilityProfiles`)
- `SERVICENOW_BASE_URL` (`ServiceNowBaseUrl`)
- `SERVICENOW_CREATE_PATH` (default `/api/now/table/incident`; env override only)
- `SERVICENOW_API_TOKEN_SECRET_ARN` (`ServiceNowApiTokenSecretArn`)
- `SERVICENOW_APPROVAL_HMAC_SECRET_ARN` (`ServiceNowApprovalHmacSecretArn`)
- `SERVICENOW_ASSIGNMENT_GROUP` (`ServiceNowAssignmentGroup`)
- `SERVICENOW_TIMEOUT_SECONDS` (`ServiceNowTimeoutSeconds`)
- `SERVICENOW_CREATE_REQUIRES_APPROVAL` (default `true`; forced `true` by `action_gated`)
- `SIDE_EFFECT_IDEMPOTENCY_ENABLED` (on with `action_gated`)
- `SIDE_EFFECT_IDEMPOTENCY_TABLE` (`SideEffectIdempotencyTableName`)
- `SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS` (`SideEffectIdempotencyRetentionDays`)

### Secrets Manager

Lambda resolves secrets at runtime via `secretsmanager:GetSecretValue` (scoped in
the deploy template to the configured ARNs).

- **API token** (`SERVICENOW_API_TOKEN_SECRET_ARN`): plain string secret or JSON
  `{"token": "..."}`.
- **Approval HMAC key** (`SERVICENOW_APPROVAL_HMAC_SECRET_ARN`): JSON
  `{"hmac_key": "..."}` preferred; `secret` or `token` fields are accepted
  fallbacks. Required when create requires approval.

Store API and approval secrets separately. Do not log secret values or
authorization headers.

### Incoming create approval payload

Place this object at the root of the incoming notable JSON. When
`SERVICENOW_CREATE_REQUIRES_APPROVAL=true` (default):

- `approved` must be the JSON boolean `true` (string values such as `"false"` are
  denied).
- `approved_by` must be a non-empty string.
- `approval_ref` and `approved_at` are optional metadata fields included in the
  signed canonical payload.
- `signature` must be present and valid.

The `signature` is an HMAC-SHA256 hex digest. The signed message is canonical
JSON (sorted keys, compact separators) of:

```json
{
  "approved": true,
  "approval_ref": "CHANGE-123",
  "approved_at": "2026-05-29T21:00:00Z",
  "approved_by": "analyst@example.com",
  "correlation_id": "<draft correlation_id>"
}
```

`correlation_id` in the signed payload is the draft's `correlation_id`
(`finding_id` from the S3 object key when present, otherwise `notable_id`). It is
not supplied inside `servicenow_create_approval`. The signing service must use
the same `correlation_id` the analyzer will derive for that notable. Unsigned,
malformed, or mismatched signatures are denied.

Example incoming notable fragment:

```json
{
  "servicenow_create_approval": {
    "approved": true,
    "approved_by": "analyst@example.com",
    "approval_ref": "CHANGE-123",
    "approved_at": "2026-05-29T21:00:00Z",
    "signature": "hex-hmac-signature"
  }
}
```

Create is also skipped when draft generation did not produce a usable
`incident_payload` (for example, missing `SERVICENOW_ASSIGNMENT_GROUP`).

## Validation And Rollout

1. With `ticket_draft`, confirm `servicenow_section.draft.incident_payload` in
   JSON output and no ServiceNow HTTP call in CloudWatch logs.
2. With `action_gated`, confirm create status `denied` when approval is missing,
   `approved` is not boolean `true`, `approved_by` is empty, or the signature
   is invalid.
3. Confirm Secrets Manager holds the API token and a separate approval HMAC secret
   as described above; Lambda IAM can call `GetSecretValue` on both ARNs.
4. Upload the same notable twice with a valid signed approval and confirm the
   second create returns `skipped` via DynamoDB idempotency
   (`servicenow_incident_create` keyed by draft `correlation_id`).

Unit test command (from repository root):

```bash
python -m unittest discover -s s3_notable_pipeline/tests -p "test_servicenow.py" -v
```

## Related Docs

- [`SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md`](SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md) — Inbound closed disposition sync (AWS DynamoDB)
- [`SPLUNK_WRITEBACK_OPERATIONS.md`](SPLUNK_WRITEBACK_OPERATIONS.md)
- [`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md)
- [`../security/SECURITY_OPERATIONS.md`](../security/SECURITY_OPERATIONS.md)
- [`../../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`](../../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md)
