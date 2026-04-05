# Dockerized On-Prem Notable Analyzer (CPU, Phi-3.5, llama.cpp)

This directory is the **CPU-bound reference** Docker bundle: **Phi-3.5-mini** (default GGUF) plus upstream **`llama.cpp`** OpenAI-compatible serving. It is a sibling of the host-venv path in `llm_notable_analysis_onprem` and is intentionally **not** the GPU / **vLLM** / large-model (for example **gpt-oss-120B**) stack—use a **separate** compose project and GHCR image names for that.

**Where the code and images live:** [docs/canonical-repos.md](docs/canonical-repos.md) — GitHub repo URL, path to this folder in Git, and GHCR image names (`ghcr.io/dreyna001/...`).

## Scope

- `onprem_service/` contains the analyzer runtime copied from the current on-prem package.
- `onprem_rag/` contains the optional retrieval-grounding runtime copied from the current sibling package.
- `compose.yaml` runs two containers:
  - `model-serving` using the upstream `llama.cpp` server image (CPU-threaded defaults)
  - `analyzer` using a local Python image build from this directory

## Host Layout

The intended deployment root on a Linux host is:

`/home/<user>/apps/notable-analyzer`

When deployed there, the main runtime paths are:

- `./models`
- `./data/incoming`
- `./data/processed`
- `./data/quarantine`
- `./data/reports`
- `./data/archive`
- `./config/config.env`
- `./kb/index`

## Key Files

- `docs/canonical-repos.md`: Git repo + GHCR image URLs for this project
- `scripts/wsl-first-up.sh`: optional first-time helper (env + dirs + optional GGUF download for known filenames + `compose up`); see `docs/container-deployment-quickstart.md`
- `docs/ghcr-login-and-push.md`: log in to GHCR (password = your PAT) and push images
- `docs/airgap-deployment.md`: pre-built images, registry mirror, `docker save` / `docker load`, and `compose.airgap.yaml`
- `compose.airgap.yaml`: same stack as `compose.yaml` but **no `build`** — only `MODEL_SERVING_IMAGE` and `ANALYZER_IMAGE` from `.env`
- `Dockerfile.analyzer`: builds the analyzer container
- `requirements.analyzer-docker.txt`: analyzer Python dependencies
- `.env.example`: Compose variables for UID/GID, model filename, and llama.cpp tuning
- `compose.yaml`: two-service Docker stack (build analyzer locally); Compose **project name** `notable-analyzer-cpu-phi35-llamacpp`
- `config/config.env.example`: example runtime env file for the analyzer
- `systemd/notable-analyzer-stack-cpu-phi35-llamacpp.service`: host unit example to keep the stack running

## Manual Edits Per Deployment

The following values must be reviewed and filled in for each unique deployment:

- `systemd/notable-analyzer-stack-cpu-phi35-llamacpp.service`
  - replace `<user>` in `User=`
  - replace `<user>` in `Group=`
  - replace `<user>` in `WorkingDirectory=`
  - if the deployment root is not `/home/<user>/apps/notable-analyzer`, update `WorkingDirectory=` to the real absolute path
  - if Docker is installed at a different binary path, update `ExecStart=` and `ExecStop=`

- `.env`
  - copy from `.env.example`
  - set `CONTAINER_UID` and `CONTAINER_GID` to match the host account that should own/write mounted files
  - set `LLM_MODEL_FILENAME` if the GGUF filename differs from the default
  - adjust llama.cpp tuning flags only if you need non-default runtime behavior

- `config/config.env`
  - copy from `config/config.env.example`
  - set the real `LLM_MODEL_NAME`
  - set Splunk values if writeback is enabled
  - set RAG values if retrieval grounding is enabled

- host runtime files
  - place the actual GGUF under `models/`
  - create the required `data/`, `config/`, and optional `kb/index/` directories

## Notes

- **WSL / Docker Desktop:** If `docker` is missing inside WSL, enable WSL integration in Docker Desktop for that distro, or install Docker in the distro. The engine must be running before `docker compose` (see `docs/container-deployment-quickstart.md` prerequisites).
- Incoming notables remain host data and are mounted into the analyzer container.
- GGUF model files remain on the host and are mounted into the inference container.
- The analyzer defaults to the non-SDK runtime path via `onprem_service.onprem_main_nonsdk`.
- First install/build is an explicit operator step; boot-time recovery should rely on Docker restart policies plus a lightweight `systemd` wrapper if desired.
- **`llm_notable_analysis_onprem`** documents and defaults toward **vLLM** and OpenAI-compatible URLs for larger on-prem models; this folder is the **small-model / CPU / llama.cpp** Docker reference only.
- If later changes prove minimal, this fork can be collapsed back into the main on-prem package.
