# Containerized Deployment Plan

## Purpose

This document describes the target containerized deployment model for `llm_notable_analysis_onprem` while preserving the current functionality and keeping the operating model minimal, predictable, and easy to deploy across different VMs.

The goal is to remove host-level Python/runtime drift by packaging the analyzer and model-serving runtimes into separate container images, while keeping only the small amount of host infrastructure that is still useful.

## Goals

- Preserve the current file-drop workflow.
- Preserve current analyzer behavior and report output.
- Preserve optional Splunk writeback behavior.
- Keep deployment simple for on-prem and air-gapped environments.
- Reduce VM-to-VM dependency/version differences.
- Separate analyzer runtime from model-serving runtime.

## Non-Goals

- Replacing the current file-drop ingestion model.
- Replacing host `sshd` / SFTP with an in-container file upload service.
- Running `systemd` inside containers.
- Rewriting the analyzer into a web service.

## Target Architecture

Two long-running containers will be deployed on the host:

- `analyzer`
- `model-serving`

The host will continue to provide:

- `Docker`
- `systemd`
- `sshd` / SFTP
- persistent data directories
- model weight storage
- optional knowledge-base storage for RAG

## Container Image Selection

The deployment uses two different images with different purposes.

### Model-serving container image

Recommended image:

- `ghcr.io/ggml-org/llama.cpp:server`

Reasoning:

- this is the upstream-maintained `llama.cpp` server image
- it is purpose-built for OpenAI-compatible HTTP serving
- it avoids unnecessary custom serving code in this repo
- it keeps the inference container focused only on model serving

Notes:

- do not bake GGUF models into the image
- mount the GGUF model directory from the host as a volume
- if an accelerator-specific upstream image variant is needed later, prefer the matching upstream variant instead of building a custom serving image unless a proven requirement appears

### Analyzer container image

Recommended image:

- `python:3.13-slim-bookworm`

Reasoning:

- it is an official Python base image
- it is small enough for a lean worker image without Alpine-related packaging friction
- it is appropriate for the analyzer / business-logic container, which is the Python application in this deployment
- it is not used for the inference server container

Conservative fallback:

- `python:3.12-slim-bookworm`

Why the fallback exists:

- this repo historically standardized on Python 3.12 in the host-install path
- if a dependency or wheel issue appears during the worker container build, 3.12 is the lower-risk fallback

### Important clarification

`python:3.13-slim-bookworm` is for the analyzer container only.

It is not the base image for both containers:

- analyzer / client worker: `python:3.13-slim-bookworm` by default
- model-serving / inference server: `ghcr.io/ggml-org/llama.cpp:server`

## Why Debian Slim

Debian `slim` is preferred over Alpine for this deployment because it is usually the simpler operational choice for Python workloads with binary dependencies.

Benefits:

- fewer musl-related package and wheel surprises
- better compatibility with common Python binary wheels
- still small enough for a minimal production-oriented worker image

This is especially relevant because the analyzer may need packages such as `numpy`, `faiss-cpu`, `sentence-transformers`, and document-processing dependencies when optional features are enabled.

## Build Specification

This section turns the deployment plan into a concrete build and runtime specification.

### Images

- inference image: pull `ghcr.io/ggml-org/llama.cpp:server`
- analyzer image: build from this repo using `python:3.13-slim-bookworm`
- analyzer fallback image base: `python:3.12-slim-bookworm`

### What is built vs. pulled

- the inference server image is pulled from upstream
- the analyzer image is built from this repo
- the GGUF model is not built into either image

### Deployment artifacts to create

- analyzer `Dockerfile`
- `compose.yaml` or `docker-compose.yml`
- host `systemd` unit that starts the Docker stack
- analyzer runtime env file
- optional model-serving env file if startup flags are externalized

## Host Dependency Checklist

The host still has a small set of required dependencies even after containerization.

### Required on the host

- `Docker`
- Docker Compose support
- `systemd`
- `sshd` / SFTP
- persistent filesystem paths for ingest, reports, archive, and models

### Required on the host for CPU inference

- no host-installed `llama.cpp` runtime
- no host-installed analyzer Python runtime
- only Docker plus the mounted model/data files

