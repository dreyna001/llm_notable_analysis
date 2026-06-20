# On-Prem Notable Analysis Service

Air-gapped-capable, single-host notable analysis service for SOC workflows. The
default deployment runs local inference through **LiteLLM -> vLLM** and uses a
file-drop workflow for incoming `.json` or `.txt` notables.

This README is a **jumping board**. Install steps, tuning, security, and
integration detail live under [`docs/`](docs/).

## What This Package Provides

- `systemd`-managed analyzer (`onprem_main`) that watches an incoming directory
  and writes markdown reports (optional HTML via `html_reports`).
- Local OpenAI-compatible inference through LiteLLM/vLLM.
- Optional RAG grounding from a local knowledge base (`rag`).
- Optional SPL or Elasticsearch read-only investigation (`spl_readonly` or
  `elastic_readonly`; mutually exclusive).
- Optional Splunk writeback and ServiceNow draft/create with approval-gated
  create (`action_gated`).
- Optional Postgres-backed analyst portal, 30-day case archive, and
  retrieval-bound chat (`analyst_portal`; separate `portal_app` service).
- MITRE ATT&CK TTP validation and operator docs for install, offline prestage,
  recovery, security, and per-customer tuning.

## Start Here

| Need | Read this |
|------|-----------|
| Doc index and reading order | [`docs/README.md`](docs/README.md) |
| Executive build summary | [`docs/delivery_package/EXECUTIVE_ONPREM_BUILD_WRITEUP.md`](docs/delivery_package/EXECUTIVE_ONPREM_BUILD_WRITEUP.md) |
| End-to-end behavior | [`docs/delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md`](docs/delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md) |
| Install on a host | [`docs/operations/deployment/INSTALL.md`](docs/operations/deployment/INSTALL.md) |
| Offline / air-gapped prep | [`docs/operations/deployment/OFFLINE_PRESTAGE_GUIDE.md`](docs/operations/deployment/OFFLINE_PRESTAGE_GUIDE.md), [`AIRGAPPED_DEPLOYMENT.md`](docs/operations/deployment/AIRGAPPED_DEPLOYMENT.md) |
| Capability profiles | [`docs/operations/platform/CAPABILITY_PROFILES.md`](docs/operations/platform/CAPABILITY_PROFILES.md) |
| Customer tuning by area | [`docs/operations/README.md`](docs/operations/README.md) |
| Analyzer config template | [`config.env.example`](config.env.example) |
| Portal config template | [`config.portal.env.example`](config.portal.env.example) |
| Tests and validation | [`docs/testing/TESTING.md`](docs/testing/TESTING.md) |
| Local dev (repo `.venv`, portal preview) | [`../DEVELOPING.md`](../DEVELOPING.md) |
| Host paths vs local checkout | [Filesystem map](#filesystem-map) |
| Security posture | [`docs/operations/security/SECURITY_OPERATIONS.md`](docs/operations/security/SECURITY_OPERATIONS.md), [`docs/security/SECURITY_POSTURE.md`](docs/security/SECURITY_POSTURE.md) |
| Deployment readiness | [`docs/delivery_package/AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_OVERVIEW.md`](docs/delivery_package/AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_OVERVIEW.md) |
| Developer / maintainer guide | [`docs/internal/DEVELOPER_MAINTAINER_GUIDE.md`](docs/internal/DEVELOPER_MAINTAINER_GUIDE.md) |
| AWS EC2 GPU lab stack | [`deploy/aws/README.md`](deploy/aws/README.md) |

## Customer Operations Guides

Config-focused pages for tuning shipped behavior without code changes.

| Area | Guide |
|------|-------|
| Capability profiles | [`docs/operations/platform/CAPABILITY_PROFILES.md`](docs/operations/platform/CAPABILITY_PROFILES.md) |
| File drop, payloads, retention, concurrency | [`docs/operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](docs/operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) |
| MITRE ATT&CK/TTP validation | [`docs/operations/platform/MITRE_TTP_OPERATIONS.md`](docs/operations/platform/MITRE_TTP_OPERATIONS.md) |
| Recovery behavior | [`docs/operations/platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](docs/operations/platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md) |
| LLM inference tuning | [`docs/operations/llm/LLM_INFERENCE_OPERATIONS.md`](docs/operations/llm/LLM_INFERENCE_OPERATIONS.md) |
| LLM serving benchmarks | [`docs/operations/llm/LLM_INFERENCE_BENCHMARKING.md`](docs/operations/llm/LLM_INFERENCE_BENCHMARKING.md) |
| Knowledge base lifecycle | [`docs/operations/rag/KNOWLEDGE_BASE_OPERATIONS.md`](docs/operations/rag/KNOWLEDGE_BASE_OPERATIONS.md) |
| RAG retrieval tuning | [`docs/operations/rag/RAG_OPERATIONS.md`](docs/operations/rag/RAG_OPERATIONS.md) |
| SPL generation and read-only execution | [`docs/operations/investigation/SPL_OPERATIONS.md`](docs/operations/investigation/SPL_OPERATIONS.md) |
| Elasticsearch read-only execution | [`docs/operations/investigation/ELASTICSEARCH_OPERATIONS.md`](docs/operations/investigation/ELASTICSEARCH_OPERATIONS.md) |
| Splunk notable writeback | [`docs/operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](docs/operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md) |
| ServiceNow draft/create | [`docs/operations/integrations/SERVICENOW_OPERATIONS.md`](docs/operations/integrations/SERVICENOW_OPERATIONS.md) |
| Analyst portal and case archive | [`docs/operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](docs/operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md) |
| Analyst portal network rollout | [`docs/operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](docs/operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md) |
| Analyst portal chat security | [`docs/operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md`](docs/operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md) |
| Analyst portal local preview (dev) | [`docs/operations/analyst_portal/ANALYST_PORTAL_PREVIEW.md`](docs/operations/analyst_portal/ANALYST_PORTAL_PREVIEW.md) |
| SOAR / Phantom file drop | [`docs/integrations/SOAR_PLAYBOOK_PHANTOM.md`](docs/integrations/SOAR_PLAYBOOK_PHANTOM.md) |

## Default Runtime Shape

```text
SOAR/SFTP/operator file drop
  -> notable-analyzer (onprem_main)
  -> LiteLLM -> vLLM
  -> markdown report (+ optional HTML)
  -> processed / quarantine movement
  -> optional Postgres case archive
  -> optional Splunk / ServiceNow outputs
  -> optional analyst portal (portal_app + nginx) for read-only browse/chat
```

**Production `systemd` units:** `vllm`, `litellm`, `notable-analyzer`; optional
`notable-portal`; optional `notable-retention` timer for file and case retention.

Supported profiles (`CAPABILITY_PROFILES`): `core`, `html_reports`, `rag`,
`spl_readonly`, `elastic_readonly`, `ticket_draft`, `action_gated`,
`analyst_portal`. Details:
[`docs/operations/platform/CAPABILITY_PROFILES.md`](docs/operations/platform/CAPABILITY_PROFILES.md).

Installed Python package:
[`src/llm_notable_analysis_onprem_systemd/`](src/llm_notable_analysis_onprem_systemd/).

## Filesystem map

Source checkout only until `scripts/install.sh` runs on the host. Local dev uses
the git tree and repo-root `.venv`; see [Local dev](#local-dev-repo-checkout-no-full-install).

### Installed host (production)

| Path | Purpose |
|------|---------|
| `/opt/notable-analyzer` | App install: venv, package, React `frontend/analyst-portal/dist` |
| `/etc/notable-analyzer/config.env` | Analyzer secrets, directories, capability profiles |
| `/etc/notable-analyzer/portal.env` | Portal Postgres DSN, bind, proxy secret |
| `/var/notables/incoming` | File drop (often symlink to SFTP incoming) |
| `/var/notables/processed`, `quarantine`, `reports`, `archive` | Runtime artifact dirs |
| `/var/notables/cache` | HuggingFace / sentence-transformers cache |
| `/var/sftp/soar` | SFTP chroot for SOAR (`incoming` under chroot) |
| `/opt/llm-notable-analysis/knowledge_base/` | RAG and query-grounding source docs |
| `/opt/models/` | LLM weights (override with `VLLM_MODEL_PATH`) |
| `/opt/vllm`, `/opt/litellm` | Inference stack venvs |
| `/etc/litellm/config.yaml` | LiteLLM routing |
| `/etc/nginx/conf.d/notable-portal.conf` | Portal TLS, basic auth, static UI, API proxy |

**PostgreSQL** runs as a separate OS service. Defaults in `config.env.example`:
database `notable_rag` on `127.0.0.1:5432`; case archive schema `notable_cases`;
RAG chunks in schema `notable_rag`; optional chat history on the same instance.

Portal: nginx on `443` serves React static files and proxies `/api/`, `/health`,
`/ready` to FastAPI on `127.0.0.1:8080`.

SFTP contract: chroot `/var/sftp/soar`; typical symlink
`/var/notables/incoming -> /var/sftp/soar/incoming`.

### Local dev (repo checkout, no full install)

| Path / endpoint | Purpose |
|-----------------|---------|
| `<repo-root>/llm_notable_analysis_onprem_systemd/` | This package |
| `<repo-root>/.venv` | Shared dev venv (Python + embedded Node/npm) |
| `<repo-root>/scripts/bootstrap_dev_venv.ps1` / `.sh` | One-time dev bootstrap |
| `<repo-root>/scripts/dev_portal_preview.ps1` | Portal preview API wrapper |
| `<repo-root>/scripts/dev_portal_ui.ps1` | Vite dev server wrapper |
| `config.portal-preview.env` | Optional local OpenAI key for preview chat (gitignored) |
| `http://127.0.0.1:8765` | Preview API (in-memory fake data, not Postgres) |
| `http://127.0.0.1:5173` | Vite dev server (proxies API to `8765`) |

Workflow: [`../DEVELOPING.md`](../DEVELOPING.md) and
[`frontend/analyst-portal/README.md`](frontend/analyst-portal/README.md). Playwright
E2E targets a deployed VM, not the local preview layout.

## Optional Capabilities

Enable bundles with `CAPABILITY_PROFILES` in `config.env`; endpoint, path, secret,
and tuning values stay in the same file (portal process reads `portal.env`).

- **RAG:** `rag` — [`RAG_OPERATIONS.md`](docs/operations/rag/RAG_OPERATIONS.md)
- **SPL read-only:** `spl_readonly` — [`SPL_OPERATIONS.md`](docs/operations/investigation/SPL_OPERATIONS.md)
- **Elastic read-only:** `elastic_readonly` instead of `spl_readonly` — [`ELASTICSEARCH_OPERATIONS.md`](docs/operations/investigation/ELASTICSEARCH_OPERATIONS.md)
- **HTML reports:** `html_reports`
- **ServiceNow draft:** `ticket_draft`
- **Analyst portal:** `analyst_portal` — [`ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](docs/operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md)
- **External writes:** `action_gated` only after Splunk writeback, ServiceNow create, approval metadata, and idempotency are accepted

Advanced overrides (not profiles): `SPL_QUERY_RAG_ENABLED`, `QUERY_RESULT_INTERPRETATION_ENABLED`.

All optional integrations are disabled by default.

## Validation Quick Links

- Test guide: [`docs/testing/TESTING.md`](docs/testing/TESTING.md) (152 service tests; 190 full package)
- Postgres/pgvector RAG smoke: [`scripts/smoke_postgres_rag.sh`](scripts/smoke_postgres_rag.sh)
- Full service-chain smoke: [`scripts/smoke_service_chain.sh`](scripts/smoke_service_chain.sh)
- Dependency manifest: [`scripts/tools/generate_dependency_manifest.sh`](scripts/tools/generate_dependency_manifest.sh)

## Repository Map

```text
llm_notable_analysis_onprem_systemd/
  config.env.example       # Analyzer runtime template
  config.portal.env.example
  deploy/                  # systemd, nginx, Postgres schema, AWS lab stack
  docs/                    # Operator, integration, security, testing docs
  frontend/analyst-portal/ # React portal UI (Vite -> dist/)
  scripts/                 # install.sh, smoke tests, RAG/case helpers
  src/                     # Installable Python package
  tests/                   # Unit and contract tests
```

Host install also requires sibling monorepo packages (`onprem_rag_notable_analysis`,
`onprem-llm-sdk`); see [`docs/operations/deployment/INSTALL.md`](docs/operations/deployment/INSTALL.md).

## Important Boundaries

- No production notables, model weights, KB indexes, wheelhouses, or secrets in git.
- RAG and portal chat context are advisory; they are not direct alert evidence.
- Portal chat is retrieval-bound and does not execute Splunk, ServiceNow, SOAR, or writeback.
- Generated SPL/Elastic queries are policy-checked; Splunk/Elastic remain syntax authority.
- ServiceNow create is approval-gated by default.
- Live Splunk, Elastic, and ServiceNow validation needs customer-controlled systems.
