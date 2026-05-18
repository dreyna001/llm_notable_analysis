# Notable analyzer Docker image

Docker packaging for the same runtime as `llm_notable_analysis_onprem_systemd/` on
host systemd: analyzer worker only (file-drop ingest, LiteLLM client, optional
Postgres RAG). LiteLLM, vLLM, and Postgres remain separate services.

## Source packages (repo root)

| Package | Path |
|---------|------|
| Analyzer | `llm_notable_analysis_onprem_systemd/` |
| LLM SDK | `onprem-llm-sdk/` |
| RAG | `onprem_rag_notable_analysis/` |

The image does **not** copy duplicate trees from this directory. Dependencies
come from each package `pyproject.toml`, matching `scripts/install.sh`.

## Build

From the **repository root** (required build context):

```bash
docker build -f llm_notable_analysis_analyzer_image/Dockerfile.analyzer -t notable-analyzer-service .
```

On Windows hosts targeting Linux deployment, build from WSL with
`--platform linux/amd64` when needed.

The Dockerfile uses a **multi-stage build**: packages install in a builder stage;
only installed site-packages land in the final image (no leftover `/deps` source).

## Run (compose)

```bash
cd llm_notable_analysis_analyzer_image
cp config.env.docker.example config.env
# Edit LLM_API_URL (and RAG/Postgres settings if enabled)
docker compose up -d --build
```

`config.env` is optional so `docker compose config` works in CI and review
without local files. For real runs, copy `config.env.docker.example` and keep
deployment-specific endpoints, tokens, and capability flags there.

Copy a test notable JSON file into `data/notables/incoming/` on your machine. That
folder is mounted as `/var/notables/incoming` inside the container.

### Linux bind-mount permissions

The container writes reports, processed files, quarantine files, and healthcheck
probes as the container user. The compose file runs the container as
`${ANALYZER_UID:-1000}:${ANALYZER_GID:-1000}` so Linux hosts can match the
container process to the owner of the bind-mounted folders.

On Linux, set these once before `docker compose up`:

```bash
echo "ANALYZER_UID=$(id -u)" > .env
echo "ANALYZER_GID=$(id -g)" >> .env
mkdir -p data/notables/{incoming,processed,quarantine,reports,archive}
```

If the folders already exist with different ownership, fix them on the host:

```bash
sudo chown -R "$(id -u):$(id -g)" data/notables
```

Docker Desktop on Windows usually handles this mapping automatically, but Linux
Docker Engine enforces host filesystem permissions directly.

### Host folder vs Docker-managed volume

- **Bind mount** (`./data/notables:/var/notables`): files live in a normal folder on
  your machine. You can open `data/notables/incoming/` in Explorer or `cp` test files
  directly. Best for local demos and smoke tests.
- **Named volume** (`notable-data:/var/notables`): Docker stores data in its own
  storage area. You cannot easily browse it from the host without `docker volume`
  commands. Better for servers where you do not need host file access.

This compose file uses a **bind mount** so local testing is straightforward.

## Healthcheck

The image runs `docker_healthcheck.py` every 30s. By default it checks:

- ingest/report directories are writable
- `GET` on the LiteLLM `/v1/models` URL derived from `LLM_API_URL`

When `RAG_ENABLED=true` with Postgres backend, it also runs `SELECT 1` on
`RAG_POSTGRES_DSN`. Postgres connection failures are intentionally reported as a
sanitized error class, not the full DSN or driver message.

Disable probes for partial lab setups:

```bash
ANALYZER_HEALTHCHECK_CHECK_LLM=false
ANALYZER_HEALTHCHECK_CHECK_POSTGRES=false
```

## Entrypoint

Same module as `deploy/systemd/notable-analyzer.service`:

```text
python -m llm_notable_analysis_onprem_systemd.onprem_service.onprem_main
```

For the nonsdk transport variant, replace the entrypoint:

```bash
docker run --rm --entrypoint python notable-analyzer-service \
  -m llm_notable_analysis_onprem_systemd.onprem_service.onprem_main_nonsdk
```

## Configuration

- Docker example: `config.env.docker.example`
- Full contract: `llm_notable_analysis_onprem_systemd/config.env.example`
- Capability bundles: `llm_notable_analysis_onprem_systemd/docs/operations/CAPABILITY_PROFILES.md`

Use compose DNS names (`litellm`, `postgres`) or `host.docker.internal` instead
of `127.0.0.1` for in-container endpoints.

## Files

- `Dockerfile.analyzer` — image build
- `docker-compose.yml` — optional local analyzer + bind-mounted data dir
- `config.env.docker.example` — minimal env template for compose
- `docker_healthcheck.py` — container health probe
