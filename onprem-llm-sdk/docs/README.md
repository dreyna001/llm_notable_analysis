# SDK Docs Map

Use this as the entry point for `onprem-llm-sdk` documentation.

## Read in this order

1. `docs/DEPLOY_AND_CONSUME.md`
   - install paths, environment keys, integration examples, and upgrade/rollback
2. `docs/ARCHITECTURE.md`
   - scope, design goals, runtime flow, and component responsibilities
3. `docs/API_REFERENCE.md`
   - public API contract (`SDKConfig`, `VLLMClient`, `CompletionResult`, exceptions)
4. `docs/OPERATIONS_RUNBOOK.md`
   - observability contract, script reference, testing, troubleshooting, supply-chain controls

## One-file onboarding

If you want one script to exercise most SDK functionality, run:

```bash
python examples/sdk_playground.py --show-config
```
