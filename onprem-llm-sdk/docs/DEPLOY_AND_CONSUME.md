# Deploy and Consume

This guide is the operator + developer reference for using `onprem-llm-sdk` from an offline bundle.

## 1) Operator flow (air-gapped host)

Assume bundle file already exists on the server:
`/path/to/onprem_llm_sdk_bundle_<version>.tar.gz`

```bash
# Place and extract
sudo mkdir -p /opt/artifacts/onprem_llm_sdk
sudo tar -xzf /path/to/onprem_llm_sdk_bundle_<version>.tar.gz -C /opt/artifacts/onprem_llm_sdk

# Verify integrity
cd /opt/artifacts/onprem_llm_sdk
sha256sum -c SHA256SUMS

# Install in app venv (network disabled)
python3.12 -m venv /opt/venvs/myapp
source /opt/venvs/myapp/bin/activate
python -m pip install --no-index --find-links /opt/artifacts/onprem_llm_sdk/wheels onprem-llm-sdk==<version>

# Verify package import/version
python -c "import onprem_llm_sdk; print(onprem_llm_sdk.__version__)"
```

## 2) App env configuration

Example env file (`/etc/myapp/llm-client.env`):

```bash
LLM_API_URL=http://127.0.0.1:8000/v1/chat/completions
LLM_MODEL_NAME=gpt-oss-20b
LLM_APP_NAME=myapp-analyzer
LLM_MAX_INFLIGHT=2
LLM_CONNECT_TIMEOUT_SEC=5
LLM_READ_TIMEOUT_SEC=120
LLM_MAX_RETRIES=3
LLM_RETRY_BACKOFF_SEC=1.0
LLM_MAX_TOKENS_DEFAULT=2048
LLM_VERIFY_TLS=false
```

Load this env file in your process manager (for example systemd `EnvironmentFile=`).

## 3) Developer integration

```python
from onprem_llm_sdk import SDKConfig, VLLMClient

cfg = SDKConfig.from_env()
client = VLLMClient(cfg)
result = client.complete("Summarize this notable.")
print(result.text)
```

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
    # short delay and retry at workflow level if needed
    pass
except (RequestTimeoutError, TransportError, ServerError):
    # transient failures
    pass
except ClientRequestError:
    # payload/model mismatch or bad request
    pass
```

## 5) Upgrade/rollback

- Upgrade: install new pinned version from new bundle.
- Rollback: reinstall previous bundle and version pin.

