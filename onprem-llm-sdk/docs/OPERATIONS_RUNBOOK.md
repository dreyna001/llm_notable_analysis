# Operations Runbook

## Preconditions

- Local vLLM process is healthy on `127.0.0.1:8000`.
- App env file includes required `LLM_*` keys.
- SDK version is pinned in each app deployment.

## Health checks

```bash
curl -sSf http://127.0.0.1:8000/health
python -c "import onprem_llm_sdk; print(onprem_llm_sdk.__version__)"
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

## Evidence retention

- Keep bundle hash manifests.
- Keep release changelog and install logs.
- Keep service logs around rollout windows.

