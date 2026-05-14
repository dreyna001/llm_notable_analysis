# Documentation index

Use this page to pick **where to start** without reading the whole root [`README.md`](../README.md).

## Recommended order (new operators and engineers)

1. **[Executive on-prem build writeup](delivery_package/EXECUTIVE_ONPREM_BUILD_WRITEUP.md)** — Short stakeholder summary of what the build provides, including AI infrastructure, the analyzer application, assumptions, hardware expectations, and constraints.

2. **[End-to-end behavior](delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md)** — File-drop flow, optional RAG (advisory context), SPL generation, read-only Splunk execution, Splunk writeback, ServiceNow draft/create and approval gates. Read this for what the service does.

3. **[Operations guide index](operations/README.md)** — Customer-facing tuning guides organized by area: SPL, KB, RAG, LLM inference, file-drop/retention, Splunk writeback, ServiceNow, MITRE, security, install, prestage, and recovery.

4. **[Installation](operations/INSTALL.md)** — Bring-up with `scripts/install.sh`, prerequisites, manual follow-ups.

5. **[Runtime env contract](../config.env.example)** — All feature flags and integration settings live here with section comments (`RAG_*`, `SPL_QUERY_RAG_*`, Splunk investigation, ServiceNow `SERVICENOW_*`). Copy to `/etc/notable-analyzer/config.env` on the host.

6. **[Knowledge base / RAG operations](operations/KNOWLEDGE_BASE_OPERATIONS.md)** and **[RAG tuning](operations/RAG_OPERATIONS.md)** — Source document lifecycle plus retrieval configuration. Only needed when `RAG_ENABLED=true`.

7. **[Deployment readiness (executive gateway)](delivery_package/AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_OVERVIEW.md)** and **[readiness checklist](delivery_package/AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_ASSESSMENT.md)** — Ownership, approvals, Splunk/RAG prerequisites before production.

Optional deep dives:

- **[Operations guide index](operations/README.md)** — Area-by-area customer tuning guide map.
- **[SPL operations](operations/SPL_OPERATIONS.md)** — Indexes, Splunk execution limits, REST vs MCP, rollout; values that change every deployment.
- **[Feature enhancements architecture](architecture/feature_enhancements_architecture.md)** — Locked runtime shape, payloads (including `servicenow_create_approval`), policies.
- **[Feature enhancements technical spec](technical_specs/feature_enhancements_technical_spec.md)** — Contract-level detail for SPL, Splunk execution, ServiceNow.

## Topic shortcuts

| Topic | Primary doc |
|-------|-------------|
| Executive on-prem build summary | [EXECUTIVE_ONPREM_BUILD_WRITEUP.md](delivery_package/EXECUTIVE_ONPREM_BUILD_WRITEUP.md) |
| RAG grounding for analysis | [EXECUTIVE_ONPREM_WORKFLOW.md § RAG](delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md), [RAG_OPERATIONS.md](operations/RAG_OPERATIONS.md), [KNOWLEDGE_BASE_OPERATIONS.md](operations/KNOWLEDGE_BASE_OPERATIONS.md), [`config.env.example`](../config.env.example) |
| LLM inference | [LLM_INFERENCE_OPERATIONS.md](operations/LLM_INFERENCE_OPERATIONS.md), [INSTALL.md](operations/INSTALL.md), [`config.env.example`](../config.env.example) (`LLM_*`) |
| SPL generation and SPL query grounding | [EXECUTIVE_ONPREM_WORKFLOW.md § SPL](delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md), [SPL_OPERATIONS.md](operations/SPL_OPERATIONS.md), [`config.env.example`](../config.env.example) (`SPL_QUERY_GENERATION_ENABLED`, `SPL_QUERY_RAG_*`) |
| Splunk search execution and result interpretation | [EXECUTIVE_ONPREM_WORKFLOW.md § Splunk](delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md), [SPL_OPERATIONS.md](operations/SPL_OPERATIONS.md), [`config.env.example`](../config.env.example) (`INVESTIGATION_*`, `QUERY_RESULT_INTERPRETATION_*`, `SPLUNK_SEARCH_*`) |
| Splunk notable writeback | [SPLUNK_WRITEBACK_OPERATIONS.md](operations/SPLUNK_WRITEBACK_OPERATIONS.md), [`config.env.example`](../config.env.example) (`SPLUNK_SINK_*`) |
| ServiceNow draft/create | [SERVICENOW_OPERATIONS.md](operations/SERVICENOW_OPERATIONS.md), [EXECUTIVE_ONPREM_WORKFLOW.md § ServiceNow](delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md), [feature_enhancements_architecture.md](architecture/feature_enhancements_architecture.md) (approval JSON) |
| File drop and retention | [FILE_DROP_AND_RETENTION_OPERATIONS.md](operations/FILE_DROP_AND_RETENTION_OPERATIONS.md), [`config.env.example`](../config.env.example) (`INCOMING_DIR`, `RETENTION_*`, `CONCURRENCY_*`) |
| MITRE/TTP validation | [MITRE_TTP_OPERATIONS.md](operations/MITRE_TTP_OPERATIONS.md), [`config.env.example`](../config.env.example) (`MITRE_IDS_PATH`) |
| Offline / air-gap prep | [OFFLINE_PRESTAGE_GUIDE.md](operations/OFFLINE_PRESTAGE_GUIDE.md) |
| Testing | [TESTING.md](testing/TESTING.md) |
| Security posture | [SECURITY_OPERATIONS.md](operations/SECURITY_OPERATIONS.md), [SECURITY_POSTURE.md](security/SECURITY_POSTURE.md) |
| Failure / recovery duties | [RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md](operations/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md) |

## Other folders

- [`delivery_package/`](delivery_package/) — Executive and release-oriented material.
- [`integrations/`](integrations/) — SOAR / Phantom playbook notes.
- [`architecture/`](architecture/) — Broader deployment and enhancement architecture (including legacy S3 pipeline narrative where still relevant).
