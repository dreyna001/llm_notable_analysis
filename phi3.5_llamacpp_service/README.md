# phi3.5_llamacpp_service

Minimal installer/runtime bundle for running `llama.cpp` `llama-server` with
Phi-3.5 GGUF on a single host.

## What this directory contains

- `install_phi35_nonroot_offline.sh`
  - non-root installer/launcher
  - expects runtime source + model to already be present locally
- `install_phi35_sudo.sh`
  - root wrapper that can install host packages
  - optional runtime/model download mode
  - optional systemd unit install/start
- `config/phi35.env.example`
  - environment knobs for runtime paths and server options
- `reset_phi35_data.sh`
  - cleanup helper for rebuild/retest loops
- `llama-phi35.service`
  - systemd unit template used by the sudo wrapper
- `CHAT_COMPLETIONS_RESPONSE_METADATA.md`
  - response field semantics for OpenAI-compatible chat completions

## Supported install modes

### 1) Offline-style (recommended default)

Use this when source/model artifacts are pre-staged on the host.

```bash
sudo bash install_phi35_sudo.sh
```

This mode:

- installs required host packages (`PHI_INSTALL_PACKAGES=true` by default)
- does not pull runtime/model from the internet unless explicitly enabled
- invokes the non-root installer to build/start locally

### 2) Online convenience mode

Use this on connected hosts only.

```bash
sudo PHI_DOWNLOAD_RUNTIME=true PHI_DOWNLOAD_MODEL=true bash install_phi35_sudo.sh
```

### 3) Non-root offline installer directly

Use this when host packages are already installed and artifacts are pre-staged.

```bash
bash install_phi35_nonroot_offline.sh
```

## Offline pre-stage checklist

### 0) Host software prerequisites (RHEL/Rocky/Alma class)

Install before running the non-root installer:

```bash
sudo dnf install -y bash coreutils curl cmake make gcc gcc-c++
```

Notes:

- `sha256sum` is provided by `coreutils`.
- optional but useful on build hosts: `git`, `patchelf`.
- if CMake/compile reports missing headers, common add-ons are:
  - `openssl-devel`
  - `pkgconf-pkg-config`
  - `zlib-devel`

### 1) Pre-stage runtime + model artifacts

Runtime source baseline:

- repo: `https://github.com/ggml-org/llama.cpp.git`
- commit: `149b249`
- local dir must contain `CMakeLists.txt` at top level

Model baseline:

- repo: `https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF`
- revision: `b1693692c4758ac83f0d0e65aff9b4f945f29941`
- filename: `Phi-3.5-mini-instruct-Q4_K_M.gguf`
- SHA256: `e4165e3a71af97f1b4820da61079826d8752a2088e313af0c7d346796c38eff5`

### 2) Configure env values

Start from:

- `config/phi35.env.example`

Set at least:

- `PHI_RUNTIME_SRC_DIR`
- `PHI_MODEL_PATH`
- `PHI_MODEL_SHA256`

### 3) Run install

```bash
cd /path/to/llm_notable_analysis/phi3.5_llamacpp_service
bash install_phi35_nonroot_offline.sh
```

## Verify runtime

```bash
curl -sf http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"<your_model_id>",
    "messages":[{"role":"user","content":"Reply with exactly OK."}],
    "temperature":0,
    "max_tokens":16
  }'
```

For field-level response interpretation (usage/timings/metrics), see
`CHAT_COMPLETIONS_RESPONSE_METADATA.md`.

## Troubleshooting quick notes

- Missing `cmake`/`make`/`curl`/`sha256sum`:
  - install host packages first, rerun installer
- Build succeeds but `llama-server` not found:
  - verify `PHI_RUNTIME_BUILD_DIR`
- Model checksum mismatch:
  - verify file source and `PHI_MODEL_SHA256`
- Health endpoint timeout:
  - inspect `llama-server.log`, reduce load, adjust runtime knobs
- `PHI_SKIP_RUNTIME_BUILD=true`:
  - still requires expected checks/tools in stock script path

## Reset data for a clean rerun

```bash
bash reset_phi35_data.sh
# or non-interactive
bash reset_phi35_data.sh --yes
```
