# Offline Pre-Stage Guide (`onprem_qwen3_sudo_llamacpp_service`)

Purpose: deploy this package on an airgapped or restricted host with no runtime/model web pulls during install.

**Host OS packages:** see [`RHEL_SOFTWARE_DEPENDENCIES.md`](RHEL_SOFTWARE_DEPENDENCIES.md) for a full RHEL checklist.

## 1) Important behavior of this installer

This package defaults to online behavior:

- runtime sync uses `git clone` / `git fetch` when `LLAMA_SKIP_RUNTIME_BUILD=false`
- model step downloads from Hugging Face when `LLAMA_SKIP_MODEL_DOWNLOAD=false`
- dependency install uses package manager when `LLAMA_INSTALL_DEPS=true`

For offline installs, use the skip flags shown in this guide and pre-stage artifacts first.

## 2) Pull pinned artifacts on an internet-connected machine

- `llama.cpp` pinned baseline used by this package:
  - repo: `https://github.com/ggml-org/llama.cpp.git`
  - tag: `b8457`
  - commit: `149b249`
- Qwen3 model pinned baseline used by this package:
  - repo: `https://huggingface.co/Qwen/Qwen3-4B-GGUF`
  - revision/commit: `a9a60d009fa7ff9606305047c2bf77ac25dbec49`
  - filename: `Qwen3-4B-Q4_K_M.gguf`
  - SHA256: `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`
  - size (bytes): `2497280256`
  - direct immutable download pattern:
    - `https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/a9a60d009fa7ff9606305047c2bf77ac25dbec49/Qwen3-4B-Q4_K_M.gguf`

## 3) Stage artifacts onto the target host

Minimum required for strict offline install with this stock installer:

- prebuilt server binary at `/usr/local/bin/llama-server`
  - if building elsewhere, validate linked libraries on target with `ldd /usr/local/bin/llama-server`
- model file at `/opt/llamacpp/models/Qwen3-4B-Q4_K_M.gguf`
- required RPM packages already installed (or available in local repo media)

Optional (for traceability): retain a local archive/note of `llama.cpp` source at commit `149b249`.

## 4) Run installer in offline mode

From package root:

```bash
cd /path/to/llm_notable_analysis/onprem_qwen3_sudo_llamacpp_service
sudo LLAMA_INSTALL_DEPS=false \
     LLAMA_SKIP_RUNTIME_BUILD=true \
     LLAMA_SKIP_MODEL_DOWNLOAD=true \
     bash install_llamacpp.sh
```

Notes:

- installer still requires root (`sudo`) because it creates service account, writes `/etc/llamacpp/llamacpp.env`, and installs systemd unit by default
- installer still checks command availability (`git`, `cmake`, `make`, `curl`, `sed`, `sha256sum`) even when skip flags are enabled

## 5) Verify on target host

```bash
sudo systemctl status llamacpp
curl -sf http://127.0.0.1:8000/health
curl -sf http://127.0.0.1:8000/metrics
```

Optional quick chat probe:

```bash
curl -sS http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"Qwen3-4B-Q4_K_M.gguf",
    "messages":[{"role":"user","content":"Reply with exactly OK."}],
    "temperature":0,
    "max_tokens":16
  }'
```

If the caller enforces a specific model string, align it with your client config and served model name.
