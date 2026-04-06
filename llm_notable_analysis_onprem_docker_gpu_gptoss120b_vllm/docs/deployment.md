# Deployment (GPU vLLM + gpt-oss-120b)

Operator guide from "we want this tool" to "the stack is running."

For zero-interruption release strategy, see
[`docs/true-no-lapse-rollout.md`](true-no-lapse-rollout.md).

This bundle keeps a two-service shape:

- `model-serving`: vLLM OpenAI-compatible API on port `8000`
- `analyzer`: file-drop worker that calls `http://model-serving:8000/v1/chat/completions`

## 1) What must exist on the host

Work from the deployment root (the directory containing `compose.yaml`).

### 1.1 Required directories

| Path | Required | Purpose |
|---|---|---|
| `models/` | Yes | Host-staged model artifacts; mounted read-only to `/models` |
| `data/incoming/` | Yes | Inbound files for analysis |
| `data/processed/` | Yes | Successfully processed inputs |
| `data/quarantine/` | Yes | Invalid or failed inputs |
| `data/reports/` | Yes | Markdown outputs |
| `data/archive/` | Yes | Retention archive |
| `config/` | Yes | Analyzer runtime env file (`config.env`) |
| `kb/index/` | Optional | RAG index mount when `RAG_ENABLED=true` |

### 1.2 Required files before startup

| File | Required | Purpose |
|---|---|---|
| `.env` | Yes | Compose substitutions (`VLLM_*`, GPU runtime knobs, UID/GID) |
| `config/config.env` | Yes | Analyzer runtime settings (`LLM_API_URL`, `LLM_MODEL_NAME`, timeouts, sinks) |
| `models/gpt-oss-120b/config.json` | Yes | Minimum readiness indicator for host-staged model artifacts |

## 2) Prerequisites

- Docker Engine running
- Docker Compose v2 (`docker compose`)
- NVIDIA GPU driver installed (`nvidia-smi` works on host)
- NVIDIA Container Toolkit configured for Docker GPU workloads
- Linux hosts: use the distro-provided `docker.service` and enable it at boot.

On Linux hosts:

```bash
sudo systemctl enable --now docker.service
sudo systemctl is-active docker.service
```

On Windows + WSL hosts, Docker daemon lifecycle is managed by Docker Desktop
(not Linux systemd inside the distro).

Quick checks:

```bash
docker version
docker compose version
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

If the last command fails, fix GPU runtime integration before continuing.

## 3) Choose one workflow

| Workflow | Use when | Follow |
|---|---|---|
| A - Connected host | Build and run on one internet-connected host | Sections 4 and 5 |
| B - Jump host to air-gapped target | Build/export on jump host, run on isolated target | Sections 6, 4 (on target), 7 |
| C - Optional registry pull | Hosts can pull prebuilt images from registry | Sections 8 and 9 |

## 4) One-time prep (on runtime host)

Run from deployment root:

```bash
mkdir -p models data/incoming data/processed data/quarantine data/reports data/archive config kb/index
cp .env.example .env
cp config/config.env.example config/config.env
```

Set `.env` at minimum:

- `CONTAINER_UID`, `CONTAINER_GID`
- `VLLM_MODEL_DIRNAME` (default `gpt-oss-120b`)
- `VLLM_SERVED_MODEL_NAME` (default `gpt-oss-120b`)
- `MODEL_SERVING_GPU_COUNT`, `NVIDIA_VISIBLE_DEVICES`

Set `config/config.env` at minimum:

- `LLM_API_URL=http://model-serving:8000/v1/chat/completions`
- `LLM_MODEL_NAME=gpt-oss-120b` (must match `VLLM_SERVED_MODEL_NAME`)
- Splunk values only when sinks are enabled

Model readiness check:

```bash
test -f models/gpt-oss-120b/config.json
```

## 5) Workflow A - Connected host build and run

`compose.yaml` builds analyzer locally and starts vLLM model-serving.

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f model-serving
docker compose logs -f analyzer
```

Stop:

```bash
docker compose down
```

## 6) Workflow B - Jump host export for air-gapped target

On jump host:

1. Clone/copy this bundle.
2. Produce both images (pull or build).
3. Export to tarball.
4. Transfer tarball and bundle to target.

### 6.1 Option A - Pull prebuilt images then save

```bash
docker pull ghcr.io/dreyna001/notable-analyzer-service:<tag>
docker pull ghcr.io/dreyna001/vllm-openai-gptoss120b:<tag>

docker save ghcr.io/dreyna001/notable-analyzer-service:<tag> \
           ghcr.io/dreyna001/vllm-openai-gptoss120b:<tag> \
  | gzip > notable-analyzer-gpu-stack-images.tar.gz
