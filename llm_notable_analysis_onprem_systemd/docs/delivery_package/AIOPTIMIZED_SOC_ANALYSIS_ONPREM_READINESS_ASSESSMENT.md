# On-Prem Readiness Assessment

Detailed readiness checklist for the host-native on-prem notable analysis stack.
Start with [`AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_OVERVIEW.md`](AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_OVERVIEW.md)
for the executive gateway; use this document for technical prerequisites,
integration decisions, and validation expectations.

**Related runbooks:** [`../operations/deployment/INSTALL.md`](../operations/deployment/INSTALL.md),
[`../operations/deployment/OFFLINE_PRESTAGE_GUIDE.md`](../operations/deployment/OFFLINE_PRESTAGE_GUIDE.md),
[`../operations/deployment/AIRGAPPED_DEPLOYMENT.md`](../operations/deployment/AIRGAPPED_DEPLOYMENT.md),
[`../operations/platform/CAPABILITY_PROFILES.md`](../operations/platform/CAPABILITY_PROFILES.md).

## What Ready Looks Like

Ready means the org can run one documented install path (`scripts/install.sh`),
stage approved artifacts, set environment-specific values in
`/etc/notable-analyzer/config.env`, and pass end-to-end smoke tests without
designing the runtime during deployment.

Default stack shape:

- analyzer from `llm_notable_analysis_onprem_systemd/` (`notable-analyzer.service`)
- `vLLM` on `127.0.0.1:8000`, `LiteLLM` on `127.0.0.1:4000`
- default example model `gemma-4-31B-it` (alternate local models require aligned
  weights, served name, and config)
- optional KB / RAG from `onprem_rag_notable_analysis/` when the `rag` profile
  is selected

The org is not deployment-ready until all of the following are settled:

| Area | Must be decided before install |
| --- | --- |
| Host | Target Linux host, owner, connected vs air-gapped delivery |
| Platform | `systemd`, Python 3.12, admin access, storage for repo + model + reports |
| GPU | Approved profile (baseline: RTX PRO 6000 96 GB class or equivalent), healthy `nvidia-smi`, CUDA/runtime match for pinned `vllm==0.21.0` |
| Model | Full `gemma-4-31B-it` tree staged under `/opt/models/gemma-4-31B-it` or approved staging process |
| Control plane | Callers use `LiteLLM` on loopback (recommended) or direct `vLLM` with matching analyzer config |
| Features | `CAPABILITY_PROFILES` chosen (`core` only to start; add `rag`, `spl_readonly`, `action_gated`, `analyst_portal`, etc. one at a time) |
| Integrations | If writeback/search/tickets/portal are in scope: Splunk, ServiceNow, Postgres, and secret owners identified |
| Operations | Owner for smoke tests, journal triage, service restart, and rollback |

## Readiness Checklist

### 1. Host and platform

- Linux host with `systemd` and Python 3.12 for analyzer and vLLM paths
- Recommended baseline: 128 GB RAM (256 GB for heavy KB/concurrency), 1 TB NVMe
  (500 GB minimum), 16+ vCPU; see
  [`../operations/deployment/deployment_profiles/README.md`](../operations/deployment/deployment_profiles/README.md)
- Connected install or offline transfer bundle per
  [`../operations/deployment/OFFLINE_PRESTAGE_GUIDE.md`](../operations/deployment/OFFLINE_PRESTAGE_GUIDE.md)

### 2. GPU and inference

- NVIDIA driver healthy; CUDA/runtime compatible with staged `vllm==0.21.0`
- vLLM starts and advertises the configured served model name
- Analyzer, LiteLLM, and vLLM agree on the model contract:

```ini
LLM_API_URL=http://127.0.0.1:4000/v1/chat/completions
LLM_MODEL_NAME=gemma-4-31B-it
LLM_API_TOKEN=<matches LiteLLM master key in /etc/litellm/config.yaml>
```

### 3. Artifacts and packaging

The repo does not ship model weights. Before go-live, resolve:

- vLLM wheelhouse / `VLLM_PIP_SPEC` delivery (default `vllm==0.21.0`)
- LiteLLM and analyzer Python dependencies (`scripts/install.sh` or offline wheelhouse)
- Model weights at the path used by `vllm.service`
- Optional KB source docs, embedding model, and Postgres RAG setup when `rag` is enabled

### 4. Runtime contract

