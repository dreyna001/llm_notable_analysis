# On-Prem Readiness Assessment

This is the detailed readiness assessment for the on-prem notable analysis stack.

Use `AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_OVERVIEW.md` as the front-door summary. Use this document when you need the full technical rationale, host and runtime assumptions, and integration framing.

## What Ready Looks Like
For the on-prem notable analysis stack, readiness means an org can take the package, provide a small number of environment-specific values, stage approved model artifacts, run one documented deployment path, and get to a successful end-to-end test without opening code or designing the runtime from scratch during deployment.

This readiness view assumes the host-native GPU deployment shape represented in this repo:

- analyzer service from `llm_notable_analysis_onprem_systemd/`
- `vLLM` serving `gpt-oss-120b` on `127.0.0.1:8000`
- `LiteLLM` acting as the caller-facing proxy on `127.0.0.1:4000`
- optional KB indexer from `onprem_setup_GLAB/`

An org is genuinely ready for this deployment when all of this is already true:

- it has a target Linux host chosen for the service, with ownership for the host and GPU
- it has an NVIDIA RTX PRO 6000 (96 GB) or greater, with driver and runtime compatibility for this project's pinned `vllm==0.14.1` deployment shape
- it knows whether the deployment is connected or air-gapped, and it already knows how artifacts from the internet get onto the host
- it has approved `gpt-oss-120b` model artifacts staged or an approved process to stage them
- it has decided that either `LiteLLM` is the control plane for callers or callers will point directly to `vLLM`
- it has an operator who owns `systemd`, logs, smoke tests, and rollback on the host
- if Splunk writeback is enabled, it has a Splunk REST API token that has read and write access to notables
- it knows whether RAG / KB grounding is enabled and, if so, already has a rebuild and content ownership process

If those decisions are still undecided, the org is not deployment-ready even if it already has a server.

## Practical Readiness Checklist

### 1. Host And Platform Readiness
They need:

- a supported Linux host with `systemd`
- Python 3.12 available for the analyzer and `vLLM` runtime paths
- a recommended compute baseline of an Intel Xeon Gold-class server CPU (or equivalent), with `128 GB` of server-grade ECC RAM (`DDR5` if the approved platform supports it; otherwise equivalent ECC server RAM); `256 GB` is better if the org wants more headroom for KB, concurrency, and host responsiveness
- root or equivalent admin access for service install, users, directories, and unit management
- enough local storage for the repo, Python environments, logs, reports, and the `gpt-oss-120b` model tree: `500 GB` NVMe is the documented minimum, but `1 TB NVMe` is the practical baseline because the model tree alone is very large and the repo, venvs, logs, and report paths add additional headroom requirements
- a clear decision on connected-host versus offline or transfer-bundle workflow

This matches the host-native deployment material in `llm_notable_analysis_onprem_systemd/INSTALL.md` and `onprem_setup_GLAB/HOST_DEPLOY_GLAB.md`.

### 2. GPU And Inference Readiness
This is the biggest hidden blocker.

They need:

- NVIDIA driver installed and healthy on the host, with `nvidia-smi` working cleanly
- a CUDA stack compatible with the staged `vllm==0.14.1` wheel, the target Linux and Python 3.12 environment, and the approved GPU profile
- confirmation that the target GPU profile is approved for `gpt-oss-120b`
- `vLLM` installed in the expected runtime path and able to start
- a clear served model name, with analyzer and proxy config aligned to it

For this package, inference readiness must be explicit, because the stack only works when these values agree:

- `vLLM` serves `gpt-oss-120b`
- `LiteLLM` maps callers to that same upstream model
- the analyzer sends `LLM_MODEL_NAME=gpt-oss-120b`

If the GPU, model path, or served model name differs from what operators configure, services may start but runtime will fail.

### 3. Artifact And Packaging Readiness
For low-friction deployment, the org should not have to invent how runtime artifacts appear on the host.

Right now, the package still assumes they can resolve:

- how `vLLM` wheels and dependencies get to the target
- how `LiteLLM` and related Python packages get installed
- how `gpt-oss-120b` model weights get staged under the expected host path
- how optional KB artifacts get staged or rebuilt

That is a readiness dependency, because the repo does not contain the model weights and many environments will need either a connected-host install path or an offline transfer bundle. If the org does not already know how it will stage wheels, model artifacts, and service configs onto the host, it is not truly ready to deploy.

### 4. Runtime Contract Readiness
The org needs to understand exactly what the on-prem stack expects and produces.

They should already agree on:

- the analyzer ingests files from the configured incoming directory
- one dropped object or file equals one analysis run
- `.json` and `.txt` are both valid input forms
- processed outputs land in the reports directory
- if Splunk writeback is enabled, the filename stem becomes the writeback identifier
- if `LiteLLM` is the intended control plane, application traffic goes to `127.0.0.1:4000`, not directly to `vLLM` on `8000`

For the GPU + `gpt-oss-120b` + `LiteLLM` profile, the critical runtime alignment is:

- `LLM_API_URL=http://127.0.0.1:4000/v1/chat/completions`
- `LLM_MODEL_NAME=gpt-oss-120b`
- `LLM_API_TOKEN` equals the `LiteLLM` master key

If operators cannot state those values clearly, they are not ready.

### 5. Secrets And External Integration Readiness
If they want anything beyond local file-to-report generation, they need the surrounding integration prepared before go-live.

For the `LiteLLM` layer:

- a strong `LiteLLM` master key is set in `/etc/litellm/config.yaml`
- the analyzer has the matching `LLM_API_TOKEN`
- loopback-only exposure is preserved unless a deliberate edge pattern is approved

For Splunk writeback:

