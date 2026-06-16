# `onprem_rag_notable_analysis` Python Package

`onprem_rag_notable_analysis` is a small Python library for optional retrieval grounding in the
on-prem notable analysis stack. It is not an API service and does not run by
itself. An application imports it when that application wants to add retrieved
knowledge-base context to an LLM prompt.

The current production-oriented on-prem backend uses PostgreSQL FTS plus
pgvector, Mixedbread embeddings, and optional Mixedbread reranking. The package can also build
and read local fallback retrieval artifacts:

- `kb.sqlite3`: chunk metadata plus SQLite FTS5 keyword search.
- `kb.faiss`: FAISS vector index for semantic search.
- `chunks.jsonl`: exported chunk records for inspection/debugging.
- `ingest_report.json`: ingestion summary and counts.

By default, embeddings are generated with `mixedbread-ai/mxbai-embed-large-v1`. The fallback
vector search uses FAISS over L2-normalized embeddings.

## End-to-End Usage

### 1. Build retrieval artifacts from source docs

Put `.txt` and `.docx` knowledge-base files under a source directory, then run
the ingestion command:

```bash
python -m onprem_rag_notable_analysis.future.corpus_ingest \
  --source-dir /path/to/source_docs \
  --index-dir /path/to/index \
  --embedding-model mixedbread-ai/mxbai-embed-large-v1
```

The command writes the retrieval artifacts into `--index-dir`.

For operator steps on the systemd deployment path, including how to add KB
documents, rebuild Postgres RAG, validate ingest reports, and roll back bad
content, see
`llm_notable_analysis_onprem_systemd/docs/operations/KNOWLEDGE_BASE_OPERATIONS.md`.

### 2. Load the context provider in your app

Your service chooses whether to enable RAG. For the default Postgres backend,
use `PostgresRAGContextProvider` with a populated pgvector table:

```python
from onprem_rag_notable_analysis.future.postgres_retrieval import (
    PostgresRAGContextProvider,
)
from onprem_rag_notable_analysis.future.rag_config import RAGConfig

rag_cfg = RAGConfig(
    enabled=True,
    backend="postgres",
    postgres_dsn="postgresql://notable_analyzer@127.0.0.1:5432/notable_rag",
    postgres_schema="notable_rag",
    postgres_chunks_table="kb_chunks",
    embedding_model_name="mixedbread-ai/mxbai-embed-large-v1",
    rerank_enabled=True,
    rerank_model_name="mixedbread-ai/mxbai-rerank-large-v2",
)
provider = PostgresRAGContextProvider.from_config(rag_cfg)
```

If RAG is disabled or the required artifacts are missing,
`RAGContextProvider.from_config(...)` returns `None`. Set
`fail_closed=True` when the caller must treat missing or failed retrieval as a
workflow error instead of advisory context loss.

For the fallback backend, point the provider at the local SQLite and FAISS
artifacts:

```python
from pathlib import Path
from onprem_rag_notable_analysis.future.rag_config import RAGConfig
from onprem_rag_notable_analysis.future.retrieval import RAGContextProvider

rag_cfg = RAGConfig(
    enabled=True,
    backend="sqlite_faiss",
    sqlite_path=Path("/path/to/index/kb.sqlite3"),
    faiss_path=Path("/path/to/index/kb.faiss"),
    embedding_model_name="mixedbread-ai/mxbai-embed-large-v1",
)
provider = RAGContextProvider.from_config(rag_cfg)
```

### 3. Build context per alert/request

Call the provider for each alert/request and pass the returned block into your
prompt template:

```python
context_block = (
    provider.build_context(
        alert_text=alert_text,
        llm_model_name=model_name,
    )
    if provider
    else ""
)
```

`context_block` is a formatted string of retrieved snippets. If no provider is
available, use an empty string and continue without retrieval grounding.

### 4. Runtime behavior to expect

- If RAG is disabled, provider is `None`.
- If `kb.sqlite3` or `kb.faiss` is missing for fallback mode, provider is `None`.
- If retrieval fails for one request, `build_context(...)` returns `""` by
  default.
- With `fail_closed=True`, retrieval failures are re-raised so production
  profiles can require KB grounding.
- Both Postgres and fallback retrieval apply rank and term-overlap gates before
  rendering prompt context. The Postgres backend uses SQL for FTS/vector fusion;
  the fallback backend performs the same fusion locally over SQLite/FAISS.

## Programmatic ingestion (optional)

Use `ingest_corpus(...)` directly if you want to build artifacts from Python
instead of the CLI:

```python
from pathlib import Path
from onprem_rag_notable_analysis.future.corpus_ingest import ingest_corpus

report = ingest_corpus(
    source_dir=Path("/path/to/source_docs"),
    index_dir=Path("/path/to/index"),
    backend="sqlite_faiss",
    embedding_model_name="mixedbread-ai/mxbai-embed-large-v1",
    target_words=500,
    overlap_words=50,
)
```

For Postgres-backed ingestion, pass the same values used by runtime config:

```python
report = ingest_corpus(
    source_dir=Path("/path/to/source_docs"),
    index_dir=Path("/path/to/index"),
    backend="postgres",
    embedding_model_name="mixedbread-ai/mxbai-embed-large-v1",
    target_words=500,
    overlap_words=50,
    postgres_dsn="postgresql://notable_analyzer@127.0.0.1:5432/notable_rag",
    postgres_schema="notable_rag",
    postgres_chunks_table="kb_chunks",
    postgres_fts_config="english",
    vector_dimensions=1024,
)
```
