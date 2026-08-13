# ServiceNow Closed Ticket RAG (AWS GovCloud)

Read-only sync of closed security tickets into S3 + DynamoDB, hybrid chunk indexing
in OpenSearch, and advisory retrieval for first-pass alert analysis and analyst
portal chat.

## One-time setup

1. Deploy the stack with closed-ticket parameters enabled:
   - `ServiceNowClosedTicketSyncEnabled=true`
   - `ClosedTicketRagEnabled=true` (for indexing and first-pass/portal retrieval)
   - `ServiceNowClosedTicketQuery` — encoded ServiceNow filter for closed security tickets
   - `ServiceNowClosedTicketTokenSecretArn` — Secrets Manager ARN with bearer token (`token` field)
   - `OpenSearchEndpoint` and `RagTenantId` when RAG is enabled

2. Store the read-only ServiceNow bearer token in Secrets Manager (same pattern as disposition sync).

3. Confirm DynamoDB tables and S3 prefix exist after deploy:
   - `{StackName}-closed-tickets` (ticket metadata + `index_status`)
   - `{StackName}-closed-ticket-sync-state` (sync cursor)
   - S3 prefix `closed_tickets/` (default) under the case archive / output bucket

## Daily operation

- **Raw sync:** `notable-closed-ticket-sync` Lambda (EventBridge `rate(1 day)`) pulls tickets,
  journals, and optional attachments. Raw envelopes land at
  `closed_tickets/<ticket_id>/envelope.json`; attachment bytes under
  `closed_tickets/<ticket_id>/attachments/`.
- **Indexing:** When `ClosedTicketRagEnabled=true`, `notable-closed-ticket-embed` indexes up to
  **500** pending/failed tickets per run into the OpenSearch `closed_tickets` corpus (default index
  name from `OpenSearchClosedTicketIndex`).
- **First-pass analysis:** When `ClosedTicketRagEnabled=true`, the analyzer Lambda retrieves
  bounded historical closed-ticket excerpts into the `HISTORICAL_CLOSED_TICKETS` advisory lane.
  Metadata fields `closed_ticket_rag_*` are recorded on the analysis payload.
- **Retention:** Each sync run purges tickets whose `expires_at` has passed (30/60/90 days from
  `ClosedTicketRetentionDays`, based on `closed_at` with fallbacks). DynamoDB TTL on
  `expires_at_epoch` provides a secondary expiry mechanism.

## Attachment text extraction (GovCloud)

When `ClosedTicketVisionEnabled=true`, the embed Lambda uses **Amazon Textract**
`DetectDocumentText` for image/PDF attachments (GovCloud-supported path). Text, JSON, CSV, and
plain-text attachments are decoded directly without Textract.

## Manual invocation

Sync:

```bash
aws lambda invoke --function-name notable-closed-ticket-sync /tmp/closed-ticket-sync.json
```

Embed/index pending tickets:

```bash
aws lambda invoke --function-name notable-closed-ticket-embed /tmp/closed-ticket-embed.json
```

## Verification

DynamoDB — active tickets by index status:

```bash
aws dynamodb query \
  --table-name <stack>-closed-tickets \
  --index-name IndexStatusIndex \
  --key-condition-expression "index_status = :s" \
  --expression-attribute-values '{":s":{"S":"ready"}}'
```

Analyzer output metadata should include `closed_ticket_rag_enabled`, `closed_ticket_rag_hit_count`,
and related fields when RAG is enabled.

## Related docs

- [`SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md`](SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md) — separate disposition sync (DynamoDB dispositions, not RAG corpus)
- [`SERVICENOW_OPERATIONS.md`](SERVICENOW_OPERATIONS.md) — ServiceNow write/draft operations
