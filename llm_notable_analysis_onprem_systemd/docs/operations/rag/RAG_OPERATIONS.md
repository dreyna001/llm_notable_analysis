# RAG Operations

This guide helps customers tune retrieval grounding for analysis without
changing code. It covers when to enable RAG, which backend to use, how strict
failure handling should be, and how much retrieved context should enter the
prompt.

For source document maintenance and rebuild commands, use
[`KNOWLEDGE_BASE_OPERATIONS.md`](KNOWLEDGE_BASE_OPERATIONS.md).

## What This Controls

RAG adds advisory SOC operational context to the analyzer prompt under the
stable header `SOC_OPERATIONAL_CONTEXT`. It can include SOPs, runbooks, Splunk
field references, escalation guidance, and customer operating notes. Retrieved
content is not treated as direct alert evidence.

Runtime retrieval is implemented by the `onprem_rag_notable_analysis` package.
The analyzer maps `RAG_*` env vars into `RAGConfig` and calls
`PostgresRAGContextProvider` (production) or `RAGContextProvider`
(`sqlite_faiss` fallback).

The production backend runs PostgreSQL FTS + pgvector hybrid search with
reciprocal-rank fusion (`RAG_RRF_K`), rank/term-overlap quality gates, optional
Mixedbread cross-encoder reranking, and near-duplicate suppression. SQLite/FAISS
applies the same gating locally.

**SPL query grounding is separate:** enabling general RAG does not authorize
environment-specific tokens in generated SPL. For Splunk index, sourcetype,
macro, and datamodel grounding in the SPL-generation call, operators use
**`SPL_QUERY_RAG_*`** and a dedicated KB table; see
[`SPL_OPERATIONS.md`](SPL_OPERATIONS.md) and
[`KNOWLEDGE_BASE_OPERATIONS.md`](KNOWLEDGE_BASE_OPERATIONS.md).

## Recommended Starting Posture

- Keep `CAPABILITY_PROFILES=core` until the KB source documents are curated and
  owned.
- Add the `rag` profile when operators approve retrieved advisory context. The
  profile sets `RAG_ENABLED=true`; avoid relying on a standalone `RAG_ENABLED`
  lab flag in production.
- Use `RAG_BACKEND=postgres` for production-like on-prem deployments.
- Keep `RAG_FAIL_CLOSED=false` while retrieval is advisory.
- Start with `RAG_RERANK_ENABLED=false`; enable rerank only after model staging
  and latency testing.
- Keep context budgets narrow and increase only after reviewing report quality.

## Customer Decisions

### Should RAG be required or advisory?

**Profile:** `rag` (sets `RAG_ENABLED=true`)

**Settings:** `RAG_FAIL_CLOSED`

- Use `CAPABILITY_PROFILES=core,rag` only when KB content is approved for
  analyst use.
- Keep `RAG_FAIL_CLOSED=false` when reports are allowed to run without KB
  grounding.
- Set `RAG_FAIL_CLOSED=true` only when operators require KB context for every
  report and accept analysis failures when retrieval init or context build fails.

### Which backend should this deployment use?

**Settings:** `RAG_BACKEND`, `RAG_POSTGRES_*`, `RAG_SQLITE_PATH`,
`RAG_FAISS_PATH`

- Prefer `postgres` for production because it keeps lexical search, vector
  search, and operational query controls in one database.
- Defaults: DSN `postgresql://notable_analyzer@127.0.0.1:5432/notable_rag`,
  schema `notable_rag`, table `kb_chunks`, FTS config `english`, statement
  timeout `5000` ms.
- Use `sqlite_faiss` for lab or constrained deployments where Postgres is not
  available. Both artifact paths must exist or the provider is skipped.
- Keep schema/table names customer-specific only when multiple deployments share
  one database instance. Names must be simple PostgreSQL identifiers.

### Which embedding and rerank models are acceptable?

**Settings:** `RAG_EMBEDDING_MODEL`, `RAG_VECTOR_DIMENSIONS`,
`RAG_RERANK_ENABLED`, `RAG_RERANK_MODEL`, `HF_HOME`,
`SENTENCE_TRANSFORMERS_HOME`

