# Observability Contract

This document defines observability behavior for `onprem-llm-sdk` version `0.1.0`.

It is split into:

1. **Runtime guarantees** (what SDK code emits/calls today).
2. **Canonical metric conventions** (recommended names/tags/units for consumers).

## Runtime Guarantees

### Structured Logging

SDK logging is emitted through `log_event(...)`, which writes one JSON object per event.

Guaranteed base fields on every SDK event:

- `timestamp` (`string`, UTC ISO-8601 from `datetime.now(timezone.utc).isoformat()`).
- `event` (`string`, event name).

### Event: `llm_request_success`

Emitted on successful completion response.

Fields:

- `timestamp` (`string`)
- `event` = `llm_request_success`
- `app_name` (`string`)
- `correlation_id` (`string`)
- `attempts` (`integer`, unit: attempts)
- `latency_seconds` (`number`, unit: seconds, rounded to 6 decimals)
- `status_code` (`integer`, expected 2xx)

### Event: `llm_request_failure`

Emitted when request ultimately fails after retry policy.

Fields:

- `timestamp` (`string`)
- `event` = `llm_request_failure`
- `app_name` (`string`)
- `correlation_id` (`string`)
- `attempts` (`integer`, unit: attempts)
- `latency_seconds` (`number`, unit: seconds, rounded to 6 decimals)
- `status_code` (`integer`)
- `error_type` (`string`)

`status_code` semantics:

- `0` means no HTTP response was available (timeout/transport failure path).
- Non-zero means terminal HTTP status code.

`error_type` values currently produced by SDK:

- `timeout`
- `transport`
- `response_json`
- `RateLimitError`
- `ServerError`
- `ClientRequestError`

### Metrics Callback Contract

SDK does not ship a built-in metrics backend. Instead, it calls methods on a consumer-provided sink.

#### Callback: `record_inflight(app_name: str, inflight: int)`

Semantics:

- Called after inflight slot acquire and after release.
- `inflight` unit is active requests in current process.
- Expected range is `0..LLM_MAX_INFLIGHT`.

#### Callback: `record_request_result(app_name: str, success: bool, status_code: int, attempts: int, latency_seconds: float, error_type: str = "")`

Semantics:

- Called once per terminal request outcome (success or failure).
- `latency_seconds` is end-to-end latency across all attempts.
- `attempts` is total attempts used for this request.
- `status_code` is terminal code (`0` for timeout/transport path).
- `error_type` is empty string on success; set on failure.

## Canonical Metric Conventions (Recommended)

These names are **recommended conventions** for downstream systems. They are not emitted by SDK directly.

### Metric: `onprem_llm_sdk_inflight_requests`

- Type: gauge
- Unit: requests
- Source callback: `record_inflight`
- Tags:
  - `app_name` (required)

### Metric: `onprem_llm_sdk_requests_total`

- Type: counter
- Unit: requests
- Source callback: `record_request_result`
- Tags:
  - `app_name` (required)
  - `success` (required; `true|false`)
  - `status_code` (required; stringified integer)
  - `error_type` (optional; include only when `success=false`)

### Metric: `onprem_llm_sdk_request_latency_seconds`

- Type: histogram
- Unit: seconds
- Source callback: `record_request_result.latency_seconds`
- Tags:
  - `app_name` (required)
  - `success` (required)
  - `status_code` (required)

### Metric: `onprem_llm_sdk_request_attempts`

- Type: histogram
- Unit: attempts
- Source callback: `record_request_result.attempts`
- Tags:
  - `app_name` (required)
  - `success` (required)

## Cardinality Guidance

Use these limits to prevent metric explosion:

- `app_name`: keep bounded and stable per service/component.
- `status_code`: low cardinality by design; safe as a tag.
- `success`: two values only; safe.
- `error_type`: keep to SDK-emitted enum values; do not inject free-form strings.
- `correlation_id`: high cardinality; log-only field, **never** a metric tag.

Additional guidance:

- Avoid endpoint URL, prompt, or model prompt fragments as metric tags.
- If multi-model usage is needed, add a bounded `model` tag only when model set is small and stable.
- Prefer environment-level dimensions (service, namespace, region) from your telemetry platform rather than SDK tags.

## Stability Notes

- Event names and callback parameter shape are part of SDK observability contract for `0.1.0`.
- Adding new optional log fields is backward-compatible.
- Renaming event names, removing fields, or changing callback semantics is a breaking change.

