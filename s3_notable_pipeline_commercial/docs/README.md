# Documentation index

Use this page to pick **where to start** without reading the whole root [`README.md`](../README.md).

## Recommended order (new operators and engineers)

1. **[Executive AWS workflow](delivery_package/EXECUTIVE_AWS_WORKFLOW.md)** — Stakeholder summary: S3 ingest, Lambda, Bedrock analysis, optional profiles, sink modes, and approval gates.

2. **[End-to-end workflow](delivery_package/EXECUTIVE_AWS_WORKFLOW.md)** and **[diagrams](delivery_package/end_to_end_diagrams/END_TO_END_DIAGRAMS.md)** — SOAR or operator upload to S3, optional Bedrock Knowledge Base retrieval, read-only Splunk or Elasticsearch investigation, S3 reports, Splunk writeback, ServiceNow draft/create.

3. **[Operations guide index](operations/README.md)** — Customer tuning guides by area (deployment, platform, portal, LLM, RAG, investigation, integrations, security).

4. **[Lambda image deploy](operations/deployment/DEPLOYMENT_IMAGE_STEPS.md)** — ECR build/push and SAM deploy. Fast path: [`../README.md`](../README.md) sections 2-3 (`scripts/setup-and-deploy.*`, `scripts/test-pipeline.*`).

5. **[Capability profiles](operations/platform/CAPABILITY_PROFILES.md)**, **[SAM template](../deploy/aws/template-sam.yaml)**, and **[runtime env contract](../config.env.example)** — Enable supported bundles with `CapabilityProfiles` / `CAPABILITY_PROFILES`; bucket names, Bedrock model id, secrets ARNs, and tuning map to SAM parameters and Lambda environment variables.

6. **[Knowledge base](operations/rag/KNOWLEDGE_BASE_OPERATIONS.md)** and **[RAG tuning](operations/rag/RAG_OPERATIONS.md)** — Only when the `rag` profile is enabled (Bedrock Knowledge Base retrieve).

7. **[Deployment readiness overview](delivery_package/AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_OVERVIEW.md)** and **[readiness checklist](delivery_package/AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md)** — Ownership, approvals, Bedrock/KB/SIEM prerequisites before production.

Optional deep dives:

- **[Commercial AWS fork plan](planning/COMMERCIAL_AWS_FORK_PLAN.md)** — Authoritative implementation sequence, safety boundaries, acceptance criteria, and live-AWS hard stops for the independent `us-east-1` product.
- **[AWS/on-prem parity technical spec](technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md)** — Normative shipped contract for profiles, portal, archive, Case Q&A, and idempotency on AWS.
- **[Portal chat capability gaps](../../PORTAL_CHATBOT_CAPABILITY_GAPS.md)** — Intentional SOTA product gaps vs consumer chat UIs (not AWS/on-prem parity).
- **[Analyst portal operations](operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md)** — S3 case archive, DynamoDB CaseIndex, JWT API Gateway, static SPA, pinned-case Q&A.
- **[SPL operations](operations/investigation/SPL_OPERATIONS.md)** — KB grounding, allowlists, Splunk REST/MCP read-only execution.
- **[Planning todos](planning/TODOS.md)** — Generated TODO report (may be empty).
- **[AWS GovCloud readiness plan](planning/AWS_GOVCLOUD_READINESS_PLAN.md)** — Implementation and validation plan for the `us-gov-east-1` target.
- **[Azure/AWS parity plan](planning/AZURE_AWS_PARITY_PLAN.md)** — Implementation contract for Azure deployment mirroring the SAM stack (planning only).

## Topic shortcuts

