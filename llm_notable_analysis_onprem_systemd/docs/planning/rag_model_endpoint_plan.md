# RAG Model Endpoint Plan

## Status

Planning document for a future `llm_notable_analysis_onprem_systemd` change.
This is not an implemented runtime contract. No `RAG_MODEL_*` keys exist in
`config.env.example` or `onprem_service/config.py` today.

Authoritative current behavior: [`../operations/rag/RAG_OPERATIONS.md`](../operations/rag/RAG_OPERATIONS.md),
[`../operations/rag/KNOWLEDGE_BASE_OPERATIONS.md`](../operations/rag/KNOWLEDGE_BASE_OPERATIONS.md),
and `onprem_rag_notable_analysis`.

## Goal

Expose the existing local RAG embedder and optional reranker through loopback
HTTP endpoints so the analyzer, KB ingest jobs, portal case Q&A, smoke tests,
and future local tools can share one model-serving contract instead of each
process loading `sentence-transformers` models independently.

The main LLM path stays unchanged:

```text
analyzer -> LiteLLM 127.0.0.1:4000 -> vLLM 127.0.0.1:8000
```

The planned RAG model path is separate:

```text
RAG ingest/retrieval/case Q&A -> RAG model endpoint 127.0.0.1:<port> -> Mixedbread embedder + reranker
```

## Current Baseline

**Retrieval backends**

- Production default: PostgreSQL FTS + pgvector (`RAG_BACKEND=postgres`).
- Fallback: SQLite FTS5 + FAISS files (`RAG_BACKEND=sqlite_faiss`).

**Where models load today (in-process)**

| Call site | Package / module | Loader |
| --- | --- | --- |
| KB ingest (general, SPL, Elastic corpora) | `onprem_rag_notable_analysis.future.postgres_ingest`, `vector_index.py`, `corpus_ingest` CLI | `SentenceTransformer` |
| Runtime retrieval (Postgres + FAISS) | `postgres_retrieval.py`, `retrieval.py` | `SentenceTransformer`; `CrossEncoder` when `RAG_RERANK_ENABLED=true` |
| Portal case chunk embed + Q&A search | `onprem_service/case_search.py`, `case_chat.py` | `SentenceTransformer` via `CASE_QA_EMBEDDING_MODEL` |

Operator ingest path: `scripts/setup_postgres_rag.sh` and
`python -m onprem_rag_notable_analysis.future.corpus_ingest`.

**Model defaults (match `config.env.example`)**

- Embedder: `mixedbread-ai/mxbai-embed-large-v1` (`RAG_EMBEDDING_MODEL`,
  `CASE_QA_EMBEDDING_MODEL`).
- Vector dims: `1024` (`RAG_VECTOR_DIMENSIONS`, `CASE_QA_VECTOR_DIMENSIONS`).
- Reranker: `mixedbread-ai/mxbai-rerank-large-v2` (`RAG_RERANK_MODEL`), disabled
  by default (`RAG_RERANK_ENABLED=false`).

**Embedding input contract**

- Query-time vectors apply the Mixedbread retrieval prefix via
  `onprem_rag_notable_analysis.future.embedding_text.format_embedding_query_text`.
- Document/chunk ingest embeddings do not use that prefix.

**Enablement and failure posture**

- General RAG: `CAPABILITY_PROFILES=core,rag` (legacy `RAG_ENABLED` still exists).
- Advisory default: `RAG_FAIL_CLOSED=false`.
- SPL and Elasticsearch grounding reuse the same Postgres retrieval stack and
  rerank knobs; they do not add separate embedder config keys.

**Model cache**

- Packaged systemd units set `HF_HOME=/var/notables/cache/huggingface` and
  `SENTENCE_TRANSFORMERS_HOME=/var/notables/cache/sentence-transformers`.
- Air-gapped staging: [`../operations/deployment/OFFLINE_PRESTAGE_GUIDE.md`](../operations/deployment/OFFLINE_PRESTAGE_GUIDE.md).

**HTTP model serving today**

- Chat completion only: LiteLLM on loopback (`LLM_API_URL`).

## In Scope

- Add a loopback-only RAG model endpoint service for embeddings and reranking.
- Preserve in-process loading as the default until endpoint mode is validated.
- Add explicit config for endpoint enablement, URLs, timeouts, and request caps.
- Add thin client adapters in `onprem_rag_notable_analysis` and portal case
  embedding paths.
