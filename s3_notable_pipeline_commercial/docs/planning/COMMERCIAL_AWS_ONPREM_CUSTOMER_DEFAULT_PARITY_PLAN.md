# Commercial AWS On-Prem Customer-Default Parity Plan

## Status

- Plan created: 2026-08-12
- P0 operator preset: **shipped** (2026-08-13)
- P1–P8 feature parity: **shipped** on branch `feature/commercial-aws-onprem-parity` (2026-08-13) — rerank, rich KB ingest, closed-ticket vertical slice, portal chat images
- Remaining: operator staging validation, customer-default preset refresh for optional closed-ticket flags, live AWS smoke
- Target product: `s3_notable_pipeline_commercial/` only (`aws`, `us-east-1`)
- Sibling production tree (`../s3_notable_pipeline/`) is out of scope unless explicitly merged later

## Goal

Port on-prem **customer-default** capabilities into commercial AWS so operators can deploy
`CapabilityProfiles=core,rag,analyst_portal` with the same advisory retrieval lanes as
on-prem, without first-pass SPL generation.

On-prem normative reference:

- [`../../../llm_notable_analysis_onprem_systemd/docs/operations/deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md`](../../../llm_notable_analysis_onprem_systemd/docs/operations/deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md)
- [`../../../llm_notable_analysis_onprem_systemd/docs/planning/CLOSED_TICKET_RAG_PLAN.md`](../../../llm_notable_analysis_onprem_systemd/docs/planning/CLOSED_TICKET_RAG_PLAN.md)

Central backlog register:
[`../../../llm_notable_analysis_onprem_systemd/docs/planning/FUTURE_ENHANCEMENTS_ROADMAP.md`](../../../llm_notable_analysis_onprem_systemd/docs/planning/FUTURE_ENHANCEMENTS_ROADMAP.md)

## Target operator bundle (commercial)

| Setting | Value |
| --- | --- |
| `CapabilityProfiles` | `core,rag,analyst_portal` |
| `RagEnabled` / `RagIngestionEnabled` | `true` |
| `SplQueryRagEnabled` | `true` (portal dictionary grounding only) |
| `spl_readonly` | **off** (no first-pass SPL generation) |
| OpenSearch | VPC-only domain; indexes: `soc_knowledge`, `case_chunks`, `splunk_dictionary` |
| Closed-ticket flags | new SAM parameters (this plan) |

## Hard boundaries

- Modify only `s3_notable_pipeline_commercial/` (per [`AGENTS.md`](../../AGENTS.md)).
- Do not edit, deploy, or import from `../s3_notable_pipeline/`.
- Partition `aws` and region `us-east-1` only; fail closed elsewhere.
- Historical ticket and KB content remain **advisory**; never promoted to alert evidence.
- No live AWS mutations without explicit operator approval per deployment runbook.
- Record intentional commercial deltas in [`../internal/COMMERCIAL_AWS_APPROVED_DIFFERENCES.md`](../internal/COMMERCIAL_AWS_APPROVED_DIFFERENCES.md).

## Already shipped (enable + configure only)

No new code required for baseline customer-default analysis + portal:

- S3 ingest, Bedrock analysis, markdown/JSON reports (`core`)
- General SOC RAG via OpenSearch (`rag`)
- Case archive, embed queue, portal API/UI, pinned-case Q&A (`analyst_portal`)
- SPL dictionary retrieval for **portal chat** when `SplQueryRagEnabled=true`
- ServiceNow **disposition** sync (metadata only; not closed-ticket RAG)

## Parity gaps (this plan)

