# `onprem_rag_notable_analysis` Python Package

`onprem_rag_notable_analysis` is a small Python library for optional retrieval grounding in the
on-prem notable analysis stack. It is not an API service and does not run by
itself. An application imports it when that application wants to add retrieved
knowledge-base context to an LLM prompt.

The package builds and reads local retrieval artifacts:

- `kb.sqlite3`: chunk metadata plus SQLite FTS5 keyword search.
- `kb.faiss`: FAISS vector index for semantic search.
- `chunks.jsonl`: exported chunk records for inspection/debugging.
- `ingest_report.json`: ingestion summary and counts.

By default, embeddings are generated with
`sentence-transformers/all-MiniLM-L6-v2`. Vector search uses FAISS over
L2-normalized embeddings.

## End-to-End Usage

### 1. Build retrieval artifacts from source docs

Put `.txt` and `.docx` knowledge-base files under a source directory, then run
the ingestion command:

```bash
python -m onprem_rag_notable_analysis.future.corpus_ingest \
  --source-dir /path/to/source_docs \
  --index-dir /path/to/index \
  --embedding-model sentence-transformers/all-MiniLM-L6-v2
```

The command writes the retrieval artifacts into `--index-dir`.

### 2. Load the context provider in your app

Your service chooses whether to enable RAG. If enabled, point the provider at
the local SQLite and FAISS artifacts:

```python
from pathlib import Path
from onprem_rag_notable_analysis.future.rag_config import RAGConfig
from onprem_rag_notable_analysis.future.retrieval import RAGContextProvider

rag_cfg = RAGConfig(
    enabled=True,
    sqlite_path=Path("/path/to/index/kb.sqlite3"),
    faiss_path=Path("/path/to/index/kb.faiss"),
    embedding_model_name="sentence-transformers/all-MiniLM-L6-v2",
)
provider = RAGContextProvider.from_config(rag_cfg)
```

If RAG is disabled or the required artifacts are missing,
`RAGContextProvider.from_config(...)` returns `None`.

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
- If `kb.sqlite3` or `kb.faiss` is missing, provider is `None`.
- If retrieval fails for one request, `build_context(...)` returns `""`.
- Retrieval is optional; the caller decides whether an empty context should
  continue, warn, or fail the larger workflow.

## Programmatic ingestion (optional)

Use `ingest_corpus(...)` directly if you want to build artifacts from Python
instead of the CLI:

```python
from pathlib import Path
from onprem_rag_notable_analysis.future.corpus_ingest import ingest_corpus

report = ingest_corpus(
    source_dir=Path("/path/to/source_docs"),
    index_dir=Path("/path/to/index"),
    embedding_model_name="sentence-transformers/all-MiniLM-L6-v2",
    target_words=500,
    overlap_words=50,
)
```
