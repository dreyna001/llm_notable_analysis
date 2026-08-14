# azure_notable_pipeline — planning backlog

_Last updated: 2026-08-13. Runtime parity plan:
[`AZURE_ONPREM_CUSTOMER_DEFAULT_PARITY_PLAN.md`](AZURE_ONPREM_CUSTOMER_DEFAULT_PARITY_PLAN.md).
AWS GovCloud reference:
[`../../../s3_notable_pipeline/docs/planning/TODOS.md`](../../../s3_notable_pipeline/docs/planning/TODOS.md).
Implementation tracker:
[`AZURE_IMPLEMENTATION_TRACKER.md`](AZURE_IMPLEMENTATION_TRACKER.md)._

## On-prem customer-default parity (P0–P8) — shipped offline

GovCloud AWS and Azure Government now implement the same customer-default feature set
(Azure-native). Live Azure Government subscription validation remains operator-owned.

- [x] **P0** — Azure customer-default preset + [`AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md`](../operations/deployment/AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md)
- [x] **P1** — RAG rerank via Azure AI Search semantic ranker (`RAG_RERANK_ENABLED`)
- [x] **P2** — Rich KB ingest (PDF/DOCX/images; optional Document Intelligence)
- [x] **P3** — Closed-ticket ServiceNow sync (timer + Cosmos + Blob)
- [x] **P4** — Closed-ticket chunk + Azure AI Search `closed_tickets` index
- [x] **P5** — Closed-ticket analysis RAG in analyzer
- [x] **P6** — Portal closed-ticket chat lane
- [x] **P7** — Closed-ticket attachment vision/OCR (Document Intelligence)
- [x] **P8** — Portal chat image uploads backend

Enablement: [`SERVICENOW_CLOSED_TICKET_OPERATIONS.md`](../operations/integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md),
[`deploy/azure/presets/customer-default.env.example`](../../deploy/azure/presets/customer-default.env.example).

## Shipped vs AWS GovCloud baseline (Phases 0–4)

Native Azure ports of the **original** AWS SAM capability set are largely code-complete offline.
Live subscription verification remains operator-owned — see the tracker.

## Parity snapshot

| Capability | GovCloud AWS | Azure Government |
| --- | --- | --- |
| Phases 0–4 baseline | Shipped | Shipped offline |
| P0–P8 customer-default | Shipped | Shipped offline |
| Live staging validation | Operator-owned | Operator-owned |

## Operator closeout (not code)

- [ ] Live Azure Government subscription staging (Front Door, `/ready`, closed-ticket sync/index smoke)
- [ ] Customer Entra + Front Door wiring when `analyst_portal` is enabled
- [ ] Document Intelligence endpoint qualification when P2/P7 vision paths are enabled

Broader product backlog:
[`FUTURE_ENHANCEMENTS_ROADMAP.md`](../../../llm_notable_analysis_onprem_systemd/docs/planning/FUTURE_ENHANCEMENTS_ROADMAP.md).
