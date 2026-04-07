# True No-Lapse Rollout (CPU Phi-3.5 + llama.cpp)

This runbook defines how to deploy code/image updates without service interruption.

## Goal

Maintain continuous:

- inference availability (`/v1/chat/completions`)
- inbound file-drop acceptance
- report generation/writeback path

## Recommended topology

- `blue` stack: current production
- `green` stack: next version candidate
- stable endpoints:
  - inference endpoint alias/load balancer
  - file-drop path or host alias used by SOC/SOAR

For CPU deployments, true no-lapse can be done on:

- two hosts (preferred), or
- one host only if enough spare CPU/RAM exists for full blue+green overlap.

## Prerequisites

- Distro-managed Docker daemon enabled:
  - `sudo systemctl enable --now docker.service`
- Immutable image tags already published to GHCR.
- GGUF model artifacts staged on both blue and green runtime slices.
- Health checks and smoke tests pass on current blue before rollout.
- Rollback target (previous image tags) documented.

## Analyzer caveat for file-drop

Current analyzer path is filesystem poller based. Do not run two analyzers against
the same `data/incoming` path unless you have an external coordination strategy.

For true no-lapse, use one of:

- active/passive analyzer ownership with controlled cutover of file-drop target, or
- external queue/locking layer to coordinate workers.

## Deployment procedure (blue -> green)

1. **Build and publish release images**
   - Build in WSL for Windows hosts, Linux shell for Linux hosts.
   - Push immutable tags to GHCR for analyzer and model-serving images.

2. **Prepare green environment**
   - Pull new image tags on green host/slice.
   - Ensure GGUF artifacts and `config/config.env` are present.
   - Start green stack with new tags:
   - `docker compose -p notable-green -f compose.airgap.yaml up -d`

3. **Validate green before cutover**
   - `docker compose -p notable-green -f compose.airgap.yaml ps`
   - `curl -sf http://<green-host>:8000/health`
   - Run one chat-completion sanity request.
   - Drop one test notable and verify processed/report output.

4. **Cut over traffic**
   - Switch inference alias/LB from blue to green.
   - Switch SOC/SOAR file-drop target to green analyzer host/path.

5. **Observe**
   - Watch green logs and health for a defined soak window.
   - Confirm Splunk ES optional writeback behavior if enabled.

6. **Drain blue**
   - After soak window success, stop blue stack.

## Rollback (green -> blue)

1. Switch inference alias/LB and file-drop target back to blue.
2. Keep green for forensics; do not destroy until stable.
3. If needed, restart blue stack with previous known-good tags.

## Minimal-lapse mode (if spare capacity is unavailable)

If you cannot run blue+green concurrently, use a maintenance window and:

- pre-pull images
- recreate only changed services
- keep previous tags for immediate rollback

This reduces downtime but is not true no-lapse.
