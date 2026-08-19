# On-Prem Build Dependency List

Direct, repo-pinned dependencies for `llm_notable_analysis_onprem_systemd`. Not a full SBOM.

**Python:** 3.12 (minimum 3.10+)

## Analyzer venv (`/opt/notable-analyzer/venv`)

| Package | Pin |
| --- | --- |
| `requests` | `2.32.5` |
| `onprem-llm-sdk` | `0.1.0` (source: `onprem-llm-sdk/`) |
| `onprem-rag-notable-analysis` | `0.1.0` (source: `onprem_rag_notable_analysis/`) |
| `psycopg[binary]` | `3.3.4` |
| `pgvector` | `0.4.2` |
| `faiss-cpu` | `1.13.2` |
| `sentence-transformers` | `5.4.1` |
| `transformers` | `5.9.0` |
| `huggingface-hub` | `1.16.4` |
| `numpy` | `2.4.4` |
| `python-docx` | `1.2.0` |
| `docx2txt` | `0.9` |
| `Pillow` | `11.1.0` |
| `pypdfium2` | `4.30.0` |
| `fastapi` | `0.115.12` |
| `uvicorn[standard]` | `0.34.0` |
| `tiktoken` | `0.9.0` (portal profile) |
| `boto3` | `1.37.38` (preview only) |

## LiteLLM venv (`/opt/litellm/venv`)

| Package | Pin |
| --- | --- |
| `litellm[proxy]` | `1.83.14` |

## vLLM venv (`/opt/vllm/venv`)

| Package | Pin |
| --- | --- |
| `vllm` | `0.21.0` |
| `huggingface_hub` | `1.16.4` (`MODEL_DOWNLOAD=true` only) |

## Models

| Role | Artifact |
| --- | --- |
| LLM | `google/gemma-4-31B-it` → `/opt/models/gemma-4-31B-it` |
| RAG embedder | `ibm-granite/granite-embedding-english-r2` |
| RAG reranker | `ibm-granite/granite-embedding-reranker-english-r2` |
| Case Q&A embedder | `ibm-granite/granite-embedding-english-r2` |

## Analyst portal npm (`frontend/analyst-portal/package.json`)

### Runtime

| Package | Range |
| --- | --- |
| `@radix-ui/react-scroll-area` | `^1.2.10` |
| `@radix-ui/react-select` | `^2.2.6` |
| `@radix-ui/react-separator` | `^1.1.8` |
| `@radix-ui/react-slot` | `^1.2.4` |
| `@radix-ui/react-tabs` | `^1.1.13` |
| `@tailwindcss/vite` | `^4.3.0` |
| `class-variance-authority` | `^0.7.1` |
| `clsx` | `^2.1.1` |
| `lucide-react` | `^1.17.0` |
| `react` | `^19.0.0` |
| `react-dom` | `^19.0.0` |
| `react-markdown` | `^10.1.0` |
| `react-router-dom` | `^7.6.0` |
| `rehype-sanitize` | `^6.0.0` |
| `remark-gfm` | `^4.0.1` |
| `tailwind-merge` | `^3.6.0` |
| `tailwindcss` | `^4.3.0` |
| `tw-animate-css` | `^1.4.0` |

### Build / test

| Package | Range |
| --- | --- |
| `@playwright/test` | `^1.55.0` |
| `@testing-library/jest-dom` | `^6.9.1` |
| `@testing-library/react` | `^16.3.2` |
| `@types/node` | `^25.9.1` |
| `@types/react` | `^19.0.0` |
| `@types/react-dom` | `^19.0.0` |
| `@vitejs/plugin-react` | `^4.4.1` |
| `@zodios/core` | `^10.9.6` |
| `jsdom` | `^29.1.1` |
| `openapi-zod-client` | `^1.18.3` |
| `typescript` | `~5.8.3` |
| `vite` | `^6.3.5` |
| `vitest` | `^4.1.8` |
| `zod` | `^3.25.76` |

## OS / infrastructure

| Component | When |
| --- | --- |
| Python 3.12 + venv + devel headers | Always |
| `systemd` | Always |
| NVIDIA driver + CUDA | vLLM GPU mode |
| PostgreSQL + pgvector | RAG or analyst portal |
| `nginx` + `htpasswd` | Analyst portal |
| Tesseract + Leptonica | Image ingest |

## Monorepo paths

| Path | Installer |
| --- | --- |
| `llm_notable_analysis_onprem_systemd/` | `install.sh`, `install_mini_qwen_cpu_client.sh` |
| `onprem-llm-sdk/` | Both |
| `onprem_rag_notable_analysis/` | `install.sh` |
