# Offline Pre-Stage Guide

Goal: list exactly what to download before installing on an offline host.

Related: [`INSTALL.md`](INSTALL.md) (connected install), [`AIRGAPPED_DEPLOYMENT.md`](AIRGAPPED_DEPLOYMENT.md) (air-gap bring-up), [`../rag/RAG_OPERATIONS.md`](../rag/RAG_OPERATIONS.md) (RAG models and cache paths), [`../rag/IMAGE_INGEST_PREREQUISITES.md`](../rag/IMAGE_INGEST_PREREQUISITES.md) (image/OCR/multimodal prerequisites).

## What This Controls

Offline readiness: monorepo source bundles, Python wheelhouse artifacts, LLM and RAG model weights, optional portal assets, OS packages, and transfer checks before an air-gapped install.

## Recommended Starting Posture

- Build the wheelhouse on a Linux host with the same OS/arch, Python 3.12, and CUDA stack as the target when practical (especially for `vllm`).
- Pre-stage model weights and tokenizer artifacts before installation day.
- Keep checksums or manifests for transferred artifacts.
- Do not pre-stage customer secrets in source bundles or wheelhouses.

## Customer Decisions

- Which exact package pins and model artifacts are approved for the environment?
- Who owns artifact download, malware scanning, checksum capture, and transfer?
- Where are offline artifacts stored and retained?
- Which runtime path will model weights use on the target host?

## 1) Source bundles (monorepo layout)

`scripts/install.sh` expects a full monorepo checkout with these siblings:

| Path | Required by | Notes |
| --- | --- | --- |
| `llm_notable_analysis_onprem_systemd/` | `install.sh`, `install_mini_qwen_cpu_client.sh` | This package |
| `onprem_rag_notable_analysis/` | `install.sh` only | Copied and installed into the analyzer venv |
| `onprem-llm-sdk/` | Both installers | Installed from local source (`SDK_SOURCE_DIR`); not skipped in production |

Override paths when the layout differs:

```bash
export RAG_PACKAGE_SRC_DIR=/path/to/onprem_rag_notable_analysis
export SDK_SOURCE_DIR=/path/to/onprem-llm-sdk
```

## Analyst portal UI (static SPA)

Build on a **connected** host; the air-gapped target only receives `dist/` (no npm on the target).

| Step | Where | Action |
| --- | --- | --- |
| 1 | Connected host | `cd llm_notable_analysis_onprem_systemd/frontend/analyst-portal && npm install && npm run build` |
| 2 | Transfer media | Include `frontend/analyst-portal/dist/` with the source bundle |
| 3 | Air-gapped host | `sudo INSTALL_PORTAL_SKIP_FRONTEND_BUILD=true INSTALL_ANALYST_PORTAL=true bash scripts/install.sh` |

- React/Tailwind/Radix assets are bundled into `dist/` at build time; nginx serves them locally at runtime.
- Not supported: offline npm cache or building the SPA on the air-gapped host.

## 2) Python wheelhouse

Create a wheelhouse on an internet-connected machine, then transfer it. Use **Python 3.12** on a **Linux** host that matches the target OS/arch and GPU/CUDA profile.

### Analyzer venv (`/opt/notable-analyzer/venv`)

Pins from `requirements.txt` (minus `onprem-llm-sdk`, which installs from source):

| Package | Pin |
| --- | --- |
| `requests` | `2.32.5` |
| `psycopg[binary]` | `3.3.4` |
| `pgvector` | `0.4.2` |
| `faiss-cpu` | `1.13.2` |
| `sentence-transformers` | `5.4.1` |
| `transformers` | `5.9.0` |
| `huggingface-hub` | `1.16.4` |
| `numpy` | `2.4.4` |
| `python-docx` | `1.2.0` |
| `docx2txt` | `0.9` |

Additional pins from `pyproject.toml` (installed when `pip install` runs against the analyzer tree):

| Package | Pin |
| --- | --- |
| `fastapi` | `0.115.12` |
| `uvicorn[standard]` | `0.34.0` |

Optional preview-only pin in `requirements.txt` (not required for production systemd install):

| Package | Pin |
| --- | --- |
| `boto3` | `1.37.38` |

Local packages (install from transferred source, not PyPI):

- `onprem-llm-sdk/` (SDK)
- `onprem_rag_notable_analysis/` (RAG helpers; full `install.sh` only)

### LiteLLM venv (`/opt/litellm/venv`)

| Package | Pin | Override env |
| --- | --- | --- |
| `litellm[proxy]` | `1.83.14` | `LITELLM_PIP_SPEC` |

### vLLM venv (`/opt/vllm/venv`)

| Package | Pin | Override env |
| --- | --- | --- |
| `vllm` | `0.21.0` | `VLLM_PIP_SPEC` |

### Example download

