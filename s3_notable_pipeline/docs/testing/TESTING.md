# Testing

## Unit Tests

Unit tests must not call live AWS, Bedrock, Splunk, Elasticsearch, ServiceNow,
or MCP endpoints. Mock AWS clients and HTTP calls, and keep fixtures bounded.

Run the full Python test suite from `s3_notable_pipeline`:

```bash
python -m pytest tests
```

Focused parity slices:

```bash
python -m pytest tests/test_config.py
python -m pytest tests/test_bedrock_kb_retrieval.py tests/test_rag_integration.py
python -m pytest tests/test_spl_query_generation.py tests/test_splunk_investigation.py
python -m pytest tests/test_query_result_enrichment.py tests/test_query_result_interpretation.py
python -m pytest tests/test_idempotency.py tests/test_servicenow.py
python -m pytest tests/test_elastic_query_generation.py tests/test_elasticsearch_investigation.py
```

## Smoke Validation

For a deployed non-production stack:

1. Upload a small representative notable to `incoming/`.
2. Confirm JSON and markdown reports are written under `reports/`.
3. If `html_reports` is enabled, confirm the HTML object is also written.
4. Confirm CloudWatch logs show bounded status metadata without secrets.
5. For read-only investigation profiles, confirm denied generated queries do not
   make outbound calls and successful calls produce `investigation_query_results`.
6. For writeback or ServiceNow create, confirm duplicate events do not duplicate
   side effects when idempotency is enabled.

## Optional Integration Tests

Local AWS integration tests are optional. If added later, use LocalStack through
`AWS_ENDPOINT_URL` and local `test/test` credentials. Do not require developer
AWS credentials for default test runs.

Real AWS, Splunk, Elasticsearch, ServiceNow, or customer MCP validation must be
explicit dev/staging/prod validation, not a default unit-test dependency.
