# RAG Operations

This guide helps customers tune retrieval grounding for analysis without
changing code. It covers when to enable RAG, which backend to use, how strict
failure handling should be, and how much retrieved context should enter the
prompt.

For source document maintenance and rebuild commands, use
[`KNOWLEDGE_BASE_OPERATIONS.md`](KNOWLEDGE_BASE_OPERATIONS.md).

## What This Controls

RAG adds advisory SOC operational context to the analyzer prompt. It can include
SOPs, runbooks, Splunk field references, escalation guidance, and customer
operating notes. Retrieved content is not treated as direct alert evidence.

The production-oriented backend is PostgreSQL FTS + pgvector with local BGE
embeddings and optional reranking. SQLite/FAISS remains a smaller fallback path.

**SPL query grounding is separate:** enabling `RAG_ENABLED` does not authorize
environment-specific tokens in generated SPL. For Splunk index, sourcetype,
macro, and datamodel grounding in the SPL-generation call, operators use
**`SPL_QUERY_RAG_*`** and a dedicated KB table; see
[`SPL_OPERATIONS.md`](SPL_OPERATIONS.md) and
[`KNOWLEDGE_BASE_OPERATIONS.md`](KNOWLEDGE_BASE_OPERATIONS.md).

## Recommended Starting Posture

- Keep `RAG_ENABLED=false` until the KB source documents are curated and owned.
- Use `RAG_BACKEND=postgres` for production-like on-prem deployments.
- Keep `RAG_FAIL_CLOSED=false` while retrieval is advisory.
- Start with `RAG_RERANK_ENABLED=false`; enable rerank only after model staging
  and latency testing.
- Keep context budgets narrow and increase only after reviewing report quality.

## Customer Decisions

### Should RAG be required or advisory?

**Settings:** `RAG_ENABLED`, `RAG_FAIL_CLOSED`

- Use `RAG_ENABLED=true` only when KB content is approved for analyst use.
- Keep `RAG_FAIL_CLOSED=false` when reports are allowed to run without KB
  grounding.
- Set `RAG_FAIL_CLOSED=true` only when operators require KB context for every
  report and accept failed/quarantined processing when retrieval is unavailable.

### Which backend should this deployment use?

**Settings:** `RAG_BACKEND`, `RAG_POSTGRES_*`, `RAG_SQLITE_PATH`,
`RAG_FAISS_PATH`

- Prefer `postgres` for production because it keeps lexical search, vector
  search, and operational query controls in one database.
- Use `sqlite_faiss` for lab or constrained deployments where Postgres is not
  available.
- Keep schema/table names customer-specific only when multiple deployments share
  one database instance.

### Which embedding and rerank models are acceptable?

**Settings:** `RAG_EMBEDDING_MODEL`, `RAG_VECTOR_DIMENSIONS`,
`RAG_RERANK_ENABLED`, `RAG_RERANK_MODEL`, `HF_HOME`,
`SENTENCE_TRANSFORMERS_HOME`

- Default embedding model: `BAAI/bge-base-en-v1.5`.
- Default vector dimension: `768`.
- Default reranker model: `BAAI/bge-reranker-base`, disabled by default.
- Stage models into approved local cache paths before enabling RAG or rerank in
  air-gapped environments.
- If the embedding model changes, rebuild the KB index.

### How much context should enter the prompt?

**Settings:** `RAG_MAX_SNIPPETS_120B`, `RAG_MAX_SNIPPETS_20B`,
`RAG_CONTEXT_BUDGET_CHARS_120B`, `RAG_CONTEXT_BUDGET_CHARS_20B`

- Smaller models usually need tighter context budgets.
- Increase snippets only after measuring whether reports improve and prompts
  remain stable.
- Prefer concise, well-headed KB content over larger context windows.

### How broad should retrieval search be?

**Settings:** `RAG_FUSED_RANK_LIMIT_120B`, `RAG_FUSED_RANK_LIMIT_20B`,
`RAG_LEXICAL_TOP_K`, `RAG_VECTOR_TOP_K`, `RAG_CANDIDATE_POOL_LIMIT`,
`RAG_RRF_K`, `RAG_NEAR_DUPLICATE_SIMILARITY_THRESHOLD`

- Start with defaults.
- Increase candidate pools only when useful snippets are consistently missing.
- Tune near-duplicate suppression when reports repeat similar KB excerpts.
- Treat these as quality knobs, not correctness guarantees.

## Config Quick Reference

| Area | Primary variables |
|------|-------------------|
| Enablement | `RAG_ENABLED`, `RAG_FAIL_CLOSED`, `RAG_BACKEND` |
| Postgres backend | `RAG_POSTGRES_DSN`, `RAG_POSTGRES_SCHEMA`, `RAG_POSTGRES_CHUNKS_TABLE`, `RAG_POSTGRES_FTS_CONFIG`, `RAG_POSTGRES_STATEMENT_TIMEOUT_MS` |
| SQLite/FAISS backend | `RAG_SQLITE_PATH`, `RAG_FAISS_PATH` |
| Models/cache | `RAG_EMBEDDING_MODEL`, `RAG_VECTOR_DIMENSIONS`, `RAG_RERANK_ENABLED`, `RAG_RERANK_MODEL`, `HF_HOME`, `SENTENCE_TRANSFORMERS_HOME` |
| Context limits | `RAG_MAX_SNIPPETS_120B`, `RAG_MAX_SNIPPETS_20B`, `RAG_CONTEXT_BUDGET_CHARS_120B`, `RAG_CONTEXT_BUDGET_CHARS_20B` |
| Retrieval tuning | `RAG_FUSED_RANK_LIMIT_*`, `RAG_LEXICAL_TOP_K`, `RAG_VECTOR_TOP_K`, `RAG_CANDIDATE_POOL_LIMIT`, `RAG_RRF_K`, `RAG_NEAR_DUPLICATE_SIMILARITY_THRESHOLD` |

## Validation And Rollout

1. Curate KB source documents and rebuild using
   [`KNOWLEDGE_BASE_OPERATIONS.md`](KNOWLEDGE_BASE_OPERATIONS.md).
2. Run `scripts/smoke_postgres_rag.sh` on a Docker-capable validation host.
3. Enable `RAG_ENABLED=true` in a lab config.
4. Process representative notables and confirm retrieved context is relevant
   and labeled advisory in the report.
5. Tune budgets/snippets only after reviewing real output.
6. Enable `RAG_FAIL_CLOSED=true` only after retrieval availability is proven.

## Related Docs

- [`KNOWLEDGE_BASE_OPERATIONS.md`](KNOWLEDGE_BASE_OPERATIONS.md)
- [`SPL_OPERATIONS.md`](SPL_OPERATIONS.md)
- [`../delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md`](../delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md)