```bash
mkdir -p wheelhouse
python3.12 -m pip download -d wheelhouse \
  requests==2.32.5 \
  'psycopg[binary]==3.3.4' \
  pgvector==0.4.2 \
  faiss-cpu==1.13.2 \
  sentence-transformers==5.4.1 \
  transformers==5.9.0 \
  huggingface-hub==1.16.4 \
  numpy==2.4.4 \
  python-docx==1.2.0 \
  docx2txt==0.9 \
  fastapi==0.115.12 \
  'uvicorn[standard]==0.34.0' \
  'litellm[proxy]==1.83.14' \
  vllm==0.21.0
```

`pip download` pulls transitive dependencies. Re-run on the target profile if wheels are platform-specific.

Offline install respects `PIP_NO_INDEX=1` and `PIP_FIND_LINKS=/path/to/wheelhouse` for all installer `pip` steps.

## 3) Model artifacts

### LLM serving (vLLM)

Default paths from `scripts/install.sh`:

| Setting | Default |
| --- | --- |
| Model directory | `/opt/models/gemma-4-31B-it` |
| Hub repo (when downloading online) | `google/gemma-4-31B-it` (`MODEL_REPO`) |

Pre-stage the full model tree so `config.json` exists under the model directory. Set `MODEL_DOWNLOAD=false` on offline hosts.

### RAG and analyst portal embeddings

When `rag` or `analyst_portal` is enabled, stage embedding (and optional rerank) models locally. Defaults from `config.env.example`:

| Role | Model | When |
| --- | --- | --- |
| RAG embedder | `ibm-granite/granite-embedding-english-r2` (768-dim) | `rag` profile |
| RAG reranker | `ibm-granite/granite-embedding-reranker-english-r2` | `RAG_RERANK_ENABLED=true` |
| Case Q&A embedder | `ibm-granite/granite-embedding-english-r2` (768-dim) | `analyst_portal` profile |

Default cache paths (override in `/etc/notable-analyzer/config.env` if needed):

- `HF_HOME=/var/notables/cache/huggingface`
- `SENTENCE_TRANSFORMERS_HOME=/var/notables/cache/sentence-transformers`

Keep weights outside the repo. Record checksums per local policy. See [`../rag/RAG_OPERATIONS.md`](../rag/RAG_OPERATIONS.md) and [`../rag/KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md) for KB source documents and rebuild steps.

### Image ingest offline bundle (OCR, PDF, Granite)

When KB images, portal chat images, closed-ticket scans, or PDF/DOCX embedded images
are in scope, pre-stage the **image-ingest bundle** in addition to the main wheelhouse
and LLM weights.

**Phase 1 (connected staging host):**

Uses `/opt/notable-analyzer/venv/bin/python` for pip and model downloads when that
venv exists (same pattern as `scripts/install.sh` model staging).

```bash
cd llm_notable_analysis_onprem_systemd
bash scripts/build_image_ingest_offline_bundle.sh \
  --output-dir /mnt/staging/image-ingest-bundle
```

**Phase 2 (air-gapped target, after `install.sh`):**

```bash
sudo bash scripts/install_image_ingest_prerequisites.sh \
  --bundle-dir /mnt/media/image-ingest-bundle
sudo bash scripts/configure_us_granite_retrieval_defaults.sh \
  --config-env /etc/notable-analyzer/config.env \
  --portal-env /etc/notable-analyzer/portal.env
sudo bash scripts/verify_image_ingest_prerequisites.sh \
  --config-env /etc/notable-analyzer/config.env
```

Bundle contents: Tesseract/Leptonica OS packages, approved language data, Python wheels
(`pypdfium2`, `Pillow`), and IBM Granite embed/rerank weights. Vision uses the
existing Gemma 4 vLLM stack (no separate vision model download).

Full scope, stack table, migration notes, and retention boundaries:
[`../rag/IMAGE_INGEST_PREREQUISITES.md`](../rag/IMAGE_INGEST_PREREQUISITES.md).

## 4) OS-level dependencies

### Python interpreter (required)

- **Minimum:** Python **3.10+** (installer fails below that).
- **Default / recommended:** Python **3.12** for analyzer, LiteLLM, and vLLM venvs (`ANALYZER_PYTHON_BIN` / `VLLM_PYTHON_BIN` default to `python3.12`).
- **Air-gapped:** pre-stage Python 3.12 OS packages; run with `INSTALL_PYTHON=false`.
- **Pin explicitly:** `sudo ANALYZER_PYTHON_BIN=python3.12 VLLM_PYTHON_BIN=python3.12 bash scripts/install.sh`
- **3.13+:** allowed with a warning; prefer 3.12 for regulated builds.

Stage matching OS packages for the chosen interpreter (names vary by RHEL/Debian variant): interpreter, pip/venv, and **devel** headers for the vLLM interpreter.

Helper used when `INSTALL_PYTHON=true`: `scripts/install_python312.sh` (or monorepo-root `scripts/install_python312.sh`).

Minimum commands used by installer:

- `python3` (or pinned `python3.12`)
- `pip3` (or `python3.12 -m ensurepip` / distro pip package)
- `systemctl` (systemd)

Commonly needed in practice:

- `python3-venv` / `python3-devel` (distro-specific)
- `git`, `curl`, `openssh-server`, `sudo`
- `policycoreutils-python-utils` (for `semanage`, optional on SELinux hosts)
- PostgreSQL server/client when using `RAG_BACKEND=postgres` or `INSTALL_ANALYST_PORTAL=true`
- PostgreSQL **pgvector** extension package for the staged PostgreSQL major version, **or** ability to build pgvector from source (`PGVECTOR_GIT_REF` defaults to `v0.8.0` in `install.sh`)

For full vLLM mode, also stage:

- NVIDIA driver + CUDA runtime/toolkit compatible with the staged `vllm==0.21.0` wheel
- CUDA toolkit `nvcc`; vLLM/FlashInfer may JIT-build kernels at startup. The installer auto-detects `CUDA_HOME` and patches `vllm.service`.

For PostgreSQL RAG mode, also stage:

- approved `.txt` / `.docx` KB source documents
- PostgreSQL backup/restore process if rollback auditability is required

For analyst portal (`INSTALL_ANALYST_PORTAL=true`), also stage or pre-install:

- `nginx`, PostgreSQL, `htpasswd` tool (`apache2-utils` / `httpd-tools`)
- TLS certificates, basic-auth credentials, DNS/firewall (operator-owned; not in repo)
- See [`../analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md)

