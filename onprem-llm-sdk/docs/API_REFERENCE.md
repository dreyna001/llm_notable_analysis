# API Reference (Public SDK Surface)

This document defines the **public API contract** for `onprem-llm-sdk` version `0.1.0`.

Public API in this document means symbols exported from `onprem_llm_sdk` package root.

For canonical log and metrics field semantics, see `docs/OBSERVABILITY_CONTRACT.md`.

## Public Exports

The following symbols are publicly exported:

- `VLLMClient`
- `SDKConfig`
- `CompletionResult`
- `SDKError`
- `ConfigError`
- `TransportError`
- `RequestTimeoutError`
- `ResponseFormatError`
- `ClientRequestError`
- `RateLimitError`
- `ServerError`

Anything not exported above is internal and may change without notice.

## `SDKConfig`

Frozen dataclass containing runtime configuration.

### Fields

- `llm_api_url: str` (default: `http://127.0.0.1:8000/v1/completions`)
- `llm_model_name: str` (default: `gpt-oss-20b`)
- `llm_api_token: str` (default: empty string)
- `llm_app_name: str` (default: `unknown-app`)
- `llm_max_tokens_default: int` (default: `2048`)
- `llm_connect_timeout_sec: float` (default: `5.0`)
- `llm_read_timeout_sec: float` (default: `120.0`)
- `llm_max_retries: int` (default: `3`)
- `llm_retry_backoff_sec: float` (default: `1.0`)
- `llm_max_inflight: int` (default: `2`)
- `llm_verify_tls: bool` (default: `True`)

### Class Methods

#### `SDKConfig.from_env(*, overrides: Optional[Mapping[str, Any]] = None) -> SDKConfig`

Loads configuration from environment keys, then applies optional field overrides.

Environment keys:

- `LLM_API_URL`
- `LLM_MODEL_NAME`
- `LLM_API_TOKEN`
- `LLM_APP_NAME`
- `LLM_MAX_TOKENS_DEFAULT`
- `LLM_CONNECT_TIMEOUT_SEC`
- `LLM_READ_TIMEOUT_SEC`
- `LLM_MAX_RETRIES`
- `LLM_RETRY_BACKOFF_SEC`
- `LLM_MAX_INFLIGHT`
- `LLM_VERIFY_TLS`

Validation behavior:

- `LLM_MAX_TOKENS_DEFAULT` must be integer `>= 1`.
- `LLM_CONNECT_TIMEOUT_SEC` must be float `>= 0.1`.
- `LLM_READ_TIMEOUT_SEC` must be float `>= 0.1`.
- `LLM_MAX_RETRIES` must be integer `>= 0`.
- `LLM_RETRY_BACKOFF_SEC` must be float `>= 0.0`.
- `LLM_MAX_INFLIGHT` must be integer `>= 1`.
- `LLM_VERIFY_TLS` must be one of: `1,true,yes,on,0,false,no,off` (case-insensitive).
- Required non-empty fields: `llm_api_url`, `llm_model_name`, `llm_app_name`.

Raises:

- `ConfigError` for invalid values or unknown override keys.

## `VLLMClient`

Synchronous client for a local OpenAI-compatible completions endpoint.

### Constructor

#### `VLLMClient(config: SDKConfig, *, session=None, metrics_sink=None, logger=None, sleep_fn=time.sleep) -> VLLMClient`

Parameters:

- `config`: validated `SDKConfig` instance (required).
- `session`: optional `requests.Session`-compatible object.
- `metrics_sink`: optional sink implementing metrics protocol methods.
- `logger`: optional `logging.Logger` instance.
- `sleep_fn`: injectable sleep function for retry delay behavior.

### Methods

#### `complete(prompt: str, *, max_tokens: Optional[int] = None, temperature: float = 0.0, correlation_id: Optional[str] = None, connect_timeout_sec: Optional[float] = None, read_timeout_sec: Optional[float] = None) -> CompletionResult`

Sends one completion request with retry/backoff and error mapping.

Request payload fields sent to endpoint:

- `model` from `SDKConfig.llm_model_name`
- `prompt` from method argument
- `max_tokens` from method argument or `SDKConfig.llm_max_tokens_default`
- `temperature` from method argument

Request headers sent by SDK:

- `Content-Type: application/json`
- `X-Correlation-ID: <correlation_id>`
- `X-LLM-App: <llm_app_name>`
- `User-Agent: onprem-llm-sdk/<llm_app_name>`
- `Authorization: Bearer <token>` only when `llm_api_token` is non-empty

