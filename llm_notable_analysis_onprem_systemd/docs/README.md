# Documentation index

Use this page to pick **where to start** without reading the whole root [`README.md`](../README.md).

## Recommended order (new operators and engineers)

1. **[Executive on-prem build writeup](delivery_package/EXECUTIVE_ONPREM_BUILD_WRITEUP.md)** — Stakeholder summary: AI stack, analyzer app, assumptions, hardware, constraints.

2. **[End-to-end workflow](delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md)** and **[diagrams](delivery_package/end_to_end_diagrams/END_TO_END_DIAGRAMS.md)** — File drop, optional RAG, SPL/Elastic read-only search, writeback, ServiceNow draft/create, approval gates.

3. **[Operations guide index](operations/README.md)** — Customer tuning guides by area (deployment, platform, portal, LLM, RAG, investigation, integrations, security).

4. **[Installation](operations/deployment/INSTALL.md)** — Host bring-up with `scripts/install.sh`, prerequisites, post-install checks. **[Host layout and updates](operations/deployment/HOST_LAYOUT_AND_UPDATES.md)** — Git checkout vs `/opt/notable-analyzer` vs `/etc/notable-analyzer/` (intended production layout).


5. **[Capability profiles](operations/platform/CAPABILITY_PROFILES.md)** and **[runtime env contract](../config.env.example)** — Enable supported bundles with `CAPABILITY_PROFILES`; secrets, paths, and tuning stay in `config.env` (`/etc/notable-analyzer/config.env` on the host). Portal uses [`config.portal.env.example`](../config.portal.env.example) as `/etc/notable-analyzer/portal.env`. Hardware starting values: **[deployment profiles](operations/deployment/deployment_profiles/README.md)**.

6. **[Knowledge base](operations/rag/KNOWLEDGE_BASE_OPERATIONS.md)** and **[RAG tuning](operations/rag/RAG_OPERATIONS.md)** — Only when the `rag` profile is enabled.

7. **[Deployment readiness overview](delivery_package/AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_OVERVIEW.md)** and **[readiness checklist](delivery_package/AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_ASSESSMENT.md)** — Ownership, approvals, Splunk/RAG prerequisites before production.

Optional deep dives:

- **[Developer maintainer guide](internal/DEVELOPER_MAINTAINER_GUIDE.md)** — Code boundaries, extension patterns, structured output, new capabilities.
- **[Feature enhancements technical spec](technical_specs/feature_enhancements_technical_spec.md)** — Normative contract for SPL, Splunk investigation, ServiceNow, and related shipped behavior.
- **[Analyst portal technical spec](technical_specs/analyst_portal_case_archive_technical_spec.md)** — Normative contract for the shipped Postgres-backed portal, case archive, and retrieval-bound chat.
- **[Analyst portal deferred work](planning/ANALYST_PORTAL_CASE_ARCHIVE_PLAN.md)** — Open portal/archive decisions; shipped behavior and network rationale live in the technical spec and rollout runbook.
- **[SPL operations](operations/investigation/SPL_OPERATIONS.md)** — Indexes, execution limits, REST vs MCP, rollout.
- **[Future enhancements roadmap](planning/FUTURE_ENHANCEMENTS_ROADMAP.md)** — Backlog (threat intel, SOAR invocation, observability, and related work).
- **[On-prem production readiness TODO](planning/ONPREM_PRODUCTION_READINESS_TODO.md)** — Lightweight checklist of remaining VM, network, security, and operational go-live work.
- **[On-prem customer deployment setup TODO](planning/ONPREM_CUSTOMER_DEPLOYMENT_SETUP_TODO.md)** — Customer-host env/Postgres/KB bring-up, auroraaihost tracker, and `install.sh` automation backlog.
- **[AI integrity / drift plan](planning/ai_integrity_drift_monitoring_plan.md)** — Planned integrity and quality-monitoring work.
- **[Golden eval (first slice)](testing/GOLDEN_EVAL.md)** — Analyzer disposition baseline corpus and rubric tests; broader harness backlog in [golden_eval_harness_todo.md](planning/golden_eval_harness_todo.md).

## Topic shortcuts

