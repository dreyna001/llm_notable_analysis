# On-Prem Notable Analysis Service

Air-gapped-capable, single-host notable analysis for SOC workflows. The default
deployment runs local inference through **LiteLLM -> vLLM** and uses a file-drop
workflow for incoming `.json` or `.txt` notables.

**Deployers start here.** Pick one path in section 2, follow the linked documents in
order, and finish at validation. Topic shortcuts live in
[`docs/README.md`](docs/README.md).

Optional capabilities include RAG grounding, read-only Splunk or Elasticsearch
investigation, Splunk/ServiceNow writeback (`action_gated`), HTML reports, and a
Postgres-backed analyst portal with retrieval-bound chat (`analyst_portal`).

## 1) Prerequisites

- RHEL 8/9 (or compatible) host with root access for install
- NVIDIA GPU with CUDA drivers when using the default vLLM path (see Path C for alternates)
- Model weights on disk before starting vLLM (default under `/opt/models/`)
- Monorepo siblings on the install host: `onprem-llm-sdk/` and `onprem_rag_notable_analysis/`
- Production layout: git checkout (pull/upgrade) vs `/opt/notable-analyzer` (runtime)
  vs `/etc/notable-analyzer/` (secrets and tuning) — see
  [`docs/operations/deployment/HOST_LAYOUT_AND_UPDATES.md`](docs/operations/deployment/HOST_LAYOUT_AND_UPDATES.md)

Quick checks:

```bash
python3.12 --version
nvidia-smi   # when using vLLM
ls ../onprem-llm-sdk ../onprem_rag_notable_analysis
```

**Air-gapped hosts:** stage artifacts with
[`docs/operations/deployment/OFFLINE_PRESTAGE_GUIDE.md`](docs/operations/deployment/OFFLINE_PRESTAGE_GUIDE.md)
before install, then follow your chosen path and finish with the acceptance checks in
[`docs/operations/deployment/AIRGAPPED_DEPLOYMENT.md`](docs/operations/deployment/AIRGAPPED_DEPLOYMENT.md).

**Before any production install or upgrade** (`scripts/install.sh`, profile apply
scripts, KB rebuilds that clear data):

1. Confirm the target host, GPU profile, and Python 3.12 runtime are approved
2. Confirm model weights, wheelhouse, and portal `dist/` are staged when offline
3. Confirm monorepo checkout paths and sibling packages
4. Review [`config.env.example`](config.env.example) (and [`config.portal.env.example`](config.portal.env.example) when portal is in scope)
5. Obtain explicit customer approval for that mutation

## 2) Deploy — pick one path

| Path | When to use |
| --- | --- |
| **A — Core only** | File-drop analysis only; no RAG or analyst portal |
| **B — Customer-default** | `core,rag,analyst_portal` parity with cloud customer-default bundles |
| **C — Custom profiles** | Specific capability bundles, hardware tuning, or alternate inference backends |

Each runbook ends with a **Next** line for path navigation. Stay on one path until you
reach [`docs/testing/TESTING.md`](docs/testing/TESTING.md).

**Core systemd units:** `vllm`, `litellm`, `notable-analyzer`; optional `notable-portal`,
`notable-retention.timer`, `notable-closed-ticket-sync.timer`.

### Path A — Core only

Follow in order:

1. [`docs/operations/deployment/HOST_LAYOUT_AND_UPDATES.md`](docs/operations/deployment/HOST_LAYOUT_AND_UPDATES.md) — checkout vs install tree vs runtime config paths
2. [`docs/operations/deployment/INSTALL.md`](docs/operations/deployment/INSTALL.md) — host install, systemd units, post-install checks
3. [`config.env.example`](config.env.example) — set `CAPABILITY_PROFILES=core`, LLM endpoint, directories, secrets
4. [`docs/operations/llm/LLM_INFERENCE_OPERATIONS.md`](docs/operations/llm/LLM_INFERENCE_OPERATIONS.md) — LiteLLM/vLLM model id, tokens, structured output
5. [`docs/testing/TESTING.md`](docs/testing/TESTING.md) — unit tests and `smoke_service_chain.sh` validation

