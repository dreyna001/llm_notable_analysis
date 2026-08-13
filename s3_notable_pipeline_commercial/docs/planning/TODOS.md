# s3_notable_pipeline — planning backlog

_Last updated: 2026-08-13. Normative parity contract:
[`../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`](../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md)._

## Top Priority Reminder

- [ ] Add an explicit AWS analyzer backlog queue: change direct S3 `ObjectCreated` -> Lambda analyzer intake to S3 -> SQS -> Lambda so concurrency caps create queue depth instead of relying on S3/Lambda redelivery as the backlog mechanism.

## Next parity block — closed-ticket RAG + rich KB ingest (shipped on feature branch)

Implementation epic for on-prem **customer-default** gaps — **P1–P8 code complete** on
`feature/commercial-aws-onprem-parity`. Phases documented in
[`COMMERCIAL_AWS_ONPREM_CUSTOMER_DEFAULT_PARITY_PLAN.md`](COMMERCIAL_AWS_ONPREM_CUSTOMER_DEFAULT_PARITY_PLAN.md).
On-prem reference: [`IMAGE_INGEST_PREREQUISITES.md`](../../../llm_notable_analysis_onprem_systemd/docs/operations/rag/IMAGE_INGEST_PREREQUISITES.md),
[`CLOSED_TICKET_RAG_PLAN.md`](../../../llm_notable_analysis_onprem_systemd/docs/planning/CLOSED_TICKET_RAG_PLAN.md).

- [x] **Rich KB ingest (P2)** — PDF, DOCX embedded images, standalone images in RAG manifests.
  On-prem: `corpus_ingest` + `IMAGE_INGEST_*` (Tesseract, PDFium, optional vision).
  AWS: `kb_document_extract.py` + Textract for images; pypdf/python-docx for PDF/DOCX.
- [x] **Closed-ticket ServiceNow sync (P3)** — raw closed tickets, journals, attachments (not disposition sync).
- [x] **Closed-ticket chunk + OpenSearch index (P4)** — render/chunk/embed advisory lane.
- [x] **Closed-ticket analysis RAG (P5)** — fail-soft grounding in analyzer before Bedrock.
- [x] **Portal closed-ticket chat lane (P6)** — merge with case + KB retrieval in portal chat.
- [x] **Closed-ticket attachment vision/OCR (P7)** — Textract OCR for PNG/JPEG/PDF during embed when `CLOSED_TICKET_VISION_ENABLED=true`; fail-soft; reuses `KB_EXTRACT_*` limits.

Related (same parity program, separate phases):

- [x] **RAG rerank wired (P1)** — Bedrock rerank after OpenSearch hybrid fetch when `RAG_RERANK_ENABLED=true`; fail-soft with `rerank_status` logging.
- [x] **Portal chat image uploads (P8)** — AWS backend shipped; opt-in via `CaseQaChatImagesEnabled=true` and multimodal Bedrock model.

## Parity snapshot (on-prem vs this tree)

| Gap | On-prem | Commercial AWS (`s3_notable_pipeline_commercial`) |
| --- | --- | --- |
| Rich KB ingest (PDF/DOCX/images) | Shipped (`IMAGE_INGEST_*`) | **Shipped** (P2) |
| Closed-ticket RAG (sync + analysis + portal) | Shipped | **Shipped** (P3–P7 closed-ticket vertical slice) |
| Portal chat image uploads | Shipped | **Shipped** (P8; opt-in via `CaseQaChatImagesEnabled`) |
| RAG rerank at runtime | Shipped | **Shipped** (P1) |
| Customer-default SAM preset | Shipped (on-prem doc) | **Shipped** (P0) |
| Gzip notable intake | Planned | Shipped |

Normative cross-platform table:
[`FUTURE_ENHANCEMENTS_ROADMAP.md`](../../../llm_notable_analysis_onprem_systemd/docs/planning/FUTURE_ENHANCEMENTS_ROADMAP.md) (section **Shipped vs backlog**).

## Parity docs

| Doc | Role |
| --- | --- |
| [AWS_ONPREM_PARITY_TECHNICAL_SPEC.md](../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md) | Normative shipped AWS/on-prem parity contract |
| [AZURE_AWS_PARITY_PLAN.md](AZURE_AWS_PARITY_PLAN.md) | Azure deployment plan mirroring AWS SAM stack (planning only) |
| [PORTAL_CHATBOT_CAPABILITY_GAPS.md](../../../PORTAL_CHATBOT_CAPABILITY_GAPS.md) | SOTA chat gaps; P3-1 multi-turn shipped |

