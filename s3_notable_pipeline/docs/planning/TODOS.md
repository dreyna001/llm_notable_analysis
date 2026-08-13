# s3_notable_pipeline — planning backlog

_Last updated: 2026-08-13. Normative parity contract:
[`../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`](../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md)._

## Top Priority Reminder

- [ ] Add an explicit AWS analyzer backlog queue: change direct S3 `ObjectCreated` -> Lambda analyzer intake to S3 -> SQS -> Lambda so concurrency caps create queue depth instead of relying on S3/Lambda redelivery as the backlog mechanism.

## Next parity block — on-prem customer-default (shipped 2026-08-13)

P0–P8 implemented on GovCloud AWS. Enable via SAM parameters documented in
[`GOVCLOUD_CUSTOMER_DEFAULT_DEPLOYMENT.md`](../operations/deployment/GOVCLOUD_CUSTOMER_DEFAULT_DEPLOYMENT.md)
and [`SERVICENOW_CLOSED_TICKET_OPERATIONS.md`](../operations/integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md).

- [x] **Rich KB ingest (P2)** — PDF/DOCX/images when `ImageIngestEnabled=true`
- [x] **Closed-ticket ServiceNow sync (P3)** — `ServiceNowClosedTicketSyncEnabled`
- [x] **Closed-ticket chunk + OpenSearch index (P4)** — embed Lambda + `closed_tickets` index
- [x] **Closed-ticket analysis RAG (P5)** — `ClosedTicketRagEnabled` in analyzer
- [x] **Portal closed-ticket chat lane (P6)** — `CaseQaClosedTicketEnabled`
- [x] **Closed-ticket attachment vision/OCR (P7)** — Textract when `ClosedTicketVisionEnabled=true`
- [x] **RAG rerank wired (P1)** — `RagRerankEnabled` + Bedrock rerank models
- [x] **Portal chat image uploads (P8)** — `CaseQaChatImagesEnabled`

## Parity snapshot (on-prem vs GovCloud AWS)

| Capability | On-prem | GovCloud AWS (`s3_notable_pipeline`) |
| --- | --- | --- |
| Rich KB ingest | Shipped | Shipped (P2; optional Textract) |
| Closed-ticket RAG | Shipped | Shipped (P3–P7) |
| Portal chat images | Shipped | Shipped (P8) |
| RAG rerank at runtime | Shipped | Shipped (P1) |
| Customer-default SAM preset | Shipped | Shipped — [`GOVCLOUD_CUSTOMER_DEFAULT_DEPLOYMENT.md`](../operations/deployment/GOVCLOUD_CUSTOMER_DEFAULT_DEPLOYMENT.md) |

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
- **On-prem customer-default parity (P0–P8)** — GovCloud preset, Bedrock rerank, rich KB ingest, closed-ticket sync/RAG, portal closed-ticket lane, Textract attachments, portal chat images.

## Backlog

**Azure parity (in progress):**

- [x] Phase 0 scaffold complete on `azure_instance` — see [AZURE_AWS_PARITY_PLAN.md](AZURE_AWS_PARITY_PLAN.md)

**Operator closeout (not code):**

- [ ] Real-AWS staging validation for Waves 1–2 profiles — see [TESTING.md](../testing/TESTING.md) staging checklists and [AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md](../delivery_package/AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md).
- [ ] Customer front-door wiring when `analyst_portal` is enabled (JWT issuer/audience, CORS, optional DNS/WAF).

**On-prem customer-default cloud parity — code complete (P0–P8 shipped 2026-08-13).**

Operator enablement: [`GOVCLOUD_CUSTOMER_DEFAULT_DEPLOYMENT.md`](../operations/deployment/GOVCLOUD_CUSTOMER_DEFAULT_DEPLOYMENT.md),
[`SERVICENOW_CLOSED_TICKET_OPERATIONS.md`](../operations/integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md).
Commercial fork parity plan (reference): [`../../s3_notable_pipeline_commercial/docs/planning/COMMERCIAL_AWS_ONPREM_CUSTOMER_DEFAULT_PARITY_PLAN.md`](../../s3_notable_pipeline_commercial/docs/planning/COMMERCIAL_AWS_ONPREM_CUSTOMER_DEFAULT_PARITY_PLAN.md).

Broader product backlog (both platforms):
[`FUTURE_ENHANCEMENTS_ROADMAP.md`](../../../llm_notable_analysis_onprem_systemd/docs/planning/FUTURE_ENHANCEMENTS_ROADMAP.md).

## Operations docs

Index: [operations/README.md](../operations/README.md).

| Area | Guides |
| --- | --- |
| Deployment | [DEPLOYMENT_IMAGE_STEPS.md](../operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) |
| Platform | [CAPABILITY_PROFILES.md](../operations/platform/CAPABILITY_PROFILES.md), [FILE_DROP_AND_RETENTION_OPERATIONS.md](../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md), [MITRE_TTP_OPERATIONS.md](../operations/platform/MITRE_TTP_OPERATIONS.md), [RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md](../operations/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md) |
| Analyst portal | [ANALYST_PORTAL_OPERATIONS.md](../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md) |
| LLM | [LLM_INFERENCE_OPERATIONS.md](../operations/LLM_INFERENCE_OPERATIONS.md) |
| RAG | [KNOWLEDGE_BASE_OPERATIONS.md](../operations/rag/KNOWLEDGE_BASE_OPERATIONS.md), [RAG_OPERATIONS.md](../operations/rag/RAG_OPERATIONS.md) |
| Investigation | [SPL_OPERATIONS.md](../operations/investigation/SPL_OPERATIONS.md), [ELASTICSEARCH_OPERATIONS.md](../operations/investigation/ELASTICSEARCH_OPERATIONS.md) |
| Integrations | [SPLUNK_WRITEBACK_OPERATIONS.md](../operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md), [SERVICENOW_OPERATIONS.md](../operations/integrations/SERVICENOW_OPERATIONS.md) |
| Security | [SECURITY_OPERATIONS.md](../operations/security/SECURITY_OPERATIONS.md) |

## Code markers

No actionable `TODO`/`FIXME` markers under `s3_notable_pipeline/` as of 2026-08-13.

Note: `python scripts/tools/todo_report.py --write` still targets this file and will overwrite it; use a different `--output` if you only want the marker scan.
