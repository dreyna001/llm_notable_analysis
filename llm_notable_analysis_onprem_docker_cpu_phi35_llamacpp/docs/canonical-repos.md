# Canonical source and container locations

This document points to the **Git repository** (compose, docs, scripts) and the **GHCR images** used for this deployment. The **folder name** reflects this **reference stack** (CPU-threaded **llama.cpp** + default **Phi-3.5** GGUF). The **analyzer** container image name is **generic** (`notable-analyzer-service`): the same Python worker can target **CPU or GPU inference** elsewhere as long as `config/config.env` points at an OpenAI-compatible endpoint (llama.cpp, vLLM, etc.). Maintainer namespace: **`dreyna001`**. If you use a fork or different GitHub user, replace that name in URLs and image names.

## Git (code, compose, documentation)

| What | URL |
|------|-----|
| **Repository** | [github.com/dreyna001/llm_notable_analysis](https://github.com/dreyna001/llm_notable_analysis) |
| **This Docker bundle in the repo** | […/tree/main/llm_notable_analysis_onprem_docker_cpu_phi35_llamacpp](https://github.com/dreyna001/llm_notable_analysis/tree/main/llm_notable_analysis_onprem_docker_cpu_phi35_llamacpp) |

**First-time setup on a host:** clone or copy that tree, then configure `.env` / `config/config.env`, add the GGUF under `models/`, and pull containers from GHCR (or `docker load` a tarball). The Git repo does **not** contain image layers or model weights.

```bash
git clone https://github.com/dreyna001/llm_notable_analysis.git
cd llm_notable_analysis/llm_notable_analysis_onprem_docker_cpu_phi35_llamacpp
```

## GitHub Container Registry (GHCR)

**Browse packages and tags:** [github.com/dreyna001?tab=packages](https://github.com/dreyna001?tab=packages)

| Image | Example reference | Notes |
|-------|-------------------|--------|
| **Analyzer** (this app) | `ghcr.io/dreyna001/notable-analyzer-service:1.0.0` | Built from `Dockerfile.analyzer` in this folder; tag may vary (check Packages). Same image is used regardless of whether inference is CPU or GPU; only the **model-serving** image/stack changes. |
| **llama.cpp server** (mirrored) | `ghcr.io/dreyna001/llama-cpp-server-cpu-phi35-llamacpp:server` | Retag/push of upstream `ghcr.io/ggml-org/llama.cpp:server`; create this package when you mirror. |

**Air-gap compose (`.env` for `compose.airgap.yaml`):**

```env
ANALYZER_IMAGE=ghcr.io/dreyna001/notable-analyzer-service:1.0.0
MODEL_SERVING_IMAGE=ghcr.io/dreyna001/llama-cpp-server-cpu-phi35-llamacpp:server
```

Align tags with whatever you published on GHCR. Private packages require `docker login ghcr.io` before `docker compose … pull` (see `ghcr-login-and-push.md`).