- `INGEST_MODE=file_drop` only; one file per analysis run (`.json` or `.txt`)
- Outputs under `REPORT_DIR`; successful inputs move to `PROCESSED_DIR`, failures to `QUARANTINE_DIR`
- Application LLM traffic goes to LiteLLM (`127.0.0.1:4000`), not directly to vLLM, unless deliberately configured otherwise
- Enable optional behavior through `CAPABILITY_PROFILES`, not ad-hoc flag sprawl; see
  [`../operations/platform/CAPABILITY_PROFILES.md`](../operations/platform/CAPABILITY_PROFILES.md)

### 5. Secrets and integrations

**LiteLLM:** strong master key in `/etc/litellm/config.yaml`; matching `LLM_API_TOKEN` in `config.env`; loopback-only unless edge exposure is approved.

**Splunk writeback** (profile `action_gated`): `SPLUNK_BASE_URL`, `SPLUNK_API_TOKEN`, endpoint path, and filename-stem-to-notable mapping confirmed with the Splunk owner. See [`../operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](../operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md).

**Splunk read-only investigation** (profile `spl_readonly`): separate from writeback; index/command allowlists and search token scope per [`../operations/investigation/SPL_OPERATIONS.md`](../operations/investigation/SPL_OPERATIONS.md).

**ServiceNow** (profiles `ticket_draft` / `action_gated`): credentials and approval boundaries per [`../operations/integrations/SERVICENOW_OPERATIONS.md`](../operations/integrations/SERVICENOW_OPERATIONS.md).

**Analyst portal** (profile `analyst_portal`): Postgres, `portal.env`, and network rollout per [`../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md).

### 6. Knowledge base and RAG

If retrieval grounding is in scope:

- add `rag` to `CAPABILITY_PROFILES` (profile overrides legacy `RAG_ENABLED` lab flags)
- stage embedding model and KB sources offline when needed
- assign an owner for source content and rebuild cadence (`scripts/setup_postgres_rag.sh`, `ingest_report.json`)

If undecided, keep `CAPABILITY_PROFILES=core`.

### 7. Operational validation

Primary smoke path:

```bash
sudo bash scripts/smoke_service_chain.sh --config-env /etc/notable-analyzer/config.env
```

Also confirm:

- `journalctl` access for `vllm`, `litellm`, and `notable-analyzer`
- ability to distinguish GPU/runtime, proxy auth, and analyzer failures
- rollback plan for units, `config.env`, venvs, and model artifacts

## Green-State Questions

The org is in true green status when it can answer immediately:

1. Target host class and who owns it?
2. Approved GPU, driver, and CUDA/runtime for `vllm==0.21.0`?
3. Full `gemma-4-31B-it` model tree staged and verified?
4. Served model name and analyzer `LLM_MODEL_NAME` aligned?
5. Analyzer pointed at LiteLLM on `127.0.0.1:4000`?
6. LiteLLM master key stored and rotated by whom?
7. Which `CAPABILITY_PROFILES` are enabled (writeback, RAG, SPL, portal)?
8. Incoming, processed, quarantine, reports, and archive paths on disk?
9. Who owns smoke testing and host troubleshooting?
10. Rollback plan if model, proxy, or analyzer update breaks the stack?

If these need a workshop, deployment is not yet low-friction.

## Engineer-Led Integration Split

| Phase | Owner | Examples |
| --- | --- | --- |
| Before start | Customer / platform team | Host and GPU approval, air-gap vs connected, model staging, profile scope, Splunk/ServiceNow/Postgres governance, ops owner |
| During integration | Engineer | `install.sh`, config alignment, `smoke_service_chain.sh`, profile-by-profile validation, handoff doc with paths and rollback |
| May block mid-flight | Customer / external teams | Late GPU approval, model transfer, token issuance, Splunk endpoint confirmation, KB content ownership |

## Current Package Friction

- Model weights and offline wheelhouses remain customer staging work
- `scripts/install.sh` covers analyzer + vLLM + LiteLLM; Postgres RAG and analyst portal need separate setup steps
- LiteLLM master key and analyzer token alignment are operator-managed
- Alternate models require coordinated edits to weights, vLLM flags, LiteLLM config, and `LLM_MODEL_NAME`
- Splunk writeback and ServiceNow create paths need customer tokens, mapping validation, and explicit `action_gated` approval
