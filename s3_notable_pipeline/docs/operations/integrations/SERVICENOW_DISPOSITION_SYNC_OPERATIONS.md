# ServiceNow Closed Disposition Sync Operations (AWS)

**Status:** Shipped for AWS `s3_notable_pipeline`. For outbound incident
draft/create, see [`SERVICENOW_OPERATIONS.md`](SERVICENOW_OPERATIONS.md).

## What This Controls

Scheduled **read-only** pull of **closed** ServiceNow security incidents into
DynamoDB (`{stack}-servicenow-dispositions`). Analyst close codes and notes are
stored separately from model `verdict` on archived cases. Optional link to a
portal case when correlation IDs match.

Direction: **ServiceNow -> our storage only**. No portal or analyzer writeback
to ServiceNow.

## AWS Resources

| Resource | Name pattern |
|----------|----------------|
| Disposition rows | `{StackName}-servicenow-dispositions` (PK `snow_sys_id`) |
| Sync cursor | `{StackName}-disposition-sync-state` (PK `job_name=servicenow_closed`) |
| Sync Lambda | `DispositionSyncLambdaName` (default `notable-disposition-sync`) |
| Schedule | EventBridge `rate(1 day)` |

Case linking reads `CaseIndex` (`correlation_id` column and optional
`CorrelationIdIndex` GSI) and may read archived case envelopes from S3 for
`alert_payload.notable_id`, `event_id`, or `sid` fallbacks.

## Customer Prerequisites

- Security Incident table available (default: **`sn_si_incident`**).
- Table API read access for a dedicated sync service account.
- HTTPS **`SERVICENOW_BASE_URL`** reachable from the disposition sync Lambda.
- Field map and code map JSON files baked into the Lambda image or mounted at
  paths referenced by env vars (see examples under
  `deploy/servicenow/disposition_*.example.json`).

### Closed tickets must expose these fields

| Field | Purpose |
|-------|---------|
| `sys_id` | Stable row key |
| `number` | INC/SIR display |
| `state` | Closed filter |
| `closed_at` | Backfill window |
| `sys_updated_on` | Incremental sync cursor |
| `close_code` | Analyst disposition (TP/FP/benign/etc.) |
| `close_notes` | Resolution text |
| `correlation_id` | Link to archived notable/case |

## Config Quick Reference

Lambda env vars (SAM/CloudFormation parameters in parentheses where they differ):

| Area | Primary variables |
|------|-------------------|
| Enablement | `SERVICENOW_DISPOSITION_SYNC_ENABLED` (`ServiceNowDispositionSyncEnabled`) |
| Endpoint/auth | `SERVICENOW_BASE_URL`, `SERVICENOW_DISPOSITION_SYNC_TOKEN` or `SERVICENOW_DISPOSITION_SYNC_TOKEN_SECRET_ARN` |
| Mapping | `SERVICENOW_DISPOSITION_FIELD_MAP`, `SERVICENOW_DISPOSITION_CODE_MAP` |
| Storage | `DISPOSITION_TABLE`, `DISPOSITION_SYNC_STATE_TABLE` (set by stack outputs) |
| Case link | `CASE_INDEX_TABLE`, `CASE_ARCHIVE_BUCKET`, `CASE_ARCHIVE_PREFIX` |
| Bounds | `SERVICENOW_DISPOSITION_BACKFILL_DAYS`, `DISPOSITION_RETENTION_DAYS` |

Defaults: sync **disabled**, backfill **90** days, retention **365** days.

## ServiceNow API Shape

```http
GET {SERVICENOW_BASE_URL}/api/now/table/{table}
Authorization: Bearer {SERVICENOW_DISPOSITION_SYNC_TOKEN}
```

Incremental query uses `sys_updated_on>{cursor}` with closed-state filter.
Auth failure fails the run without advancing the cursor. Reopened tickets in a
processed batch are marked `is_active=false`.

## Validation And Rollout

1. Deploy stack with disposition tables and sync Lambda (sync disabled).
2. Store read-only token in Secrets Manager; set
   `ServiceNowDispositionSyncTokenSecretArn`.
3. Package field/code maps into the Lambda image; set map path env vars.
4. Enable `ServiceNowDispositionSyncEnabled=true`; invoke Lambda manually once.
5. Confirm rows in the disposition table and cursor in sync-state table.
6. Close a test incident with known `close_code` and `correlation_id`; confirm
   normalized disposition and optional `case_id` link.

## Related Docs

- [`SERVICENOW_OPERATIONS.md`](SERVICENOW_OPERATIONS.md) — Outbound draft/create
- [`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md) — Case archive (model verdict today)
- On-prem planning reference: `llm_notable_analysis_onprem_systemd/docs/planning/SERVICENOW_CLOSED_DISPOSITION_SYNC_PLAN.md`