- Preserve query-prefix behavior for retrieval and case Q&A query embeddings.
- Add systemd unit, install/prestage notes, health checks, and tests.
- Keep Postgres/FAISS retrieval policy, prompt assembly, and advisory labeling
  unchanged except for where vectors and rerank scores are computed.

## Out Of Scope

- Replacing LiteLLM/vLLM chat completion routing.
- Exposing RAG model endpoints outside loopback by default.
- Generic model-serving platform, plugin registry, or multi-vendor abstraction.
- Changing RAG evidence rules (KB context stays advisory).
- Enabling rerank by default before latency testing.
- Changing existing retrieval tuning keys (`RAG_LEXICAL_TOP_K`, snippet budgets,
  SPL/Elastic grounding limits, etc.).

## Endpoint Shape

One small local service with two routes unless validation shows embedder and
reranker need separate process isolation.

```text
GET  /health
POST /v1/embeddings
POST /v1/rerank
```

Proposed default bind: `127.0.0.1:4101` (not reserved in repo today; pick during
implementation if it conflicts with customer port policy).

### Embeddings

OpenAI-style request body; server validates `model` against configured embedder
name and returns L2-normalized vectors when the current in-process path does.

Request:

```json
{
  "model": "mixedbread-ai/mxbai-embed-large-v1",
  "input": ["text chunk one", "text chunk two"]
}
```

Response:

```json
{
  "model": "mixedbread-ai/mxbai-embed-large-v1",
  "dimensions": 1024,
  "data": [
    {"index": 0, "embedding": [0.01, 0.02]},
    {"index": 1, "embedding": [0.03, 0.04]}
  ]
}
```

Optional request flag or dedicated route may be needed for query-prefixed
embeddings (`Represent this sentence for searching relevant passages: ...`).
Exact shape is an open question; adapters must preserve current retrieval and
case Q&A behavior.

### Rerank

No universal rerank API standard. Use a small Cohere-style local contract mapped
to `CrossEncoder` scoring.

Request:

```json
{
  "model": "mixedbread-ai/mxbai-rerank-large-v2",
  "query": "notable summary or retrieval query",
  "documents": ["candidate snippet one", "candidate snippet two"],
  "top_n": 5
}
```

Response:

```json
{
  "model": "mixedbread-ai/mxbai-rerank-large-v2",
  "results": [
    {"index": 1, "relevance_score": 0.91},
    {"index": 0, "relevance_score": 0.73}
  ]
}
```

## Runtime Configuration

### Proposed keys (add only when implemented)

```text
RAG_MODEL_ENDPOINTS_ENABLED=false
RAG_EMBEDDING_API_URL=http://127.0.0.1:4101/v1/embeddings
RAG_RERANK_API_URL=http://127.0.0.1:4101/v1/rerank
RAG_MODEL_API_TIMEOUT_SECONDS=30
RAG_EMBEDDING_MAX_BATCH_SIZE=64
RAG_RERANK_MAX_DOCUMENTS=64
```

`RAG_EMBEDDING_MAX_BATCH_SIZE=64` matches the current Postgres ingest default
in `postgres_ingest.py`.

### Existing keys (unchanged; remain authoritative)

Model identity, cache, backend, and retrieval tuning stay on current `RAG_*`
keys in `config.env.example` / `onprem_service/config.py`, including:

```text
RAG_ENABLED
RAG_BACKEND
RAG_FAIL_CLOSED
RAG_SQLITE_PATH
RAG_FAISS_PATH
RAG_POSTGRES_DSN
RAG_POSTGRES_SCHEMA
RAG_POSTGRES_CHUNKS_TABLE
RAG_POSTGRES_FTS_CONFIG
RAG_POSTGRES_STATEMENT_TIMEOUT_MS
RAG_EMBEDDING_MODEL
RAG_VECTOR_DIMENSIONS
RAG_RERANK_ENABLED
RAG_RERANK_MODEL
HF_HOME
SENTENCE_TRANSFORMERS_HOME
RAG_MAX_SNIPPETS_120B
RAG_MAX_SNIPPETS_20B
RAG_CONTEXT_BUDGET_CHARS_120B
RAG_CONTEXT_BUDGET_CHARS_20B
RAG_FUSED_RANK_LIMIT_120B
RAG_FUSED_RANK_LIMIT_20B
RAG_NEAR_DUPLICATE_SIMILARITY_THRESHOLD
RAG_LEXICAL_TOP_K
RAG_VECTOR_TOP_K
RAG_CANDIDATE_POOL_LIMIT
RAG_RRF_K
```

