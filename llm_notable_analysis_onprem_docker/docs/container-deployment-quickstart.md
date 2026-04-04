# Container Deployment Quickstart

This quickstart assumes the Dockerized project has been copied to:

`/home/<user>/apps/notable-analyzer`

## Prerequisites (check these before the first `docker compose up`)

- **Docker engine must be running.** On native Linux, enable and start the daemon (e.g. `systemctl enable --now docker` on systemd distros). On **Docker Desktop** (Windows or macOS), open Docker Desktop and wait until it is fully started. If commands fail with something like `open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified`, the Desktop engine is not running.
- **Compose v2:** use `docker compose` (the plugin). A standalone `docker-compose` binary is optional.
- **WSL2:** If your shell is *inside* a Linux distro and `docker` is not found, either:
  - enable **Docker Desktop → Settings → Resources → WSL integration** for that distro (recommended on Windows so WSL uses the same engine as Desktop), or
  - install Docker Engine *inside* that distro (a separate engine). For performance and fewer permission surprises, prefer cloning or copying this project under the Linux home directory (e.g. `~/apps/notable-analyzer`) rather than only under `/mnt/c/...`.
- **`config/config.env` must exist** before `docker compose up`. `compose.yaml` references `./config/config.env` via `env_file`; a missing file causes Compose to error. Copy from `config/config.env.example` first (see below).
- **Valid GGUF on disk:** `model-serving` must load the file named by `LLM_MODEL_FILENAME` (default under `models/`). The analyzer waits until `model-serving` is **healthy**; a wrong path, missing file, or broken image healthcheck keeps the stack from starting fully.
- **Host user IDs:** set `CONTAINER_UID` and `CONTAINER_GID` in `.env` to match the numeric owner of the mounted `data/` and `models/` directories when the analyzer needs to write or read without permission errors.
- **CPU inference and timeouts:** `model-serving` defaults to **4** llama.cpp threads (`LLAMA_THREADS` / `LLAMA_THREADS_BATCH` in `.env`); that is a safe generic default, not auto-detected from your CPU. The analyzer’s **`LLM_TIMEOUT`** in `config/config.env` caps how long it waits for one completion. On **CPU-only** setups (common under Docker Desktop / WSL), Phi-class models plus a long structured prompt can exceed **120s** per request; logs will show `LLM API timeout` while the server is still working. Raise `LLM_TIMEOUT` (e.g. **300–600**) and, if you have headroom, raise thread counts toward your host’s logical core count, then `docker compose up -d --force-recreate`.

## Manual edits required per deployment

Before starting the stack, review these deployment-specific values:

- in `.env`
  - copy `.env.example` to `.env`
  - set `CONTAINER_UID` and `CONTAINER_GID` to match the host account that should own/write mounted files
  - set `LLM_MODEL_FILENAME` if your GGUF filename is different
  - adjust llama.cpp tuning only if you need non-default runtime behavior

- in `systemd/notable-analyzer-stack.service`
  - replace `<user>` in `User=`
  - replace `<user>` in `Group=`
  - replace `<user>` in `WorkingDirectory=`
  - if your deployment root differs, update `WorkingDirectory=` to the real absolute path
  - if Docker is not at `/usr/bin/docker`, update `ExecStart=` and `ExecStop=`

- in `config/config.env`
  - set `LLM_MODEL_NAME` to the actual model id exposed by the inference server
  - fill in Splunk settings if writeback is enabled
  - fill in RAG settings if retrieval grounding is enabled

## 1. Create runtime directories

Create these directories under the deployment root:

- `models/`
- `data/incoming/`
- `data/processed/`
- `data/quarantine/`
- `data/reports/`
- `data/archive/`
- `config/`
- `kb/index/` if using RAG

## 2. Configure the analyzer

Copy:

- `.env.example` -> `.env`
- `config/config.env.example` -> `config/config.env`

Then edit at least:

- `LLM_MODEL_NAME`
- Splunk settings if writeback is enabled
- RAG settings if retrieval grounding is enabled

## 3. Add the GGUF model

Place the model file under:

- `models/<your-model>.gguf`

The default compose configuration expects:

- `models/Phi-3.5-mini-instruct-Q4_K_M.gguf`

If you use a different filename, set:

- `LLM_MODEL_FILENAME=<your-model>.gguf`

in the environment when starting Compose.

## 4. First install / first start

From the deployment root:

```bash
docker compose up -d --build
```

### Optional: scripted first boot (WSL or Linux)

`scripts/wsl-first-up.sh` automates a common first run: ensure `.env` and `config/config.env` exist, set `CONTAINER_UID` / `CONTAINER_GID` from `id -u` / `id -g`, create `data/*` directories, align `LLM_MODEL_NAME` in `config/config.env` with `LLM_MODEL_FILENAME` from `.env`, download the **Phi-3.5-mini-instruct Q4_K_M** GGUF (~2.2 GiB) **only if** `models/<LLM_MODEL_FILENAME>` is missing and the filename matches that default, then `docker compose pull`, `build`, and `up -d --force-recreate`. For any other filename, place the GGUF under `models/` yourself before running the script.

From the deployment root (bash):

```bash
sed -i 's/\r$//' scripts/wsl-first-up.sh   # only if the file has Windows CRLF line endings
bash scripts/wsl-first-up.sh
```

If you want the Docker daemon to start on future boots, enable it once on the host
using your normal OS workflow.

## 5. Verify

Check:

- `docker compose ps`
- `docker compose logs -f model-serving`
- `docker compose logs -f analyzer`

## 6. Submit a test notable

Drop a `.json` or `.txt` file into:

- `data/incoming/`

The analyzer should move the file to `processed/` or `quarantine/` and write a markdown report into `reports/`.

## 7. Stop the stack

```bash
docker compose down
```

## Air-gapped or registry-only hosts

For **pre-pushed** images (no `docker build` on the target), see **`docs/airgap-deployment.md`** and use **`compose.airgap.yaml`** with `MODEL_SERVING_IMAGE` and `ANALYZER_IMAGE` in `.env`.

## Rollback

To roll back after an image or code change:

- restore the prior image tag or prior project contents
- run `docker compose up -d --build` again

## Reboot / restart behavior

After the first install has created the containers, normal reboot and restart
behavior should work like this:

- Docker daemon starts on boot
- Docker restart policies bring the containers back
- the optional `systemd/notable-analyzer-stack.service` wrapper should be treated
  as a lightweight control surface, not as the mechanism that rebuilds images on
  every boot