```

### 6.2 Option B - Build analyzer locally, pull vLLM base, then save

```bash
docker compose build analyzer
docker pull vllm/vllm-openai:v0.14.1

docker save notable-analyzer-service-analyzer:latest \
           vllm/vllm-openai:v0.14.1 \
  | gzip > notable-analyzer-gpu-stack-images.tar.gz
```

Transfer to target:

- `notable-analyzer-gpu-stack-images.tar.gz`
- this bundle directory (`compose.airgap.yaml`, examples, docs, and any files you use)

## 7) Workflow B - Air-gapped target run

Load images:

```bash
gunzip -c notable-analyzer-gpu-stack-images.tar.gz | docker load
docker images
```

Complete section 4 on this target host, then set `.env` image refs to match
loaded image names exactly:

```env
ANALYZER_IMAGE=<loaded-analyzer-image:tag>
MODEL_SERVING_IMAGE=<loaded-vllm-image:tag>
```

Start:

```bash
docker compose -f compose.airgap.yaml up -d
docker compose -f compose.airgap.yaml ps
```

## 8) Optional workflow C - Publish images to registry

Connected host example:

```bash
docker compose build analyzer
docker tag notable-analyzer-service-analyzer:latest ghcr.io/dreyna001/notable-analyzer-service:<tag>
docker push ghcr.io/dreyna001/notable-analyzer-service:<tag>

docker pull vllm/vllm-openai:v0.14.1
docker tag vllm/vllm-openai:v0.14.1 ghcr.io/dreyna001/vllm-openai-gptoss120b:<tag>
docker push ghcr.io/dreyna001/vllm-openai-gptoss120b:<tag>
```

## 9) Optional workflow C - Pull and run from registry

Set `.env`:

```env
ANALYZER_IMAGE=ghcr.io/dreyna001/notable-analyzer-service:<tag>
MODEL_SERVING_IMAGE=ghcr.io/dreyna001/vllm-openai-gptoss120b:<tag>
```

Run:

```bash
docker compose -f compose.airgap.yaml pull
docker compose -f compose.airgap.yaml up -d
```

## 10) Smoke tests (required)

Health checks:

```bash
curl -sf http://127.0.0.1:8000/health
docker compose ps
```

Chat completion sanity check:

```bash
curl -sS http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-oss-120b","messages":[{"role":"user","content":"Respond with OK."}],"max_tokens":16}'
```

File-drop flow check:

- place one `.json` or `.txt` file into `data/incoming/`
- verify move to `data/processed/` or `data/quarantine/`
- verify report in `data/reports/`

## 11) Common failures and first checks

| Symptom | Likely cause | First checks |
|---|---|---|
| `model-serving` unhealthy | GPU runtime not wired | `nvidia-smi`, Docker GPU test command, container logs |
| vLLM exits during load | Model artifacts missing/incomplete | `models/gpt-oss-120b/config.json` and shard files present |
| analyzer LLM timeouts | Long generations or overload | increase `LLM_TIMEOUT`, reduce concurrency, review model logs |
| model mismatch errors | Served model name drift | match `VLLM_SERVED_MODEL_NAME` and `LLM_MODEL_NAME` |
| permission denied on mounted dirs | UID/GID mismatch | check `CONTAINER_UID/GID` and host ownership |

## 12) Rollback steps

1. Keep previous known-good analyzer and model-serving image tags.
2. In `.env`, revert `ANALYZER_IMAGE` and `MODEL_SERVING_IMAGE` (or rebuild
   previous analyzer tag).
3. Re-apply previous stable `config/config.env` values.
4. Restart stack:

```bash
docker compose -f compose.airgap.yaml up -d --force-recreate
```

5. Re-run smoke tests from section 10.

## 13) Responsibility boundaries

Package provides:

- compose stack definitions
- analyzer image build recipe
- example runtime configuration
- docs for startup, smoke tests, troubleshooting, rollback

Operator must provide:

- host GPU runtime prerequisites and policy controls
- model artifact staging and provenance checks
- production secrets and env values
- monitoring, backup/retention policy decisions, and access controls

## 14) Optional systemd wrapper

Edit `systemd/notable-analyzer-stack.service` (`User`, `Group`,
`WorkingDirectory`, Docker binary path), then install and enable it on hosts
where boot-time stack recovery is required.

## 15) Which compose file to use

| Goal | Compose file |
|---|---|
| Connected host build + run | `compose.yaml` |
| Air-gapped or registry-only image flow | `compose.airgap.yaml` |
