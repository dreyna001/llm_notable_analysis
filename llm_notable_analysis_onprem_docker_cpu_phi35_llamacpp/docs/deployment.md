# Deployment

Operator guide from “we want this tool” to “the stack is running.” Pick **one workflow** from the table below; do not mix steps from different workflows unless you know why.

For zero-interruption release strategy, see
[`docs/true-no-lapse-rollout.md`](true-no-lapse-rollout.md).

---

## 1) What must exist on the host (deployment root)

You need **this Docker bundle on disk** (the folder that contains `compose.yaml`). Everything in section 1.3 must live under that folder. You can use the clone path as the deployment root, or copy that subtree to another path (example: `/home/<user>/apps/notable-analyzer`). All paths below are **relative to that deployment root**.

### 1.0 Get the bundle (clone or copy)

**From GitHub (typical):** clone the monorepo, then work inside this subfolder. That subfolder is your deployment root for `docker compose`.

```bash
git clone https://github.com/dreyna001/llm_notable_analysis.git
cd llm_notable_analysis/llm_notable_analysis_onprem_docker_cpu_phi35_llamacpp
```

Use your fork or internal mirror URL if applicable. **Canonical Git + GHCR names** for this bundle: section 6 table. Overview: [README.md](../README.md).

**Air-gap / no Git on target:** copy the same directory tree onto the host (zip, `rsync`, artifact tarball). The deployment root must still contain `compose.yaml`, `onprem_service/`, `onprem_rag/`, and the other files listed in section 1.3.

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

The following are what you get from the clone or copy in section 1.0. At minimum for **running** containers you need:

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

- Docker Engine running; **Compose v2** available as the plugin (`docker compose`, not the legacy `docker-compose` binary unless you know it maps to the same stack).
- **Minimum:** Docker Engine **24.0+** and Compose **v2** (this bundle uses modern compose features such as `depends_on: condition: service_healthy`).
- **Validated:** Docker Engine **27.4.1** with Compose **v2** shipped alongside that engine (your `docker compose version` line should show `v2.x`).
- WSL: enable Docker Desktop **WSL integration** if `docker` is missing in the distro.
- Linux hosts: use the distro-provided `docker.service` and enable it at boot.

On Linux hosts:

```bash
sudo systemctl enable --now docker.service
sudo systemctl is-active docker.service
```

On Windows + WSL hosts, Docker daemon lifecycle is managed by Docker Desktop
(not Linux systemd inside the distro).

```bash
docker version
docker compose version
```

---

## 3) Pick your workflow

Use **one** row below. Later headings name the workflow (A, B, or optional C) where it matters.

| Workflow | When | Where you work | Follow |
|----------|------|----------------|--------|
| **A — Single connected host** | One machine has internet and is where the stack runs | Same host for build + run | section 4 on that host, then **section 5** |
| **B — Jump server → air-gapped target** | Internet only on a jump/build host; production is air-gapped; you transfer files with `scp` (or similar), **no registry on the target** | Jump: build/save images. Target: load + run | **section 6** (jump), **section 4** (target only), **section 7** (target `up`) |
| **C — Optional: GHCR** | Hosts can reach a registry; you want `docker pull` instead of image tarballs | Registry + login | **section 8** (publish), **section 9** (pull + run). **Skip** if you use workflow B. |

**Workflow B (jump → air-gap) in order**

1. **Jump server (internet):** Clone or copy this bundle. Build the images you need (`docker compose build`, and/or `docker pull` for `model-serving` if you are baking that in). Run **`docker save`** (see section 6) to produce an image tarball. **Recommended:** skip section 4 on the jump host. Only run section 4 there if you intentionally **smoke-test** with `docker compose up`.
2. **Transfer:** `scp` (or USB, artifact repo) the image tarball **and** a copy of this bundle (at least `compose.airgap.yaml`, `.env.example`, `config/config.env.example`, `onprem_service/` / `onprem_rag/` only if the target will rebuild—which air-gap usually does not—or any extra files you use) to the air-gapped host.
3. **Air-gapped target:** `docker load` from the tarball. Then run **full section 4** on the target (dirs, `.env`, `config/config.env`, GGUF under `models/`, UID/GID for **this** host). Then **section 7** (`compose.airgap.yaml` — no `pull`).

---

## 4) One-time prep (host that runs the stack)

**Applies to:** the machine where you will run **`docker compose up`** (workflow A: that connected host; workflow B: normally the **air-gapped target**).

**Workflow B — jump server (recommended):** Treat the jump host as a **build and export** machine only: clone/bundle, `docker compose build` / `docker pull`, `docker save`, then `scp` the image tarball and bundle to the target. **Do not** bother with `mkdir`, `.env` / `config/config.env`, or the GGUF on the jump host for that path. **Always** run the full checklist below on the **air-gapped target** before `compose up` there.

