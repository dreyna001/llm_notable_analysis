# On-Prem Test Guide

This project includes a minimal automated `unittest` suite for the on-prem service.

## Run the suite

From repository root:

```bash
python -m unittest discover -s llm_notable_analysis_onprem_systemd/tests -p "test*.py" -v
```

## What is covered

- `tests/onprem_service/test_markdown_generator.py`
  - Section order contract for markdown output:
    1. Alert Reconciliation
    2. Competing Hypotheses & Pivots
    3. Evidence vs Inference
    4. Indicators of Compromise (IOCs)
    5. Scored TTPs
  - Alert reconciliation rendering with missing optional fields
  - Deterministic markdown rendering for stable inputs

- `tests/onprem_service/test_local_llm_client_contract.py`
  - Response schema/default normalization checks
  - `alert_reconciliation` type/list coercion
  - JSON extraction cleanup behavior
  - Content policy validation guards (URL/placeholder constraints)
  - Scored TTP score normalization

- `tests/onprem_service/test_ingest_and_formatting.py`
  - Ingest normalization for JSON and text inputs
  - Notable ID extraction/sanitization behavior
  - LLM alert input formatting behavior
  - FIFO file discovery ordering

- `tests/onprem_service/test_integration_mocks.py`
  - Mocked `LocalLLMClient.analyze_alert()` success path
  - Mocked timeout/retry error path
  - Mocked repair-flow path (initial invalid response, then valid repaired response)
  - Real TTP filtering behavior with a temporary MITRE IDs file
  - Mocked Splunk sink payload build path and branch behavior (`disabled`, `search_name` fallback, request error)

## Notes

- Tests are isolated from external systems (vLLM, Splunk, network) via mocks.
- This suite focuses on high-value regression coverage while keeping maintenance overhead low.