### Required on the host for accelerator-backed inference

- the relevant host driver stack for the selected accelerator
- the relevant container runtime exposure needed by Docker for that accelerator

This remains a host dependency because containers use the host kernel and device drivers.

### Not required on the host in the target design

- analyzer Python packages
- analyzer virtualenv
- host-installed `llama.cpp` binaries
- host-installed model-serving application libraries

## Canonical Host and Container Path Mapping

The containerized deployment should standardize on explicit host-to-container path mappings.

## Canonical Host Working Directories

The containerized deployment should keep the host storage layout simple and use one canonical non-`sudo`-friendly host root for the Docker setup.

Default host root for the Docker deployment:

- `/home/<user>/apps/notable-analyzer`

Important note:

- replace `<user>` with the actual non-`sudo` account used to operate the stack
- this must be treated as a fixed absolute path, not a shell-relative working directory

### Host directories to keep as the source of truth

- Docker stack working directory: `/home/<user>/apps/notable-analyzer`
- model storage: `/home/<user>/apps/notable-analyzer/models`
- incoming drop path: `/home/<user>/apps/notable-analyzer/data/incoming`
- processed path: `/home/<user>/apps/notable-analyzer/data/processed`
- quarantine path: `/home/<user>/apps/notable-analyzer/data/quarantine`
- reports path: `/home/<user>/apps/notable-analyzer/data/reports`
- archive path: `/home/<user>/apps/notable-analyzer/data/archive`
- analyzer env file: `/home/<user>/apps/notable-analyzer/config/config.env`
- optional RAG index path: `/home/<user>/apps/notable-analyzer/kb/index`

### What stays in place vs. what changes

Keep in place:

- one canonical host root for Docker-managed runtime assets
- one canonical model path under that root
- one canonical data path tree under that root
- one canonical config path under that root

Change:

- stop using host-installed analyzer runtime components as the active execution path
- stop using host-installed `llama.cpp` binaries as the active execution path
- use `/home/<user>/apps/notable-analyzer` as the Docker stack working directory for files such as `compose.yaml`

### Important clarification

In the target design, the host directories remain the durable storage locations, but the application and inference runtimes move into containers.

That means:

- data stays on the host and is mounted into containers
- images provide the software runtime
- the old host runtime directories are no longer the primary execution model

### Inference server model mount

Canonical mapping:

- host: `/home/<user>/apps/notable-analyzer/models`
- container: `/models`

Reasoning:

- this keeps the Docker deployment under one non-`sudo`-friendly host root
- it keeps the GGUF outside the image
- it makes model replacement or offline copy procedures straightforward

The inference container should read the GGUF from `/models/<filename>.gguf`.

### Analyzer data mounts

Recommended canonical mappings:

- host: `/home/<user>/apps/notable-analyzer/data/incoming` -> container: `/watch/incoming`
- host: `/home/<user>/apps/notable-analyzer/data/processed` -> container: `/watch/processed`
- host: `/home/<user>/apps/notable-analyzer/data/quarantine` -> container: `/watch/quarantine`
- host: `/home/<user>/apps/notable-analyzer/data/reports` -> container: `/watch/reports`
- host: `/home/<user>/apps/notable-analyzer/data/archive` -> container: `/watch/archive`

Important note:

- incoming notables are written to the host filesystem, not "into the Docker image"
- the analyzer container reads those files through mounted volumes
- this is intentional because incoming notables are runtime data, not application code
- the host filesystem remains the source of truth so queued files survive container restarts, image rebuilds, and redeployments
- this also keeps SFTP integration simple because `sshd` remains on the host

### Optional analyzer RAG mounts

- host: `/home/<user>/apps/notable-analyzer/kb/index` -> container: `/kb/index`

### Analyzer config mount

Recommended mapping:

- host: `/home/<user>/apps/notable-analyzer/config/config.env`
- container: mounted as env file for the analyzer container

## Runtime Configuration Mapping

The analyzer env file should be updated to use the container paths rather than the old host-local service paths.

Recommended container-facing values:

