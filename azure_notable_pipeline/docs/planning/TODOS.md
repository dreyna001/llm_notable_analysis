# azure_notable_pipeline — planning backlog

_Last updated: 2026-08-12. AWS parity plan:
[`../../../s3_notable_pipeline/docs/planning/AZURE_AWS_PARITY_PLAN.md`](../../../s3_notable_pipeline/docs/planning/AZURE_AWS_PARITY_PLAN.md).
Implementation tracker:
[`AZURE_IMPLEMENTATION_TRACKER.md`](AZURE_IMPLEMENTATION_TRACKER.md)._

## Shipped vs AWS GovCloud baseline

Phases 0–4 native Azure ports of the **existing** AWS SAM capability set are largely
code-complete offline. Live subscription verification remains operator-owned — see the tracker.

## On-prem customer-default cloud parity (Azure + AWS GovCloud)

Azure matches AWS GovCloud/commercial on these gaps: on-prem customer-default features are
**not** implemented in either cloud stack yet. Normative checklist:
[`FUTURE_ENHANCEMENTS_ROADMAP.md`](../../../llm_notable_analysis_onprem_systemd/docs/planning/FUTURE_ENHANCEMENTS_ROADMAP.md)
(section **On-prem customer-default cloud parity**). On-prem reference:
[`CUSTOMER_DEFAULT_DEPLOYMENT.md`](../../../llm_notable_analysis_onprem_systemd/docs/operations/deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md).

- [ ] Closed-ticket ServiceNow sync (raw tickets, journals, attachments) — not disposition sync
- [ ] Closed-ticket chunking, embedding, and advisory RAG in analysis
- [ ] Portal closed-ticket chat lane
- [ ] Closed-ticket attachment vision/OCR before indexing (approved Azure multimodal or OCR path)
- [ ] KB image/PDF/DOCX manifest ingest (extend Search ingestion beyond text/json)
- [ ] Portal chat image upload backend (OpenAPI scaffold only today)
- [ ] Confirm semantic ranker wiring matches intended `RAG_RERANK_ENABLED` contract end-to-end
- [ ] Publish Azure customer-default Bicep parameter preset +
  `core,rag,analyst_portal` staging smoke (no first-pass SPL; Spl dictionary grounding for portal only)

Each slice needs an Azure-native spec delta (Cosmos/Blob/Timer/Key Vault, retention, fail-soft
boundaries) before implementation. Mirror AWS GovCloud behavior unless a documented Azure-only
difference is approved.

Broader product backlog:
[`FUTURE_ENHANCEMENTS_ROADMAP.md`](../../../llm_notable_analysis_onprem_systemd/docs/planning/FUTURE_ENHANCEMENTS_ROADMAP.md).
