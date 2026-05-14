# On-Prem Test Guide

Run commands from the repository root.

## Unit Tests

```bash
PYTHONPATH=.:llm_notable_analysis_onprem_systemd/src:onprem-llm-sdk/src \
  llm_notable_analysis_onprem_systemd/.venv/bin/python -m unittest discover \
  -s llm_notable_analysis_onprem_systemd/tests -p "test_*.py"
```

Expected result for the on-prem service suite: `126 passed`.
Expected result for the full on-prem package suite: `164 passed`.

The unit suite uses mocks for vLLM, LiteLLM, Splunk, ServiceNow, and Postgres.
It covers analyzer contracts, RAG SQL construction, Postgres ingest/retrieval
branches, deployment files, installer contracts, query-result interpretation,
and operator helper scripts.

## Shell Checks

```bash
find llm_notable_analysis_onprem_systemd/scripts onprem-llm-sdk/scripts \
  -type f -name "*.sh" -print |
  sort |
  while IFS= read -r script; do bash -n "$script" || exit 1; done
```

## Docker-Backed pgvector Smoke

Run this when Docker is available on a validation workstation or release host:

```bash
llm_notable_analysis_onprem_systemd/scripts/smoke_postgres_rag.sh
```

The smoke starts a disposable `pgvector/pgvector:pg16` container, runs the real
Postgres schema/ingest/retrieval path twice (general KB snippets into the default
`kb_chunks`-style smoke table **and** separate SPL grounding snippets into
`spl_query_chunks`), validates both `SOC_OPERATIONAL_CONTEXT` and
`SPL_QUERY_GROUNDING_CONTEXT` retrieval with deterministic smoke embeddings, and
removes the container afterward. Override table names via `SMOKE_TABLE` /
`SMOKE_SPL_TABLE` if needed.

Docker is only the test harness; production uses the configured host
PostgreSQL/pgvector service.

This proves the database, pgvector extension, schema/table DDL, insert/upsert,
and both retrieval-context code paths used by analyzers (`SOC_OPERATIONAL_CONTEXT`
and SPL query grounding). It does not prove BGE model loading or reranking.

## Full Service Chain

After vLLM, LiteLLM, and `notable-analyzer` are running on a host:

```bash
sudo bash llm_notable_analysis_onprem_systemd/scripts/smoke_service_chain.sh \
  --config-env /etc/notable-analyzer/config.env
```
