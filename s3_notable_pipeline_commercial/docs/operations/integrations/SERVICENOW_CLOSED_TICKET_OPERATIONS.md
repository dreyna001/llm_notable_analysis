# ServiceNow Closed Ticket Sync Operations (AWS)

**Status:** P3 foundation shipped (sync only). Index/embed (P4) is not included in
this block.

## What This Controls

Scheduled **read-only** pull of **closed security tickets** from ServiceNow Table
API into versioned S3 raw storage with sync cursor and ticket registry in DynamoDB.
Optional journal and attachment download (bytes only; no execution).

Direction: **ServiceNow -> our storage only**. No ticket creation or writeback.

This is separate from **disposition sync** (metadata-only close codes for case
linking). See
[`SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md`](SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md).

## AWS Resources

| Resource | Name pattern |
|----------|----------------|
| Raw ticket JSON + attachments | S3 `{ClosedTicketRawPrefix}/...` on archive/output bucket |
| Sync cursor | `{StackName}-closed-ticket-sync-state` (PK `job_name=servicenow_closed_tickets`) |
| Ticket registry | `{StackName}-closed-ticket-registry` (PK `ticket_id`; TTL `expires_at_epoch`) |
| Sync Lambda | `ClosedTicketSyncLambdaName` (default `notable-closed-ticket-sync`) |
| Schedule | EventBridge `rate(1 day)` |

## S3 Key Layout (P4 consumer)

P4 render/chunk/index workers should treat `manifest.json` as the entry point:

```text
{ClosedTicketRawPrefix}/
  tickets/{ticket_sys_id}/
    manifest.json
    versions/{content_hash}/ticket.json
  attachments/{ticket_sys_id}/{attachment_sys_id}/{safe_filename}
```

`manifest.json` fields include `version_key`, `content_hash`, `index_status`
(`pending` when ready for P4), `is_active`, and retention timestamps.

## Customer Prerequisites

- Security Incident table (default **`sn_si_incident`**).
- Table API read access for a dedicated sync service account.
- HTTPS **`SERVICENOW_BASE_URL`** reachable from the closed-ticket sync Lambda.
- Encoded query for closed tickets (example: `state=3^assignment_group=...`).

## Config Quick Reference

| Area | Primary variables |
|------|-------------------|
| Enablement | `SERVICENOW_CLOSED_TICKET_SYNC_ENABLED` (`ServiceNowClosedTicketSyncEnabled`) |
| Endpoint/auth | `SERVICENOW_BASE_URL`, `SERVICENOW_CLOSED_TICKET_TOKEN` or `SERVICENOW_CLOSED_TICKET_TOKEN_SECRET_ARN` |
| Query/table | `SERVICENOW_CLOSED_TICKET_QUERY`, `SERVICENOW_CLOSED_TICKET_TABLE` |
| Storage | `CLOSED_TICKET_RAW_PREFIX`, `CLOSED_TICKET_ARCHIVE_BUCKET` (defaults to output/archive bucket) |
| State | `CLOSED_TICKET_SYNC_STATE_TABLE`, `CLOSED_TICKET_REGISTRY_TABLE` (set by stack) |
| Child rows | `SERVICENOW_CLOSED_TICKET_FETCH_JOURNALS`, `SERVICENOW_CLOSED_TICKET_FETCH_ATTACHMENTS` |
| Bounds | `SERVICENOW_CLOSED_TICKET_BACKFILL_DAYS`, `CLOSED_TICKET_RETENTION_DAYS` (30/60/90), `CLOSED_TICKET_ATTACHMENT_MAX_BYTES` |

Defaults: sync **disabled**, backfill **30** days, retention **30** days.

## ServiceNow API Shape

```http
GET {SERVICENOW_BASE_URL}/api/now/table/{table}
Authorization: Bearer {SERVICENOW_CLOSED_TICKET_TOKEN}
```

Incremental sync uses customer query plus cursor clause on `sys_updated_on` and
`sys_id`. Auth failure fails the run without advancing the cursor.

## Validation And Rollout

1. Deploy stack with closed-ticket tables and sync Lambda (sync disabled).
2. Store read-only token in Secrets Manager; set `ServiceNowClosedTicketTokenSecretArn`.
3. Set `ServiceNowClosedTicketQuery` to the customer closed-ticket encoded query.
4. Enable `ServiceNowClosedTicketSyncEnabled=true` and invoke Lambda once manually.
5. Confirm S3 objects under `{ClosedTicketRawPrefix}/tickets/` and cursor row in
   sync state table.
6. P4 index worker (future): scan registry for `index_status=pending` or read
   manifests directly.

## Known Limitations (P3)

- No OpenSearch indexing or analyzer/portal RAG lanes (P4-P6).
- Attachment vision/OCR not implemented (P7).
- Reconciliation skips deactivation when ServiceNow source fetch hits the page cap.
