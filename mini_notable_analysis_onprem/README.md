# On-Prem `llama.cpp` PoC Service Package

Standalone package for deploying a local `llama.cpp` (`llama-server`) endpoint on a single CPU-only host for one local consumer service.

This package follows `mini_notable_analysis_onprem/outline.md` and pins:

- `llama.cpp` baseline: `b8457` / commit `149b249`
- model repo: `Qwen/Qwen3-4B-GGUF`
- model file: `Qwen3-4B-Q4_K_M.gguf`
- model revision: `a9a60d009fa7ff9606305047c2bf77ac25dbec49`
- model SHA256: `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`

## What is included

- `install_llamacpp.sh` - installer for user, runtime build, model pull, env file, and systemd unit.
- `systemd/llamacpp.service` - baseline unit installed to `/etc/systemd/system/llamacpp.service`.
- `config/llamacpp.env.example` - configuration surface reference.
- `docs/TROUBLESHOOTING.md` - fast triage and recovery commands.

## Quick start

```bash
cd /path/to/mini_notable_analysis_onprem
sudo bash install_llamacpp.sh
```

## Common options

```bash
# Override model location (keeps pinned filename/revision unless also overridden)
sudo LLAMA_MODEL_PATH=/opt/llamacpp/models/Qwen3-4B-Q4_K_M.gguf bash install_llamacpp.sh

# Skip runtime build if llama-server already installed
sudo LLAMA_SKIP_RUNTIME_BUILD=true bash install_llamacpp.sh

# Skip model download step
sudo LLAMA_SKIP_MODEL_DOWNLOAD=true bash install_llamacpp.sh

# Install only (no service auto-start)
sudo AUTO_START_LLAMACPP=false bash install_llamacpp.sh

# Container/non-systemd environments (Runpod, Docker): skip systemd setup
sudo LLAMA_SKIP_SYSTEMD=true bash install_llamacpp.sh
```

## Runtime defaults

- Service name: `llamacpp`
- Host/port: `127.0.0.1:8000`
- Model path: `/opt/llamacpp/models/Qwen3-4B-Q4_K_M.gguf`
- Threads: `10`
- Threads batch: `12`
- Parallel slots: `1`
- Context size: `8192`
- Default output token limit: `8192` (`--n-predict`)
- Hard output token ceiling (policy): `8192`
- Metrics: enabled
- Web UI: disabled

## Run without systemd (container/etc)

```bash
# Foreground (keeps logs in current terminal)
sudo bash -lc 'source /etc/llamacpp/llamacpp.env; /usr/local/bin/llama-server --model "$LLAMA_MODEL_PATH" --host "$LLAMA_HOST" --port "$LLAMA_PORT" --threads "$LLAMA_THREADS" --threads-batch "$LLAMA_THREADS_BATCH" --parallel "$LLAMA_PARALLEL" --ctx-size "$LLAMA_CTX_SIZE" --n-predict "$LLAMA_DEFAULT_MAX_TOKENS" --cache-type-k "$LLAMA_CACHE_TYPE_K" --cache-type-v "$LLAMA_CACHE_TYPE_V" ${LLAMA_CONT_BATCHING_FLAG:-} ${LLAMA_MMAP_FLAG:-} ${LLAMA_MLOCK_FLAG:-} --metrics --no-webui ${LLAMA_EXTRA_ARGS:-}'

# Background (returns shell immediately; logs -> /tmp/llama-server.log)
sudo bash -lc 'source /etc/llamacpp/llamacpp.env; nohup /usr/local/bin/llama-server --model "$LLAMA_MODEL_PATH" --host "$LLAMA_HOST" --port "$LLAMA_PORT" --threads "$LLAMA_THREADS" --threads-batch "$LLAMA_THREADS_BATCH" --parallel "$LLAMA_PARALLEL" --ctx-size "$LLAMA_CTX_SIZE" --n-predict "$LLAMA_DEFAULT_MAX_TOKENS" --cache-type-k "$LLAMA_CACHE_TYPE_K" --cache-type-v "$LLAMA_CACHE_TYPE_V" ${LLAMA_CONT_BATCHING_FLAG:-} ${LLAMA_MMAP_FLAG:-} ${LLAMA_MLOCK_FLAG:-} --metrics --no-webui ${LLAMA_EXTRA_ARGS:-} >/tmp/llama-server.log 2>&1 &'

# Check process/logs
pgrep -af llama-server
tail -n 100 /tmp/llama-server.log

# Stop manual process
pkill -f "/usr/local/bin/llama-server"
```

## Quick health checks

```bash
sudo systemctl status llamacpp
curl -sf http://127.0.0.1:8000/health
curl -sf http://127.0.0.1:8000/metrics
sudo journalctl -u llamacpp -n 100 --no-pager
```

## Reasoning control (`/no_think`)

For Qwen3 chat templates, add `/no_think` in the system instruction to suppress
reasoning traces and reduce latency/token usage. Remove it to allow reasoning.

```bash
# No reasoning (recommended for PoC JSON workflows)
curl -sS http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"Qwen3-4B-Q4_K_M.gguf",
    "temperature":0,
    "messages":[
      {"role":"system","content":"Return only valid JSON. /no_think"},
      {"role":"user","content":"Summarize this alert in JSON: failed logins then success from same src_ip."}
    ]
  }'

# With reasoning (remove /no_think)
curl -sS http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"Qwen3-4B-Q4_K_M.gguf",
    "temperature":0,
    "messages":[
      {"role":"system","content":"Return only valid JSON."},
      {"role":"user","content":"Summarize this alert in JSON: failed logins then success from same src_ip."}
    ]
  }'
```

Note: `/no_think` is model/template-specific behavior, not a generic OpenAI API standard.

## PoC tests (3 files)

```bash
cd /path/to/mini_notable_analysis_onprem
chmod +x tests/*.sh

# Run all tests
bash tests/run_poc_tests.sh all

# Run static checks only
bash tests/run_poc_tests.sh static

# Run integration checks only
bash tests/run_poc_tests.sh integration
```

The integration suite combines installer smoke, config validation, artifact integrity, service readiness, API smoke/negative checks, observability, and one end-to-end single-consumer flow.