| ID | Capability | On-prem modules (reference) | Commercial AWS target |
| --- | --- | --- | --- |
| P0 | Customer-default operator preset | `CUSTOMER_DEFAULT_DEPLOYMENT.md` | SAM parameter preset doc + staging smoke |
| P1 | RAG rerank runtime | Postgres + Granite reranker | Bedrock rerank in `opensearch_retrieval` / ingest paths |
| P2 | KB image/PDF/DOCX ingest | `corpus_ingest`, `IMAGE_INGEST_*` | Extend `rag_ingestion.py` + ingestion Lambda (Textract/Bedrock vision TBD) |
| P3 | Closed-ticket ServiceNow sync | `servicenow_closed_ticket_sync.py` | Scheduled Lambda + S3 raw store + DynamoDB sync state |
| P4 | Closed-ticket render/chunk/index | `closed_ticket_render.py`, `closed_ticket_index.py` | Post-sync worker + OpenSearch `closed_ticket` index lane |
| P5 | Closed-ticket analysis RAG | `historical_closed_ticket_grounding.py` | Analyzer advisory lane before Bedrock (fail-soft) |
| P6 | Portal closed-ticket lane | `closed_ticket_retrieval.py`, `case_chat.py` | `portal_chat_kb.py` + case-aware query |
| P7 | Attachment vision/OCR | vision LLM + Tesseract on-prem | Bedrock multimodal or Textract in sync/index path |
| P8 | Portal chat image uploads | `portal_chat_images.py` | **Shipped** — portal handler validation + Bedrock multimodal synthesis |

## Implementation phases

### Phase P0 — Operator preset (docs + smoke, no feature code)

**Status:** shipped 2026-08-13

**Deliverables**