Timeout behavior:

- Connect/read timeouts are tuple `(connect_timeout_sec, read_timeout_sec)`.
- Per-call timeout overrides win over config values when provided.

Retry behavior:

- Retryable transport conditions: request timeout and request transport exceptions.
- Retryable HTTP statuses: `429` and `5xx`.
- Non-retryable HTTP statuses: all other `4xx`.
- Total attempts: `llm_max_retries + 1`.
- Delay policy: `Retry-After` header when valid, else exponential backoff:
  - `llm_retry_backoff_sec * 2^(attempt-1)`

Raises:

- `ValueError` when `prompt` is empty/whitespace.
- `RequestTimeoutError` when timeout retries are exhausted.
- `TransportError` when transport retries are exhausted.
- `ResponseFormatError` when response is not JSON or does not match expected shape.
- `RateLimitError` when `429` fails after retries.
- `ServerError` when `5xx` fails after retries.
- `ClientRequestError` for non-retryable `4xx`.

## `CompletionResult`

Frozen dataclass returned by `VLLMClient.complete(...)`.

Fields:

- `text: str`
- `raw_response: Dict[str, Any]`
- `latency_seconds: float`
- `attempts: int`
- `correlation_id: str`
- `status_code: int`

## Exceptions

Exception hierarchy:

- `SDKError` (base)
  - `ConfigError`
  - `TransportError`
    - `RequestTimeoutError`
  - `ResponseFormatError`
  - `ClientRequestError` (`status_code`, `response_body`)
  - `RateLimitError` (`status_code`, `response_body`)
  - `ServerError` (`status_code`, `response_body`)

## Behavioral Limits and Constraints

### Prompt Size Expectations

- SDK constraint: no explicit max prompt character/token limit enforced by SDK.
- Effective limit comes from upstream endpoint/model context window and server policy.
- Status: **unknown** exact limit from SDK contract alone.

### Token Limits

- SDK default response token budget: `llm_max_tokens_default` (default `2048`).
- Per-call override: `complete(..., max_tokens=...)`.
- SDK validation for config default requires integer `>= 1`.
- SDK does **not** enforce an upper bound for `max_tokens`.
- Status: **unknown** hard upper bound from SDK contract alone.

### Temperature Bounds

- Method accepts `temperature: float` and forwards value as-is.
- SDK does **not** enforce min/max temperature bounds.
- Status: **unknown** accepted range depends on endpoint behavior.

### Correlation ID Constraints

- If omitted, SDK auto-generates UUID4 string.
- If provided, value is forwarded as `X-Correlation-ID` without additional SDK format validation.
- SDK does **not** enforce max length or character set.
- Status: **unknown** endpoint/proxy header constraints are outside SDK contract.

## Feature Scope (Supported vs Unsupported)

### Supported

- Synchronous completion calls via one configurable HTTP endpoint (`llm_api_url`).
- OpenAI-compatible completion response extraction from:
  - `choices[0].text`
  - `choices[0].message.content`
- Retry, timeout, and per-process in-flight request limiting.
- Structured logging integration and pluggable metrics sink.

### Explicitly Unsupported by Current Public API

- Streaming responses.
- Async client API (`async`/`await` usage).
- Dedicated Chat Completions API surface.
- Embeddings API surface.
- Responses API surface.
- Batch API surface.
- Tool/function-calling API surface.
- Automatic pagination or cursor-based iteration APIs.
- Server lifecycle/model management operations.

## Compatibility Guarantees

### Python Versions

- Packaging requirement: `requires-python = ">=3.10"`.
- Build scripts and air-gap examples reference Python `3.12` for bundle workflows.
- Guaranteed minimum from package metadata: Python 3.10+.

### Operating System Scope

- Package classifier declares: `Operating System :: POSIX :: Linux`.
- Guaranteed scope from metadata: POSIX/Linux.
- Other OS behavior: **unknown** from published contract.

### Dependency Bounds

- Runtime dependency:
  - `requests>=2.31,<3`
- `3.x` for `requests` is outside guaranteed compatibility.

### vLLM / OpenAI-Compat Guarantees

- SDK expects an OpenAI-compatible completions endpoint URL (default `/v1/completions`).
- SDK contract guarantees parsing support only for:
  - `choices[0].text`
  - `choices[0].message.content`
- SDK does not publish a pinned vLLM version matrix.
- Status of exact tested vLLM versions: **unknown** in current public contract.