**Workflow B — optional:** If you want to **smoke-test** the full stack on the jump host before transfer, run **this entire section 4** on the jump host as well (same as workflow A), then still run **section 4 again on the target** using that host’s UID/GID and paths.

Run from the **deployment root** (the folder that contains `compose.yaml` or `compose.airgap.yaml`).

```bash
mkdir -p models data/incoming data/processed data/quarantine data/reports data/archive config kb/index
cp .env.example .env
cp config/config.env.example config/config.env
```

Edit **`.env`** at least:

- `CONTAINER_UID`, `CONTAINER_GID` (match numeric owner of `data/` and `models/` on the host)
- `LLM_MODEL_FILENAME` (must match the GGUF filename under `models/`)

Get `CONTAINER_UID` / `CONTAINER_GID` on the target Linux/WSL host:

```bash
# Current shell user
id -u
id -g

# Or a specific service account
id -u <user>
id -g <user>
```

If directories already exist and you want container writes to match existing ownership:

```bash
stat -c '%u %g' data/incoming
stat -c '%u %g' models
```

Edit **`config/config.env`** at least:

- `LLM_MODEL_NAME` (must match the model id the inference server exposes; for default llama.cpp + Phi GGUF this is usually the GGUF filename)
- `LLM_API_URL` (default in example targets `http://model-serving:8000/v1/chat/completions` inside the compose network)

Place the model:

```text
models/<same-as-LLM_MODEL_FILENAME>
```

**CPU note:** default llama.cpp thread counts are conservative. If you see `LLM API timeout` under load, raise `LLM_TIMEOUT` in `config/config.env` and/or `LLAMA_THREADS` in `.env`, then recreate containers.

---

## 5) Workflow A — Single connected host (build + run here)

**Workflow A.** **Before `compose up`:** finish **section 4** on this host (`mkdir`, `cp` to create `.env` and `config/config.env`, edit both, place GGUF under `models/`).

Uses **`compose.yaml`**: pulls **model-serving** from the upstream registry; **builds** **analyzer** from `Dockerfile.analyzer` (base image + `pip install` need network unless you use a private mirror).

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

## 6) Workflow B — Jump server (internet): images + bundle to transfer

**Workflow B.** **Recommended:** no section 4 on the jump host—only build, `docker save`, and transfer. Use section 4 on the jump host only if you **smoke-test** with `docker compose up` before `scp`.

### Canonical URLs (this project)

| Item | Location |
|------|----------|
| **Git repository** | `https://github.com/dreyna001/llm_notable_analysis.git` |
| **This Docker bundle in the repo** | `llm_notable_analysis/llm_notable_analysis_onprem_docker_cpu_phi35_llamacpp/` |
| **GHCR — analyzer image** | `ghcr.io/dreyna001/notable-analyzer-service:<tag>` (example tag below: `1.0.0`; use the tag you published) |
| **GHCR — model-serving mirror** | `ghcr.io/dreyna001/llama-cpp-server-cpu-phi35-llamacpp:server` |
| **Upstream model-serving** (used by `compose.yaml` when you `compose pull model-serving`) | `ghcr.io/ggml-org/llama.cpp:server` |

### 6.1 Get the bundle on the jump host

```bash
git clone https://github.com/dreyna001/llm_notable_analysis.git
cd llm_notable_analysis/llm_notable_analysis_onprem_docker_cpu_phi35_llamacpp
```

### 6.2 Option A — Pull both images from GHCR (recommended if you already published them)

Log in if the packages are private:

```bash
docker login ghcr.io -u dreyna001
```

Pull (replace `1.0.0` with your real **analyzer** tag if different):

```bash
docker pull ghcr.io/dreyna001/notable-analyzer-service:1.0.0
docker pull ghcr.io/dreyna001/llama-cpp-server-cpu-phi35-llamacpp:server
```

### 6.3 Option B — Build analyzer locally; pull upstream llama.cpp

From the deployment root (`llm_notable_analysis_onprem_docker_cpu_phi35_llamacpp`):

```bash
docker compose pull model-serving
docker compose build analyzer
```

Resulting image names (fixed by this repo’s `compose.yaml` / project name):

- **Analyzer:** `notable-analyzer-service-analyzer:latest`
- **Model-serving:** `ghcr.io/ggml-org/llama.cpp:server`

### 6.4 Save images to one tarball

**After option A** (`docker save` must list the **exact** same references you will set in `.env` on the target):

```bash
docker save ghcr.io/dreyna001/notable-analyzer-service:1.0.0 \
           ghcr.io/dreyna001/llama-cpp-server-cpu-phi35-llamacpp:server \
  | gzip > notable-analyzer-stack-images.tar.gz
```

**After option B:**

```bash
docker save notable-analyzer-service-analyzer:latest \
           ghcr.io/ggml-org/llama.cpp:server \
  | gzip > notable-analyzer-stack-images.tar.gz
```

