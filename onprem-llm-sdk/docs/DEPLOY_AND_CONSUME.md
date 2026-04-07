# Deploy and Consume

Single usage guide for developers and operators.

## 1) Quick start (developer)

Run from the repo root (`onprem-llm-sdk/`):

```bash
python -m pip install -e .
python examples/basic_completion.py
```

If your endpoint is not at the default URL, set env first:

```bash
export LLM_API_URL=http://127.0.0.1:8000/v1/chat/completions
export LLM_MODEL_NAME=gpt-oss-20b
export LLM_APP_NAME=myapp-analyzer
```

Windows PowerShell:

```powershell
$env:LLM_API_URL="http://127.0.0.1:8000/v1/chat/completions"
$env:LLM_MODEL_NAME="gpt-oss-20b"
$env:LLM_APP_NAME="myapp-analyzer"
```

## 2) Required environment keys

Defaults are safe for local same-host deployments; set explicit values in production.

| Key | Default | Purpose |
| --- | --- | --- |
| `LLM_API_URL` | `http://127.0.0.1:8000/v1/chat/completions` | Chat-completions endpoint |
| `LLM_MODEL_NAME` | `gpt-oss-20b` | Model field sent in payload |
| `LLM_API_TOKEN` | empty | Bearer token (optional) |
| `LLM_APP_NAME` | `unknown-app` | Caller identity (`X-LLM-App`) |
| `LLM_MAX_TOKENS_DEFAULT` | `2048` | Default response token budget |
| `LLM_CONNECT_TIMEOUT_SEC` | `5.0` | Connect timeout |
| `LLM_READ_TIMEOUT_SEC` | `120.0` | Read timeout |
| `LLM_MAX_RETRIES` | `3` | Retry count (`attempts = retries + 1`) |
| `LLM_RETRY_BACKOFF_SEC` | `1.0` | Base exponential backoff |
| `LLM_MAX_INFLIGHT` | `2` | Process-local concurrent request limit |
| `LLM_VERIFY_TLS` | `true` | TLS cert verification toggle |

For full validation rules, see `docs/API_REFERENCE.md`.

## 3) Minimal integration

```python
from onprem_llm_sdk import SDKConfig, VLLMClient

cfg = SDKConfig.from_env()
client = VLLMClient(cfg)
result = client.complete("Summarize this notable.")
print(result.text)
```

Header behavior:

- `X-LLM-App` comes from `LLM_APP_NAME` / `llm_app_name`.
- `X-Correlation-ID` comes from `correlation_id` argument; auto-generated when omitted.

## 4) Error handling pattern

```python
from onprem_llm_sdk import (
    ClientRequestError,
    RateLimitError,
    RequestTimeoutError,
    ServerError,
    TransportError,
    VLLMClient,
)

try:
    result = VLLMClient(SDKConfig.from_env()).complete("Analyze this event")
except RateLimitError:
    # Workflow-level throttling or delayed retry.
    pass
except (RequestTimeoutError, TransportError, ServerError):
    # Transient failure path.
    pass
except ClientRequestError:
    # Non-retryable request/model mismatch path.
    pass
```

## 5) Playground script (onboarding)

`examples/sdk_playground.py` demonstrates:

- config loading + overrides
- explicit and auto-generated correlation IDs
- per-call overrides (`max_tokens`, `temperature`, `connect/read timeout`)
- custom logger + metrics sink integration
- typed exception handling

```bash
python examples/sdk_playground.py --show-config
```

## 6) Air-gapped install (operator)

Assume bundle file exists:
`/path/to/onprem_llm_sdk_bundle_<version>.tar.gz`

```bash
# Extract
sudo mkdir -p /opt/artifacts/onprem_llm_sdk
sudo tar -xzf /path/to/onprem_llm_sdk_bundle_<version>.tar.gz -C /opt/artifacts/onprem_llm_sdk

# Verify integrity
cd /opt/artifacts/onprem_llm_sdk
sha256sum -c SHA256SUMS

# Install with network disabled
python3.12 -m venv /opt/venvs/myapp
source /opt/venvs/myapp/bin/activate
python -m pip install --no-index --find-links /opt/artifacts/onprem_llm_sdk/wheels onprem-llm-sdk==<version>

# Verify import/version
python -c "import onprem_llm_sdk; print(onprem_llm_sdk.__version__)"
```

## 7) Upgrade and rollback

- Upgrade:
  - install a new pinned version from a new verified bundle
- Rollback:
  - reinstall the prior pinned version from the previous bundle

Operational procedures (health checks, scripts, testing, troubleshooting, security controls)
are in `docs/OPERATIONS_RUNBOOK.md`.

## 8) Docker: quick path

Use this decision:

- Want only RAG in `llm_notable_analysis_onprem_docker_cpu_phi35_llamacpp`:
  - keep default entrypoint (`onprem_main_nonsdk`)
  - set RAG values in `config/config.env`
  - keep `kb/index` mount
  - `onprem_rag` is a Python package used by the analyzer (not a standalone service); see `onprem_rag/README.md`
  - SDK is not required
- Want SDK transport:
  - install `onprem-llm-sdk` in the image
  - run `python -m onprem_service.onprem_main`
  - RAG settings stay the same

Build context (important):

- To use `COPY onprem-llm-sdk ...`, `onprem-llm-sdk/` must be inside the folder Docker is building from.
- Easiest path: run `docker build` from the repo root so both the app folder and `onprem-llm-sdk/` are included.
- If `onprem-llm-sdk/` is not in that folder, Docker cannot copy it into the image.

Example that works:

```bash
docker build -f llm_notable_analysis_analyzer_image/Dockerfile.analyzer -t notable-analyzer-service .
```

Example that does not work:

```bash
docker build -f llm_notable_analysis_analyzer_image/Dockerfile.analyzer -t notable-analyzer-service .
```

### Option A: copy SDK source (simple)

```dockerfile
COPY onprem-llm-sdk /tmp/onprem-llm-sdk
RUN pip install /tmp/onprem-llm-sdk
```

### Option B: install pinned wheel (preferred for production/air-gap)

```dockerfile
COPY wheels /opt/artifacts/onprem_llm_sdk/wheels
RUN pip install --no-index --find-links /opt/artifacts/onprem_llm_sdk/wheels onprem-llm-sdk==<version>
```

Note: `wheels/` must also be inside your build context.

Deploy recommendation:

- preferred: CI build -> push image -> targets run `docker pull`
- valid: build on target host with repo cloned locally
- set runtime env from section 2 and use a unique `LLM_APP_NAME` per app

