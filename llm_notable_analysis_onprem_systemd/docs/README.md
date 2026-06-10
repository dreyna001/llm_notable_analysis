# Documentation index

Use this page to pick **where to start** without reading the whole root [`README.md`](../README.md).

## Recommended order (new operators and engineers)

1. **[Executive on-prem build writeup](delivery_package/EXECUTIVE_ONPREM_BUILD_WRITEUP.md)** — Short stakeholder summary of what the build provides, including AI infrastructure, the analyzer application, assumptions, hardware expectations, and constraints.

2. **[End-to-end behavior](delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md)** and **[end-to-end diagrams](delivery_package/end_to_end_diagrams/END_TO_END_DIAGRAMS.md)** — File-drop flow, optional RAG (advisory context), SPL generation, read-only Splunk execution, Splunk writeback, ServiceNow draft/create and approval gates. Read these for what the service does.

3. **[Operations guide index](operations/README.md)** — Customer-facing tuning guides organized by area: analyst portal, SPL, KB, RAG, LLM inference, file-drop/retention, Splunk writeback, ServiceNow, MITRE, security, install, prestage, and recovery.

4. **[Installation](operations/INSTALL.md)** — Bring-up with `scripts/install.sh`, prerequisites, manual follow-ups.

5. **[Capability profiles](operations/CAPABILITY_PROFILES.md)** and **[runtime env contract](../config.env.example)** — Operators choose supported bundles with `CAPABILITY_PROFILES`; endpoint, path, secret, and tuning values remain in `config.env`. Copy to `/etc/notable-analyzer/config.env` on the host. The analyst portal uses the narrower [`config.portal.env.example`](../config.portal.env.example) as `/etc/notable-analyzer/portal.env`.

   For host-specific vLLM and concurrency starting values, see **[deployment hardware profiles](operations/deployment_profiles/README.md)**.

6. **[Knowledge base / RAG operations](operations/KNOWLEDGE_BASE_OPERATIONS.md)** and **[RAG tuning](operations/RAG_OPERATIONS.md)** — Source document lifecycle plus retrieval configuration. Only needed when the `rag` profile is selected.

7. **[Deployment readiness (executive gateway)](delivery_package/AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_OVERVIEW.md)** and **[readiness checklist](delivery_package/AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_ASSESSMENT.md)** — Ownership, approvals, Splunk/RAG prerequisites before production.

Optional deep dives:

- **[Operations guide index](operations/README.md)** — Area-by-area customer tuning guide map.
- **[Developer maintainer guide](internal/DEVELOPER_MAINTAINER_GUIDE.md)** — Code boundaries, design patterns, tool-call structured output, and how to add new capabilities.
- **[SPL operations](operations/SPL_OPERATIONS.md)** — Indexes, Splunk execution limits, REST vs MCP, rollout; values that change every deployment.
- **[Feature enhancements architecture](architecture/feature_enhancements_architecture.md)** — Locked runtime shape, payloads (including `servicenow_create_approval`), policies.
- **[Feature enhancements technical spec](technical_specs/feature_enhancements_technical_spec.md)** — Contract-level detail for SPL, Splunk execution, ServiceNow.
- **[Analyst portal technical spec](technical_specs/analyst_portal_case_archive_technical_spec.md)** — Draft implementation contract and diff plan for the Postgres-backed portal/archive/chatbot.
- **[Analyst portal and case archive plan](planning/ANALYST_PORTAL_CASE_ARCHIVE_PLAN.md)** — Living scope for the on-prem 30-day case archive, read-only portal, and archive-backed chatbot.
- **[Analyst portal networking plan](planning/ANALYST_PORTAL_NETWORKING_PLAN.md)** — Planned internal URL, DNS, TLS, nginx, firewall, and FastAPI serving shape.
- **[Compressed inputs plan](planning/COMPRESSED_INPUTS_PLAN.md)** — Planned on-prem gzip intake parity with AWS (`*.json.gz`, `MAX_DECOMPRESSED_INPUT_BYTES`, stem/writeback rules).
- **[Golden evaluation harness TODO](planning/golden_eval_harness_todo.md)** — Planning TODO for future regression, hallucination, weak-retrieval, and assistant Q&A quality evaluation.
- **[AI integrity and drift monitoring plan](planning/ai_integrity_drift_monitoring_plan.md)** — Planning proposal for model/prompt/KB hash checks plus simple Evidently-based drift reporting.

## Topic shortcuts