### 6.5 Copy to the air-gapped host (`scp`)

Transfer at least:

- **`notable-analyzer-stack-images.tar.gz`**
- This **bundle directory** from the clone (`compose.airgap.yaml`, `.env.example`, `config/config.env.example`, plus any of `docs/`, `systemd/`, scripts you use). You do **not** need `onprem_service/` / `onprem_rag/` on the target unless you will run `docker build` there.

---

## 7) Workflow B — Air-gapped target: load, prep, run

**Workflow B.** **All of section 4** applies on **this** host before `compose up`.

### 7.1 Load images

```bash
gunzip -c notable-analyzer-stack-images.tar.gz | docker load
```

Check loaded tags match what you will reference in `.env`:

```bash
docker images
```

### 7.2 Configure for `compose.airgap.yaml`

Complete **section 4** (dirs, `cp` examples → `.env` and `config/config.env`, edit for **this** host’s UID/GID, place GGUF).

In **`.env`**, set **`ANALYZER_IMAGE`** and **`MODEL_SERVING_IMAGE`** to the **same strings** you used in **`docker save`** on the jump host (section 6.4). After `docker load`, `docker images` on the target should show those repositories/tags.

**If you used section 6.4 option A (GHCR pulls + save):**

```env
ANALYZER_IMAGE=ghcr.io/dreyna001/notable-analyzer-service:1.0.0
MODEL_SERVING_IMAGE=ghcr.io/dreyna001/llama-cpp-server-cpu-phi35-llamacpp:server
```

(Change `1.0.0` if you saved a different analyzer tag.)

**If you used section 6.4 option B (local build + upstream llama):**

```env
ANALYZER_IMAGE=notable-analyzer-service-analyzer:latest
MODEL_SERVING_IMAGE=ghcr.io/ggml-org/llama.cpp:server
```

### 7.3 Start (no registry)

Do **not** run `pull` on a host without registry access:

```bash
docker compose -f compose.airgap.yaml up -d
```

Verify / stop: same as section 5 but always pass `-f compose.airgap.yaml`.

---

## 8) Optional workflow C — Publish images to GHCR (connected host)

**Skip** if you only use jump server + tarball (workflow B).

Create/use a GitHub PAT with `read:packages` and `write:packages`. Login:

```bash
docker logout ghcr.io
docker login ghcr.io -u dreyna001
```

Use your GitHub username when logging in to GHCR if you use a fork or different account.

Build and push **analyzer**:

```bash
git clone https://github.com/dreyna001/llm_notable_analysis.git
cd llm_notable_analysis/llm_notable_analysis_onprem_docker_cpu_phi35_llamacpp
docker compose build analyzer
docker tag notable-analyzer-service-analyzer:latest ghcr.io/dreyna001/notable-analyzer-service:1.0.0
docker push ghcr.io/dreyna001/notable-analyzer-service:1.0.0
```

Mirror and push **model-serving** (optional mirror name):

```bash
docker pull ghcr.io/ggml-org/llama.cpp:server
docker tag ghcr.io/ggml-org/llama.cpp:server ghcr.io/dreyna001/llama-cpp-server-cpu-phi35-llamacpp:server
docker push ghcr.io/dreyna001/llama-cpp-server-cpu-phi35-llamacpp:server
```

`denied` usually means wrong PAT scopes or username; `docker logout ghcr.io` and login again if stale.

---

## 9) Optional workflow C — Run from registry (`docker pull`)

**Skip** if you use workflow B (air-gap, no pull).

Uses **`compose.airgap.yaml`**. In **`.env`**:

```env
ANALYZER_IMAGE=ghcr.io/dreyna001/notable-analyzer-service:1.0.0
MODEL_SERVING_IMAGE=ghcr.io/dreyna001/llama-cpp-server-cpu-phi35-llamacpp:server
```

Use the same **analyzer** tag you published; `1.0.0` is an example. Private GHCR:

```bash
docker login ghcr.io -u dreyna001
```

Use your GitHub username if packages are under a different account.

Finish **section 4** on this host, then:

```bash
docker compose -f compose.airgap.yaml pull
docker compose -f compose.airgap.yaml up -d
```

---

## 10) Smoke test

Drop a `.json` or `.txt` file into `data/incoming/`. Expect: file moves to `data/processed/` or `data/quarantine/`, and a report under `data/reports/`.

---

## 11) Optional: systemd

Edit `systemd/notable-analyzer-stack.service` (`User`, `Group`, `WorkingDirectory`, docker path), install the unit, enable on boot. The unit only runs `docker compose up` / `stop` in `WorkingDirectory`—it does not rebuild images.

---

## 12) Which compose file when

| Goal | Compose file |
|------|----------------|
| Workflow A: build analyzer here + pull model-serving | `compose.yaml` |
| Workflow B or C: pre-built images only (air-gap load or registry pull) | `compose.airgap.yaml` |