- `SPLUNK_SINK_ENABLED=true` only when the feature is intentionally enabled
- `SPLUNK_BASE_URL` is correct for the target Splunk deployment
- `SPLUNK_API_TOKEN` is approved and has the right write scope
- the team has confirmed the endpoint path and identifier mapping with the Splunk owner

If they do not already know where these secrets live, who rotates them, and how they are injected into `config.env` or host-owned config, they are not ready.

### 6. Knowledge Base And RAG Readiness
If they want retrieval grounding, they need the KB process prepared before deployment.

They need:

- a clear decision whether `RAG_ENABLED` is on
- a staged embedding model if the environment is offline
- known paths for `kb.sqlite3` and `kb.faiss`
- someone responsible for KB source content and rebuild cadence

If none of that is decided, RAG should stay off.

### 7. Operational Readiness
A low-issue deployment also requires basic day-2 readiness:

- someone knows to check the systemd journal for `vllm`, `litellm`, `notable-analyzer`, and if KB is enabled `kb-rebuild.service` / `kb-rebuild.timer`
- someone can run a health check against `127.0.0.1:8000/health`
- someone can run a chat completion smoke test through `LiteLLM`
- someone can drop a known-good notable file and verify a report is produced
- someone can tell the difference between GPU/runtime failure, proxy auth failure, and analyzer failure
- there is a rollback path for Python envs, service units, config files, and model or image tags where applicable

Without this, install may succeed but the org will still feel blocked.

## The Real "Green State"
For the on-prem GPU notable analysis stack, an org is in true green status when it can answer these questions immediately:

1. What exact host or host class is this going onto?
2. What GPU, driver, and CUDA/runtime combination is approved there?
3. Do we have the full `gpt-oss-120b` model tree staged and verified?
4. What exact `vLLM` served model name are we using?
5. Is the analyzer pointed at `LiteLLM` on `127.0.0.1:4000` or directly at `vLLM`?
6. What is the `LiteLLM` master key and where is it stored?
7. Are Splunk writeback and RAG enabled or intentionally off?
8. Where do the incoming, processed, quarantine, reports, and archive paths live on disk?
9. Who owns smoke testing, service restart, and host-level troubleshooting?
10. What is the rollback plan if the model, proxy, or analyzer update breaks the stack?

If they cannot answer those without a workshop, they are not ready for low-friction deployment.

## How To Think About Engineer-Led Integration
This section does not add new requirements. It reorganizes the same readiness points above into three buckets: what must already be true before engineer-led work starts, what an engineer can execute once access is available, and what may still require customer or external-team action during the work.

### 1. What Must Be True Before Engineer-Led Integration Starts
- the target Linux host is chosen and the org knows who owns the host and GPU
- the deployment model is decided: connected host or air-gapped / transfer-bundle workflow
- the host has the expected platform baseline: `systemd`, Python 3.12, root/admin access, recommended CPU/RAM, and enough storage for the repo, runtime files, and the `gpt-oss-120b` model tree
- the approved GPU profile is chosen, with NVIDIA driver health and CUDA/runtime compatibility for this pinned `vllm==0.14.1` deployment shape
- the org has already decided whether callers will use `LiteLLM` or go directly to `vLLM`
- the full `gpt-oss-120b` model tree is staged, or there is an approved and understood process to stage it
- if Splunk writeback is in scope, the team already has the correct endpoint and a Splunk REST API token with the needed rights
- if RAG is in scope, the team already knows where KB artifacts come from and who owns rebuild cadence
- someone is identified to own smoke testing, runtime support, and rollback on the host

### 2. What An Engineer Can Do Once Access Is Available
- verify host prerequisites such as Python, storage, `nvidia-smi`, service paths, and systemd access
- install or standardize the analyzer, `vLLM`, `LiteLLM`, and optional KB components along the documented on-prem path
- align runtime values such as `LLM_API_URL`, `LLM_MODEL_NAME`, `LLM_API_TOKEN`, and the served model name
- validate that `vLLM`, `LiteLLM`, and the analyzer agree on the `gpt-oss-120b` runtime contract
- check the systemd journal for `vllm`, `litellm`, `notable-analyzer`, and if enabled the KB units
- run health checks, a chat completion smoke test, and a known-good file-drop test
- verify report generation and, if enabled, Splunk writeback behavior
- document or hand off the exact commands, paths, and values needed for rerun and rollback

### 3. What May Still Require Customer Or External-Team Action During Integration
- final approval of the target host, GPU profile, and runtime stack if those are still under review
- staging or transfer of the `gpt-oss-120b` model artifacts if they are not yet present on the host
- issuance, storage, rotation, and access review for the `LiteLLM` master key
- issuance and governance of the Splunk REST API token if Splunk writeback is enabled
- confirmation from the Splunk owner that the endpoint path and writeback identifier mapping are correct
- approval of loopback-only versus broader exposure if the org wants anything other than the local-host control-plane pattern
- customer ownership of KB source content and rebuild decisions if RAG is enabled

## Current Package Friction
For this on-prem stack specifically, these are the main sources of deployment friction today:

- the base `llm_notable_analysis_onprem_systemd/config.env.example` still defaults to a direct local endpoint and a non-`gpt-oss-120b` model value, so a `LiteLLM` + `gpt-oss-120b` deployment still requires operator edits
- the host-native GLAB path is documented, but it is not a single one-command installer for analyzer + `vLLM` + `LiteLLM` + KB together
- `gpt-oss-120b` model artifacts are not in the repo and are a major staging dependency
- `LiteLLM` master key creation and downstream analyzer token alignment are still operator-managed, not standardized by one shared install path
- Splunk writeback is implemented, but customers still need to supply and govern the right REST endpoint, token, and identifier mapping

