# Azure documentation index

**Deployers:** start at the root [`README.md`](../README.md), pick Path A/B/C in section 2,
and follow each linked runbook in order through
[`operations/testing/AZURE_GOVERNMENT_TESTING.md`](operations/testing/AZURE_GOVERNMENT_TESTING.md).
The live Azure mutation gate lives in the root README prerequisites.

## Operations index

**[Operations guide index](operations/README.md)** — all tuning guides by category
(deployment, platform, portal, LLM, RAG, investigation, integrations, security, retention).

## Topic shortcuts

| Topic | Primary doc |
| --- | --- |
| Deploy journey (Path A/B/C) | [`../README.md`](../README.md) section 2 |
| Image build + Bicep parameters | [DEPLOYMENT_IMAGE_STEPS.md](operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) |
| Customer-default preset | [AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md](operations/deployment/AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md), [`../deploy/azure/presets/`](../deploy/azure/presets/) |
| Customer configuration inputs | [AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md](operations/deployment/AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md) |
| Upgrade and rollback | [AZURE_UPGRADE_AND_ROLLBACK.md](operations/deployment/AZURE_UPGRADE_AND_ROLLBACK.md) |
| Azure OpenAI inference | [LLM_INFERENCE_OPERATIONS.md](operations/llm/LLM_INFERENCE_OPERATIONS.md) |
| Azure AI Search / RAG | [KNOWLEDGE_BASE_OPERATIONS.md](operations/rag/KNOWLEDGE_BASE_OPERATIONS.md), [AZURE_AI_SEARCH_RAG_INGESTION.md](operations/rag/AZURE_AI_SEARCH_RAG_INGESTION.md) |
| Portal private deploy gate | [ANALYST_PORTAL_DEPLOYMENT.md](operations/ANALYST_PORTAL_DEPLOYMENT.md) |
| Analyst portal day-two | [ANALYST_PORTAL_OPERATIONS.md](operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md) |
| Capability profiles | [CAPABILITY_PROFILES.md](operations/platform/CAPABILITY_PROFILES.md), [`../config.env.example`](../config.env.example) |
| Splunk/Elastic investigation and writeback | [SPLUNK_ELASTICSEARCH_WRITEBACK.md](operations/investigation/SPLUNK_ELASTICSEARCH_WRITEBACK.md) |
| ServiceNow disposition and writeback | [SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md](operations/integrations/SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md), [SERVICENOW_WRITEBACK_OPERATIONS.md](operations/integrations/SERVICENOW_WRITEBACK_OPERATIONS.md) |
| SIEM/SOAR private intake | [SIEM_SOAR_PRIVATE_INTAKE_OPERATIONS.md](operations/integrations/SIEM_SOAR_PRIVATE_INTAKE_OPERATIONS.md) |
| Testing and staging | [AZURE_GOVERNMENT_TESTING.md](operations/testing/AZURE_GOVERNMENT_TESTING.md) |
| Security | [AZURE_GOVERNMENT_SECURITY.md](operations/security/AZURE_GOVERNMENT_SECURITY.md) |
| Monitoring and poison replay | [AZURE_MONITORING_AND_RECOVERY.md](operations/AZURE_MONITORING_AND_RECOVERY.md) |
| Local emulator parity | [LOCAL_AZURE_PARITY.md](operations/LOCAL_AZURE_PARITY.md) |
| Azure/AWS parity contract | [AZURE_AWS_PARITY_TECHNICAL_SPEC.md](technical_specs/AZURE_AWS_PARITY_TECHNICAL_SPEC.md) |
| Customer-default parity plan | [AZURE_ONPREM_CUSTOMER_DEFAULT_PARITY_PLAN.md](planning/AZURE_ONPREM_CUSTOMER_DEFAULT_PARITY_PLAN.md) |

## Context (optional, before deploy)

1. **[Azure Government architecture](architecture/AZURE_GOVERNMENT_ARCHITECTURE.md)** — logical architecture and boundary rules
2. **[End-to-end workflow diagrams](architecture/AZURE_GOVERNMENT_END_TO_END.md)** — intake sequence and failure/recovery path
3. **[Delivery-package diagrams](delivery_package/end_to_end_diagrams/END_TO_END_DIAGRAMS.md)** — deployment visuals
4. **[Production readiness checklist](delivery_package/AZURE_READINESS.md)** — production gate
5. **[Executive workflow and readiness](delivery_package/EXECUTIVE_WORKFLOW_READINESS.md)** — stakeholder summary

## Optional deep dives

- [AZURE_IMPLEMENTATION_TRACKER.md](planning/AZURE_IMPLEMENTATION_TRACKER.md) — implementation status
- [AZURE_GOVERNMENT_PARITY_IMPLEMENTATION_PLAN.md](planning/AZURE_GOVERNMENT_PARITY_IMPLEMENTATION_PLAN.md) — sovereign-cloud parity work
- [MODULE_INVENTORY.md](planning/MODULE_INVENTORY.md) — module inventory
- [TODOS.md](planning/TODOS.md) — backlog register
- [Published portal OpenAPI contract](contracts/portal.openapi.json)

Customer-specific identities, endpoints, thresholds, approvals, tokens, and private DNS
belong in the approved customer deployment record and must not be committed.
