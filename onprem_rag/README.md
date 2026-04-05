# `onprem_rag` Python Package

`onprem_rag` is an internal Python package for retrieval grounding.
It is not a standalone API service.

## Full usage (end-to-end)

### 1) Build retrieval artifacts from source docs

Source docs are `.txt` and `.docx` files under your source directory.

```bash
python -m onprem_rag.future.corpus_ingest \
  --source-dir /path/to/source_docs \
  --index-dir /path/to/index \
  --embedding-model sentence-transformers/all-MiniLM-L6-v2
```

Outputs in `--index-dir`:

- `kb.sqlite3`
- `kb.faiss`
- `chunks.jsonl`
- `ingest_report.json`

### 2) Load provider in your app

```python
from pathlib import Path
from onprem_rag.future.rag_config import RAGConfig
from onprem_rag.future.retrieval import RAGContextProvider

rag_cfg = RAGConfig(
    enabled=True,
    sqlite_path=Path("/path/to/index/kb.sqlite3"),
    faiss_path=Path("/path/to/index/kb.faiss"),
    embedding_model_name="sentence-transformers/all-MiniLM-L6-v2",
)
provider = RAGContextProvider.from_config(rag_cfg)
```

### 3) Build context per alert/request

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

Use `context_block` as grounded context in your prompt/template.

### 4) Runtime behavior to expect

- If RAG is disabled, provider is `None`.
- If `kb.sqlite3` or `kb.faiss` is missing, provider is `None`.
- If retrieval fails for one request, `build_context(...)` returns `""` (fail-open path).

## Programmatic ingestion (optional)

```python
from pathlib import Path
from onprem_rag.future.corpus_ingest import ingest_corpus

report = ingest_corpus(
    source_dir=Path("/path/to/source_docs"),
    index_dir=Path("/path/to/index"),
    embedding_model_name="sentence-transformers/all-MiniLM-L6-v2",
    target_words=500,
    overlap_words=50,
)
```
