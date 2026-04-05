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

## Playground example

Use the full-featured playground script to exercise config loading, overrides,
correlation IDs, per-call timeout/token controls, metrics sink callbacks, and
typed exception handling.

```bash
python -m pip install -e .
python examples/sdk_playground.py --show-config
```

## Documentation

- `docs/README.md` (start here)
- `docs/DEPLOY_AND_CONSUME.md`
- `docs/ARCHITECTURE.md`
- `docs/API_REFERENCE.md`
- `docs/OPERATIONS_RUNBOOK.md`

