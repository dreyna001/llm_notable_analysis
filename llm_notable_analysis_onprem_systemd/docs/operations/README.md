# Operations Guide Index

Customer-facing operations decisions: which settings to enable, what values differ by
environment, and how to validate a safe configuration without changing application code.

**Deployers:** ordered Path A/B/C journeys live in the root
[`README.md`](../../README.md) section 2. Use this index for topic discovery after you
pick a path.

Start with [`platform/CAPABILITY_PROFILES.md`](platform/CAPABILITY_PROFILES.md)
and [`../../config.env.example`](../../config.env.example) for supported feature bundles.
Then open the category that matches your task.

## Deployment

Host install, offline prestage, air-gapped bring-up, customer-default bundle, and
hardware-specific starting values.

| Guide | Purpose |
|-------|---------|
| [`deployment/INSTALL.md`](deployment/INSTALL.md) | Host install, services, post-install smoke checks. |
| [`deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md`](deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md) | Path B: portal + RAG + closed-ticket env mirror and data-plane checklist. |
| [`../../scripts/preflight_customer_deployment.sh`](../../scripts/preflight_customer_deployment.sh) | Read-only customer-default host and staged-input checks. |
| [`../../scripts/audit_customer_target_host.sh`](../../scripts/audit_customer_target_host.sh) | Read-only deployed-host audit and saved deployment result. |
| [`deployment/HOST_LAYOUT_AND_UPDATES.md`](deployment/HOST_LAYOUT_AND_UPDATES.md) | Git checkout vs `/opt/notable-analyzer` vs `/etc/notable-analyzer/`; pull and upgrade workflow. |
| [`deployment/OFFLINE_PRESTAGE_GUIDE.md`](deployment/OFFLINE_PRESTAGE_GUIDE.md) | Artifacts to stage before an air-gapped install. |
| [`deployment/DEPENDENCY_LIST.md`](deployment/DEPENDENCY_LIST.md) | Declared repo-pinned dependencies (Python, npm, models, OS). |
| [`deployment/SECURITY_LIST.md`](deployment/SECURITY_LIST.md) | Declared security controls (network, credentials, gates, hardening). |
| [`deployment/AIRGAPPED_DEPLOYMENT.md`](deployment/AIRGAPPED_DEPLOYMENT.md) | Air-gapped bring-up: AWS-to-on-prem mapping, sizing, acceptance checks. |
| [`rag/IMAGE_INGEST_PREREQUISITES.md`](rag/IMAGE_INGEST_PREREQUISITES.md) | OCR, PDF, Granite retrieval, offline image-ingest bundle. |
| [`deployment/deployment_profiles/README.md`](deployment/deployment_profiles/README.md) | Recommended vLLM and `config.env` starting values per CPU/GPU build. |

## Platform

Cross-cutting runtime configuration: `CAPABILITY_PROFILES` bundles (default `core`),
file-drop ingest, MITRE validation, retention, and recovery expectations.

| Guide | Purpose |
|-------|---------|
| [`platform/CAPABILITY_PROFILES.md`](platform/CAPABILITY_PROFILES.md) | Supported operator-facing feature bundles and legacy low-level flag behavior. |
| [`platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) | Incoming, processed, quarantine, reports, archive, polling, retention, concurrency. |
| [`platform/MITRE_TTP_OPERATIONS.md`](platform/MITRE_TTP_OPERATIONS.md) | TTP ID data source and validation expectations. |
| [`platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md) | Failure behavior, ownership, and recovery duties. |

## Analyst Portal

Requires the `analyst_portal` profile. Internal HTTPS rollout, day-two portal ops,
chat security boundaries, and local dev preview.

