# Offline Pre-Stage Guide (`phi3.5_llamacpp_service`)

Purpose: run `llama-server` with Phi-3.5 GGUF on an airgapped host with **no web pulls** from installer/runtime.

## 1) Pull artifacts on an internet-connected machine

- `llama.cpp` source snapshot at pinned commit:
  - repo: `https://github.com/ggml-org/llama.cpp.git`
  - commit: `149b249` (baseline used by current package family)
  - create an archive directory that contains `CMakeLists.txt` at top level.
- Phi-3.5 mini instruct GGUF Q4_K_M model artifact (pinned baseline):
  - repo: `https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF`
  - revision/commit: `b1693692c4758ac83f0d0e65aff9b4f945f29941`
  - filename: `Phi-3.5-mini-instruct-Q4_K_M.gguf`
  - SHA256 (LFS OID): `e4165e3a71af97f1b4820da61079826d8752a2088e313af0c7d346796c38eff5`
  - direct immutable download pattern:
    - `https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF/resolve/b1693692c4758ac83f0d0e65aff9b4f945f29941/Phi-3.5-mini-instruct-Q4_K_M.gguf`
  - if you intentionally choose a different publisher/revision, record that exact source + revision + SHA256 in deployment notes.

## 2) Transfer artifacts into the airgapped VM

Copy artifacts onto the VM (USB, secure transfer media, etc.) into these target paths:

- Runtime source tree:
  - `$HOME/.local/share/phi35_llamacpp/runtime/llama.cpp`
  - must contain `CMakeLists.txt` directly under that directory.
- Model file:
  - `$HOME/.local/share/phi35_llamacpp/models/<your_phi_gguf_filename>.gguf`

## 3) Configure local env values

From `phi3.5_llamacpp_service/config/phi35.env.example`, set at least:

- `PHI_RUNTIME_SRC_DIR` to your local runtime source path.
- `PHI_MODEL_PATH` to your local GGUF file path.
- `PHI_MODEL_SHA256` to the exact pinned hash (recommended for integrity, required for strict reproducibility).

## 4) Run offline installer/launcher (non-root)

From repo root:

```bash
cd /path/to/llm_notable_analysis/phi3.5_llamacpp_service
bash install_phi35_nonroot_offline.sh
```

The script only:

- verifies local source/model paths
- builds llama.cpp locally (unless `PHI_SKIP_RUNTIME_BUILD=true`)
- starts `llama-server` from your home directory

It does **not** call `git clone`, `git fetch`, `curl` download, package manager, or systemd.

## 5) Quick verification

```bash
curl -sf http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"<set to your served model name>",
    "messages":[{"role":"user","content":"Reply with exactly OK."}],
    "temperature":0,
    "max_tokens":16
  }'
```

If your API caller requires an exact model string, align it with your runtime request value and client config.
