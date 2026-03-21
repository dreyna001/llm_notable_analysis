# LLM Client Contract (v1)

This document defines the required runtime contract for any project using `onprem-llm-sdk`.

## Supported deployment model

- Same-host consumers only.
- Endpoint default: `http://127.0.0.1:8000/v1/completions`.

## Environment keys


| Key                       | Required | Default                                | Purpose                                    |
| ------------------------- | -------- | -------------------------------------- | ------------------------------------------ |
| `LLM_API_URL`             | yes      | `http://127.0.0.1:8000/v1/completions` | vLLM API endpoint                          |
| `LLM_MODEL_NAME`          | yes      | `gpt-oss-20b`                          | `model` field sent per request             |
| `LLM_API_TOKEN`           | no       | empty                                  | Bearer token when vLLM auth is enabled     |
| `LLM_APP_NAME`            | yes      | `unknown-app`                          | Caller identity in logs/headers/metrics    |
| `LLM_MAX_TOKENS_DEFAULT`  | yes      | `2048`                                 | Default response token budget              |
| `LLM_CONNECT_TIMEOUT_SEC` | yes      | `5`                                    | TCP/connect timeout                        |
| `LLM_READ_TIMEOUT_SEC`    | yes      | `120`                                  | Response read timeout                      |
| `LLM_MAX_RETRIES`         | yes      | `3`                                    | Retry count (total attempts = retries + 1) |
| `LLM_RETRY_BACKOFF_SEC`   | yes      | `1.0`                                  | Base exponential backoff delay             |
| `LLM_MAX_INFLIGHT`        | yes      | `2`                                    | Per-process semaphore limit                |
| `LLM_VERIFY_TLS`          | yes      | `true`                                 | TLS certificate verification behavior      |


## Behavioral guarantees

- Retries occur for timeout, transport failures, `429`, and `5xx`.
- No retries for non-`429` `4xx`.
- A process-local semaphore limits concurrent in-flight calls.
- Structured logs include `app_name` and `correlation_id`.
- Canonical observability fields and metric conventions are defined in `docs/OBSERVABILITY_CONTRACT.md`.
- Response parsing supports:
  - `choices[0].text`
  - `choices[0].message.content`

## Error contract

Callers should handle these SDK exceptions:

- `RequestTimeoutError`
- `TransportError`
- `RateLimitError`
- `ServerError`
- `ClientRequestError`
- `ResponseFormatError`
- `ConfigError`

## Header contract

Every request sends:

- `X-Correlation-ID`
- `X-LLM-App`
- `Content-Type: application/json`
- `Authorization: Bearer <token>` when `LLM_API_TOKEN` is set

