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
| Executive on-prem build summary | [`docs/delivery_package/EXECUTIVE_ONPREM_BUILD_WRITEUP.md`](docs/delivery_package/EXECUTIVE_ONPREM_BUILD_WRITEUP.md) |
| End-to-end behavior | [`docs/delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md`](docs/delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md) |
| Customer tuning by area | [`docs/operations/README.md`](docs/operations/README.md) |
| Install on a host | [`docs/operations/INSTALL.md`](docs/operations/INSTALL.md) |
| Offline or air-gapped prep | [`docs/operations/OFFLINE_PRESTAGE_GUIDE.md`](docs/operations/OFFLINE_PRESTAGE_GUIDE.md) |
| Runtime config values | [`config.env.example`](config.env.example) |
| Tests and validation | [`docs/testing/TESTING.md`](docs/testing/TESTING.md) |
| Local dev venv (Python + frontend) | [`../DEVELOPING.md`](../DEVELOPING.md) |
| Host paths vs local checkout | [Filesystem map](#filesystem-map) (below) |
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

Capability profiles and tunable path overrides are in
[`config.env.example`](config.env.example). Installed Python imports use
[`src/llm_notable_analysis_onprem_systemd/`](src/llm_notable_analysis_onprem_systemd/).

## Filesystem map

This checkout is **source only**. A full host install (`scripts/install.sh`)
copies code and creates the production paths below. **Local dev does not use
that layout** — it runs from the git tree with a repo-root `.venv` and optional
in-memory portal preview; see [Local dev](#local-dev-repo-checkout-no-full-install).

### Installed host (production)

Set by `scripts/install.sh` unless overridden in env files. Writable runtime
data stays outside `/opt/notable-analyzer`.

| Path | Purpose |
|------|---------|
| `/opt/notable-analyzer` | Installed app: Python package, venv, built React at `frontend/analyst-portal/dist` |
| `/etc/notable-analyzer/config.env` | Analyzer secrets, directories, capability profiles |
| `/etc/notable-analyzer/portal.env` | Portal service: Postgres DSN, bind, proxy secret |
| `/var/notables/incoming` | Notable file drop (often symlink to SFTP incoming) |
| `/var/notables/processed` | Successfully handled inputs |
| `/var/notables/quarantine` | Rejected or oversized inputs |
| `/var/notables/reports` | Generated markdown/HTML reports |
| `/var/notables/archive` | Archived notable payloads |
| `/var/notables/cache` | HuggingFace / sentence-transformers model cache |
| `/var/sftp/soar` | SFTP chroot for SOAR upload (`incoming` under chroot) |
| `/opt/llm-notable-analysis/knowledge_base/` | RAG source docs and ingest indexes |
| `/opt/models/` | Local LLM weights (default; override with `VLLM_MODEL_PATH`) |
| `/opt/vllm`, `/opt/litellm` | Inference stack venvs |
| `/etc/litellm/config.yaml` | LiteLLM routing config |
| `/etc/nginx/conf.d/notable-portal.conf` | Portal TLS, basic auth, static `dist`, API proxy |

**PostgreSQL** is a separate OS service (data files under the distro Postgres
data directory, not under `/opt/notable-analyzer`). The app connects via DSN;
defaults in `config.env.example`:

- Database: `notable_rag` on `127.0.0.1:5432`
- Case archive schema: `notable_cases` (`CASE_POSTGRES_SCHEMA`)
- RAG chunks: schema `notable_rag` (and related tables)
- Optional chat history: same Postgres instance when enabled

Portal traffic: analysts hit nginx on `443`; nginx serves React static files and
proxies `/api/`, `/health`, `/ready` to FastAPI on `127.0.0.1:8080`. See
[`docs/operations/ANALYST_PORTAL_OPERATIONS.md`](docs/operations/ANALYST_PORTAL_OPERATIONS.md).

SFTP file-drop contract: chroot `/var/sftp/soar`; typical symlink
`/var/notables/incoming -> /var/sftp/soar/incoming`.

### Local dev (repo checkout, no full install)

| Path / endpoint | Purpose |
|---------------|---------|
| `<repo-root>/llm_notable_analysis_onprem_systemd/` | Package source (this tree) |
| `<repo-root>/.venv` | Shared dev venv (Python + embedded Node/npm) |
| `llm_notable_analysis_onprem_systemd/config.portal-preview.env` | Optional local OpenAI key for preview chat (gitignored) |
| `llm_notable_analysis_onprem_systemd/frontend/analyst-portal/node_modules/`, `dist/` | Frontend deps and build output (gitignored) |
| `http://127.0.0.1:8765` | Portal preview API (`scripts/preview_portal_ui.py`) with **in-memory fake data**, not Postgres |
| `http://127.0.0.1:5173` | Vite dev server; proxies API routes to `8765` |

Workflow: [`../DEVELOPING.md`](../DEVELOPING.md) and
[`frontend/analyst-portal/README.md`](frontend/analyst-portal/README.md).
Playwright E2E against a deployed VM is optional and uses the remote host paths
above, not your local checkout layout.

## Optional Capabilities

- **Profiles:** enable supported bundles with `CAPABILITY_PROFILES`; see
  [`docs/operations/CAPABILITY_PROFILES.md`](docs/operations/CAPABILITY_PROFILES.md).
- **RAG grounding:** add the `rag` profile; tune with
  [`docs/operations/RAG_OPERATIONS.md`](docs/operations/RAG_OPERATIONS.md).
- **SPL generation and read-only execution:** add the `spl_readonly` profile;
  tune generation/execution controls with
  [`docs/operations/SPL_OPERATIONS.md`](docs/operations/SPL_OPERATIONS.md).
- **SPL-dedicated KB grounding:** keep as an advanced override
  (`SPL_QUERY_RAG_ENABLED=true`) after curated Splunk facts have been ingested
  into the separate SPL KB table.
- **Query-result interpretation:** enable with
  `QUERY_RESULT_INTERPRETATION_ENABLED=true` after deterministic query execution
  quality is accepted; this adds narrative interpretation without changing
  confidence scores or deterministic query facts.
- **HTML reports:** add the `html_reports` profile.
- **ServiceNow draft:** add the `ticket_draft` profile.
- **External write/actions:** add the `action_gated` profile only after Splunk
  writeback, ServiceNow create, approval metadata, and idempotency behavior are
  accepted.
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