| Topic | Primary doc |
|-------|-------------|
| Executive AWS workflow summary | [EXECUTIVE_AWS_WORKFLOW.md](delivery_package/EXECUTIVE_AWS_WORKFLOW.md) |
| SAM deploy and fast path | [DEPLOYMENT_IMAGE_STEPS.md](operations/deployment/DEPLOYMENT_IMAGE_STEPS.md), [`../README.md`](../README.md), [`../deploy/aws/template-sam.yaml`](../deploy/aws/template-sam.yaml) |
| Capability profiles | [CAPABILITY_PROFILES.md](operations/platform/CAPABILITY_PROFILES.md), [`../config.env.example`](../config.env.example) |
| On-prem profile semantics (parity) | [`../../llm_notable_analysis_onprem_systemd/docs/operations/platform/CAPABILITY_PROFILES.md`](../../llm_notable_analysis_onprem_systemd/docs/operations/platform/CAPABILITY_PROFILES.md) |
| Analyst portal operations | [ANALYST_PORTAL_OPERATIONS.md](operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md), [`../frontend/analyst-portal/README.md`](../frontend/analyst-portal/README.md) |
| Analyst portal OpenAPI contract | [`contracts/portal.openapi.json`](contracts/portal.openapi.json) |
| SOAR / Phantom S3 upload | [SOAR_PLAYBOOK_PHANTOM.md](integrations/SOAR_PLAYBOOK_PHANTOM.md) |
| Shared local dev venv (Python + Node) | [DEVELOPING.md](../../DEVELOPING.md) |
| S3 intake, gzip, lifecycle, retention | [FILE_DROP_AND_RETENTION_OPERATIONS.md](operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) |
| On-prem file-drop policy alignment | [`../../llm_notable_analysis_onprem_systemd/docs/operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../../llm_notable_analysis_onprem_systemd/docs/operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) |
| RAG grounding for analysis | [EXECUTIVE_AWS_WORKFLOW.md](delivery_package/EXECUTIVE_AWS_WORKFLOW.md), [RAG_OPERATIONS.md](operations/rag/RAG_OPERATIONS.md), [KNOWLEDGE_BASE_OPERATIONS.md](operations/rag/KNOWLEDGE_BASE_OPERATIONS.md) |
| LLM inference (Bedrock) | [LLM_INFERENCE_OPERATIONS.md](operations/llm/LLM_INFERENCE_OPERATIONS.md) |
| SPL generation and read-only execution | [SPL_OPERATIONS.md](operations/investigation/SPL_OPERATIONS.md), [AWS_ONPREM_PARITY_TECHNICAL_SPEC.md](technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md) |
| On-prem SPL/investigation normative contract (parity) | [`../../llm_notable_analysis_onprem_systemd/docs/technical_specs/feature_enhancements_technical_spec.md`](../../llm_notable_analysis_onprem_systemd/docs/technical_specs/feature_enhancements_technical_spec.md) |
| Elasticsearch read-only execution | [ELASTICSEARCH_OPERATIONS.md](operations/investigation/ELASTICSEARCH_OPERATIONS.md) (`elastic_readonly`; mutually exclusive with `spl_readonly`) |
| Splunk notable writeback | [SPLUNK_WRITEBACK_OPERATIONS.md](operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md) (`SplunkSinkMode=notable_rest`; prefer `action_gated` in production) |
| ServiceNow draft/create | [SERVICENOW_OPERATIONS.md](operations/integrations/SERVICENOW_OPERATIONS.md), [AWS_ONPREM_PARITY_TECHNICAL_SPEC.md](technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md) |
| MITRE/TTP validation | [MITRE_TTP_OPERATIONS.md](operations/platform/MITRE_TTP_OPERATIONS.md) |
| AWS/on-prem parity contract | [AWS_ONPREM_PARITY_TECHNICAL_SPEC.md](technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md), [`../../PORTAL_CHATBOT_CAPABILITY_GAPS.md`](../../PORTAL_CHATBOT_CAPABILITY_GAPS.md) |
| Testing | [TESTING.md](testing/TESTING.md) |
| Security operations | [SECURITY_OPERATIONS.md](operations/security/SECURITY_OPERATIONS.md), [ATTACK_LLM_ANALYSIS.md](security/ATTACK_LLM_ANALYSIS.md) |
| Failure / recovery duties | [RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md](operations/platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md) |

## Doc folders

| Folder | Contents |
|--------|----------|
| [`delivery_package/`](delivery_package/) | Executive workflow, readiness, cost comparison, end-to-end diagrams |
| [`operations/`](operations/) | Customer tuning guides: `deployment/`, `platform/`, `analyst_portal/`, `llm/`, `rag/`, `investigation/`, `integrations/`, `security/` |
| [`integrations/`](integrations/) | SOAR / Phantom S3 upload pattern |
| [`technical_specs/`](technical_specs/) | Normative AWS shipped contracts (parity implementation spec) |
| [`planning/`](planning/) | Parity plans, requirements, CMDB enrichment backlog (`CMDB_SPL_INTEGRATION.md`), generated TODO report |
| [`security/`](security/) | ATT&CK grounding and LLM trust-boundary reference |
| [`testing/`](testing/) | Unit, smoke, LocalStack integration, and validation commands |
| [`contracts/`](contracts/) | Portal OpenAPI schema |
