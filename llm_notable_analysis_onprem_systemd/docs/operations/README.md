# Operations Guide Index

Use this folder for customer-facing operations decisions: which settings to
enable, what values should differ by environment, and how to validate a safe
configuration without changing application code.

## Common Guide Shape

Area guides should generally use this pattern:

- **What This Controls**: the runtime behavior covered by the page.
- **Recommended Starting Posture**: conservative defaults for first rollout.
- **Customer Decisions**: questions operators must answer for each deployment.
- **Config Quick Reference**: the relevant `config.env` variables.
- **Validation And Rollout**: how to prove the configuration is safe.
- **Related Docs**: where to go for deeper install, architecture, or security
  context.

The guides are not feature specs. They should help customers tune the shipped
behavior within supported config bounds.

## Area Guides

| Area | Guide | Purpose |
|------|-------|---------|
| Deployment hardware profiles | [`deployment_profiles/README.md`](deployment_profiles/README.md) | Recommended vLLM and `config.env` starting values per CPU/GPU build. |
| Capability profiles | [`CAPABILITY_PROFILES.md`](CAPABILITY_PROFILES.md) | Supported operator-facing feature bundles and legacy low-level flag behavior. |
| Analyst portal | [`ANALYST_PORTAL_OPERATIONS.md`](ANALYST_PORTAL_OPERATIONS.md) | Enable/disable, portal service, nginx, health checks, DB maintenance, chunk rebuild, backfill, and chat guardrails. |
| SPL generation and execution | [`SPL_OPERATIONS.md`](SPL_OPERATIONS.md) | Customer-specific indexes, SPL query KB grounding, command controls, timeouts, REST vs MCP, and rollout. |
| Elasticsearch generation and execution | [`ELASTICSEARCH_OPERATIONS.md`](ELASTICSEARCH_OPERATIONS.md) | Customer-specific index patterns, field mappings, Elastic query grounding, Query DSL controls, timeouts, and rollout. |
| Knowledge base content | [`KNOWLEDGE_BASE_OPERATIONS.md`](KNOWLEDGE_BASE_OPERATIONS.md) | Add, rebuild, validate, and roll back KB source documents. |
| RAG retrieval | [`RAG_OPERATIONS.md`](RAG_OPERATIONS.md) | RAG enablement, fail-open/fail-closed posture, backend, embeddings, rerank, context budgets. |
| LLM inference | [`LLM_INFERENCE_OPERATIONS.md`](LLM_INFERENCE_OPERATIONS.md) | Local LiteLLM/vLLM endpoint, model id, structured output mode, tokens, timeouts, optional LiteLLM Admin UI (master key + SSH tunnel). |
| LLM inference benchmarking | [`LLM_INFERENCE_BENCHMARKING.md`](LLM_INFERENCE_BENCHMARKING.md) | Load-test the serving stack with the repo benchmark script or vLLM bench; live monitoring and rollout gates. |
| File-drop and retention | [`FILE_DROP_AND_RETENTION_OPERATIONS.md`](FILE_DROP_AND_RETENTION_OPERATIONS.md) | Incoming, processed, quarantine, reports, archive, polling, retention, concurrency. |
| Splunk writeback | [`SPLUNK_WRITEBACK_OPERATIONS.md`](SPLUNK_WRITEBACK_OPERATIONS.md) | Optional notable comment writeback, endpoint, token, TLS, identifier mapping. |
| ServiceNow | [`SERVICENOW_OPERATIONS.md`](SERVICENOW_OPERATIONS.md) | Incident draft/create profiles, assignment group, HTTPS/token, approval payload. |
| MITRE ATT&CK/TTP | [`MITRE_TTP_OPERATIONS.md`](MITRE_TTP_OPERATIONS.md) | TTP ID data source and validation expectations. |
| Security | [`SECURITY_OPERATIONS.md`](SECURITY_OPERATIONS.md) | Customer decisions around exposure, secrets, TLS, systemd hardening, and audit posture. |
| Installation | [`INSTALL.md`](INSTALL.md) | Host install, services, post-install smoke checks. |
| Offline prestage | [`OFFLINE_PRESTAGE_GUIDE.md`](OFFLINE_PRESTAGE_GUIDE.md) | Artifacts to stage before an air-gapped install. |
| Recovery | [`RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md) | Failure behavior, ownership, and recovery duties. |