Install command:

```bash
cd /path/to/llm_notable_analysis_onprem_systemd
sudo bash scripts/install.sh
```

Offline example:

```bash
sudo INSTALL_PYTHON=false MODEL_DOWNLOAD=false PIP_NO_INDEX=1 \
  PIP_FIND_LINKS=/path/to/wheelhouse bash scripts/install.sh
```

### Path B — Customer-default

Bundle: analyzer `CAPABILITY_PROFILES=core,rag,analyst_portal`; portal
`core,analyst_portal` with explicit RAG mirror flags on `portal.env`. Follow in order.

1. [`docs/operations/deployment/HOST_LAYOUT_AND_UPDATES.md`](docs/operations/deployment/HOST_LAYOUT_AND_UPDATES.md) — host path model before first install
2. [`docs/operations/deployment/OFFLINE_PRESTAGE_GUIDE.md`](docs/operations/deployment/OFFLINE_PRESTAGE_GUIDE.md) — artifact staging when the host has no outbound internet
3. [`docs/operations/deployment/INSTALL.md`](docs/operations/deployment/INSTALL.md) — install with portal assets and Postgres schema hooks
4. [`docs/operations/deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md`](docs/operations/deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md) — dual-file env checklist and data-plane steps
5. [`docs/operations/rag/KNOWLEDGE_BASE_OPERATIONS.md`](docs/operations/rag/KNOWLEDGE_BASE_OPERATIONS.md) — general SOC and SPL KB ingest
6. [`docs/operations/integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md`](docs/operations/integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md) — closed-ticket sync when ServiceNow is in scope
7. [`docs/operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](docs/operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md) — TLS, nginx, DNS, firewall, analyst browser validation
8. [`docs/operations/deployment/deployment_profiles/README.md`](docs/operations/deployment/deployment_profiles/README.md) — optional hardware tuning (Blackwell, A6000, T4 demo)
9. [`docs/testing/TESTING.md`](docs/testing/TESTING.md) — `smoke_postgres_rag.sh`, service chain, portal case and chat checks

Install command:

```bash
sudo INSTALL_ANALYST_PORTAL=true bash scripts/install.sh
```

Air-gapped portal build:

```bash
sudo INSTALL_ANALYST_PORTAL=true INSTALL_PORTAL_SKIP_FRONTEND_BUILD=true \
  MODEL_DOWNLOAD=false bash scripts/install.sh
```

Portal env mirror: the portal process does **not** inherit analyzer env. Copy RAG DSN,
embedding model ids, and `PORTAL_PROXY_SECRET` to both `/etc/notable-analyzer/config.env`
and `portal.env` per the customer-default checklist.

### Path C — Custom profiles

1. [`docs/operations/platform/CAPABILITY_PROFILES.md`](docs/operations/platform/CAPABILITY_PROFILES.md) — select bundles; note mutual exclusions (`spl_readonly` vs `elastic_readonly`)
2. [`docs/operations/deployment/HOST_LAYOUT_AND_UPDATES.md`](docs/operations/deployment/HOST_LAYOUT_AND_UPDATES.md) — when upgrading an existing host
3. [`docs/operations/deployment/INSTALL.md`](docs/operations/deployment/INSTALL.md) — base install (or alternate installers below)
4. Profile ops from [`docs/operations/README.md`](docs/operations/README.md) — enable only guides matching your `CAPABILITY_PROFILES` slice
5. [`docs/operations/deployment/deployment_profiles/README.md`](docs/operations/deployment/deployment_profiles/README.md) — GPU/CPU starting values when sizing differs from defaults
6. [`docs/testing/TESTING.md`](docs/testing/TESTING.md) — profile-specific smoke and contract tests

Alternate inference backends (Path C only, not default production):

- Two-T4 llama.cpp demo: [`docs/operations/deployment/deployment_profiles/t4x2-llamacpp-gemma4-demo.md`](docs/operations/deployment/deployment_profiles/t4x2-llamacpp-gemma4-demo.md) via `scripts/install_t4x2_llamacpp_demo.sh`
- External CPU Qwen at `127.0.0.1:8000`: `scripts/install_mini_qwen_cpu_client.sh` in [`INSTALL.md`](docs/operations/deployment/INSTALL.md)

Runtime env reference: [`config.env.example`](config.env.example),
[`config.portal.env.example`](config.portal.env.example).

## 3) Validate (all paths end here)

Path-specific checklists live in [`docs/testing/TESTING.md`](docs/testing/TESTING.md).
You are done when path-specific smoke and staging checks pass on the deployed host.

Core service chain (on host):

```bash
sudo bash scripts/smoke_service_chain.sh --config-env /etc/notable-analyzer/config.env
```

Customer-default RAG smoke (workstation or host with Docker):

```bash
bash scripts/smoke_postgres_rag.sh
```

Unit tests (from monorepo root, dev venv):

```bash
pytest llm_notable_analysis_onprem_systemd/tests/onprem_service -q
```

## 4) Rollback and teardown

**Rollback (failed release, not teardown):** redeploy a previous git checkout and
re-run `scripts/install.sh` with `AUTO_START_SERVICES=false` first; restore env files
from backup. Hardware profile scripts write backups under `/root/notable-profile-backups/`
— see [`docs/operations/deployment/deployment_profiles/README.md`](docs/operations/deployment/deployment_profiles/README.md).
KB content rollback: [`docs/operations/rag/KNOWLEDGE_BASE_OPERATIONS.md`](docs/operations/rag/KNOWLEDGE_BASE_OPERATIONS.md)
(Rollback). T4 llama.cpp backend rollback:
[`t4x2-llamacpp-gemma4-demo.md`](docs/operations/deployment/deployment_profiles/t4x2-llamacpp-gemma4-demo.md).

**Teardown (destructive — approval required):** stopping services and removing install
trees is **irreversible** for local runtime state and is not rollback. After explicit
customer approval, follow [`docs/operations/deployment/INSTALL.md`](docs/operations/deployment/INSTALL.md)
(Uninstall) plus customer procedures for Postgres data, nginx TLS material, and retained
artifacts under `/var/notables/`. No automated bulk deletion workflow is provided.

## 5) Important boundaries

- No production notables, model weights, KB indexes, wheelhouses, or secrets in git.
- RAG and portal chat context are advisory; they are not direct alert evidence.
- Portal chat is retrieval-bound and does not execute Splunk, ServiceNow, SOAR, or writeback.
- Generated SPL/Elastic queries are policy-checked; Splunk/Elastic remain syntax authority.
- ServiceNow create is approval-gated by default (`action_gated`).
- Live Splunk, Elastic, and ServiceNow validation needs customer-controlled systems.

## 6) Further reading

| Topic | Doc |
| --- | --- |
| Capability profiles | [`docs/operations/platform/CAPABILITY_PROFILES.md`](docs/operations/platform/CAPABILITY_PROFILES.md) |
| Operations guides by area | [`docs/operations/README.md`](docs/operations/README.md) |
| Recovery and replay behavior | [`docs/operations/platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](docs/operations/platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md) |
| Security posture | [`docs/operations/security/SECURITY_OPERATIONS.md`](docs/operations/security/SECURITY_OPERATIONS.md) |
| Analyst portal UI (build/E2E) | [`frontend/analyst-portal/README.md`](frontend/analyst-portal/README.md) |
| Documentation index | [`docs/README.md`](docs/README.md) |
| Local dev (repo checkout) | [`../DEVELOPING.md`](../DEVELOPING.md) |