| Topic | Primary doc |
|-------|-------------|
| Executive on-prem build summary | [EXECUTIVE_ONPREM_BUILD_WRITEUP.md](delivery_package/EXECUTIVE_ONPREM_BUILD_WRITEUP.md) |
| Capability profiles | [CAPABILITY_PROFILES.md](operations/CAPABILITY_PROFILES.md), [`config.env.example`](../config.env.example) (`CAPABILITY_PROFILES`) |
| Analyst portal operations | [`ANALYST_PORTAL_OPERATIONS.md`](ANALYST_PORTAL_OPERATIONS.md), [`notable-portal.service`](../deploy/systemd/notable-portal.service), [`notable-portal.conf`](../deploy/nginx/notable-portal.conf) |
| Analyst portal chat security | [`ANALYST_PORTAL_CHAT_SECURITY.md`](operations/ANALYST_PORTAL_CHAT_SECURITY.md) |
| Analyst portal local preview (dev) | [`ANALYST_PORTAL_PREVIEW.md`](operations/ANALYST_PORTAL_PREVIEW.md), [`PREVIEW_CASE_INVESTIGATION_GUIDE.md`](../../PREVIEW_CASE_INVESTIGATION_GUIDE.md) |
| Analyst portal React UI (dev spike) | [`frontend/analyst-portal/README.md`](../frontend/analyst-portal/README.md) |
| Shared local dev venv (Python + Node) | [`DEVELOPING.md`](../../DEVELOPING.md) |
| Host paths vs local checkout | [`README.md` § Filesystem map](../README.md#filesystem-map) |
| Analyst portal technical spec | [analyst_portal_case_archive_technical_spec.md](technical_specs/analyst_portal_case_archive_technical_spec.md) |
| Analyst portal case archive plan | [ANALYST_PORTAL_CASE_ARCHIVE_PLAN.md](planning/ANALYST_PORTAL_CASE_ARCHIVE_PLAN.md) |
| Analyst portal networking plan | [ANALYST_PORTAL_NETWORKING_PLAN.md](planning/ANALYST_PORTAL_NETWORKING_PLAN.md) |
| RAG grounding for analysis | [EXECUTIVE_ONPREM_WORKFLOW.md § RAG](delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md), [RAG_OPERATIONS.md](operations/RAG_OPERATIONS.md), [KNOWLEDGE_BASE_OPERATIONS.md](operations/KNOWLEDGE_BASE_OPERATIONS.md), [`config.env.example`](../config.env.example) |
| Planned golden eval / quality regression harness | [golden_eval_harness_todo.md](planning/golden_eval_harness_todo.md) |
| Planned AI integrity / drift monitoring | [ai_integrity_drift_monitoring_plan.md](planning/ai_integrity_drift_monitoring_plan.md) |
| LLM inference | [LLM_INFERENCE_OPERATIONS.md](operations/LLM_INFERENCE_OPERATIONS.md), [LLM_INFERENCE_BENCHMARKING.md](operations/LLM_INFERENCE_BENCHMARKING.md), [INSTALL.md](operations/INSTALL.md), [`config.env.example`](../config.env.example) (`LLM_*`) |
| SPL generation and SPL query grounding | [EXECUTIVE_ONPREM_WORKFLOW.md § SPL](delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md), [SPL_OPERATIONS.md](operations/SPL_OPERATIONS.md), [`config.env.example`](../config.env.example) (`CAPABILITY_PROFILES`, `SPL_QUERY_RAG_*`) |
| Splunk search execution and result interpretation | [EXECUTIVE_ONPREM_WORKFLOW.md § Splunk](delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md), [SPL_OPERATIONS.md](operations/SPL_OPERATIONS.md), [`config.env.example`](../config.env.example) (`CAPABILITY_PROFILES`, `INVESTIGATION_*`, `QUERY_RESULT_INTERPRETATION_*`, `SPLUNK_SEARCH_*`) |
| Elasticsearch generation and read-only execution | [ELASTICSEARCH_OPERATIONS.md](operations/ELASTICSEARCH_OPERATIONS.md), [`config.env.example`](../config.env.example) (`CAPABILITY_PROFILES`, `INVESTIGATION_QUERY_BACKEND`, `ELASTICSEARCH_*`) |
| Splunk notable writeback | [SPLUNK_WRITEBACK_OPERATIONS.md](operations/SPLUNK_WRITEBACK_OPERATIONS.md), [CAPABILITY_PROFILES.md](operations/CAPABILITY_PROFILES.md) (`action_gated`) |
| ServiceNow draft/create | [SERVICENOW_OPERATIONS.md](operations/SERVICENOW_OPERATIONS.md), [CAPABILITY_PROFILES.md](operations/CAPABILITY_PROFILES.md) (`ticket_draft`, `action_gated`), [EXECUTIVE_ONPREM_WORKFLOW.md § ServiceNow](delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md), [feature_enhancements_architecture.md](architecture/feature_enhancements_architecture.md) (approval JSON) |
| File drop and retention | [FILE_DROP_AND_RETENTION_OPERATIONS.md](operations/FILE_DROP_AND_RETENTION_OPERATIONS.md), [`config.env.example`](../config.env.example) (`INCOMING_DIR`, `RETENTION_*`, `CONCURRENCY_*`) |
| Planned gzip file intake (AWS parity) | [COMPRESSED_INPUTS_PLAN.md](planning/COMPRESSED_INPUTS_PLAN.md) |
| MITRE/TTP validation | [MITRE_TTP_OPERATIONS.md](operations/MITRE_TTP_OPERATIONS.md), [`config.env.example`](../config.env.example) (`MITRE_IDS_PATH`) |
| Offline / air-gap prep | [OFFLINE_PRESTAGE_GUIDE.md](operations/OFFLINE_PRESTAGE_GUIDE.md) |
| Developer / maintainer guide | [DEVELOPER_MAINTAINER_GUIDE.md](internal/DEVELOPER_MAINTAINER_GUIDE.md) |
| Testing | [TESTING.md](testing/TESTING.md) |
| Security posture | [SECURITY_OPERATIONS.md](operations/SECURITY_OPERATIONS.md), [SECURITY_POSTURE.md](security/SECURITY_POSTURE.md) |
| Failure / recovery duties | [RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md](operations/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md) |

## Other folders

- [`delivery_package/`](delivery_package/) — Executive and release-oriented material.
- [`integrations/`](integrations/) — SOAR / Phantom playbook notes.
- [`architecture/`](architecture/) — Broader deployment and enhancement architecture (including legacy S3 pipeline narrative where still relevant).
- [`planning/`](planning/) — Planning-only proposals for future changes that are not yet runtime contracts.
- [`internal/`](internal/) — Developer and maintainer guidance for code structure, extension patterns, and implementation conventions.