- Default embedding model: `mixedbread-ai/mxbai-embed-large-v1`.
- Default vector dimension: `1024`. Must match `CASE_QA_VECTOR_DIMENSIONS`
  (currently fixed at `1024` for v1).
- Default reranker model: `mixedbread-ai/mxbai-rerank-large-v2`, disabled by
  default.
- `HF_HOME` and `SENTENCE_TRANSFORMERS_HOME` are not `RAG_*` keys; packaged
  systemd units set them under `/var/notables/cache/...` for model loading.
- Stage models into approved local cache paths before enabling RAG or rerank in
  air-gapped environments.
- If the embedding model or vector dimensions change, rebuild all KB indexes and
  re-embed archived case chunks. Reranker-only changes do not require a KB
  rebuild.

### On-prem retrieval models (US defaults)

**Status:** Active repo default on on-prem deployments.

| Component | Model | Notes |
| --- | --- | --- |
| Embedder | `mixedbread-ai/mxbai-embed-large-v1` | Apache 2.0, US-made |
| Vector dims | `1024` | Must match `RAG_VECTOR_DIMENSIONS` and `CASE_QA_VECTOR_DIMENSIONS` |
| Reranker | `mixedbread-ai/mxbai-rerank-large-v2` | Apache 2.0, disabled by default |
| Loader | `SentenceTransformer` + `CrossEncoder` | In-process in analyzer |
| KB rebuild | Required when embedder or dims change | Not required for reranker-only |

**Config defaults:**

```bash
RAG_EMBEDDING_MODEL=mixedbread-ai/mxbai-embed-large-v1
RAG_VECTOR_DIMENSIONS=1024
CASE_QA_EMBEDDING_MODEL=mixedbread-ai/mxbai-embed-large-v1
CASE_QA_VECTOR_DIMENSIONS=1024
RAG_RERANK_MODEL=mixedbread-ai/mxbai-rerank-large-v2
RAG_RERANK_ENABLED=false
```

**Operator rollout:**

1. Stage both Mixedbread models under `HF_HOME` / `SENTENCE_TRANSFORMERS_HOME`.
2. Update `/etc/notable-analyzer/config.env` and portal env if used.
3. Run `scripts/setup_postgres_rag.sh` and rebuild general, SPL, and Elastic KB
   corpora per [`KNOWLEDGE_BASE_OPERATIONS.md`](KNOWLEDGE_BASE_OPERATIONS.md).
4. On existing portal hosts, apply case-archive schema dimension changes, then
   re-embed case chunks for archived cases.
5. Enable `RAG_RERANK_ENABLED=true` only after latency testing.

**Existing Postgres hosts (case archive):** new installs use `vector(1024)` in
`deploy/postgres/notable_cases_schema.sql`. Hosts still on older `vector(768)`
case-chunk indexes require a planned migration and full re-embed before portal
Q&A retrieval is trusted again. General `kb_chunks` tables follow
`RAG_VECTOR_DIMENSIONS` via ingest/setup DDL.

Query embeddings use the Mixedbread retrieval prompt prefix automatically at
encode time. Document/chunk embeddings do not.

### How much context should enter the prompt?

**Settings:** `RAG_MAX_SNIPPETS_120B`, `RAG_MAX_SNIPPETS_20B`,
`RAG_CONTEXT_BUDGET_CHARS_120B`, `RAG_CONTEXT_BUDGET_CHARS_20B`

- Limits are chosen from `LLM_MODEL_NAME`: names containing `20b` use the `20B`
  knobs; all others (including default `gemma-4-31B-it`) use the `120B` knobs.
- Smaller models usually need tighter context budgets.
- Increase snippets only after measuring whether reports improve and prompts
  remain stable.
- Prefer concise, well-headed KB content over larger context windows.

### How broad should retrieval search be?

**Settings:** `RAG_FUSED_RANK_LIMIT_120B`, `RAG_FUSED_RANK_LIMIT_20B`,
`RAG_LEXICAL_TOP_K`, `RAG_VECTOR_TOP_K`, `RAG_CANDIDATE_POOL_LIMIT`,
`RAG_RRF_K`, `RAG_NEAR_DUPLICATE_SIMILARITY_THRESHOLD`

