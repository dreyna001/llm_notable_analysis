# On-Prem Test Guide

Run commands from the repository root.

## Unit Tests

```bash
PYTHONPATH=.:llm_notable_analysis_onprem_systemd/src:onprem-llm-sdk/src \
  llm_notable_analysis_onprem_systemd/.venv/bin/python -m unittest discover \
  -s llm_notable_analysis_onprem_systemd/tests -p "test_*.py"
```

Expected result: `Ran 120 tests ... OK`.

The unit suite uses mocks for vLLM, LiteLLM, Splunk, ServiceNow, and Postgres.
It covers analyzer contracts, RAG SQL construction, Postgres ingest/retrieval
branches, deployment files, installer contracts, and operator helper scripts.

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
Postgres schema/ingest/retrieval path with deterministic smoke embeddings, and
removes the container afterward. Docker is only the test harness; production uses
the configured host PostgreSQL/pgvector service.

This proves the database, pgvector extension, schema/table DDL, insert/upsert,
and retrieval context path. It does not prove BGE model loading or reranking.

## Full Service Chain

After vLLM, LiteLLM, and `notable-analyzer` are running on a host:

```bash
sudo bash llm_notable_analysis_onprem_systemd/scripts/smoke_service_chain.sh \
  --config-env /etc/notable-analyzer/config.env
```
