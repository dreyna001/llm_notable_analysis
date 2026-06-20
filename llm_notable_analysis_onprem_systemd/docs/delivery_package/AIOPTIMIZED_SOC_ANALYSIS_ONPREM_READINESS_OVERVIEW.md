# On-Prem Readiness Overview

Executive gateway for the host-native on-prem notable analysis path. Use this
document to decide whether engineer-led deployment can begin. Use
[`AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_ASSESSMENT.md`](AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_ASSESSMENT.md)
for the detailed checklist.

**Install and validation runbooks:**
[`../operations/deployment/INSTALL.md`](../operations/deployment/INSTALL.md),
[`../operations/deployment/OFFLINE_PRESTAGE_GUIDE.md`](../operations/deployment/OFFLINE_PRESTAGE_GUIDE.md),
[`../operations/deployment/AIRGAPPED_DEPLOYMENT.md`](../operations/deployment/AIRGAPPED_DEPLOYMENT.md),
[`../operations/platform/CAPABILITY_PROFILES.md`](../operations/platform/CAPABILITY_PROFILES.md).

## In Scope

Single-host stack:

- analyzer from `llm_notable_analysis_onprem_systemd/` (`notable-analyzer.service`)
- `vLLM` on `127.0.0.1:8000`, `LiteLLM` on `127.0.0.1:4000`
- default example model `gemma-4-31B-it` (alternate local models need aligned weights and config)
- optional KB / RAG from `onprem_rag_notable_analysis/` when the `rag` profile is selected
- optional integrations (Splunk search/writeback, ServiceNow, analyst portal) via `CAPABILITY_PROFILES`

Documented install path: `scripts/install.sh` with runtime values in
`/etc/notable-analyzer/config.env`.

## What "Ready" Means

Ready means the organization has settled host, GPU, artifact, feature-scope,
security, and ownership decisions so an engineer can install, configure profiles,
and pass smoke tests without first resolving major platform questions.

## Executive Readiness Buckets

An organization is broadly ready when it can answer these six questions:

1. **Host and platform**: Target host, connected vs air-gapped delivery, and baseline CPU, RAM, storage, `systemd`, and Python 3.12 expectations?
2. **GPU and runtime**: Approved GPU profile, healthy NVIDIA driver/CUDA stack for pinned `vllm==0.21.0`, and whether callers use `LiteLLM` (recommended) or direct `vLLM`?
3. **Artifacts and configuration**: `gemma-4-31B-it` model tree staged (or approved staging process) and core runtime values aligned (`LLM_API_URL`, `LLM_MODEL_NAME`, `LLM_API_TOKEN`)?
4. **Feature scope**: Which `CAPABILITY_PROFILES` are in scope (`core` only to start; then `rag`, `spl_readonly`, `action_gated`, `analyst_portal`, etc.)?
5. **Security and integration**: For selected profiles, are Splunk, ServiceNow, Postgres/portal, KB sources, and required secrets owned and governed?
6. **Ownership and support**: Who owns smoke testing, host operations, journal triage, and rollback after deployment?

If those buckets are not understood, this is not yet a low-friction deployment.

## Before Engineer-Led Integration Starts

- target host, host owner, and GPU owner are identified
- connected-host vs air-gapped delivery is chosen
- host baseline is ready: `systemd`, Python 3.12, admin access, recommended CPU/RAM/storage
- approved GPU profile, healthy `nvidia-smi`, and CUDA/runtime compatibility for `vllm==0.21.0`
- control-plane choice is settled: `LiteLLM` on loopback or direct `vLLM`
- full `gemma-4-31B-it` model tree is staged, or there is an approved process to stage it
- `CAPABILITY_PROFILES` scope is decided (start with `core`; add profiles one at a time)
- if integrations are in scope, secret owners and mapping validation are identified (Splunk writeback needs `action_gated`; read-only Splunk search is separate via `spl_readonly`)
- someone is identified to own smoke testing, runtime support, and rollback

## What The Engineer Can Do Once Engaged

- verify host prerequisites, service paths, `nvidia-smi`, and systemd access
- run `scripts/install.sh` and align `/etc/notable-analyzer/config.env` plus LiteLLM config
- validate that `vLLM`, `LiteLLM`, and the analyzer agree on the model contract
- run `scripts/smoke_service_chain.sh --config-env /etc/notable-analyzer/config.env`
- enable and validate optional profiles incrementally (RAG rebuild, Splunk paths, portal setup)
- hand off rerun and rollback commands, paths, and values

## What May Still Depend On The Customer

- final approval of the host, GPU profile, and runtime stack
- staging or transfer of model weights and offline wheelhouses if not yet on the host
- issuance, storage, rotation, and access review for the LiteLLM master key
- Splunk REST token and endpoint/mapping confirmation when `action_gated` or `spl_readonly` is enabled
- ServiceNow credentials and approval boundaries when `ticket_draft` / `action_gated` is enabled
- Postgres, `portal.env`, and network rollout when `analyst_portal` is enabled
- KB source ownership and rebuild cadence when `rag` is enabled
- approval of loopback-only vs broader exposure for the LLM control plane

## Most Common Blockers

- `gemma-4-31B-it` artifacts are not yet staged
- GPU driver/runtime or CUDA compatibility is not validated for `vllm==0.21.0`
- runtime values are not aligned between `vLLM`, `LiteLLM`, and the analyzer
- no settled owner for the LiteLLM master key or integration tokens
- `CAPABILITY_PROFILES` scope is still unresolved (especially writeback vs read-only Splunk, portal/Postgres, RAG)
- connected-host vs air-gapped delivery is undecided

## Status Language

- **Ready**: all six readiness buckets are answered
- **Ready with dependencies**: the path is mostly clear, but approvals, staging, credentials, or profile scope steps are still pending
- **Not ready**: major questions remain in host/platform, runtime, artifacts, feature scope, security/integration, or ownership

## Next Document

See [`AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_ASSESSMENT.md`](AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_ASSESSMENT.md) for the detailed assessment.