- Postgres retrieval pulls `RAG_LEXICAL_TOP_K` FTS hits and `RAG_VECTOR_TOP_K`
  vector hits, fuses with `RAG_RRF_K`, caps at `RAG_CANDIDATE_POOL_LIMIT`, then
  applies profile rank limits and term-overlap gates before prompt rendering.
- Start with defaults.
- Increase candidate pools only when useful snippets are consistently missing.
- Tune near-duplicate suppression when reports repeat similar KB excerpts.
- Treat these as quality knobs, not correctness guarantees.

## Config Quick Reference

| Area | Primary variables |
|------|-------------------|
| Enablement | `CAPABILITY_PROFILES=core,rag` (sets `RAG_ENABLED=true`), `RAG_FAIL_CLOSED`, `RAG_BACKEND` |
| Postgres backend | `RAG_POSTGRES_DSN`, `RAG_POSTGRES_SCHEMA`, `RAG_POSTGRES_CHUNKS_TABLE`, `RAG_POSTGRES_FTS_CONFIG`, `RAG_POSTGRES_STATEMENT_TIMEOUT_MS` |
| SQLite/FAISS backend | `RAG_SQLITE_PATH`, `RAG_FAISS_PATH` |
| Models/cache | `RAG_EMBEDDING_MODEL`, `RAG_VECTOR_DIMENSIONS`, `RAG_RERANK_ENABLED`, `RAG_RERANK_MODEL`, `HF_HOME`, `SENTENCE_TRANSFORMERS_HOME` |
| Context limits | `RAG_MAX_SNIPPETS_120B`, `RAG_MAX_SNIPPETS_20B`, `RAG_CONTEXT_BUDGET_CHARS_120B`, `RAG_CONTEXT_BUDGET_CHARS_20B` |
| Retrieval tuning | `RAG_FUSED_RANK_LIMIT_*`, `RAG_LEXICAL_TOP_K`, `RAG_VECTOR_TOP_K`, `RAG_CANDIDATE_POOL_LIMIT`, `RAG_RRF_K`, `RAG_NEAR_DUPLICATE_SIMILARITY_THRESHOLD` |

**Repo defaults (`config.py` / `config.env.example`):**

| Variable | Default |
| --- | --- |
| `RAG_BACKEND` | `postgres` |
| `RAG_FAIL_CLOSED` | `false` |
| `RAG_POSTGRES_DSN` | `postgresql://notable_analyzer@127.0.0.1:5432/notable_rag` |
| `RAG_POSTGRES_SCHEMA` | `notable_rag` |
| `RAG_POSTGRES_CHUNKS_TABLE` | `kb_chunks` |
| `RAG_POSTGRES_FTS_CONFIG` | `english` |
| `RAG_POSTGRES_STATEMENT_TIMEOUT_MS` | `5000` |
| `RAG_MAX_SNIPPETS_120B` / `_20B` | `5` / `4` |
| `RAG_CONTEXT_BUDGET_CHARS_120B` / `_20B` | `2200` / `1600` |
| `RAG_FUSED_RANK_LIMIT_120B` / `_20B` | `8` / `6` |
| `RAG_LEXICAL_TOP_K` / `RAG_VECTOR_TOP_K` | `30` / `30` |
| `RAG_CANDIDATE_POOL_LIMIT` | `40` |
| `RAG_RRF_K` | `60` |
| `RAG_NEAR_DUPLICATE_SIMILARITY_THRESHOLD` | `0.80` |

## Validation And Rollout

1. Curate KB source documents and run `scripts/setup_postgres_rag.sh`; see
   [`KNOWLEDGE_BASE_OPERATIONS.md`](KNOWLEDGE_BASE_OPERATIONS.md).
2. Run `scripts/smoke_postgres_rag.sh` on a Docker-capable validation host.
3. Add `rag` to `CAPABILITY_PROFILES` in a lab config.
4. Process representative notables and confirm retrieved context is relevant
   and labeled advisory in the report.
5. Tune budgets/snippets only after reviewing real output.
6. Enable `RAG_FAIL_CLOSED=true` only after retrieval availability is proven.

## Related Docs

- [`KNOWLEDGE_BASE_OPERATIONS.md`](KNOWLEDGE_BASE_OPERATIONS.md)
- [`SPL_OPERATIONS.md`](SPL_OPERATIONS.md)
- [`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md)
- [`../delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md`](../../delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md)
