# Dockerized On-Prem Notable Analyzer (Phi-3.5 + llama.cpp reference stack)

This directory is a **reference Docker bundle**: default **Phi-3.5-mini** GGUF plus upstream **`llama.cpp`** OpenAI-compatible **model-serving** (CPU-threaded defaults in `compose.yaml`). It is a sibling of the host-venv path in `llm_notable_analysis_onprem`.

The **analyzer** is packaged as **`notable-analyzer-service`** on GHCR: a **generic Python worker** that talks to whatever inference endpoint you configure in `config/config.env` (`LLM_API_URL`). The same container image does **not** imply CPU-only for your whole deployment—you can point it at **GPU / vLLM** or another OpenAI-compatible server; only the **model-serving** side changes (separate compose project or image recommended for large GPU stacks).

**Where the code and images live:** [docs/canonical-repos.md](docs/canonical-repos.md) — GitHub repo URL, path to this folder in Git, and GHCR image names (`ghcr.io/dreyna001/...`).

## Scope

- `onprem_service/` contains the analyzer runtime copied from the current on-prem package.
- `onprem_rag/` contains the optional retrieval-grounding runtime copied from the current sibling package.
- `compose.yaml` runs two containers:
  - `model-serving` using the upstream `llama.cpp` server image (CPU-threaded defaults)
  - `analyzer` using a local Python image build from this directory (`Dockerfile.analyzer` → publish as **`notable-analyzer-service`**)

## Analyzer container image (`notable-analyzer-service`)

- **Base:** `python:3.13-slim-bookworm` — official slim Debian image so heavy Python deps (e.g. optional RAG stacks) install reliably compared to Alpine.
- **Role:** file-drop ingest, HTTP client to the LLM API, optional RAG, report output — **not** the vLLM or llama.cpp server.
- **CPU vs GPU:** the analyzer process does not need a GPU to call a remote/local OpenAI-compatible API; GPU matters for the **inference** service you run separately.

## Host layout

Canonical operator guide (directory tree, required files, mount map, build vs pull vs air-gap): **[docs/deployment.md](docs/deployment.md)**.

Typical deployment root: `/home/<user>/apps/notable-analyzer`. Runtime paths under that root: `models/`, `data/{incoming,processed,quarantine,reports,archive}/`, `config/config.env`, optional `kb/index/`.

## Key Files

- `docs/canonical-repos.md`: Git repo + GHCR image URLs for this project
- `docs/deployment.md`: **single deployment guide** (host files, env, scenarios: local build, GHCR pull, air-gap)
- `scripts/wsl-first-up.sh`: optional first-time helper (env + dirs + optional GGUF download + `compose up`); details in `docs/deployment.md`
- `docs/ghcr-login-and-push.md`: log in to GHCR (password = your PAT) and push images
- `compose.airgap.yaml`: same stack as `compose.yaml` but **no `build`** — only `MODEL_SERVING_IMAGE` and `ANALYZER_IMAGE` from `.env`
- `Dockerfile.analyzer`: builds the analyzer container
- `requirements.analyzer-docker.txt`: analyzer Python dependencies
- `.env.example`: Compose variables for UID/GID, model filename, and llama.cpp tuning
- `compose.yaml`: two-service Docker stack (build analyzer locally); Compose **project name** `notable-analyzer-service` (local build image: `notable-analyzer-service-analyzer:latest`)
- `config/config.env.example`: example runtime env file for the analyzer
- `systemd/notable-analyzer-stack.service`: host unit example to keep the stack running

## Manual Edits Per Deployment

The following values must be reviewed and filled in for each unique deployment:

- `systemd/notable-analyzer-stack.service`
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

- **WSL / Docker Desktop:** If `docker` is missing inside WSL, enable WSL integration in Docker Desktop for that distro, or install Docker in the distro. The engine must be running before `docker compose` (see `docs/deployment.md` prerequisites).
- Incoming notables remain host data and are mounted into the analyzer container.
- GGUF model files remain on the host and are mounted into the inference container.
- The analyzer defaults to the non-SDK runtime path via `onprem_service.onprem_main_nonsdk`.
- First install/build is an explicit operator step; boot-time recovery should rely on Docker restart policies plus a lightweight `systemd` wrapper if desired.
- **`llm_notable_analysis_onprem`** documents host-venv deployment with **vLLM**-style URLs for larger models; this folder is the **llama.cpp + default Phi-3.5** Docker reference, while the **analyzer image name** stays **`notable-analyzer-service`** for reuse.
- If later changes prove minimal, this fork can be collapsed back into the main on-prem package.
