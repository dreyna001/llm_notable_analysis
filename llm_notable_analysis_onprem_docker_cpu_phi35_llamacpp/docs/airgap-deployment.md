# Air-gapped deployment (pre-built images)

**This project’s Git repo and GHCR image names:** [canonical-repos.md](canonical-repos.md).

Your stack uses **two** container images:

| Image | Role | Typical source on an internet-connected machine |
|--------|------|-----------------------------------------------|
| **Analyzer** | Python app + copied `onprem_service` / `onprem_rag` | You **build** from this repo (`Dockerfile.analyzer`) |
| **model-serving** | llama.cpp OpenAI-compatible server | Upstream **`ghcr.io/ggml-org/llama.cpp:server`** (you **mirror** or save/load) |

**Pre-built images are the right default** for air-gapped servers: either push both to a registry the isolated network can reach, or transfer **`docker save`** tarballs and **`docker load`** on the target. You still need **host-mounted** `config/`, `.env`, `data/`, and especially the **GGUF under `models/`** — those are **not** inside the images.

## This repository (GHCR)

Published images for **`dreyna001`** (adjust if you fork):

- `ghcr.io/dreyna001/notable-analyzer-cpu-phi35-llamacpp` (e.g. tag `1.0.0`)
- `ghcr.io/dreyna001/llama-cpp-server-cpu-phi35-llamacpp` (e.g. tag `server`, after you mirror upstream)

**Packages UI:** [github.com/dreyna001?tab=packages](https://github.com/dreyna001?tab=packages)

## One registry vs two

- **One private registry, two repositories (or two tags)** is enough, for example:
  - `registry.example.com/notable/analyzer:1.0.0`
  - `registry.example.com/notable/llama-cpp:server-20250404`
- **Two registries** (e.g. GHCR + internal Harbor) only matters for policy/redundancy; operationally you still pull **two** images.

## Connected machine: build, mirror, push

Replace registry names and tags with yours.

```bash
cd llm_notable_analysis_onprem_docker_cpu_phi35_llamacpp

# 1) Analyzer (your code + Python deps baked in)
docker compose build analyzer
docker tag notable-analyzer-cpu-phi35-llamacpp-analyzer:latest YOUR_REGISTRY/notable-analyzer-cpu-phi35-llamacpp:1.0.0
docker push YOUR_REGISTRY/notable-analyzer-cpu-phi35-llamacpp:1.0.0

# 2) llama.cpp server (mirror upstream; pin digest in prod if you want reproducibility)
docker pull ghcr.io/ggml-org/llama.cpp:server
docker tag ghcr.io/ggml-org/llama.cpp:server YOUR_REGISTRY/llama-cpp-server-cpu-phi35-llamacpp:server
docker push YOUR_REGISTRY/llama-cpp-server-cpu-phi35-llamacpp:server
```

Optional: save both to files for sneakernet/USB (no registry on the air-gapped side):

```bash
docker save YOUR_REGISTRY/notable-analyzer-cpu-phi35-llamacpp:1.0.0 YOUR_REGISTRY/llama-cpp-server-cpu-phi35-llamacpp:server \
  | gzip > notable-analyzer-cpu-phi35-llamacpp-images.tar.gz
```

On the isolated host:

```bash
gunzip -c notable-analyzer-cpu-phi35-llamacpp-images.tar.gz | docker load
```

## Air-gapped host: config and compose

1. Copy the **deployment directory** (or a release tarball): `compose.airgap.yaml`, `config/config.env.example`, `.env.example`, `systemd/`, `docs/`, etc. You do **not** need the full Git history to **run** if images are already loaded.

2. Create `config/config.env`, `.env`, `data/*`, place **GGUF** in `models/`.

3. In `.env`, set at least:

   - `CONTAINER_UID` / `CONTAINER_GID`
   - `LLM_MODEL_FILENAME` (must match the file on disk under `models/`)
   - `LLAMA_*` tuning if needed
   - **Air-gap image references** (if using the same `.env` for compose substitution):

```env
# Example for this project on GHCR (see canonical-repos.md):
# MODEL_SERVING_IMAGE=ghcr.io/dreyna001/llama-cpp-server-cpu-phi35-llamacpp:server
# ANALYZER_IMAGE=ghcr.io/dreyna001/notable-analyzer-cpu-phi35-llamacpp:1.0.0

MODEL_SERVING_IMAGE=YOUR_REGISTRY/llama-cpp-server-cpu-phi35-llamacpp:server
ANALYZER_IMAGE=YOUR_REGISTRY/notable-analyzer-cpu-phi35-llamacpp:1.0.0
```

4. Start **without** building:

```bash
docker compose -f compose.airgap.yaml pull   # if the host can reach your registry
# OR docker load ... first, then skip pull

docker compose -f compose.airgap.yaml up -d
```

5. Verify: `docker compose -f compose.airgap.yaml ps` and logs as in `container-deployment-quickstart.md`.

## What is still not “one pull”

- **Weights**: the GGUF is large and is mounted from the host; ship it separately (media, object store export, second tarball).
- **Secrets / environment**: `config/config.env` and `.env` stay local; do not bake secrets into images.
- **Optional RAG**: FAISS/SQLite under `kb/index/` if you enable RAG.

## Reproducibility

To avoid surprise upgrades when re-pulling `llama.cpp:server`, after a successful test run:

```bash
docker inspect ghcr.io/ggml-org/llama.cpp:server --format '{{.RepoDigests}}'
```

Tag and push that digest on your mirror, or document the digest in your runbook.
