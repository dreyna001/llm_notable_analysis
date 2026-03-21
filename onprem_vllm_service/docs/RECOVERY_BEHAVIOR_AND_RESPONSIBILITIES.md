# Recovery Behavior and Responsibilities

This document defines expected recovery behavior for the standalone `vllm` systemd service.

## Scope

- Service runtime: `systemd/vllm.service`
- Installation lifecycle: `install_vllm.sh`
- Endpoint: local OpenAI-compatible HTTP server on configured host/port

## Recovery behavior matrix

### 1) Graceful service restart (`systemctl restart vllm`)

- systemd sends `SIGTERM` (per unit) and starts service again.
- In-flight inference requests may be interrupted.
- Clients should treat restart windows as transient failures and retry at caller level.

### 2) Host reboot while service healthy

- If enabled, service is started by systemd at boot.
- Model is loaded again on startup; readiness depends on model size and host resources.
- `/health` may remain unavailable during model load.

### 3) Power loss or hard crash during inference

- No request-level checkpoint/replay exists in this package.
- Partially served requests are not resumed.
- Clients must resend requests after service recovery.

### 4) Startup with missing model artifacts

- Installer skips auto-start when `<model_path>/config.json` is absent.
- If service is started manually without valid model path, startup fails and logs explain why.

### 5) Existing systemd drop-ins conflict with installed unit

- Drop-ins can override command flags and cause drift.
- Installer warns when drop-ins exist.
- Setting `VLLM_RESET_OVERRIDES=true` removes drop-ins during install.

## Responsibility boundaries

- **This package guarantees**
  - deterministic install flow for vLLM user/venv/unit baseline
  - unit patching for install path, model path, host/port, and GPU utilization
  - best-effort health wait after start
- **This package does not guarantee**
  - exactly-once inference completion across restarts
  - request persistence/checkpointing
  - downstream client retry behavior
  - model artifact distribution/provenance workflow
- **Operator responsibilities**
  - provide valid model artifacts
  - verify post-change health and logs
  - manage rollback pin and release approval
  - monitor restart loops and GPU memory pressure

## Practical implication for consumers

Any application consuming this local endpoint should implement bounded retries and timeouts because service restarts and model-load windows are expected operational events.

