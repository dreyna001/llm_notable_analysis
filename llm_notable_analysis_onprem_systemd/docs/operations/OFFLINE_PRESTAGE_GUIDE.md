# Offline Pre-Stage Guide (`llm_notable_analysis_onprem_systemd`)

Goal: list exactly what to download before installing on an offline host.

## What This Controls

This guide controls offline readiness: source bundles, wheelhouse artifacts,
model weights, vLLM/LiteLLM runtime dependencies, and transfer checks before an
air-gapped install.

## Recommended Starting Posture

- Build the wheelhouse from the same OS/Python profile used by the target host
  when practical.
- Pre-stage model weights and tokenizer artifacts before installation day.
- Keep checksums or manifests for transferred artifacts.
- Do not pre-stage customer secrets in source bundles or wheelhouses.

## Customer Decisions

- Which exact package pins and model artifacts are approved for the environment?
- Who owns artifact download, malware scanning, checksum capture, and transfer?
- Where are offline artifacts stored and retained?
- Which runtime path will model weights use on the target host?

## 1) Download source bundles

- `llm_notable_analysis_onprem_systemd/` (this package)
- `onprem_rag_notable_analysis/` source bundle (installed into the analyzer venv)
- `onprem-llm-sdk/` source bundle (recommended for offline)

## 2) Download Python artifacts (wheelhouse)

Create a wheelhouse on an internet-connected machine, then transfer it.

Required pins from this package:

- `requests==2.32.5`
- `onprem-llm-sdk==0.1.0` (or install from local `onprem-llm-sdk/` source)
- `psycopg[binary]==3.3.4`
- `pgvector==0.4.2`
- `faiss-cpu==1.13.2`
- `sentence-transformers==5.4.1`
- `numpy==2.4.4`
- `python-docx==1.2.0`
- `docx2txt==0.9`
- `litellm[proxy]==1.83.14` (default installer pin; installed into `/opt/litellm/venv`)
- `huggingface_hub==1.14.0` (default installer pin for optional model download helper)
- `vllm==0.14.1` (default installer pin; includes transitive dependencies)

Example:

```bash
mkdir -p wheelhouse
python3 -m pip download -d wheelhouse \
  requests==2.32.5 \
  'psycopg[binary]==3.3.4' \
  pgvector==0.4.2 \
  faiss-cpu==1.13.2 \
  sentence-transformers==5.4.1 \
  numpy==2.4.4 \
  python-docx==1.2.0 \
  docx2txt==0.9 \
  'litellm[proxy]==1.83.14' \
  huggingface_hub==1.14.0 \
  vllm==0.14.1
```

For `onprem-llm-sdk`, either:

- build/download a wheel and place it in `wheelhouse`, or
- keep `onprem-llm-sdk/` as a local sibling source directory and install it from source offline.

## 3) Download model artifacts

Default service path expects:

- model directory: `/opt/models/gemma-4-31B-it`
- model repo used by installer helper defaults: `google/gemma-4-31B-it`

Pre-download model files and transfer them so `config.json` exists under `/opt/models/gemma-4-31B-it`.

If RAG is enabled, also stage the local embedding/reranking model artifacts
needed by `sentence-transformers`:

- embedder: `BAAI/bge-base-en-v1.5`
- reranker: `BAAI/bge-reranker-base` when `RAG_RERANK_ENABLED=true`

Keep model artifacts outside the repo, record checksums where local policy
requires it, and update `config.env` if local model paths are used instead of
Hub-style identifiers.

## 4) Download OS-level dependencies (RPMs)

### Python interpreter (required)

- **Minimum:** Python **3.10+** (installer fails below that).
- **Default / recommended:** Python **3.12** for both analyzer and vLLM venvs (`scripts/install.sh` defaults `ANALYZER_PYTHON_BIN` / `VLLM_PYTHON_BIN` to `python3.12`).
- **Pin explicitly:** `sudo ANALYZER_PYTHON_BIN=python3.12 VLLM_PYTHON_BIN=python3.12 bash scripts/install.sh`
- **3.13+:** allowed; installer warns (vLLM wheel compatibility may break—prefer 3.12 for regulated builds).

Stage matching OS packages for your chosen interpreter (names vary by RHEL/variant), e.g. `python3.12`, pip/venv, and **devel** headers for the vLLM interpreter.

Minimum commands used by installer:

- `python3` (or the exact `python3.12` you pin)
- `pip3` (or `python3.12 -m ensurepip` / distro pip package)
- `systemctl` (systemd)

Commonly needed in practice:

- `python3-venv` / `python3-devel` (depends on distro packaging)
- `git`, `curl`, `openssh-server`, `sudo`
- `policycoreutils-python-utils` (for `semanage`, optional but recommended on SELinux hosts)
- PostgreSQL server/client packages when using `RAG_BACKEND=postgres`
- pgvector extension package compatible with the staged PostgreSQL version

For full vLLM mode, also stage:

- NVIDIA driver + CUDA runtime/toolkit compatible with your GPU

For PostgreSQL RAG mode, also stage:

- approved `.txt` / `.docx` KB source documents
- PostgreSQL data-directory backup/restore process if rollback auditability is required

## 5) Offline install modes

### A) Full vLLM mode

Install from local wheelhouse/model artifacts:

```bash
cd /path/to/llm_notable_analysis_onprem_systemd
sudo PIP_NO_INDEX=1 \
     PIP_FIND_LINKS=/mnt/media/wheelhouse \
     VLLM_PIP_SPEC="/mnt/media/wheelhouse/vllm-0.14.1-*.whl" \
     VLLM_SKIP_INSTALL=false \
     MODEL_DOWNLOAD=false \
     bash scripts/install.sh
```

`PIP_NO_INDEX/PIP_FIND_LINKS` make installer `pip install` steps use the local wheelhouse only.
The installer also installs the sibling `onprem_rag_notable_analysis/` source
bundle into `/opt/notable-analyzer/venv`, so keep that directory next to
`llm_notable_analysis_onprem_systemd/` in the transferred source bundle.

### B) Client-only mode (using `onprem_qwen3_sudo_llamacpp_service`)

No vLLM/GPU install path:

```bash
cd /path/to/llm_notable_analysis_onprem_systemd
sudo SDK_SOURCE_DIR=/path/to/onprem-llm-sdk bash scripts/install_mini_qwen_cpu_client.sh
```
