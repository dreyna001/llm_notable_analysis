# On-prem documentation index

**Deployers:** start at the root [`README.md`](../README.md), pick Path A/B/C in section 2,
and follow each linked runbook in order through
[`testing/TESTING.md`](testing/TESTING.md).
The production install approval gate lives in the root README prerequisites.

## Operations index

**[Operations guide index](operations/README.md)** — tuning guides by category
(deployment, platform, portal, LLM, RAG, investigation, integrations, security).

## Topic shortcuts

| Topic | Primary doc |
| --- | --- |
| Deploy journey (Path A/B/C) | [`../README.md`](../README.md) section 2 |
| Host install | [`operations/deployment/INSTALL.md`](operations/deployment/INSTALL.md) |
| Customer-default bundle | [`operations/deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md`](operations/deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md) |
| Host paths and upgrades | [`operations/deployment/HOST_LAYOUT_AND_UPDATES.md`](operations/deployment/HOST_LAYOUT_AND_UPDATES.md) |
| Offline / air-gap staging | [`operations/deployment/OFFLINE_PRESTAGE_GUIDE.md`](operations/deployment/OFFLINE_PRESTAGE_GUIDE.md), [`operations/deployment/AIRGAPPED_DEPLOYMENT.md`](operations/deployment/AIRGAPPED_DEPLOYMENT.md) |
| Hardware deployment profiles | [`operations/deployment/deployment_profiles/README.md`](operations/deployment/deployment_profiles/README.md) |
| Capability profiles | [`operations/platform/CAPABILITY_PROFILES.md`](operations/platform/CAPABILITY_PROFILES.md), [`../config.env.example`](../config.env.example) |
| LLM inference | [`operations/llm/LLM_INFERENCE_OPERATIONS.md`](operations/llm/LLM_INFERENCE_OPERATIONS.md) |
| Knowledge base / RAG | [`operations/rag/KNOWLEDGE_BASE_OPERATIONS.md`](operations/rag/KNOWLEDGE_BASE_OPERATIONS.md), [`operations/rag/RAG_OPERATIONS.md`](operations/rag/RAG_OPERATIONS.md) |
| Analyst portal network rollout | [`operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md) |
| Analyst portal day-two | [`operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md) |
| Closed-ticket sync | [`operations/integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md`](operations/integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md) |
| Splunk / Elastic investigation | [`operations/investigation/SPL_OPERATIONS.md`](operations/investigation/SPL_OPERATIONS.md), [`operations/investigation/ELASTICSEARCH_OPERATIONS.md`](operations/investigation/ELASTICSEARCH_OPERATIONS.md) |
| Splunk writeback / ServiceNow | [`operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md), [`operations/integrations/SERVICENOW_OPERATIONS.md`](operations/integrations/SERVICENOW_OPERATIONS.md) |
| Recovery behavior | [`operations/platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](operations/platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md) |
| Testing and validation | [`testing/TESTING.md`](testing/TESTING.md) |
| Security | [`operations/security/SECURITY_OPERATIONS.md`](operations/security/SECURITY_OPERATIONS.md), [`security/SECURITY_POSTURE.md`](security/SECURITY_POSTURE.md) |
| SOAR / Phantom file drop | [`integrations/SOAR_PLAYBOOK_PHANTOM.md`](integrations/SOAR_PLAYBOOK_PHANTOM.md) |
| Analyst portal React UI | [`../frontend/analyst-portal/README.md`](../frontend/analyst-portal/README.md) |
| Local dev venv | [`../../DEVELOPING.md`](../../DEVELOPING.md) |

## Context (optional)

- **[Executive on-prem workflow](delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md)** — intake, optional RAG, writeback, approval gates
- **[End-to-end diagrams](delivery_package/end_to_end_diagrams/END_TO_END_DIAGRAMS.md)** — deployment visuals
- **[Production readiness](delivery_package/AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_OVERVIEW.md)** — ownership and go-live gate
- **[Developer maintainer guide](internal/DEVELOPER_MAINTAINER_GUIDE.md)** — code boundaries and extension patterns
- **[Technical specs](technical_specs/)** — normative shipped contracts
- **[Planning backlog](planning/)** — not part of the operator critical path

Customer-specific identities, endpoints, thresholds, approvals, tokens, and private DNS
belong in the approved customer deployment record and must not be committed.