- `INCOMING_DIR=/watch/incoming`
- `PROCESSED_DIR=/watch/processed`
- `QUARANTINE_DIR=/watch/quarantine`
- `REPORT_DIR=/watch/reports`
- `ARCHIVE_DIR=/watch/archive`
- `LLM_API_URL=http://model-serving:8000/v1/chat/completions`
- `RAG_SQLITE_PATH=/kb/index/kb.sqlite3`
- `RAG_FAISS_PATH=/kb/index/kb.faiss`

For the inference container, the model path should resolve under:

- `/models/<gguf-file>`

## Build and Runtime Boundaries

To keep the deployment minimal and maintainable, each container should have a single responsibility.

### Inference container

- contains the `llama.cpp` server runtime
- serves OpenAI-compatible HTTP
- reads model files from `/models`
- does not contain analyzer business logic
- does not watch ingest folders

### Analyzer container

- contains the Python application and its dependencies
- watches the mounted file-drop directories
- calls the inference container over internal HTTP
- writes reports and manages retention
- does not contain the model-serving runtime

## Additional Mappings Required Before Build

The following items should be explicitly mapped as part of the implementation so the Docker images remain solid but simple.

### Service naming

- Compose service name for inference: `model-serving`
- Compose service name for analyzer: `analyzer`
- internal analyzer target hostname: `model-serving`

This keeps Docker DNS and application configuration aligned.

### Port mapping

- internal inference port: `8000`
- analyzer does not need an inbound service port
- default production preference: do not publish the inference port externally unless an external caller actually needs it

### Entrypoints

- inference container entrypoint: upstream `llama.cpp` server command
- analyzer container entrypoint: Python module entrypoint for the analyzer runtime

### Image boundaries

- no source-code bind mounts in production for the analyzer image
- no model files copied into the inference image
- no app code copied into the inference image
- no inference binaries copied into the analyzer image

### User and permissions mapping

The file-drop model requires the host and analyzer container to agree on filesystem access.

Must be mapped during implementation:

- which host user/group owns `/home/<user>/apps/notable-analyzer/data/incoming`
- which UID/GID the analyzer container runs as
- read/write permissions for `processed`, `quarantine`, `reports`, and `archive`

Goal:

- SFTP can write incoming files
- analyzer can read incoming files and move/write output files
- neither container needs unnecessary root privileges

### Secrets and env mapping

- analyzer env file location on host
- whether Splunk token remains in the env file or moves to a Docker secret later
- whether the inference container needs a separate env file or only Compose command arguments

For the initial implementation, keep this simple:

- analyzer uses an env file
- inference container uses Compose command arguments unless a separate env file clearly improves readability

### Healthcheck mapping

Must be defined:

- inference healthcheck target
- analyzer healthcheck strategy

Recommended initial approach:

- inference: HTTP health check against the server endpoint
- analyzer: simple process health check or a lightweight file/process-based check

### Logging mapping

- container logs should go to stdout/stderr
- Docker and `journalctl` should be the primary operational log access path
- do not introduce an extra log aggregation dependency in v1

### Restart and startup order mapping

- Docker restart policy for both services
- Compose dependency ordering
- host `systemd` unit starts the stack, not the individual app runtimes directly

### Build context mapping

- analyzer build context should be limited to the on-prem project directory
- large local artifacts such as virtualenvs, caches, and models must be excluded from the analyzer build context

This requires a `.dockerignore`.

## Planned Files To Generate

The implementation should generate a small, explicit set of files.

### `Dockerfile.analyzer`

Scope:

- builds the analyzer image only
- installs the analyzer runtime and its Python dependencies
- sets the analyzer entrypoint
- does not build or include the GGUF model

### `requirements.analyzer-docker.txt`

Scope:

- pinned Python dependency set for the analyzer container
- should reflect the `nonsdk` analyzer path if that is the chosen runtime
- should be container-build focused, not host-install focused

### `.dockerignore`

Scope:

- reduces analyzer build context size
- excludes `.venv`, caches, test artifacts, local model files, and other non-runtime files
- prevents accidental inclusion of large or sensitive local data in the image build context

### `compose.yaml`

Scope:

