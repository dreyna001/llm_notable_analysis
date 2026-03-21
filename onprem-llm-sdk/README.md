# onprem-llm-sdk

Reusable Python SDK for same-host access to a local vLLM endpoint in on-prem and air-gapped environments.

## Why this exists

- Standardize retries, timeouts, and concurrency limits across projects.
- Keep a stable contract for vLLM endpoint usage.
- Support offline installation from a signed/checksummed wheel bundle.

## Quick start

```python
from onprem_llm_sdk import SDKConfig, VLLMClient

cfg = SDKConfig.from_env()
client = VLLMClient(cfg)
result = client.complete("Summarize this notable in one sentence.")
print(result.text)
```

## Documentation

- `docs/API_REFERENCE.md`
- `docs/OBSERVABILITY_CONTRACT.md`
- `docs/HIGH_LEVEL_OVERVIEW.md`
- `docs/ARCHITECTURE.md`
- `docs/LLM_CLIENT_CONTRACT.md`
- `docs/PACKAGING_RATIONALE.md`
- `docs/AIRGAP_DISTRIBUTION.md`
- `docs/DEPLOY_AND_CONSUME.md`
- `docs/SCRIPTS_REFERENCE.md`
- `docs/TESTING_AND_CI.md`