Portal case Q&A uses parallel keys (`CASE_QA_EMBEDDING_MODEL`,
`CASE_QA_VECTOR_DIMENSIONS`) with the same Mixedbread defaults today. Endpoint
mode should either reuse the RAG embedding URL or add an explicit case-QA URL;
decision deferred (see Open Questions).

Startup validation should fail fast when `RAG_MODEL_ENDPOINTS_ENABLED=true` and
required URLs are missing, malformed, or non-loopback by default.

## Security And Operations

- Bind to `127.0.0.1` by default.
- Run as a dedicated unprivileged user (mirror LiteLLM/vLLM unit patterns).
- Stage weights under documented `HF_HOME` / `SENTENCE_TRANSFORMERS_HOME` paths
  (`/var/notables/cache/...` in packaged units).
- Enforce request caps for batch size, input text length, and rerank candidate
  count.
- Use explicit client timeouts; keep bounded separately from
  `RAG_POSTGRES_STATEMENT_TIMEOUT_MS`.
- Do not log raw documents, alert text, embeddings, tokens, or secrets.
- Expose `/health` for systemd and operator smoke checks.
- Log model load status, request counts, latency, and validation failures without
  sensitive payloads.

## Architecture Fit

Matches existing on-prem patterns:

- systemd-managed local services
- loopback-only model endpoints by default
- explicit `config.env` runtime contract
- thin adapters for transport and normalization
- deterministic validation before endpoint calls
- no live network calls in unit tests
- operator docs updated only after behavior is supported

The endpoint service owns model loading and scoring. Callers still own retrieval
policy, prompt assembly, advisory-context labeling, and fail-open vs fail-closed
behavior (`RAG_FAIL_CLOSED`, SPL/Elastic failure modes).

## Acceptance Criteria

- Embedding endpoint returns validated `RAG_VECTOR_DIMENSIONS` vectors for valid
  input.
- Query-prefixed embeddings match current `format_embedding_query_text` behavior
  for retrieval and case Q&A.
- Rerank endpoint returns stable document indexes and relevance scores without
  mutating candidate text.
- Callers run in endpoint mode and in current in-process mode.
- Invalid model names, empty input, oversize batches, and non-loopback endpoint
  config fail with clear errors.
- `scripts/smoke_postgres_rag.sh` and/or service-chain smoke cover endpoint-backed
  ingest and retrieval with fake or deterministic clients.
- Systemd unit starts on loopback and passes `/health`.
- [`RAG_OPERATIONS.md`](../operations/rag/RAG_OPERATIONS.md) and prestage docs
  explain model staging before enabling endpoint mode.

## Diff Plan

1. Add endpoint service skeleton and request/response validators.
   - Files: new focused module under `llm_notable_analysis_onprem_systemd/src/`.
   - Tests: schemas, caps, empty input, health, loopback bind.

2. Add embedding and rerank client adapters.
   - Files: `onprem_rag_notable_analysis/future/` adapter module; config wiring in
     `onprem_service/config.py`.
   - Tests: fake HTTP for success, timeout, malformed JSON, dimension mismatch.

3. Wire optional endpoint mode into RAG and case embedding call sites.
   - Files: `postgres_ingest.py`, `postgres_retrieval.py`, `vector_index.py`,
     `retrieval.py`, `corpus_ingest.py`; `onprem_service/case_search.py` and
     `case_chat.py` if case Q&A shares the endpoint.
   - Tests: injected fake clients; in-process path unchanged when disabled.

4. Add deployment contract.
   - Files: `config.env.example`, systemd unit, install/prestage docs,
     `tests/onprem_service/test_config_runtime_contract.py`.
   - Tests: URL validation, timeout bounds, loopback defaults.

5. Add smoke validation and operator documentation.
   - Files: extend `scripts/smoke_postgres_rag.sh` / `smoke_service_chain.sh`;
     update [`RAG_OPERATIONS.md`](../operations/rag/RAG_OPERATIONS.md) after
     implementation.
   - Commands: `/health`, `/v1/embeddings`, `/v1/rerank`, one endpoint-backed
     retrieval pass.

## Open Questions

- One process for embedder + reranker initially, or split services for memory /
  CPU/GPU placement?
- How should query-prefix embeddings be represented in the HTTP contract (flag,
  separate route, or client-side prefix only)?
- Should endpoint mode land for ingest first, with runtime retrieval enabled
  after latency testing?
- Should portal case Q&A reuse `RAG_EMBEDDING_API_URL` or get a dedicated URL /
  config key?
- Which deployment profile has headroom to enable rerank under normal analyzer
  and portal concurrency?
