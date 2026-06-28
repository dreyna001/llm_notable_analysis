# Operations Guide Index

Use this folder for customer-facing operations decisions: which settings to
enable, what values should differ by environment, and how to validate a safe
configuration without changing application code.

Start with [`platform/CAPABILITY_PROFILES.md`](platform/CAPABILITY_PROFILES.md)
and [`../../config.env.example`](../../config.env.example) for supported feature
bundles and runtime variables. Then open the category that matches your task.

## Common Guide Shape

Area guides should generally use this pattern:

- **What This Controls**: the runtime behavior covered by the page.
- **Recommended Starting Posture**: conservative defaults for first rollout.
- **Customer Decisions**: questions operators must answer for each deployment.
- **Config Quick Reference**: the relevant `config.env` variables.
- **Validation And Rollout**: how to prove the configuration is safe.
- **Related Docs**: where to go for deeper install, architecture, or security
  context.

These guides are not feature specs. They help customers tune shipped behavior
within supported config bounds.

## Deployment

Host install, offline prestage, air-gapped bring-up, and hardware-specific
starting values. Not controlled by capability profiles.

| Guide | Purpose |
|-------|---------|
| [`deployment/INSTALL.md`](deployment/INSTALL.md) | Host install, services, post-install smoke checks. |
| [`deployment/OFFLINE_PRESTAGE_GUIDE.md`](deployment/OFFLINE_PRESTAGE_GUIDE.md) | Artifacts to stage before an air-gapped install. |
| [`deployment/AIRGAPPED_DEPLOYMENT.md`](deployment/AIRGAPPED_DEPLOYMENT.md) | Air-gapped bring-up: AWS-to-on-prem mapping, sizing, acceptance checks. |
| [`deployment/deployment_profiles/README.md`](deployment/deployment_profiles/README.md) | Recommended vLLM and `config.env` starting values per CPU/GPU build. |

## Platform

Cross-cutting runtime configuration: `CAPABILITY_PROFILES` bundles (default
`core`), file-drop ingest, MITRE validation, retention, and recovery
expectations.

| Guide | Purpose |
|-------|---------|
| [`platform/CAPABILITY_PROFILES.md`](platform/CAPABILITY_PROFILES.md) | Supported operator-facing feature bundles and legacy low-level flag behavior. |
| [`platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) | Incoming, processed, quarantine, reports, archive, polling, retention, concurrency. |
| [`platform/MITRE_TTP_OPERATIONS.md`](platform/MITRE_TTP_OPERATIONS.md) | TTP ID data source and validation expectations. |
| [`platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md) | Failure behavior, ownership, and recovery duties. |

## Analyst Portal

Requires the `analyst_portal` profile. Internal HTTPS rollout, day-two portal
ops, chat security boundaries, and local dev preview.

| Guide | Purpose |
|-------|---------|
| [`analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md) | Internal HTTPS URL: install portal, TLS, nginx, DNS, firewall, analyst browser validation. |
| [`analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](analyst_portal/ANALYST_PORTAL_OPERATIONS.md) | Enable/disable, portal service, nginx, health checks, DB maintenance, chunk rebuild, backfill, chat guardrails. |
| [`analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md`](analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md) | LLM non-execution boundaries, prompting, post-checks, separation from analyzer actions. |
| [`analyst_portal/ANALYST_PORTAL_PREVIEW.md`](analyst_portal/ANALYST_PORTAL_PREVIEW.md) | Dev preview with stored cases 1-5, synthetic cases 6-55, optional live chat LLM. |

## LLM Inference

Core inference path (LiteLLM/vLLM on every host). Endpoint tuning and serving
benchmarks.

| Guide | Purpose |
|-------|---------|
| [`llm/LLM_INFERENCE_OPERATIONS.md`](llm/LLM_INFERENCE_OPERATIONS.md) | LiteLLM/vLLM endpoint, model id, structured output mode, tokens, timeouts, optional LiteLLM Admin UI. |
| [`llm/LLM_INFERENCE_BENCHMARKING.md`](llm/LLM_INFERENCE_BENCHMARKING.md) | Load-test the serving stack; live monitoring and rollout gates. |

## RAG and Knowledge Base

Requires the `rag` profile. Source document lifecycle and retrieval tuning.

| Guide | Purpose |
|-------|---------|
| [`rag/KNOWLEDGE_BASE_OPERATIONS.md`](rag/KNOWLEDGE_BASE_OPERATIONS.md) | Add, rebuild, validate, and roll back KB source documents. |
| [`rag/RAG_OPERATIONS.md`](rag/RAG_OPERATIONS.md) | RAG enablement, fail-open/fail-closed posture, backend, embeddings, rerank, context budgets. |

## Investigation

Requires `spl_readonly` or `elastic_readonly` (mutually exclusive). Read-only
query generation and execution against Splunk or Elasticsearch.

| Guide | Purpose |
|-------|---------|
| [`investigation/SPL_OPERATIONS.md`](investigation/SPL_OPERATIONS.md) | Indexes, SPL query KB grounding, command controls, timeouts, REST vs MCP, rollout. |
| [`investigation/ELASTICSEARCH_OPERATIONS.md`](investigation/ELASTICSEARCH_OPERATIONS.md) | Index patterns, field mappings, Elastic query grounding, Query DSL controls, timeouts, rollout. |

## Integrations

Optional outbound writeback and ticketing. ServiceNow drafts use
`ticket_draft`; Splunk writeback and ServiceNow create require `action_gated`.

| Guide | Purpose |
|-------|---------|
| [`integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](integrations/SPLUNK_WRITEBACK_OPERATIONS.md) | Notable comment writeback: endpoint, token, TLS, identifier mapping. |
| [`integrations/SERVICENOW_OPERATIONS.md`](integrations/SERVICENOW_OPERATIONS.md) | Incident draft/create profiles, assignment group, HTTPS/token, approval payload. |
| [`integrations/SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md`](integrations/SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md) | Inbound closed disposition sync: SN table/fields, read token, field maps (planned). |

## Security

Customer decisions around exposure, secrets, TLS, systemd hardening, and audit
posture. Applies regardless of capability profiles.

| Guide | Purpose |
|-------|---------|
| [`security/SECURITY_OPERATIONS.md`](security/SECURITY_OPERATIONS.md) | Exposure, secrets, TLS, systemd hardening, and audit decisions. |

Deeper implemented posture: [`../security/SECURITY_POSTURE.md`](../security/SECURITY_POSTURE.md).
