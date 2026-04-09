# On-Prem Readiness Overview

Executive gateway for the host-native on-prem notable analysis path. Use this document to decide whether engineer-led deployment can begin. Use `AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_ASSESSMENT.md` for the detailed technical rationale.

## In Scope
Analyzer from `llm_notable_analysis_onprem_systemd/`, `vLLM` serving `gpt-oss-120b`, `LiteLLM` as the caller-facing proxy, and optional KB / RAG indexing from `onprem_setup_GLAB/`.

## What "Ready" Means
Ready means the organization has already settled the key host, runtime, artifact, security, and ownership decisions so an engineer can install and validate the stack without first resolving major platform questions.

## Executive Readiness Buckets
An organization is broadly ready when it can answer these five questions:

1. **Host and platform**: Do we know the target host, delivery model, and baseline CPU, RAM, storage, and OS/runtime expectations?
2. **GPU and runtime**: Do we know the approved GPU, driver, CUDA/runtime combination, and whether callers will use `LiteLLM` or direct `vLLM`?
3. **Artifacts and configuration**: Do we have the `gpt-oss-120b` model tree staged, or an approved way to stage it, and do we know the core runtime values?
4. **Security and integration**: If Splunk or RAG is in scope, do we know where the required secrets, KB artifacts, and integration decisions come from?
5. **Ownership and support**: Do we know who owns smoke testing, host operations, and rollback after deployment?

If those five buckets are not already understood, this is not yet a low-friction deployment.

## Before Engineer-Led Integration Starts
- target host, host owner, and GPU owner are identified
- connected-host versus air-gapped delivery is chosen
- host baseline is ready: `systemd`, Python 3.12, admin access, recommended CPU/RAM, and enough storage
- approved GPU profile, healthy NVIDIA driver state, and CUDA/runtime compatibility for this pinned `vllm==0.14.1` shape are in place
- the control-plane choice is settled: `LiteLLM` or direct `vLLM`
- the `gpt-oss-120b` model tree is staged, or there is an approved process to stage it
- if Splunk or RAG is in scope, the team already knows the source of secrets, KB artifacts, and key integration decisions
- someone is identified to own smoke testing, runtime support, and rollback on the host

## What The Engineer Can Do Once Engaged
- verify host prerequisites, service paths, `nvidia-smi`, and systemd access
- install or standardize the analyzer, `vLLM`, `LiteLLM`, and optional KB components
- align runtime values and validate that the stack agrees on the `gpt-oss-120b` contract
- run health checks, a chat completion smoke test, and a known-good file-drop test
- verify logs, report generation, and if enabled the Splunk writeback path
- hand off rerun and rollback commands, paths, and values

## What May Still Depend On The Customer
- final approval of the host, GPU profile, and runtime stack
- staging or transfer of `gpt-oss-120b` artifacts if they are not yet present
- issuance, storage, rotation, and access review for the `LiteLLM` master key
- issuance and governance of the Splunk REST API token if Splunk writeback is enabled
- confirmation from the Splunk owner that endpoint and writeback identifier mapping are correct
- approval of loopback-only versus broader exposure if the org wants anything other than the local-host control-plane pattern
- customer ownership of KB source content and rebuild decisions if RAG is enabled

## Most Common Blockers
- `gpt-oss-120b` artifacts are not yet staged
- GPU driver/runtime or CUDA compatibility is not yet validated for `vllm==0.14.1`
- runtime values are not aligned between `vLLM`, `LiteLLM`, and the analyzer
- there is no settled owner for the `LiteLLM` master key or Splunk writeback token
- the KB / RAG decision is still unresolved
- the org has not yet decided between connected-host and air-gapped delivery

## Status Language
- `Ready`: all five readiness buckets are already answered
- `Ready with dependencies`: the path is mostly clear, but one or more approvals, staging tasks, or credential/governance steps are still pending
- `Not ready`: major questions remain in host/platform, runtime, artifacts, security/integration, or ownership

## Next Document
See `AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_ASSESSMENT.md` for the detailed assessment.