| Topic | Primary doc |
|-------|-------------|
| Executive on-prem build summary | [EXECUTIVE_ONPREM_BUILD_WRITEUP.md](delivery_package/EXECUTIVE_ONPREM_BUILD_WRITEUP.md) |
| Capability profiles | [CAPABILITY_PROFILES.md](operations/platform/CAPABILITY_PROFILES.md), [`config.env.example`](../config.env.example) |
| Analyst portal network rollout | [ANALYST_PORTAL_NETWORK_DEPLOYMENT.md](operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md) |
| Analyst portal operations | [ANALYST_PORTAL_OPERATIONS.md](operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md), [`notable-portal.service`](../deploy/systemd/notable-portal.service), [`notable-portal.conf`](../deploy/nginx/notable-portal.conf) |
| Analyst portal chat security | [ANALYST_PORTAL_CHAT_SECURITY.md](operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md) |
| Analyst portal local preview (dev) | [ANALYST_PORTAL_PREVIEW.md](operations/analyst_portal/ANALYST_PORTAL_PREVIEW.md), [PREVIEW_CASE_INVESTIGATION_GUIDE.md](../../PREVIEW_CASE_INVESTIGATION_GUIDE.md) |
| Analyst portal React UI (dev) | [frontend/analyst-portal/README.md](../frontend/analyst-portal/README.md) |
| SOAR / Phantom file drop | [SOAR_PLAYBOOK_PHANTOM.md](integrations/SOAR_PLAYBOOK_PHANTOM.md), [SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md](integrations/SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md) |
| Shared local dev venv (Python + Node) | [DEVELOPING.md](../../DEVELOPING.md) |
| Host paths vs local checkout | [README.md § Filesystem map](../README.md#filesystem-map) |
| RAG grounding for analysis | [EXECUTIVE_ONPREM_WORKFLOW.md](delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md), [RAG_OPERATIONS.md](operations/rag/RAG_OPERATIONS.md), [KNOWLEDGE_BASE_OPERATIONS.md](operations/rag/KNOWLEDGE_BASE_OPERATIONS.md) |
| LLM inference | [LLM_INFERENCE_OPERATIONS.md](operations/llm/LLM_INFERENCE_OPERATIONS.md), [LLM_INFERENCE_BENCHMARKING.md](operations/llm/LLM_INFERENCE_BENCHMARKING.md) |
| SPL generation and read-only execution | [SPL_OPERATIONS.md](operations/investigation/SPL_OPERATIONS.md), [feature_enhancements_technical_spec.md](technical_specs/feature_enhancements_technical_spec.md) |
| Elasticsearch read-only execution | [ELASTICSEARCH_OPERATIONS.md](operations/investigation/ELASTICSEARCH_OPERATIONS.md) (`elastic_readonly` profile; mutually exclusive with `spl_readonly`) |
| Splunk notable writeback | [SPLUNK_WRITEBACK_OPERATIONS.md](operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md) (`action_gated`) |
| ServiceNow draft/create | [SERVICENOW_OPERATIONS.md](operations/integrations/SERVICENOW_OPERATIONS.md), [feature_enhancements_technical_spec.md](technical_specs/feature_enhancements_technical_spec.md) |
| ServiceNow closed disposition sync (planned) | [SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md](operations/integrations/SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md) |
| File drop and retention | [FILE_DROP_AND_RETENTION_OPERATIONS.md](operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) |
| Reset server-side app data (preserves RAG) | [FILE_DROP_AND_RETENTION_OPERATIONS.md § Reset Server-Side Application Data](operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md#reset-server-side-application-data) |
| Planned gzip file intake | On-prem planned in [FILE_DROP_AND_RETENTION_OPERATIONS.md](operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md); AWS implemented in [s3 FILE_DROP ops](../../s3_notable_pipeline/docs/operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) |
| MITRE/TTP validation | [MITRE_TTP_OPERATIONS.md](operations/platform/MITRE_TTP_OPERATIONS.md) |
| Offline / air-gap prep | [OFFLINE_PRESTAGE_GUIDE.md](operations/deployment/OFFLINE_PRESTAGE_GUIDE.md), [AIRGAPPED_DEPLOYMENT.md](operations/deployment/AIRGAPPED_DEPLOYMENT.md) |
| Developer / maintainer guide | [DEVELOPER_MAINTAINER_GUIDE.md](internal/DEVELOPER_MAINTAINER_GUIDE.md) |
| Testing | [TESTING.md](testing/TESTING.md) |
| Security posture | [SECURITY_OPERATIONS.md](operations/security/SECURITY_OPERATIONS.md), [SECURITY_POSTURE.md](security/SECURITY_POSTURE.md) |
| Failure / recovery duties | [RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md](operations/platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md) |

## Doc folders

| Folder | Contents |
|--------|----------|
| [`delivery_package/`](delivery_package/) | Executive summaries, readiness, end-to-end diagrams |
| [`operations/`](operations/) | Customer tuning guides: `deployment/`, `platform/`, `analyst_portal/`, `llm/`, `rag/`, `investigation/`, `integrations/`, `security/` |
| [`integrations/`](integrations/) | SOAR / Phantom playbook notes |
| [`technical_specs/`](technical_specs/) | Normative shipped contracts (portal, SPL/investigation enhancements) |
| [`planning/`](planning/) | Backlog and planning-only proposals |
| [`security/`](security/) | Implemented security posture reference |
| [`testing/`](testing/) | Unit, smoke, and validation commands |
| [`internal/`](internal/) | Developer and maintainer guidance |
