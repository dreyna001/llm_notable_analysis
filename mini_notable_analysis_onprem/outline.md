# Mini Notable Analysis On-Prem Requirements (CPU-Only)

## 1) Goal

Deliver a production-usable, single-host, on-prem LLM inference path for cybersecurity triage on hardware with:

- 12 vCPU
- 48 GB RAM
- 1 TB SSD
- no GPU

The service must provide deterministic-enough, schema-valid JSON outputs for downstream automation while remaining simple to operate.

## 2) Facts, Inferences, and Unknowns

### Facts (direct evidence)

- Host has no GPU.
- Current design target is a local inference service with OpenAI-compatible API semantics.
- Workload is cyber incident/log triage with structured outputs.

### Inferences (design choices)

- `llama.cpp` is preferred over `vLLM` for this CPU-only profile.
- Concurrency must remain low to control tail latency.
- Context size must be bounded to avoid memory and latency blowups.

### Unknowns (must be resolved for production)

- Required p95 latency SLO for priority use-cases.
- Required monthly availability target.
- Final retention period for prompt/response audit records.
- Whether remote callers are ever allowed (vs local-only forever).

## 3) Architecture Decision

### ADR-001 Runtime

- **MUST** run a single local `llama-server` process (`llama.cpp`) on the host.
- **MUST** expose OpenAI-compatible chat completions endpoint for application integration.
- **MUST** keep model artifacts on local SSD.

Rationale: smallest operational surface for a CPU-only deployment.

## 4) Scope

### In Scope

- Local inference service lifecycle (install, run, restart, observe).
- Structured prompt/response flow for cyber triage.
- Security baseline for local endpoint usage.
- Operational runbook requirements.

### Out of Scope

- Multi-node inference clustering.
- GPU scheduling/tuning.
- Exactly-once request completion guarantees.
- Full SIEM pipeline design and data normalization internals.

## 5) Functional Requirements

### API and Request/Response Contract

- **FR-001**: Service **MUST** expose `POST /v1/chat/completions`.
- **FR-002**: Service **MUST** expose readiness endpoint `GET /health`.
- **FR-003**: Service **MUST** expose metrics endpoint `GET /metrics`.
- **FR-004**: Service **MUST** expose slot/queue visibility endpoint `GET /slots`.
- **FR-005**: Inference calls **MUST** use JSON schema constrained output (`response_format` + schema).
- **FR-006**: Application **MUST** reject model output that fails JSON schema validation.

### Prompting and Inference Behavior

- **FR-007**: System prompt **MUST** require "JSON only" responses.
- **FR-008**: Requests **MUST** set bounded generation (`max_tokens`) and low randomness defaults.
- **FR-009**: Input payload **MUST** be pre-normalized and compacted before model invocation into a canonical incident bundle containing at minimum: alert metadata, top contributing events, extracted entities, compact timeline, counts/stats/notable fields, and optional candidate ATT&CK techniques.

### Error Handling

- **FR-010**: Caller **MUST** implement bounded retries with backoff for transient inference failures.
- **FR-011**: Caller **MUST** use per-request timeout and classify timeout as retryable failure.
- **FR-012**: On final failure, system **MUST** emit structured failure record with reason code.

### Canonical Triage Output Schema

- **FR-013**: Canonical triage output schema **MUST** be an object with `additionalProperties: false` and required fields:
  - `summary`: string
  - `severity`: enum [`low`, `medium`, `high`, `critical`]
  - `likely_disposition`: enum [`true_positive`, `false_positive`, `needs_investigation`]
  - `confidence`: number in range [0, 1]
  - `entities`: array of strings
  - `mitre_attack`: array of strings
  - `recommended_next_steps`: array of strings

## 6) Non-Functional Requirements

### Performance and Capacity

- **NFR-001**: Baseline concurrency target **MUST** be 2 parallel requests max.
- **NFR-002**: Context window **MUST** default to 8192 tokens max.
- **NFR-003**: Service **SHOULD** keep p95 latency <= 12s for standard triage requests (provisional baseline, pending final SLO sign-off and load test validation).
- **NFR-004**: Service **SHOULD** sustain at least 2 requests/min under baseline load without restart loops.

### Resource Constraints

- **NFR-005**: Model + runtime + cache **MUST** fit within host RAM with safety margin (no swap thrash).
- **NFR-006**: Host CPU saturation **SHOULD** avoid sustained 100% across all cores under normal profile.

### Availability

