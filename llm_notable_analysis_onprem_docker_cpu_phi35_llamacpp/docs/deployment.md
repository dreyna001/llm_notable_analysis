# Deployment (all scenarios)

Single operator guide for this bundle. Image names and clone URLs: [canonical-repos.md](canonical-repos.md). Publishing to GHCR: [ghcr-login-and-push.md](ghcr-login-and-push.md).

---

## 1) What must exist on the host (deployment root)

Pick a directory (example: `/home/<user>/apps/notable-analyzer`). All paths below are **relative to that root**.

### 1.1 Directory tree you create or ship

| Path | Required | Purpose |
|------|----------|---------|
| `models/` | Yes | GGUF weights; mounted read-only into **model-serving** as `/models` |
| `data/incoming/` | Yes | File-drop ingest; mounted as `/watch/incoming` in **analyzer** |
| `data/processed/` | Yes | Successful ingests |
| `data/quarantine/` | Yes | Rejected ingests |
| `data/reports/` | Yes | Markdown reports |
| `data/archive/` | Yes | Archive |
| `config/` | Yes | Holds `config.env` for **analyzer** |
| `kb/index/` | If RAG enabled | Mount read-only into **analyzer** as `/kb/index` (e.g. `kb.sqlite3`, `kb.faiss`) |

### 1.2 Files you must have before `compose up`

| File | Required | Purpose |
|------|----------|---------|
| `.env` | Yes | Compose substitution: UID/GID, `LLM_MODEL_FILENAME`, `LLAMA_*`, and (pre-built path) `ANALYZER_IMAGE` / `MODEL_SERVING_IMAGE` |
| `config/config.env` | Yes | Analyzer runtime: `LLM_API_URL`, `LLM_MODEL_NAME`, Splunk, RAG, timeouts, etc. |
| `models/<name>.gguf` | Yes | Model file; name must match `LLM_MODEL_FILENAME` in `.env` |

### 1.3 What comes from Git (this repo folder)

At minimum for **running** containers you need:

- `compose.yaml` **or** `compose.airgap.yaml` (plus the other compose file if you switch modes later)
- `Dockerfile.analyzer`, `requirements.analyzer-docker.txt`, `.dockerignore` (only for **build** scenario)
- `onprem_service/`, `onprem_rag/` (build context for analyzer image)
- `.env.example`, `config/config.env.example`
- Optional: `scripts/wsl-first-up.sh`, `systemd/notable-analyzer-stack.service`, `docs/`

**Not in Git (normal):** `.env`, `config/config.env`, `models/*.gguf`, runtime files under `data/*`, RAG index files under `kb/index/` (except `.gitkeep` if present).

### 1.4 Container mount map (for debugging)

| Host path | Service | In-container path |
|-----------|---------|-------------------|
| `./models` | model-serving | `/models` (read-only) |
| `./data/incoming` … `archive` | analyzer | `/watch/incoming` … `/watch/archive` |
| `./kb/index` | analyzer | `/kb/index` (read-only) |

---

## 2) Prerequisites

- Docker engine running; `docker compose` available  
- WSL: enable Docker Desktop **WSL integration** if `docker` is missing in the distro  

```bash
docker version
docker compose version
```

---

## 3) One-time prep (every scenario)

Run from the **deployment root** (the folder that contains `compose.yaml`).

```bash
mkdir -p models data/incoming data/processed data/quarantine data/reports data/archive config kb/index
cp .env.example .env
cp config/config.env.example config/config.env
```

Edit **`.env`** at least:

- `CONTAINER_UID`, `CONTAINER_GID` (match numeric owner of `data/` and `models/` on the host)
- `LLM_MODEL_FILENAME` (must match the GGUF filename under `models/`)

Edit **`config/config.env`** at least:

- `LLM_MODEL_NAME` (must match the model id the inference server exposes; for default llama.cpp + Phi GGUF this is usually the GGUF filename)
- `LLM_API_URL` (default in example targets `http://model-serving:8000/v1/chat/completions` inside the compose network)

Place the model:

```text
models/<same-as-LLM_MODEL_FILENAME>
```

**CPU note:** default llama.cpp thread counts are conservative. If you see `LLM API timeout` under load, raise `LLM_TIMEOUT` in `config/config.env` and/or `LLAMA_THREADS` in `.env`, then recreate containers.

---

## 4) Scenario A — Build analyzer on this host (internet for build)

Uses **`compose.yaml`**: pulls **model-serving** image from upstream; **builds** analyzer from `Dockerfile.analyzer` (base image + `pip install` need network unless you use a private mirror).

```bash
docker compose up -d --build
```

Verify:

```bash
docker compose ps
docker compose logs -f model-serving
docker compose logs -f analyzer
```

Stop:

```bash
docker compose down
```

Optional first boot script (Linux/WSL bash):

```bash
sed -i 's/\r$//' scripts/wsl-first-up.sh   # only if CRLF
bash scripts/wsl-first-up.sh
```

---

## 5) Scenario B — Pre-built images, registry reachable (no `docker build` on host)

Uses **`compose.airgap.yaml`**. Set image references in **`.env`** (replace registry/user if not `dreyna001`):

```env
ANALYZER_IMAGE=ghcr.io/dreyna001/notable-analyzer-service:1.0.0
MODEL_SERVING_IMAGE=ghcr.io/dreyna001/llama-cpp-server-cpu-phi35-llamacpp:server
```

Private GHCR packages:

```bash
docker login ghcr.io -u <github-username>
```

Start:

```bash
docker compose -f compose.airgap.yaml pull
docker compose -f compose.airgap.yaml up -d
```

Verify / stop: same as scenario A but pass `-f compose.airgap.yaml` on every `docker compose` command.

---

## 6) Scenario C — Air-gapped or no registry (image tarball)

On a **connected** machine that already has both images loaded:

```bash
docker save ghcr.io/dreyna001/notable-analyzer-service:1.0.0 \
           ghcr.io/dreyna001/llama-cpp-server-cpu-phi35-llamacpp:server \
  | gzip > notable-analyzer-stack-images.tar.gz
```

Copy **`notable-analyzer-stack-images.tar.gz`** plus a **folder copy** of this bundle (or a release tarball containing at least: `compose.airgap.yaml`, `.env.example`, `config/config.env.example`, and any scripts/systemd you use) to the target.

On the **target** host:

```bash
gunzip -c notable-analyzer-stack-images.tar.gz | docker load
```

Complete **section 3** (dirs, `.env`, `config/config.env`, GGUF). In **`.env`**, set `ANALYZER_IMAGE` and `MODEL_SERVING_IMAGE` to the **same references** as the tags you loaded (if you retagged after load, use those names).

**Do not run `pull`** if the host has no registry access:

```bash
docker compose -f compose.airgap.yaml up -d
```

---

## 7) Smoke test

Drop a `.json` or `.txt` file into `data/incoming/`. Expect: file moves to `data/processed/` or `data/quarantine/`, and a report under `data/reports/`.

---

## 8) Optional: systemd

Edit `systemd/notable-analyzer-stack.service` (`User`, `Group`, `WorkingDirectory`, docker path), install the unit, enable on boot. The unit only runs `docker compose up` / `stop` in `WorkingDirectory`—it does not rebuild images.

---

## 9) Which compose file when

| Goal | Compose file |
|------|----------------|
| Build analyzer here | `compose.yaml` |
| Only pull pre-built images | `compose.airgap.yaml` |