| Guide | Purpose |
|-------|---------|
| [`analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md) | Internal HTTPS URL: install portal, TLS, nginx, DNS, firewall, analyst browser validation. |
| [`analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](analyst_portal/ANALYST_PORTAL_OPERATIONS.md) | Enable/disable, portal service, nginx, health checks, DB maintenance, chunk rebuild, backfill, chat guardrails. |
| [`analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md`](analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md) | LLM non-execution boundaries, prompting, post-checks, separation from analyzer actions. |
| [`analyst_portal/ANALYST_PORTAL_PREVIEW.md`](analyst_portal/ANALYST_PORTAL_PREVIEW.md) | Dev preview with stored cases 1-5, synthetic cases 6-55, optional live chat LLM. |
| [`analyst_portal/ANALYST_PORTAL_THEME.md`](analyst_portal/ANALYST_PORTAL_THEME.md) | "Federal SOC Dark" theme: palette, fonts, radius, WCAG notes. |

## LLM Inference

Core inference path (LiteLLM/vLLM on every host). Endpoint tuning and serving benchmarks.

| Guide | Purpose |
|-------|---------|
| [`llm/LLM_INFERENCE_OPERATIONS.md`](llm/LLM_INFERENCE_OPERATIONS.md) | LiteLLM/vLLM endpoint, model id, structured output mode, tokens, timeouts, optional LiteLLM Admin UI. |
| [`llm/LLM_INFERENCE_BENCHMARKING.md`](llm/LLM_INFERENCE_BENCHMARKING.md) | Load-test the serving stack; live monitoring and rollout gates. |

## RAG and Knowledge Base

Requires the `rag` profile. Source document lifecycle and retrieval tuning.

| Guide | Purpose |
|-------|---------|
| [`rag/KNOWLEDGE_BASE_OPERATIONS.md`](rag/KNOWLEDGE_BASE_OPERATIONS.md) | Add, rebuild, validate, and roll back KB source documents. |
| [`rag/IMAGE_INGEST_PREREQUISITES.md`](rag/IMAGE_INGEST_PREREQUISITES.md) | Image/OCR/PDF prerequisites, Granite migration, offline bundle. |
| [`rag/RAG_OPERATIONS.md`](rag/RAG_OPERATIONS.md) | RAG enablement, fail-open/fail-closed posture, backend, embeddings, rerank, context budgets. |

## Investigation

Requires `spl_readonly` or `elastic_readonly` (mutually exclusive). Read-only query
generation and execution against Splunk or Elasticsearch.

| Guide | Purpose |
|-------|---------|
| [`investigation/SPL_OPERATIONS.md`](investigation/SPL_OPERATIONS.md) | Indexes, SPL query KB grounding, command controls, timeouts, REST vs MCP, rollout. |
| [`investigation/ELASTICSEARCH_OPERATIONS.md`](investigation/ELASTICSEARCH_OPERATIONS.md) | Index patterns, field mappings, Elastic query grounding, Query DSL controls, timeouts, rollout. |

## Integrations

Optional outbound writeback and ticketing. ServiceNow drafts use `ticket_draft`; Splunk
writeback and ServiceNow create require `action_gated`.

| Guide | Purpose |
|-------|---------|
| [`integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](integrations/SPLUNK_WRITEBACK_OPERATIONS.md) | Notable comment writeback: endpoint, token, TLS, identifier mapping. |
| [`integrations/SERVICENOW_OPERATIONS.md`](integrations/SERVICENOW_OPERATIONS.md) | Incident draft/create profiles, assignment group, HTTPS/token, approval payload. |
| [`integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md`](integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md) | Closed-ticket sync, vision/OCR ingest, portal closed-ticket lane (Path B). |
| [`integrations/SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md`](integrations/SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md) | Inbound closed disposition sync (planned). |

## Security

Customer decisions around exposure, secrets, TLS, systemd hardening, and audit posture.

| Guide | Purpose |
|-------|---------|
| [`security/SECURITY_OPERATIONS.md`](security/SECURITY_OPERATIONS.md) | Exposure, secrets, TLS, systemd hardening, and audit decisions. |

Deeper implemented posture: [`../security/SECURITY_POSTURE.md`](../security/SECURITY_POSTURE.md).

Validation terminus for all paths: [`../testing/TESTING.md`](../testing/TESTING.md).