- defines the two-service stack
- defines service names, restart policies, networks, mounts, env file usage, and health checks
- defines the host-to-container path mappings
- is the main runtime orchestration file for Docker

### `systemd/notable-analyzer-stack.service`

Scope:

- host-level `systemd` unit that starts and stops the Docker stack
- replaces direct host execution of the analyzer runtime
- does not run application logic itself
- reference implementation in repo path `llm_notable_analysis_onprem_docker_cpu_phi35_llamacpp/`; GHCR analyzer package **`notable-analyzer-service`** is the generic Python worker image (CPU/GPU-agnostic at the container level). A **separate** Compose project or host layout for GPU / vLLM / large-model serving is still recommended so model-serving images and ports do not collide

### `config.env.container.example`

Scope:

- example analyzer env file for the containerized deployment
- uses container-facing paths such as `/watch/...`
- documents required and optional analyzer settings in the new Docker layout

### `docs/container-deployment-quickstart.md`

Scope:

- operator-facing quickstart for building, loading, and running the stack
- focuses on the container path, not the legacy host-venv path
- includes startup, verification, and rollback basics

### Optional file: `compose.override.example.yaml`

Scope:

- example overrides for environment-specific tuning
- can hold optional port publishing, alternate model filename, or accelerator-specific adjustments
- should remain optional so the base Compose file stays minimal

## File Generation Rules

To keep the implementation simple, each generated file should have a narrow purpose.

- one analyzer build file
- one analyzer dependency file
- one Docker orchestration file
- one host `systemd` stack unit
- one container-oriented example env file
- one quickstart doc

Avoid generating:

- a separate custom inference Dockerfile unless the upstream image is proven insufficient
- multiple overlapping Compose files unless there is a real environment split
- duplicate env examples that describe the same runtime behavior

## Runtime Flow

1. SOAR, Splunk, or another sender uploads a notable file to the VM using host SFTP/SSH.
2. The host writes that file into a persistent incoming directory.
3. Host `systemd` ensures the Docker stack is started after boot and restarted when needed.
4. Docker starts two containers: `model-serving` and `analyzer`.
5. The `analyzer` container watches mounted host directories for new files.
6. When a new notable appears, the analyzer reads it from the mounted incoming directory.
7. The analyzer sends the prompt to the `model-serving` container over the internal Docker network.
8. The `model-serving` container returns an OpenAI-compatible response.
9. The analyzer generates the same markdown/report output as today.
10. The analyzer writes results back to mounted host directories and optionally performs Splunk writeback.
11. Retention remains in the analyzer process unless intentionally split out later.

## Responsibility Split

### Host responsibilities

- Accept incoming files over SFTP/SSH.
- Persist files and reports on disk.
- Store model weights.
- Store optional RAG artifacts.
- Start and keep the Docker stack running with `systemd`.

### Analyzer container responsibilities

- Poll `incoming` for new files.
- Normalize and process notables.
- Call the model-serving API.
- Generate markdown reports.
- Move files to `processed` or `quarantine`.
- Run retention logic.
- Perform optional Splunk writeback.
- Remain a pure business-logic worker with no embedded model-serving runtime.

### Model-serving container responsibilities

- Load the selected local model.
- Expose an OpenAI-compatible API endpoint to the analyzer container.
- Handle inference independently of analyzer lifecycle.
- Remain a pure serving container with no analyzer business logic.

## Why This Shape

This is the preferred shape because it keeps the host small and stable while still preserving the current operational model:

- SFTP remains a host concern because it is already the ingress mechanism.
- `systemd` remains a host concern because it is the simplest way to ensure the container stack starts on boot.
- The analyzer becomes portable because its Python environment is pinned in an image.
- The model-serving layer becomes independently replaceable or upgradable.
- Failures are easier to isolate because analyzer and inference are separate runtimes.

## Storage Model

The host remains the source of truth for durable data.

Expected persistent host directories:

- `incoming`
- `processed`
- `quarantine`
- `reports`
- `archive`
- model weights path
- optional RAG knowledge-base path

These directories will be mounted into the containers as volumes. The analyzer should operate on the mounted paths directly rather than relying on host-side symlinks.

## Network Model

