# On-Prem Build Dependency List

Declared dependencies for the production on-prem `systemd` stack (`llm_notable_analysis_onprem_systemd`). This document lists **direct, repo-pinned components** used by `scripts/install.sh` and related installers.

**Scope:** This is a human-readable dependency inventory, **not** a full SBOM. Transitive Python/npm packages, OS package versions, and GPU driver builds vary by target host. For an evidence bundle from an installed environment (including optional Syft SBOM output), run:

```bash
sudo bash scripts/tools/generate_dependency_manifest.sh
```

Related: [`OFFLINE_PRESTAGE_GUIDE.md`](OFFLINE_PRESTAGE_GUIDE.md), [`INSTALL.md`](INSTALL.md), [`SECURITY_POSTURE.md`](../../security/SECURITY_POSTURE.md).

---

## Runtime layout

| Virtual environment | Install path | Primary role |
| --- | --- | --- |
| Analyzer | `/opt/notable-analyzer/venv` | Notable analysis, RAG, analyst portal API |
| LiteLLM | `/opt/litellm/venv` | OpenAI-compatible proxy on loopback |
| vLLM | `/opt/vllm/venv` | Local LLM inference |

**Python:** 3.12 recommended (minimum 3.10+). Pin both venvs explicitly in regulated builds:

```bash
sudo ANALYZER_PYTHON_BIN=python3.12 VLLM_PYTHON_BIN=python3.12 bash scripts/install.sh
```

---

## Python — analyzer venv (`/opt/notable-analyzer/venv`)

Pins from `requirements.txt` and `pyproject.toml` (production `install.sh` path).

| Package | Pin | Notes |
| --- | --- | --- |
| `requests` | `2.32.5` | HTTP client for LLM API calls |
| `onprem-llm-sdk` | `0.1.0` | Installed from monorepo source (`onprem-llm-sdk/`) |
| `onprem-rag-notable-analysis` | `0.1.0` | Installed from monorepo source (`onprem_rag_notable_analysis/`) |
| `psycopg[binary]` | `3.3.4` | Postgres client (RAG + case archive) |
| `pgvector` | `0.4.2` | Python pgvector bindings |
| `faiss-cpu` | `1.13.2` | Vector index (RAG profile) |
| `sentence-transformers` | `5.4.1` | Embedding models |
| `transformers` | `5.9.0` | Hugging Face model stack |
| `huggingface-hub` | `1.16.4` | Model artifact access |
| `numpy` | `2.4.4` | Numeric stack |
| `python-docx` | `1.2.0` | DOCX KB ingest |
| `docx2txt` | `0.9` | DOCX text extraction |
| `Pillow` | `11.1.0` | Image I/O (image ingest) |
| `pypdfium2` | `4.30.0` | PDF rendering (image ingest) |
| `fastapi` | `0.115.12` | Analyst portal API (when portal profile enabled) |
| `uvicorn[standard]` | `0.34.0` | Portal ASGI server |

### Analyst portal optional (installed with portal profile)

| Package | Pin | Notes |
| --- | --- | --- |
| `tiktoken` | `0.9.0` | Chat context token estimation (`pyproject.toml` `[project.optional-dependencies.portal]`) |

### Preview / dev only (not required for production systemd install)

| Package | Pin | Notes |
| --- | --- | --- |
| `boto3` | `1.37.38` | Bedrock chat in `scripts/preview_portal_ui.py` only |

### Local source packages (not from PyPI)

| Package | Version | Monorepo path |
| --- | --- | --- |
| `onprem-llm-sdk` | `0.1.0` | `onprem-llm-sdk/` |
| `onprem-rag-notable-analysis` | `0.1.0` | `onprem_rag_notable_analysis/` |

`onprem-llm-sdk` runtime dependency: `requests>=2.31,<3` (satisfied by analyzer pin).

---

## Python — LiteLLM venv (`/opt/litellm/venv`)

| Package | Pin | Override env var |
| --- | --- | --- |
| `litellm[proxy]` | `1.83.14` | `LITELLM_PIP_SPEC` |

---

## Python — vLLM venv (`/opt/vllm/venv`)

| Package | Pin | Override env var |
| --- | --- | --- |
| `vllm` | `0.21.0` | `VLLM_PIP_SPEC` |

When `MODEL_DOWNLOAD=true`, the installer also uses:

| Package | Pin | Override env var |
| --- | --- | --- |
| `huggingface_hub` | `1.16.4` | `HUGGINGFACE_HUB_PIP_SPEC` |

---

## Model artifacts (not Python packages)

Pre-stage weights locally for offline installs (`MODEL_DOWNLOAD=false` on target).

### LLM serving (default production path)

