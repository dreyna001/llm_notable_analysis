# On-Prem Notable Analysis Service

Air-gapped-capable, single-host notable analysis service for SOC workflows. The
default deployment runs local inference through **LiteLLM -> vLLM** and uses a
file-drop workflow for incoming `.json` or `.txt` notables.

This root README is intentionally a **jumping board**. Detailed setup,
operations, tuning, security, and integration guidance lives under
[`docs/`](docs/).

## What This Package Provides

- A `systemd`-managed analyzer service that watches an incoming directory and
  writes markdown reports.
- Local OpenAI-compatible inference through LiteLLM/vLLM by default.
- Optional RAG grounding from a local knowledge base.
- Optional SPL generation, read-only Splunk search execution, and Splunk
  notable writeback.
- Optional ServiceNow incident draft/create behavior with approval-gated create.
- MITRE ATT&CK TTP validation.
- Operator docs for install, offline prestage, recovery, security, and
  per-customer tuning.

## Start Here

| Need | Read this |
|------|-----------|
| New to the project | [`docs/README.md`](docs/README.md) |
| End-to-end behavior | [`docs/delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md`](docs/delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md) |
| Customer tuning by area | [`docs/operations/README.md`](docs/operations/README.md) |
| Install on a host | [`docs/operations/INSTALL.md`](docs/operations/INSTALL.md) |
| Offline or air-gapped prep | [`docs/operations/OFFLINE_PRESTAGE_GUIDE.md`](docs/operations/OFFLINE_PRESTAGE_GUIDE.md) |
| Runtime config values | [`config.env.example`](config.env.example) |
| Tests and validation | [`docs/testing/TESTING.md`](docs/testing/TESTING.md) |
| Security posture | [`docs/operations/SECURITY_OPERATIONS.md`](docs/operations/SECURITY_OPERATIONS.md) and [`docs/security/SECURITY_POSTURE.md`](docs/security/SECURITY_POSTURE.md) |
| Deployment readiness | [`docs/delivery_package/AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_OVERVIEW.md`](docs/delivery_package/AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_OVERVIEW.md) |

## Customer Operations Guides

These are the config-focused pages customers should use to tune shipped
behavior without changing code.

| Area | Guide |
|------|-------|
| SPL generation and read-only execution | [`docs/operations/SPL_OPERATIONS.md`](docs/operations/SPL_OPERATIONS.md) |
| Knowledge base content lifecycle | [`docs/operations/KNOWLEDGE_BASE_OPERATIONS.md`](docs/operations/KNOWLEDGE_BASE_OPERATIONS.md) |
| RAG retrieval tuning | [`docs/operations/RAG_OPERATIONS.md`](docs/operations/RAG_OPERATIONS.md) |
| LLM inference tuning | [`docs/operations/LLM_INFERENCE_OPERATIONS.md`](docs/operations/LLM_INFERENCE_OPERATIONS.md) |
| File drop, payloads, retention, concurrency | [`docs/operations/FILE_DROP_AND_RETENTION_OPERATIONS.md`](docs/operations/FILE_DROP_AND_RETENTION_OPERATIONS.md) |
| Splunk notable writeback | [`docs/operations/SPLUNK_WRITEBACK_OPERATIONS.md`](docs/operations/SPLUNK_WRITEBACK_OPERATIONS.md) |
| ServiceNow draft/create | [`docs/operations/SERVICENOW_OPERATIONS.md`](docs/operations/SERVICENOW_OPERATIONS.md) |
| MITRE ATT&CK/TTP validation | [`docs/operations/MITRE_TTP_OPERATIONS.md`](docs/operations/MITRE_TTP_OPERATIONS.md) |
| Recovery behavior | [`docs/operations/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](docs/operations/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md) |

## Default Runtime Shape

```text
SOAR/SFTP/operator file drop
  -> notable-analyzer systemd service
  -> LiteLLM -> vLLM local model
  -> markdown report
  -> processed/quarantine movement
  -> optional Splunk/ServiceNow outputs
```

Default host paths and feature flags are documented in
[`config.env.example`](config.env.example). The app package lives under
[`src/llm_notable_analysis_onprem_systemd/`](src/llm_notable_analysis_onprem_systemd/)
so installed imports and service entrypoints stay stable.

For SFTP file-drop deployments, the installer-created chroot contract is:
Chroot: `/var/sftp/soar`; incoming symlink:
`/var/notables/incoming -> /var/sftp/soar/incoming`.

## Optional Capabilities

- **RAG grounding:** enable with `RAG_ENABLED=true`; tune with
  [`docs/operations/RAG_OPERATIONS.md`](docs/operations/RAG_OPERATIONS.md).
- **SPL generation:** enable with `SPL_QUERY_GENERATION_ENABLED=true`; tune
  generation/execution controls with
  [`docs/operations/SPL_OPERATIONS.md`](docs/operations/SPL_OPERATIONS.md).
- **SPL-dedicated KB grounding:** enable with `SPL_QUERY_RAG_ENABLED=true`
  after curated Splunk facts have been ingested into the separate SPL KB table.
- **Read-only Splunk execution:** enable with
  `INVESTIGATION_QUERY_EXECUTION_ENABLED=true` after allowlists and load bounds
  are agreed with Splunk owners.
- **Query-result interpretation:** enable with
  `QUERY_RESULT_INTERPRETATION_ENABLED=true` after deterministic query execution
  quality is accepted; this adds narrative interpretation without changing
  confidence scores or deterministic query facts.
- **Splunk writeback:** enable with `SPLUNK_SINK_ENABLED=true`; validate
  endpoint and identifier mapping first.
- **ServiceNow:** enable draft first, then create only with approval metadata and
  customer sign-off.
- **Freeform analyzer mode:** documented in
  [`docs/operations/LLM_INFERENCE_OPERATIONS.md`](docs/operations/LLM_INFERENCE_OPERATIONS.md);
  do not run it against the same incoming directory as the structured analyzer.

All optional integrations are disabled by default.

## Validation Quick Links

- Unit and smoke test guide: [`docs/testing/TESTING.md`](docs/testing/TESTING.md)
- Postgres/pgvector RAG smoke:
  [`scripts/smoke_postgres_rag.sh`](scripts/smoke_postgres_rag.sh)
- Full service-chain smoke:
  [`scripts/smoke_service_chain.sh`](scripts/smoke_service_chain.sh)
- Dependency manifest evidence:
  [`scripts/tools/generate_dependency_manifest.sh`](scripts/tools/generate_dependency_manifest.sh)

## Repository Map

```text
llm_notable_analysis_onprem_systemd/
  config.env.example       # Runtime configuration template
  deploy/                  # systemd and LiteLLM assets
  docs/                    # Operator, architecture, security, testing docs
  scripts/                 # Install, smoke, RAG setup, evidence helpers
  src/                     # Installable Python package
  tests/                   # Unit and contract tests
```

## Important Boundaries

- This package does not contain production notables, model weights, KB indexes,
  wheelhouses, or secrets.
- RAG content is advisory context, not direct alert evidence.
- Generated SPL is policy-checked before execution, but Splunk remains the final
  authority on SPL syntax.
- ServiceNow create is approval-gated by default.
- Live Splunk and ServiceNow validation requires customer-controlled lab or
  production-like systems.