- [`../operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](../operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md) — parameter checklist, OpenSearch index list, ingestion order, smoke steps
- [`../operations/deployment/OPENSEARCH_PROVISIONING.md`](../operations/deployment/OPENSEARCH_PROVISIONING.md) — customer-managed VPC OpenSearch domain before SAM deploy
- [`../../deploy/aws/presets/customer-default.env.example`](../../deploy/aws/presets/customer-default.env.example) and [`../../deploy/aws/presets/samconfig.customer-default.toml.example`](../../deploy/aws/presets/samconfig.customer-default.toml.example)
- Update [`TESTING.md`](../testing/TESTING.md) Wave 1 row for customer-default bundle

**Exit criteria**

- Operator can deploy `core,rag,analyst_portal` from documented parameters without guessing flags
- `test-pipeline.ps1 -Wave1Smoke -ExpectCapabilityProfiles "core,rag,analyst_portal"` documented as required staging gate

**Depends on:** none

---

### Phase P1 — Wire RAG rerank (`RAG_RERANK_ENABLED`)

**Scope**

- Invoke Bedrock rerank (`cohere.rerank-v3-5:0` / fallback) after hybrid OpenSearch candidate fetch when enabled
- Apply to SOC RAG and portal KB lanes; bounded snippet count unchanged
- Log `rerank_status=skipped|success|failed`; fail-soft default

**Primary files**

- `src/s3_notable_pipeline/opensearch_retrieval.py`
- `src/s3_notable_pipeline/bedrock_kb_retrieval.py` (if shared path)
- `deploy/aws/template-sam.yaml` (IAM for rerank model)
- `tests/test_opensearch_rag.py`

**On-prem reference:** Granite rerank in Postgres retrieval (behavioral, not code copy)

**Exit criteria**

- Unit tests with mocked Bedrock rerank
- `RagRerankEnabled=true` changes result ordering vs disabled control in fixture test

**Depends on:** none

---

### Phase P2 — KB image/PDF/DOCX manifest ingest

**Scope**

- Extend `parse_s3_document` / ingestion pipeline for PDF, DOCX, and image MIME types
- Bounded limits: max bytes, pages, pixels, output chars (mirror on-prem `IMAGE_INGEST_*` semantics)
- Text extraction path: **decision required** — Amazon Textract vs Bedrock vision vs pre-converted operator uploads
- Output remains deterministic text chunks embedded to OpenSearch via existing manifest flow

**Primary files**

- `src/s3_notable_pipeline/rag_ingestion.py`
- New helper module e.g. `kb_document_extract.py`
- `rag_ingest_handler.py`, `config.py`, SAM ingestion Lambda env/IAM
- `docs/operations/rag/KNOWLEDGE_BASE_OPERATIONS.md`
- `tests/test_rag_ingestion_media.py`

**On-prem reference:** [`IMAGE_INGEST_PREREQUISITES.md`](../../../llm_notable_analysis_onprem_systemd/docs/operations/rag/IMAGE_INGEST_PREREQUISITES.md)

**Exit criteria**

- Manifest ingest of sample PDF and PNG fixtures indexes searchable chunks with provenance
- Unsupported/oversized media fails to DLQ with explicit validation error

**Depends on:** P0 (operator doc for corpus layout)

---

### Phase P3 — Closed-ticket ServiceNow sync

**Status:** shipped 2026-08-13

**Scope**

- Read-only Table API sync of closed security tickets (configurable encoded query)
- Store raw JSON payload in versioned S3 prefix; sync cursor in DynamoDB
- Optional attachment download to private S3 prefix (bytes only; no execution)
- Scheduled Lambda (EventBridge), separate from disposition sync
- Secrets via Secrets Manager ARN

**Primary files**

- Port/adapt from `llm_notable_analysis_onprem_systemd/.../servicenow_closed_ticket_sync.py`
- New `servicenow_closed_ticket_sync.py`, `closed_ticket_sync_handler.py`
- SAM: Lambda, schedule, tables, bucket prefix, parameters
- `docs/operations/integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md`
- `tests/test_servicenow_closed_ticket_sync.py`

**Exit criteria**

- Backfill + incremental run against mocked ServiceNow pages
- Idempotent upsert on source sys_id; cursor advances; auth failure surfaces clearly

**Depends on:** P0

---

### Phase P4 — Closed-ticket render, chunk, OpenSearch index

**Status:** shipped 2026-08-13

**Scope**

- Deterministic render of raw ticket JSON to searchable text (fields + journals)
- Chunk + Titan embed; index to new OpenSearch lane e.g. `closed_tickets` with tenant filter
- Post-sync queue or inline step after P3 writes
- Tombstone/replace on ticket update; retention via ISM or scheduled cleanup

**Primary files**

- Port patterns from `closed_ticket_render.py`, `closed_ticket_index.py`
- `closed_ticket_embed.py` or extend `rag_ingestion.py` with ticket corpus_id
- `opensearch_retrieval.py` (corpus filter)
- SAM parameters: `OpenSearchClosedTicketIndex`, queue wiring

**Exit criteria**

- Fixture ticket indexes; hybrid query returns cited chunks with source ticket id
- Replay does not duplicate active chunks

**Depends on:** P3, OpenSearch domain from customer deploy

---

### Phase P5 — Closed-ticket advisory lane in analyzer

**Scope**

- Before main Bedrock analysis: bounded hybrid retrieval over closed-ticket index
- Inject separate prompt block (not alert evidence); metadata `closed_ticket_rag_status`
- Fail-soft when index empty or unavailable

**Primary files**

- Port from `historical_closed_ticket_grounding.py`
- `lambda_handler.py`, `ttp_analyzer.py` or pre-analysis helper
- `config.py`, SAM flags: `ClosedTicketRagEnabled`, budgets

**Exit criteria**

- Golden fixture: advisory block present in prompt path; analysis completes when RAG misses
- JSON metadata records status and snippet count

**Depends on:** P4

---

### Phase P6 — Portal closed-ticket chat lane

**Scope**

- When `CaseQaClosedTicketEnabled=true`: merge closed-ticket retrieval into portal chat context
- Case-aware query construction (reuse `portal_chat_kb_query.py` patterns)
- Separate section label in synthesis prompt

**Primary files**

- `portal_chat_kb.py`, `case_chat.py`, `portal_chat.py`
- `config.py`, SAM portal Lambda env
- `tests/test_portal_chat_closed_ticket.py`

**Exit criteria**

- Portal chat with pinned case + closed-ticket question includes advisory lane in fixture test
- No cross-tenant/cross-case leakage in retrieval filters

**Depends on:** P4, `analyst_portal` profile

---

### Phase P7 — Attachment vision/OCR for closed tickets

**Scope**

- For image/pdf attachments on synced tickets: extract text or generate bounded caption before chunking
- Commercial path: **Bedrock multimodal** or **Textract** (pick one in spec delta before coding)
- Respect max attachment bytes; skip unsupported types with logged reason

**Primary files**

- New `closed_ticket_attachment_extract.py`
- Hook in P3 download path or P4 index path
- IAM for chosen AWS service

**Exit criteria**

- Fixture screenshot attachment produces indexable text in chunk
- Vision disabled → sync still succeeds; attachment skipped explicitly

**Depends on:** P3, P4; decision on Textract vs Bedrock vision

---

### Phase P8 — Portal chat image uploads

**Status:** shipped 2026-08-13

**Scope**

- Implement backend for OpenAPI `chat_images_*` fields (validation, size/dimension caps, base64 or S3 ref)
- Pass bounded image context to Bedrock chat synthesis when `CaseQaChatImagesEnabled=true`
- No persistence of images beyond request scope unless explicitly approved

**Primary files**

- Port from `portal_chat_images.py`
- `portal_handler.py`, `case_chat.py`, `portal_api_models.py`
- Frontend already has schema fields; verify end-to-end

**Exit criteria**

- Contract test + handler test for oversize/rejected images
- Staging: one image question returns synthesis or bounded refusal

**Depends on:** P6 optional; Bedrock multimodal model approved for portal chat

---

## Recommended delivery order

```text
P0 (docs) -> P1 (rerank) -> P2 (KB media ingest)
         -> P3 -> P4 -> P5 -> P6 (closed-ticket vertical)
         -> P7 (attachments; can parallel P4 after P3)
         -> P8 (portal images; after portal chat stable)
```

Closed-ticket work (P3–P7) should land as one reviewable vertical slice before claiming closed-ticket parity.

## Testing strategy

| Phase | Tests |
| --- | --- |
| All | Unit tests with mocked AWS clients; no live AWS in CI |
| P0 | Doc link scan / existing `test_documentation_contract.py` |
| P1–P2 | Extend `test_opensearch_rag.py`, new ingestion media tests |
| P3–P7 | Port on-prem closed-ticket test patterns; HTTP mocked ServiceNow |
| P8 | Portal OpenAPI contract + handler validation tests |
| Staging | `test-pipeline.ps1 -Wave1Smoke` + new closed-ticket smoke section |

## SAM / config additions (summary)

New parameters (names tentative; finalize in P0 doc):

| Parameter | Purpose |
| --- | --- |
| `ClosedTicketRagEnabled` | Analyzer advisory lane |
| `CaseQaClosedTicketEnabled` | Portal lane |
| `ServiceNowClosedTicketSyncEnabled` | Scheduler sync |
| `ServiceNowClosedTicketQuery` | Encoded Table API query |
| `ServiceNowClosedTicketTokenSecretArn` | Read-only token |
| `ClosedTicketArchivePrefix` | S3 raw + attachment prefix |
| `ClosedTicketSyncStateTable` | Cursor/idempotency |
| `OpenSearchClosedTicketIndex` | Vector index name |
| `ClosedTicketRetentionDays` | Default 30 |
| `ClosedTicketVisionEnabled` | P7 attachment extract |
| `CaseQaChatImagesEnabled` | P8 portal uploads |
| `ImageIngestEnabled` | P2 KB media types |

## Out of scope for this plan

- First-pass SPL generation (`spl_readonly`)
- Archer connector (on-prem backlog)
- Other cloud partition ports (separate plans; track in central roadmap)
- Replacing disposition sync with closed-ticket sync
- Customer-default preset for hardware-tuned vLLM (on-prem only)

## Acceptance (plan complete)

Commercial AWS matches on-prem customer-default when all are true:

1. P0 doc enables reproducible `core,rag,analyst_portal` deploy + smoke
2. SOC + case + SPL dictionary + closed-ticket corpora ingest to OpenSearch with tenant scope
3. Analyzer runs SOC RAG + closed-ticket advisory; no SPL in JSON unless `spl_readonly` added
4. Portal chat: case chunks + SOC KB + SPL dictionary + closed-ticket lanes; optional chat history/images
5. KB PDF/image sources ingest through manifest pipeline
6. `RAG_RERANK_ENABLED` affects retrieval when on
7. Fail-soft behavior preserved; no advisory content becomes alert evidence
8. Approved differences doc updated for Textract/vision choices and any commercial-only limits

## Tracking

- Implementation checklist: [`TODOS.md`](TODOS.md)
- Fork status: [`COMMERCIAL_AWS_FORK_PLAN.md`](COMMERCIAL_AWS_FORK_PLAN.md)
- Update this plan status as each phase completes
