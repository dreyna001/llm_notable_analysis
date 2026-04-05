# Recovery Behavior and Responsibilities

What to expect during failures and restarts for the standalone `vllm` service.

## Expected behavior

| Event | What happens | What clients should do |
| --- | --- | --- |
| `systemctl restart vllm` | Service stops and starts again; in-flight requests can fail | Retry with bounded retries + backoff |
| Host reboot | Service comes back if enabled; model loads again before ready | Treat startup window as transient unavailability |
| Power loss / hard crash | No request replay or checkpoint restore | Resend failed requests after recovery |
| Missing model files at install | Installer skips auto-start if `config.json` is missing | Provide artifacts, then start service |
| Unit override drift | Drop-ins can change runtime flags unexpectedly | Reinstall with `VLLM_RESET_OVERRIDES=true` |

## Responsibility boundaries

### Package provides

- repeatable install flow for service user, venv, and unit
- unit patching from installer flags (model path, served name, host, port, GPU target)
- best-effort health wait after start

### Package does not provide

- request persistence across crashes/restarts
- exactly-once inference completion
- client retry behavior
- artifact distribution/provenance workflow

### Operator must provide

- valid model artifacts and readable permissions
- post-change verification (`systemctl`, `/health`, smoke inference)
- version pinning and rollback decisions
- monitoring for restart loops and GPU memory issues

## Consumer requirement

Any service calling this endpoint should implement timeouts and bounded retries because restart/model-load windows are normal operational events.