| Artifact | Default path / repo | Notes |
| --- | --- | --- |
| Gemma 4 31B IT | `/opt/models/gemma-4-31B-it` | Hub: `google/gemma-4-31B-it` (`MODEL_REPO`) |
| Served model name | `gemma-4-31B-it` | Configured via `config.env` |

### RAG and analyst portal embeddings

| Role | Model | When needed |
| --- | --- | --- |
| RAG embedder | `ibm-granite/granite-embedding-english-r2` (768-dim) | `rag` profile |
| RAG reranker | `ibm-granite/granite-embedding-reranker-english-r2` | `RAG_RERANK_ENABLED=true` |
| Case Q&A embedder | `ibm-granite/granite-embedding-english-r2` (768-dim) | `analyst_portal` profile |

Default cache paths: `HF_HOME=/var/notables/cache/huggingface`, `SENTENCE_TRANSFORMERS_HOME=/var/notables/cache/sentence-transformers`.

---

## Analyst portal frontend (build-time npm)

Built on a connected host; air-gapped targets receive pre-built `frontend/analyst-portal/dist/` only.

Source: `frontend/analyst-portal/package.json` (`analyst-portal-ui@0.1.0`).

### Runtime dependencies (bundled into `dist/`)

| Package | Declared range |
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

### Build / test tooling (connected build host only)

| Package | Declared range |
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

Build requires **Node.js and npm** on the connected staging host. Resolved versions depend on the lockfile/npm resolution at build time; record `npm ls --depth=0` output per local policy when pinning frontend supply chain.

---

## OS and infrastructure dependencies

Distro-specific package names vary (RHEL vs Debian/Ubuntu). Stage versions that match the target host.

| Component | Required when | Notes |
| --- | --- | --- |
| Python 3.12 + venv + devel headers | Always | `python3.12`, `python3.12-dev` / `python3-devel` |
| `systemd` / `systemctl` | Always | Service management |
| NVIDIA driver + CUDA stack | vLLM GPU mode | Must match staged `vllm==0.21.0` wheel |
| PostgreSQL server + client | `RAG_BACKEND=postgres` or `INSTALL_ANALYST_PORTAL=true` | Case archive and/or RAG |
| PostgreSQL **pgvector** extension | Postgres RAG / portal | Package for staged PG major, or build from source (`PGVECTOR_GIT_REF`, default `v0.8.0`) |
| `nginx` + `htpasswd` | `INSTALL_ANALYST_PORTAL=true` | `apache2-utils` or `httpd-tools` |
| `git`, `curl`, `sudo` | Install / maintenance | Used by installer and ops scripts |
| Tesseract + Leptonica + language data | Image ingest enabled | See image ingest section |

Operator-owned (not in repo): TLS certificates, basic-auth credentials, DNS/firewall rules.

---

## Image ingest optional stack

When KB images, portal chat images, closed-ticket attachments, or PDF/DOCX embedded images are in scope:

| Layer | Component | Pin / reference |
| --- | --- | --- |
| OCR | Tesseract + Leptonica | OS packages (offline bundle via `scripts/build_image_ingest_offline_bundle.sh`) |
| PDF | pypdfium2 / PDFium | `pypdfium2==4.30.0` |
| Image I/O | Pillow | `Pillow==11.1.0` |
| Vision (advisory) | Gemma 4 via vLLM + LiteLLM | Same LLM stack as analysis |
| Retrieval | IBM Granite embed + rerank | See model artifacts table |

Install on target after base `install.sh`:

```bash
sudo bash scripts/install_image_ingest_prerequisites.sh --bundle-dir /path/to/bundle
```

See [`../rag/IMAGE_INGEST_PREREQUISITES.md`](../rag/IMAGE_INGEST_PREREQUISITES.md).

---

## Monorepo layout required by installer

| Path | Required by |
| --- | --- |
| `llm_notable_analysis_onprem_systemd/` | `install.sh`, `install_mini_qwen_cpu_client.sh` |
| `onprem-llm-sdk/` | Both installers |
| `onprem_rag_notable_analysis/` | Full `install.sh` only |

Override when layout differs: `SDK_SOURCE_DIR`, `RAG_PACKAGE_SRC_DIR`.

---

## Pin sources (for maintainers)

| File | What it pins |
| --- | --- |
| `requirements.txt` | Analyzer venv direct Python deps |
| `pyproject.toml` | Analyzer + portal optional deps |
| `onprem-llm-sdk/pyproject.toml` | SDK runtime dep range |
| `onprem_rag_notable_analysis/pyproject.toml` | RAG package deps |
| `scripts/install.sh` | vLLM, LiteLLM, Hugging Face hub, default model paths |
| `frontend/analyst-portal/package.json` | Portal UI npm deps |

When pins change, update this document and re-run offline wheelhouse staging per [`OFFLINE_PRESTAGE_GUIDE.md`](OFFLINE_PRESTAGE_GUIDE.md).
