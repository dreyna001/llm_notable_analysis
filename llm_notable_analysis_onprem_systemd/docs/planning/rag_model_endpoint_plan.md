# RAG Model Endpoint Plan

## Status

Planning document for a future `llm_notable_analysis_onprem_systemd` change.
This is not an implemented runtime contract.

## Goal

Expose the existing local RAG embedder and optional reranker through loopback
HTTP endpoints so the analyzer, ingest jobs, smoke tests, and future local tools
can consume one supported model-serving contract instead of each process loading
`sentence-transformers` models independently.

The current main LLM path remains unchanged:

```text
analyzer -> LiteLLM 127.0.0.1:4000 -> vLLM 127.0.0.1:8000
```

The planned RAG model path is separate:

```text
RAG ingest/retrieval -> RAG model endpoint 127.0.0.1:<port> -> BGE embedder/reranker
```

## Current Baseline

- KB ingest loads `BAAI/bge-base-en-v1.5` in-process and writes vectors to
  Postgres `pgvector` or FAISS.
- Runtime retrieval loads the same embedder in-process to encode query text.
- Runtime rerank loads `BAAI/bge-reranker-base` in-process only when
  `RAG_RERANK_ENABLED=true`.
- `RAG_RERANK_ENABLED=false` by default.
- The only supported HTTP model path today is LiteLLM/vLLM for chat completion.

## In Scope

- Add a loopback-only RAG model endpoint service for embeddings and reranking.
- Preserve the current in-process path as the default until the endpoint path is
  validated.
- Add explicit config values for endpoint URLs, model names, timeouts, request
  caps, and feature enablement.
- Add thin client adapters for embedding and rerank calls.
- Add systemd units, install/prestage docs, health checks, and tests.
- Keep Postgres/FAISS retrieval behavior and prompt construction unchanged
  except for where embedding/rerank scores are computed.

## Out Of Scope

- Replacing LiteLLM/vLLM chat completion routing.
- Exposing the endpoints outside loopback by default.
- Adding a generic model-serving platform, plugin registry, or multi-vendor
  abstraction.
- Changing RAG evidence rules: retrieved KB context remains advisory, not direct
  alert evidence.
- Enabling rerank by default before latency testing.

## Endpoint Shape

Use one small local service with two endpoints unless validation shows the
embedder and reranker need separate process isolation.

```text
GET  /health
POST /v1/embeddings
POST /v1/rerank
```

### Embeddings

Request:

```json
{
  "model": "BAAI/bge-base-en-v1.5",
  "input": ["text chunk one", "text chunk two"]
}
```

Response:

```json
{
  "model": "BAAI/bge-base-en-v1.5",
  "dimensions": 768,
  "data": [
    {"index": 0, "embedding": [0.01, 0.02]},
    {"index": 1, "embedding": [0.03, 0.04]}
  ]
}
```

### Rerank

Rerank does not have one universal API standard. Use a small Cohere-style local
contract because it is simple and maps directly to `CrossEncoder` scoring.

Request:

```json
{
  "model": "BAAI/bge-reranker-base",
  "query": "notable summary or retrieval query",
  "documents": ["candidate snippet one", "candidate snippet two"],
  "top_n": 5
}
```

Response:

```json
{
  "model": "BAAI/bge-reranker-base",
  "results": [
    {"index": 1, "relevance_score": 0.91},
    {"index": 0, "relevance_score": 0.73}
  ]
}
```

## Runtime Configuration

Add only if the endpoint implementation is built:

```text
RAG_MODEL_ENDPOINTS_ENABLED=false
RAG_EMBEDDING_API_URL=http://127.0.0.1:4101/v1/embeddings
RAG_RERANK_API_URL=http://127.0.0.1:4101/v1/rerank
RAG_MODEL_API_TIMEOUT_SECONDS=30
RAG_EMBEDDING_MAX_BATCH_SIZE=64
RAG_RERANK_MAX_DOCUMENTS=64
```

Existing values remain authoritative for model identity:

```text
RAG_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
RAG_VECTOR_DIMENSIONS=768
RAG_RERANK_ENABLED=false
RAG_RERANK_MODEL=BAAI/bge-reranker-base
```

Startup validation should fail fast when endpoint mode is enabled and required
URLs are missing, malformed, or non-loopback by default.

## Security And Operations

- Bind the service to `127.0.0.1` by default.
- Run as a dedicated unprivileged user.
- Keep model cache paths under `/var/notables/cache` or another documented
  host-managed cache path.
- Enforce request caps for batch size, input text length, and rerank candidate
  count.
- Use explicit client timeouts.
- Do not log raw documents, alert text, embeddings, tokens, or secrets.
- Add `/health` for systemd and operator smoke checks.
- Add journal logging with model load status, request counts, latency, and
  validation failures without sensitive payloads.

## Architecture Fit

This follows the existing on-prem patterns:

- systemd-managed local services
- loopback-only model endpoints by default
- explicit `config.env` runtime contract
- thin adapters for transport and normalization
- deterministic validation before endpoint calls
- no live network calls in unit tests
- operator docs updated only after a behavior becomes supported

The endpoint service owns model loading and scoring. The analyzer still owns RAG
retrieval policy, prompt assembly, advisory-context labeling, and fail-open or
fail-closed behavior.

## Acceptance Criteria

- Embedding endpoint returns normalized 768-dimension vectors for valid input.
- Rerank endpoint returns stable document indexes and relevance scores without
  mutating candidate text.
- Analyzer can run in endpoint mode and in current in-process mode.
- Invalid model names, empty input, oversize batches, and non-loopback endpoint
  config fail with clear errors.
- RAG smoke tests cover endpoint-backed ingest and retrieval using fake or
  deterministic model clients.
- Systemd units start on loopback and pass `/health`.
- Docs explain staging model artifacts before enabling endpoint mode.

## Diff Plan

1. Add endpoint service skeleton and request/response validators.
   - Files: new focused module under `src/llm_notable_analysis_onprem_systemd/`.
   - Tests: unit tests for schemas, caps, empty input, and health behavior.

2. Add embedding and rerank client adapters.
   - Files: focused adapter module plus config loading.
   - Tests: fake HTTP responses for success, timeout, malformed JSON, and bad
     dimensions.

3. Wire optional endpoint mode into RAG ingest and retrieval.
   - Files: `onprem_rag_notable_analysis/future/postgres_ingest.py`,
     `postgres_retrieval.py`, and FAISS path if retained.
   - Tests: endpoint mode uses injected fake clients and preserves existing
     in-process behavior when disabled.

4. Add deployment contract.
   - Files: `config.env.example`, systemd unit, install/prestage docs, runtime
     contract tests.
   - Tests: config validation for required URLs, timeout bounds, and loopback
     defaults.

5. Add smoke validation and operator documentation.
   - Files: smoke script and `docs/operations/RAG_OPERATIONS.md` after the
     feature is implemented.
   - Tests/commands: local smoke for `/health`, `/v1/embeddings`, `/v1/rerank`,
     and one endpoint-backed retrieval pass.

## Open Questions

- Should embedding and rerank run in one process initially, or separate services
  if memory and CPU/GPU placement differ materially?
- Should endpoint mode be allowed for ingest only first, with runtime retrieval
  enabled after latency testing?
- Which host profile has enough CPU/GPU headroom to enable rerank under normal
  analyzer concurrency?
