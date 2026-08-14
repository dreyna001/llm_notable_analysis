# Azure Government on-prem customer-default parity plan

## Status

**In progress (2026-08-13).** AWS GovCloud shipped P0–P8 on `main`; this plan tracks the
Azure Government native port. Behavioral source of truth: `s3_notable_pipeline/` (GovCloud)
and on-prem `llm_notable_analysis_onprem_systemd/`.

## Target

- **Cloud:** `AzureUSGovernment` only (`usgovvirginia` default).
- **Profiles:** `core,rag,analyst_portal` customer-default bundle (no first-pass SPL generation).
- **Behavior:** Match GovCloud fail-soft boundaries, retention, and portal OpenAPI contracts.
- **Implementation:** Azure-native SDKs and resources only (Cosmos, Blob, Timer Functions, AI Search).

## Phase mapping (AWS GovCloud -> Azure Government)

| Phase | AWS (GovCloud) | Azure (Government) |
| --- | --- | --- |
| **P0** | `customer-default.env.example`, `GOVCLOUD_CUSTOMER_DEFAULT_DEPLOYMENT.md` | `deploy/azure/presets/customer-default.env.example`, `AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md` |
| **P1** | Bedrock Cohere/Amazon rerank after OpenSearch hybrid fetch | Azure AI Search **semantic ranker** when `RAG_RERANK_ENABLED=true`; log `rerank_status=skipped` on SKU/billing failure |
| **P2** | `kb_document_extract.py` (pypdf, python-docx, optional Textract) | `kb_document_extract.py` (pypdf, python-docx; optional **Document Intelligence Read** for images) |
| **P3** | Scheduled Lambda + DynamoDB cursor + S3 raw envelopes | Daily **timer Function** on disposition app (or dedicated sync app) + **Cosmos** ticket/sync-state containers + Blob archive |
| **P4** | `closed_tickets` OpenSearch index + embed Lambda | **Azure AI Search** `closed_tickets` index + timer embed pass |
| **P5** | `historical_closed_ticket_grounding.py` in analyzer | Same module (cloud-neutral); wired in `blob_handler.py` |
| **P6** | Portal `closed_ticket` chat lane | `portal_chat.py` / `case_chat.py` lane merge with Search retrieval |
| **P7** | Textract OCR on closed-ticket attachments | **Document Intelligence Read** when `CLOSED_TICKET_VISION_ENABLED=true` |
| **P8** | `portal_chat_images.py` + multimodal Bedrock | `portal_chat_images.py` + Azure OpenAI multimodal when enabled |

## Azure-native resource additions

| Resource | Purpose |
| --- | --- |
| Cosmos `{prefix}-closed-tickets` | Ticket metadata, `index_status`, retention `expires_at` |
| Cosmos `{prefix}-closed-ticket-sync-state` | Sync cursor (`job_name=servicenow_closed_tickets`) |
| Blob prefix `closed_tickets/` | Raw envelopes + attachment bytes |
| Search index `closed_tickets` | Hybrid BM25 + 1024-d vector (customer-provisioned endpoint) |
| Timer `closed_ticket_sync_timer` | Daily ServiceNow Table API pull |
| Timer `closed_ticket_embed_timer` | Daily pending-ticket index pass |

Disposition sync (`servicenow_disposition_sync.py`) remains separate from closed-ticket raw sync.

## Config flags (mirror GovCloud names)

All default **off** in customer-default preset:

- `IMAGE_INGEST_*`, `SERVICENOW_CLOSED_TICKET_*`, `CLOSED_TICKET_*`
- `CASE_QA_CLOSED_TICKET_*`, `CASE_QA_CHAT_IMAGES_*`
- `RAG_RERANK_ENABLED` (Search semantic ranker; no Bedrock model IDs on Azure)

## Explicit Azure-only differences

| Area | Difference |
| --- | --- |
| Rerank | Search semantic configuration instead of Bedrock model ARNs |
| OCR / vision | Document Intelligence Read endpoint (customer-provisioned) instead of Textract |
| Persistence | Cosmos containers + Blob names instead of DynamoDB + S3 keys |
| Schedulers | Azure Functions timer triggers instead of EventBridge |
| Multimodal chat | Azure OpenAI vision-capable deployment instead of Bedrock converse |

## Out of scope (same as GovCloud)

- Backup/RPO/RTO product guarantees
- Commercial Azure partition
- Analyzer explicit backlog queue (separate AWS backlog item)

## Verification

- Unit tests ported from GovCloud with Azure client fakes
- `pytest tests -q` under `azure_notable_pipeline/`
- Bicep compile: `az bicep build --file deploy/azure/main.bicep`
- Live Azure Government staging (operator-owned): sync cursor, Search index, portal lanes

## References

- GovCloud shipped checklist: [`../../../s3_notable_pipeline/docs/planning/TODOS.md`](../../../s3_notable_pipeline/docs/planning/TODOS.md)
- Azure baseline tracker: [`AZURE_IMPLEMENTATION_TRACKER.md`](AZURE_IMPLEMENTATION_TRACKER.md)
- On-prem normative: [`../../../llm_notable_analysis_onprem_systemd/docs/planning/FUTURE_ENHANCEMENTS_ROADMAP.md`](../../../llm_notable_analysis_onprem_systemd/docs/planning/FUTURE_ENHANCEMENTS_ROADMAP.md)