- **NFR-007**: Service **MUST** auto-restart on failure via systemd.
- **NFR-008**: During restart/model load windows, callers **MUST** degrade gracefully via retry policy.

## 7) Security Requirements

- **SEC-001**: Service **MUST** bind to `127.0.0.1` by default.
- **SEC-002**: Service **MUST** require API key authentication for inference endpoints even for local calls. Health probes **MAY** be unauthenticated and **MUST NOT** expose sensitive internals.
- **SEC-003**: Web UI **MUST** be disabled.
- **SEC-004**: Runtime process **MUST** run as dedicated non-privileged service account.
- **SEC-005**: systemd hardening flags **MUST** be enabled (no new privileges, capability drop, home/tmp protections).
- **SEC-006**: Prompt/response logging **MUST** redact sensitive tokens/secrets where policy requires.
- **SEC-007**: If remote exposure is enabled, deployment **MUST** add TLS + network ACLs + auth controls.

## 8) Observability and Audit Requirements

- **OBS-001**: Logs **MUST** be structured and include request id, latency, token counts, status, and error code. The caller or service layer **MUST** generate and propagate a correlation id per request.
- **OBS-002**: Metrics **MUST** include request count, error count, retry count, and latency histogram.
- **OBS-003**: Audit trail **MUST** persist prompt metadata, response metadata, model id, and schema validation result.
- **OBS-004**: Health behavior **MUST** be documented and distinguish process-up vs model-ready states during startup/restart windows when possible.

## 9) Recovery and Responsibility Boundaries

- **REL-001**: In-flight requests may fail during restart; clients **MUST** retry within bounded limits.
- **REL-002**: System **MUST NOT** claim checkpoint/replay or exactly-once inference semantics.
- **REL-003**: Operators **MUST** verify health, logs, and one real completion after install or upgrade.
- **REL-004**: Rollback path **MUST** support reverting to prior known-good runtime and model config.

## 10) Configuration Requirements

All operationally relevant values **MUST** be externally configurable (environment variables or service config), including:

- model path/name
- host/port
- thread/thread-batch
- parallel slots
- context size
- cache quantization
- continuous batching enable/disable
- mmap and mlock behavior
- jinja/template mode
- reasoning mode
- default `temperature` and `top_p`
- default `max_tokens`
- API key file path
- timeout/retry settings
- log level

Magic strings **MUST NOT** be hardcoded in application logic where config is expected.

## 11) Baseline Runtime Profile (Initial Defaults)

These are starting defaults, not permanent guarantees:

- Runtime: `llama.cpp` (`llama-server`)
- Model: `Qwen3.5-4B-Q4_K_M.gguf`
- Host/port: `127.0.0.1:8080`
- Threads: `10`
- Threads batch: `12`
- Parallel slots: `2`
- Context size: `8192`
- KV cache type K/V: `q8_0`
- Continuous batching: enabled
- mmap: enabled
- mlock: enabled where supported by host limits/policy
- Jinja/template mode: enabled
- Reasoning mode: off
- Default temperature: `0.1`
- Default top_p: `0.9`
- Default max_tokens: `700`
- Web UI: disabled
- Metrics: enabled
- API key file: required

## 12) Acceptance Test Criteria

- **TST-001**: Service starts under systemd and reports healthy on `GET /health`.
- **TST-002**: Valid schema-constrained request returns schema-valid JSON.
- **TST-003**: Invalid or malformed output path is detected and rejected by caller validator.
- **TST-004**: Restart test confirms caller retries and eventual success or failure classification.
- **TST-005**: Unauthorized inference call without API key is rejected.
- **TST-006**: Metrics endpoint emits request/error/latency metrics after test traffic.
- **TST-007**: Load test at concurrency=2 for 15 minutes completes without crash loop.
- **TST-008**: Canonical triage schema contract test validates required fields, enums, `confidence` range, and `additionalProperties: false`.
- **TST-009**: Health behavior test validates documented startup semantics (process-up vs model-ready) during model load and restart windows.

## 13) Non-Goals

- Running large model families that require GPU acceleration.
- Serving arbitrary freeform chat UX traffic.
- Exposing public internet endpoint directly from inference process.

## 14) Open Decisions Before Production Sign-Off

1. Final p95 latency SLO and error budget.
2. Final retention policy for prompt/response artifacts.
3. Approved model provenance and checksum workflow.
4. Whether any remote consumer hosts are permitted.
5. Incident severity taxonomy and confidence calibration policy.
