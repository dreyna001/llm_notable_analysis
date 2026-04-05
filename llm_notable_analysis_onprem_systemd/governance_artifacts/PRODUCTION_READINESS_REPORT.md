# Production Readiness Report (On-Prem Notable Analyzer)

**Status:** Ready for production  
**Assessment date:** 2026-03-02  
**Deployment profile:** On-prem single host, vLLM local endpoint (`127.0.0.1:8000`), model `gpt-oss-20b`

## Scope

This report summarizes deployment readiness for:
- `vllm.service` (local inference service)
- `notable-analyzer.service` (file-drop ingest and analysis pipeline)
- On-prem unittest suite under `llm_notable_analysis_onprem_systemd/tests`

## Validation evidence

- **vLLM health and model availability**
  - `GET /health` returned success.
  - `GET /v1/models` returned `gpt-oss-20b`.
- **End-to-end pipeline validation**
  - Synthetic notable (`install-smoke-*`) processed successfully.
  - Realistic test notable (`real-test-001.json`) processed successfully.
  - Report generated at `/var/notables/reports/real-test-001.md`.
  - Source input moved to `/var/notables/processed/real-test-001.json`.
- **Automated tests**
  - `unittest discover` completed with **22/22 passing**.
- **Service state**
  - `vllm.service`: active/running.
  - `notable-analyzer.service`: active/running.

## Security and operations notes

- vLLM endpoint is local-only by configuration (`127.0.0.1`).
- Splunk writeback is implemented but controlled by config flag (`SPLUNK_SINK_ENABLED`).
- Retention and archive workflow is active per configured intervals.

## Non-blocking follow-ups

- If host has legacy `vllm.service.d` drop-ins, run installer with:
  - `VLLM_RESET_OVERRIDES=true`
  to normalize systemd behavior to repo defaults.
- For production onboarding, record host-specific evidence package (service status, test output, report artifact hashes) in release documentation.

## Conclusion

Based on service health, model/API validation, end-to-end processing success, and fully passing on-prem automated tests, the current deployment is **ready for production use**.