- The analyzer and model-serving containers communicate over an internal Docker network.
- The model-serving API is not required to be publicly exposed beyond what the deployment needs.
- SFTP remains exposed from the host, not from a container.
- Splunk writeback, if enabled, is initiated from the analyzer container.
- HTTP timeouts, retries, and bounded concurrency should remain enabled between analyzer and model-serving.

## Build Plan

### Phase 1: containerize the analyzer

- Build a dedicated analyzer image with pinned Python and dependencies.
- Use the existing non-SDK analyzer path to keep the image lean.
- Mount host data directories into the analyzer container.
- Point the analyzer at the existing model endpoint first if needed for transition testing.

Outcome:

- Analyzer runtime becomes portable and VM-consistent.

### Phase 2: containerize model serving

- Build a dedicated image for the selected model-serving runtime.
- Mount model weights from the host into the serving container.
- Expose an internal OpenAI-compatible endpoint to the analyzer container.
- Update analyzer configuration to call the model-serving container over Docker networking.

Outcome:

- Inference runtime also becomes portable and separated from host package drift.

### Phase 3: wire host startup to Docker

- Replace the host analyzer runtime service with a small host `systemd` unit that manages the Docker stack.
- Keep restart behavior at the Docker/container level and boot orchestration at the host `systemd` level.

Outcome:

- Reboot/startup behavior remains simple and Linux-native.

### Phase 4: verify parity

- Confirm incoming file processing still works.
- Confirm reports are written to the expected host directory.
- Confirm processed/quarantine/archive flows still behave as expected.
- Confirm optional Splunk writeback still works when enabled.
- Confirm retention still works.

Outcome:

- The containerized deployment matches current functionality.

## Configuration Approach

Configuration should remain environment-driven so deployment stays simple:

- analyzer behavior stays controlled by the existing env file pattern
- model-serving settings stay controlled by its own env/config inputs
- host paths remain explicit and mounted into containers

This keeps the runtime contract familiar and minimizes code churn.

## Operational Model

### Start sequence

1. Host boots.
2. `systemd` starts Docker.
3. `systemd` starts the Docker stack.
4. Docker starts `model-serving`.
5. Docker starts `analyzer`.
6. Analyzer waits for or retries against the model-serving API as needed.

### Failure handling

- If the analyzer exits, Docker restarts only the analyzer container.
- If the model-serving container exits, Docker restarts only the model-serving container.
- If the host reboots, `systemd` brings the stack back up.
- Persistent files remain on the host and survive container replacement.

### Upgrade model

- Build a new analyzer image tag and/or model-serving image tag.
- Replace the running image with the new tag.
- Restart the stack.
- Roll back by redeploying the previous image tag if needed.

## Open Decisions

These items should be confirmed during implementation:

- whether model-serving should bind only internally or also expose a host port
- whether health checks will be added for both containers
- whether RAG artifacts are mounted read-only into the analyzer container
- whether freeform mode also gets its own deployment profile

## Recommended First Implementation

The first implementation should target the simplest production-worthy shape:

- host `sshd` / SFTP stays unchanged
- one `analyzer` container
- one `model-serving` container
- host-mounted persistent directories
- host `systemd` starts the Docker stack
- no `systemd` inside containers
- upstream `llama.cpp` server image for inference
- `python:3.13-slim-bookworm` for the analyzer worker, with `python:3.12-slim-bookworm` as the conservative fallback

Implementation preferences:

- keep the LLM container pure serving only
- keep the analyzer container pure business logic only
- do not combine file watching and inference serving into one container
- run both containers as non-root where practical
- add health checks
- pin exact image tags, and preferably digests, for production deployments

This gives the containerization benefits without changing the existing ingestion model or introducing unnecessary moving parts.

## Definition of Done

This migration is complete when:

- a fresh VM can run the stack without installing analyzer Python dependencies directly on the host
- a fresh VM can run the stack without installing model-serving runtime dependencies directly on the host
- a notable dropped through SFTP is processed successfully
- the analyzer receives model output from the model-serving container
- reports and file movements match current behavior
- optional Splunk writeback still works
- reboot recovery is handled by host `systemd` plus Docker restart behavior