## 5) Transfer verification (before install day)

- [ ] All three source trees present (or `RAG_PACKAGE_SRC_DIR` / `SDK_SOURCE_DIR` set).
- [ ] Wheelhouse contains platform-compatible wheels for analyzer, LiteLLM, and vLLM venvs.
- [ ] LLM model tree includes `config.json` at the planned `VLLM_MODEL_PATH`.
- [ ] RAG/portal Granite embedding + rerank models staged under planned `HF_HOME` / `SENTENCE_TRANSFORMERS_HOME` when those profiles are in scope.
- [ ] Image-ingest bundle built and transferred when OCR/PDF/KB images or chat images are in scope (`verify_image_ingest_prerequisites.sh` passes).
- [ ] Python 3.12 OS packages staged when `INSTALL_PYTHON=false`.
- [ ] GPU driver/CUDA verified on target when using vLLM.
- [ ] Checksums/manifests recorded per local policy.

## 6) Offline install modes

### A) Full vLLM mode (production default)

```bash
cd /path/to/llm_notable_analysis_onprem_systemd
sudo INSTALL_PYTHON=false \
     ANALYZER_PYTHON_BIN=python3.12 \
     VLLM_PYTHON_BIN=python3.12 \
     PIP_NO_INDEX=1 \
     PIP_FIND_LINKS=/mnt/media/wheelhouse \
     LITELLM_PIP_SPEC="/mnt/media/wheelhouse/litellm-1.83.14-*.whl" \
     VLLM_PIP_SPEC="/mnt/media/wheelhouse/vllm-0.21.0-*.whl" \
     MODEL_DOWNLOAD=false \
     bash scripts/install.sh
```

Notes:

- `PIP_NO_INDEX` / `PIP_FIND_LINKS` apply to all installer `pip install` steps.
- The installer copies and installs sibling `onprem_rag_notable_analysis/` into `/opt/notable-analyzer/onprem_rag_notable_analysis`.
- Skip vLLM wheel install when pre-provisioned: `VLLM_SKIP_INSTALL=true`.
- Pre-staged portal assets: `INSTALL_PORTAL_SKIP_OS_PACKAGES=true` and/or `INSTALL_PORTAL_SKIP_FRONTEND_BUILD=true` with `INSTALL_ANALYST_PORTAL=true`.

Post-install smoke (when services are up):

```bash
sudo bash scripts/smoke_service_chain.sh --config-env /etc/notable-analyzer/config.env
```

### B) Client-only mode (external llama.cpp CPU service)

For `onprem_qwen3_sudo_llamacpp_service` on loopback; no vLLM/GPU/LiteLLM/RAG install path:

```bash
cd /path/to/llm_notable_analysis_onprem_systemd
sudo PIP_NO_INDEX=1 \
     PIP_FIND_LINKS=/mnt/media/wheelhouse \
     SDK_SOURCE_DIR=/path/to/onprem-llm-sdk \
     bash scripts/install_mini_qwen_cpu_client.sh
```

Requires only `llm_notable_analysis_onprem_systemd/` and `onprem-llm-sdk/` (no RAG bundle). See [`INSTALL.md`](INSTALL.md) (Mini/Qwen CPU client section).

## Related docs

| Topic | Doc |
| --- | --- |
| Standard install | [`INSTALL.md`](INSTALL.md) |
| Air-gap bring-up | [`AIRGAPPED_DEPLOYMENT.md`](AIRGAPPED_DEPLOYMENT.md) |
| RAG models and tuning | [`../rag/RAG_OPERATIONS.md`](../rag/RAG_OPERATIONS.md) |
| KB source lifecycle | [`../rag/KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md) |
| Image/OCR prerequisites | [`../rag/IMAGE_INGEST_PREREQUISITES.md`](../rag/IMAGE_INGEST_PREREQUISITES.md) |
| Analyst portal rollout | [`../analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md) |
| Hardware starting points | [`deployment_profiles/README.md`](deployment_profiles/README.md) |
