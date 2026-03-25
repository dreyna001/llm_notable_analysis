# On-Prem `llama.cpp` Endpoint Service Requirements (CPU-Only, PoC)

## 1) Goal

Define requirements for a standalone on-prem endpoint service package, analogous to `onprem_vllm_service`, implemented with `llama.cpp` (`llama-server`) for CPU-only deployment.

This package is for a proof of concept and provides one shared local endpoint for a single local consumer service on the same host.

## 2) Scope

### In Scope

- `llama.cpp` runtime installation and lifecycle management.
- Service account, systemd unit, startup, and restart behavior.
- Local endpoint exposure and baseline hardening for loopback-only operation.
- Runtime configuration through install-time variables or environment.
- Operations documentation for install, startup, troubleshooting, and recovery expectations.
- Health and metrics requirements for endpoint operations.

### Out of Scope

- Application-specific prompts and business logic.
- Application-specific response schemas and downstream workflows.
- SIEM internals, enrichment logic, and storage design.
- Multi-host distributed inference or cluster scheduling.
- Remote endpoint exposure, TLS termination, reverse proxies, and external auth layers.
- Multi-model serving.
- Multi-consumer fairness or quality-of-service guarantees.

## 3) Service Model

- **SM-001**: Deployment model **MUST** be single-host.
- **SM-002**: Endpoint **MUST** default to local-only access (`127.0.0.1`).
- **SM-003**: Package **MUST** support one local consumer service on the same host.
- **SM-004**: Runtime **MUST** be `llama.cpp` (`llama-server`).
- **SM-005**: Service instance **MUST** load and serve exactly one configured GGUF model artifact.
- **SM-006**: Model path **MUST** default to the pinned GGUF artifact in this document and **MAY** be overridden via `LLAMA_MODEL_PATH` for controlled PoC testing.
- **SM-007**: Endpoint compatibility scope **MUST** be OpenAI-compatible `POST /v1/chat/completions` only for inference.

## 4) Functional Requirements

### Installation and Packaging

- **FR-001**: Package **MUST** provide an installer script for install and re-install.
- **FR-002**: Installer **MUST** create or validate a dedicated non-login service account.
- **FR-003**: Installer **MUST** install or update a systemd unit for `llama-server`.
- **FR-004**: Installer **MUST** support install-only mode (no auto-start).
- **FR-005**: Installer **MUST** support idempotent re-runs for configuration changes and re-installation.
- **FR-006**: Installer or startup preflight **MUST** validate critical configuration inputs and fail with actionable errors when invalid.

### Endpoint Contract

- **FR-007**: Service **MUST** expose `POST /v1/chat/completions`.
- **FR-008**: Service **MUST** expose `GET /health`.
- **FR-009**: Service **MUST** expose `GET /metrics`.
- **FR-010**: Service **MUST** return machine-parseable errors for invalid requests and runtime failures.

### Runtime Behavior

- **FR-011**: Service **MUST** serve the pinned default model artifact unless `LLAMA_MODEL_PATH` explicitly overrides it.
- **FR-012**: Service **MUST** run under systemd with restart-on-failure policy.
- **FR-013**: Service **MUST** emit actionable startup errors when model files, permissions, or runtime arguments are invalid.
- **FR-014**: Service **MUST** fail fast if the configured model path is missing, unreadable, or invalid.
- **FR-015**: Service **MUST NOT** report healthy until model load is complete and inference requests can be accepted.

## 5) Non-Functional Requirements

### Performance and Resource Controls

- **NFR-001**: Runtime **MUST** support bounded concurrency controls for CPU-only operation.
- **NFR-002**: Runtime **MUST** support bounded context and generation limits.
- **NFR-003**: Runtime **SHOULD** use deterministic-friendly inference defaults for automation workloads.
- **NFR-004**: Service **MUST** avoid unbounded memory growth under sustained local traffic.
- **NFR-005**: Service **MUST** support configurable bounds for request input size, output token generation, and inference timeout.

### Availability and Operability

- **NFR-006**: Service **MUST** auto-recover from crashes via systemd policy.
- **NFR-007**: Health semantics during startup and model-load windows **MUST** be documented.
- **NFR-008**: Startup timeout behavior **MUST** be configurable and documented.

## 6) Security Requirements

- **SEC-001**: Service **MUST** bind to loopback by default.
- **SEC-002**: Runtime process **MUST** run as a dedicated non-privileged account.
- **SEC-003**: systemd hardening baseline **SHOULD** include no-new-privileges and dropped capabilities for PoC where it does not block startup.

## 7) Observability Requirements

- **OBS-001**: Logs **MUST** support operational triage, including timestamp, level, component, message, and failure cause where available.
- **OBS-002**: Logs **MUST** be accessible via `journalctl`.
- **OBS-003**: Metrics endpoint **MUST** be enabled.

## 8) Recovery and Responsibilities

- **REL-001**: In-flight requests may fail during restart or host reboot; this behavior **MUST** be documented.
- **REL-002**: Package **MUST NOT** claim checkpoint, replay, or exactly-once inference semantics.
- **REL-003**: Operators **MUST** validate health and at least one real inference after install or re-install.
- **REL-004**: Client retry and backoff behavior is a consumer responsibility and **MUST** be documented.