## Shipped (code on `main`)

- **Wave 1** — profiles, RAG/KB, SPL and Elastic read-only investigation, query enrichment, ServiceNow, idempotency, HTML reports, operations guides.
- **Wave 2** — `analyst_portal`, S3 case archive, DynamoDB CaseIndex, portal API/UI, pinned-case Q&A, IAM split.
- **Wave 3 + P3-1** — portal chat contract parity, hybrid retrieval (W3-4), analyzer verdict and SOC header, chat-readiness diagnostics, OpenAPI sync, multi-turn synthesis.

## Backlog

**Azure parity (in progress):**

- [x] Phase 0 scaffold complete on `azure_instance` — see [AZURE_AWS_PARITY_PLAN.md](AZURE_AWS_PARITY_PLAN.md)

**Operator closeout (not code):**

- [ ] Real-AWS staging validation for Waves 1–2 profiles — see [TESTING.md](../testing/TESTING.md) staging checklists and [AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md](../delivery_package/AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md).
- [ ] Customer front-door wiring when `analyst_portal` is enabled (JWT issuer/audience, CORS, optional DNS/WAF).

**On-prem customer-default cloud parity — remaining code (P1, P2–P8):**

Implementation plan:
[`COMMERCIAL_AWS_ONPREM_CUSTOMER_DEFAULT_PARITY_PLAN.md`](COMMERCIAL_AWS_ONPREM_CUSTOMER_DEFAULT_PARITY_PLAN.md)
(phases P0–P8). **P0 shipped** (customer-default preset + ops runbooks). Open work is tracked in **Next parity block** above (P1–P8).

- [x] Publish commercial AWS customer-default SAM parameter preset +
  `core,rag,analyst_portal` staging smoke docs (no first-pass SPL; `SplQueryRagEnabled` for portal only) —
  [`COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](../operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md),
  [`deploy/aws/presets/`](../../deploy/aws/presets/)

Broader product backlog (both platforms — threat intel, SOAR playbooks, observability, CMDB, Security Lake):
[`FUTURE_ENHANCEMENTS_ROADMAP.md`](../../../llm_notable_analysis_onprem_systemd/docs/planning/FUTURE_ENHANCEMENTS_ROADMAP.md).

## Operations docs

Index: [operations/README.md](../operations/README.md).

| Area | Guides |
| --- | --- |
| Deployment | [DEPLOYMENT_IMAGE_STEPS.md](../operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) |
| Platform | [CAPABILITY_PROFILES.md](../operations/platform/CAPABILITY_PROFILES.md), [FILE_DROP_AND_RETENTION_OPERATIONS.md](../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md), [MITRE_TTP_OPERATIONS.md](../operations/platform/MITRE_TTP_OPERATIONS.md), [RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md](../operations/platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md) |
| Analyst portal | [ANALYST_PORTAL_OPERATIONS.md](../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md) |
| LLM | [LLM_INFERENCE_OPERATIONS.md](../operations/llm/LLM_INFERENCE_OPERATIONS.md) |
| RAG | [KNOWLEDGE_BASE_OPERATIONS.md](../operations/rag/KNOWLEDGE_BASE_OPERATIONS.md), [RAG_OPERATIONS.md](../operations/rag/RAG_OPERATIONS.md) |
| Investigation | [SPL_OPERATIONS.md](../operations/investigation/SPL_OPERATIONS.md), [ELASTICSEARCH_OPERATIONS.md](../operations/investigation/ELASTICSEARCH_OPERATIONS.md) |
| Integrations | [SPLUNK_WRITEBACK_OPERATIONS.md](../operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md), [SERVICENOW_OPERATIONS.md](../operations/integrations/SERVICENOW_OPERATIONS.md) |
| Security | [SECURITY_OPERATIONS.md](../operations/security/SECURITY_OPERATIONS.md) |

## Code markers

No actionable `TODO`/`FIXME` markers under `s3_notable_pipeline_commercial/` as of 2026-08-13.

Note: `python scripts/tools/todo_report.py --write` still targets this file and will overwrite it; use a different `--output` if you only want the marker scan.
