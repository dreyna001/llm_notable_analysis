# Operations Runbook

Operational reference for deployment health, observability, scripts, testing,
troubleshooting, and supply-chain controls.

## Preconditions

- Endpoint is reachable and healthy.
- App environment contains required `LLM_*` keys.
- SDK version is pinned per deployment.

## Health checks

```bash
curl -sSf http://127.0.0.1:8000/health
python -c "import onprem_llm_sdk; print(onprem_llm_sdk.__version__)"
```

## Observability contract

### SDK log events

`onprem-llm-sdk` emits one JSON line per event.

- `llm_request_success`
  - fields: `timestamp`, `event`, `app_name`, `correlation_id`, `attempts`, `latency_seconds`, `status_code`
- `llm_request_failure`
  - fields: `timestamp`, `event`, `app_name`, `correlation_id`, `attempts`, `latency_seconds`, `status_code`, `error_type`

Failure semantics:

- `status_code=0` means timeout/transport path (no HTTP response).
- current `error_type` set includes:
  - `timeout`
  - `transport`
  - `response_json`
  - `RateLimitError`
  - `ServerError`
  - `ClientRequestError`

### Metrics callback contract

SDK does not ship a backend; it calls sink methods:

- `record_inflight(app_name, inflight)`
  - called after acquire/release
  - `inflight` expected range: `0..LLM_MAX_INFLIGHT`
- `record_request_result(app_name, success, status_code, attempts, latency_seconds, error_type="")`
  - called once per terminal request outcome
  - `status_code=0` on timeout/transport path
  - `error_type` empty on success

### Recommended metric names

- `onprem_llm_sdk_inflight_requests` (gauge)
- `onprem_llm_sdk_requests_total` (counter)
- `onprem_llm_sdk_request_latency_seconds` (histogram)
- `onprem_llm_sdk_request_attempts` (histogram)

Cardinality guidance:

- keep `app_name` bounded and stable
- do not use `correlation_id` as a metric tag
- keep `error_type` to SDK enum values

## Script reference

| Script | Purpose | Typical usage |
| --- | --- | --- |
| `scripts/build_offline_bundle.sh` | Build offline bundle with wheelhouse + checksums | `bash scripts/build_offline_bundle.sh` |
| `scripts/verify_bundle.sh` | Verify extracted bundle integrity | `bash scripts/verify_bundle.sh [BUNDLE_DIR]` |
| `scripts/install_from_bundle.sh` | Install from local wheelhouse only | `bash scripts/install_from_bundle.sh [BUNDLE_DIR] [VENV_DIR] [VERSION]` |
| `scripts/smoke_test_install.sh` | Verify import and optional endpoint health | `bash scripts/smoke_test_install.sh [VENV_DIR]` |

Recommended air-gap sequence:

1. `verify_bundle.sh`
2. `install_from_bundle.sh`
3. `smoke_test_install.sh`

## Testing

Run from `onprem-llm-sdk/`.

`unittest` (default):

```bash
PYTHONPATH=src python -m unittest discover -s tests -p "test*.py" -v
```

PowerShell:

```powershell
$env:PYTHONPATH='src'; python -m unittest discover -s tests -p "test*.py" -v
```

`pytest` (optional):

```bash
PYTHONPATH=src pytest -q
```

## Common failure modes

| Symptom | Likely cause | Action |
|---|---|---|
| `RequestTimeoutError` spikes | model overloaded or long generations | reduce inflight, increase read timeout, tune max tokens |
| `RateLimitError` | endpoint pressure | reduce caller concurrency, stagger batch jobs |
| `ClientRequestError` | payload or model mismatch | validate model name and request data |
| `ResponseFormatError` | response schema drift | inspect raw response and update parser/contract tests |
| install fails in air gap | missing wheel or bad checksum | rebuild bundle and verify manifest |

## Rollback steps

1. Keep previous bundle available on host.
2. Reinstall prior version pin from prior wheelhouse.
3. Restart application service.
4. Confirm import version and endpoint health.

## Security and supply-chain controls

### Core controls

- bundle integrity checks via `SHA256SUMS`
- offline install via `pip --no-index`
- pinned SDK version per app deployment
- credentials injected via environment, not source code

### Recommended hardening

- sign release bundles with approved internal tooling
- preserve build logs and SBOM data where required
- apply least-privilege access to artifact and env file paths
- restrict who can publish and transfer bundles

### Out of SDK scope

- enclave compliance enforcement
- malware scanning of model artifacts
- host/network policy enforcement

## Evidence retention

- Keep bundle hash manifests.
- Keep release changelog and install logs.
- Keep service logs around rollout windows.

