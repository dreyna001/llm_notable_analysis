# ServiceNow Closed Ticket RAG (Azure Government)

Read-only sync of closed security tickets into Blob storage + Cosmos DB, hybrid
chunk indexing in Azure AI Search, and advisory retrieval for first-pass alert
analysis and analyst portal chat.

## One-time setup

1. Deploy the stack with closed-ticket Bicep parameters enabled:
   - `ServiceNowClosedTicketSyncEnabled=true`
   - `ClosedTicketRagEnabled=true` (for indexing and first-pass/portal retrieval)
   - `ServiceNowClosedTicketQuery` -- encoded ServiceNow filter for closed security tickets
   - `ServiceNowClosedTicketTokenSecretName` -- Key Vault secret name with bearer token
   - `AzureSearchEndpoint`, `AzureSearchResourceId`, and `RagTenantId` when RAG is enabled
   - `ClosedTicketAzureSearchIndex` (default `closed_tickets`)

2. Store the read-only ServiceNow bearer token in Key Vault (same pattern as disposition sync).

3. Confirm Cosmos containers and Blob prefix exist after deploy:
   - `{DeploymentPrefix}-closed-tickets` (ticket metadata + `index_status`, partition key `/ticket_id`)
   - `{DeploymentPrefix}-closed-ticket-sync-state` (sync cursor, partition key `/job_name`)
   - Blob prefix `closed_tickets/` under the output / case archive container

## Daily operation

- **Raw sync:** `closed_ticket_sync_timer` on the disposition Function app (daily at 01:00 UTC) pulls tickets, journals, and optional attachments. Raw envelopes land at `closed_tickets/<ticket_id>/envelope.json`; attachment bytes under `closed_tickets/<ticket_id>/attachments/`.
- **Indexing:** When `ClosedTicketRagEnabled=true`, `closed_ticket_embed_timer` (daily at 01:30 UTC) indexes up to **500** pending/failed tickets per run into the Azure AI Search `closed_tickets` corpus.
- **First-pass analysis:** When `ClosedTicketRagEnabled=true`, the analyzer Function app retrieves bounded historical closed-ticket excerpts into the `HISTORICAL_CLOSED_TICKETS` advisory lane. Metadata fields `closed_ticket_rag_*` are recorded on the analysis payload.
- **Portal chat:** When `CaseQaClosedTicketEnabled=true` and `ClosedTicketRagEnabled=true`, the portal Function app merges a closed-ticket advisory lane into chat responses.
- **Retention:** Each sync run purges tickets whose `expires_at` has passed (30/60/90 days from `ClosedTicketRetentionDays`, based on `closed_at` with fallbacks).

## Attachment text extraction (Azure Government)

When `ClosedTicketVisionEnabled=true`, the disposition embed timer uses **Azure AI
Document Intelligence Read** for image/PDF attachments. Text, JSON, CSV, and
plain-text attachments are decoded directly without Document Intelligence.

## Manual invocation

Sync (disposition Function app):

```bash
az functionapp function show \
  --resource-group <resource-group> \
  --name <prefix>-notable-disposition-sync \
  --function-name closed_ticket_sync_timer
```

Embed/index pending tickets:

```bash
az functionapp function show \
  --resource-group <resource-group> \
  --name <prefix>-notable-disposition-sync \
  --function-name closed_ticket_embed_timer
```

Use the Azure portal "Test/Run" path or an authenticated admin invoke against the
Function host when manual replay is approved.

## Verification

Cosmos -- active tickets by index status (Data Explorer or SDK query):

```sql
SELECT TOP 20 c.ticket_id, c.index_status, c.source_updated_at
FROM c
WHERE c.index_status = "ready"
ORDER BY c.source_updated_at ASC
```

Analyzer output metadata should include `closed_ticket_rag_enabled`,
`closed_ticket_rag_hit_count`, and related fields when RAG is enabled.

## Related docs

- [`SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md`](SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md) -- separate disposition sync (Cosmos dispositions, not RAG corpus)
- [`../deployment/AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md`](../deployment/AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md) -- customer-default preset (closed-ticket flags off by default)