## 9) Configuration Requirements

All operationally relevant values **MUST** be externally configurable, including:

- install paths (service name fixed to `llamacpp` for this PoC)
- host and port
- threads
- batch threads
- parallel slots
- context size
- maximum input tokens
- default output token limit
- hard output token ceiling
- inference timeout
- HTTP timeout
- cache behavior and feature flags (`mmap`, `mlock`, KV cache type)
- startup timeout and health wait window
- log level

Environment-specific paths and magic strings **MUST NOT** be hardcoded in service logic.

## 10) Baseline Profile (Initial Defaults)

These defaults are initial PoC deployment defaults and **NOT** final production commitments:

- runtime: `llama.cpp` (`llama-server`)
- pinned runtime baseline: `b8457` / `149b249`
- deployment: single host
- consumer model: one local consumer service
- service name: `llamacpp`
- bind: `127.0.0.1`
- process manager: systemd
- hardware target: CPU-only (Intel Xeon Gold, 12 vCPU, 48 GB RAM, no GPU)
- model default repo: `Qwen/Qwen3-4B-GGUF`
- model default filename: `Qwen3-4B-Q4_K_M.gguf`
- model default revision (pinned): `a9a60d009fa7ff9606305047c2bf77ac25dbec49`
- model default SHA256 (pinned): `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`
- model default size: `2497280256` bytes
- model source URL (pinned): `https://huggingface.co/Qwen/Qwen3-4B-GGUF/blob/a9a60d009fa7ff9606305047c2bf77ac25dbec49/Qwen3-4B-Q4_K_M.gguf`
- model raw pointer URL (pinned): `https://huggingface.co/Qwen/Qwen3-4B-GGUF/raw/a9a60d009fa7ff9606305047c2bf77ac25dbec49/Qwen3-4B-Q4_K_M.gguf`
- override path: `LLAMA_MODEL_PATH` (optional for controlled PoC testing)
- authentication: none
- observability: health checks, journal logs, metrics
- inference surface: `POST /v1/chat/completions` only
- threads: `10`
- batch threads: `12`
- parallel slots: `1`
- context size: `8192`
- maximum input tokens: `3072`
- default output token limit: `384`
- hard output token ceiling: `512`
- inference timeout: `120s`
- HTTP timeout: `180s`
- KV cache type (K): `q8_0`
- KV cache type (V): `q8_0`
- continuous batching: enabled
- `mmap`: enabled
- `mlock`: disabled by default for PoC unless explicitly validated on host

## 11) Acceptance Tests

- **TST-001**: Installer completes on a clean host and creates expected artifacts such as user, unit, and paths.
- **TST-002**: Service starts and reports healthy on the configured health endpoint only after model load is complete.
- **TST-003**: Valid `POST /v1/chat/completions` request succeeds.
- **TST-004**: Invalid request returns a machine-parseable error response.
- **TST-005**: Restart and reboot behavior matches documented recovery expectations.
- **TST-006**: Metrics endpoint is reachable locally after successful startup.

Nice-to-have tests (post-PoC hardening):

- Requests exceeding maximum input token bounds are rejected or bounded per documented behavior.
- Requests exceeding output token or timeout bounds are rejected or terminated per documented behavior.

## 12) Documentation Deliverables

Package **MUST** include:

- `README.md` for quick start and install options
- `docs/TROUBLESHOOTING.md`

Post-PoC docs:

- `docs/OPERATIONS_RUNBOOK.md`
- `docs/SECURITY_POSTURE.md`

## 13) Implementation File Inventory (PoC)

The PoC implementation **MUST** create exactly the following repository files:

- `onprem_qwen3_sudo_llamacpp_service/README.md`
- `onprem_qwen3_sudo_llamacpp_service/install_llamacpp.sh`
- `onprem_qwen3_sudo_llamacpp_service/systemd/llamacpp.service`
- `onprem_qwen3_sudo_llamacpp_service/config/llamacpp.env.example`
- `onprem_qwen3_sudo_llamacpp_service/docs/TROUBLESHOOTING.md`

Optional local validation artifact (not part of package source and **MUST NOT** be committed):

- `onprem_qwen3_sudo_llamacpp_service/model_cache/Qwen3-4B-Q4_K_M.gguf`

The installer/runtime **MUST** create or manage the following host artifacts:

- `/etc/systemd/system/llamacpp.service`
- `/etc/llamacpp/llamacpp.env`
- `/usr/local/bin/llama-server` (or documented equivalent install path)
- `/opt/llamacpp/models/` (default model directory)
- system user and group `llamacpp`

Any additional created file outside this list **MUST** be explicitly documented in this section before implementation is considered complete.

## 14) Open Decisions Before Implementation Lock

No blocking open decisions remain for PoC implementation.

[1]: https://github.com/ggml-org/llama.cpp/releases "Releases · ggml-org/llama.cpp · GitHub"
