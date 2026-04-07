#!/usr/bin/env bash
# Publish analyzer and model-serving mirror images to GHCR from WSL (or Linux).
#
# Prerequisites:
#   - Docker Desktop running (Windows) with WSL integration enabled for this distro,
#     or Docker Engine on Linux. Verify: `docker version` shows a reachable Server.
#   - `docker login ghcr.io -u <github_user>` using a PAT with write:packages (and read:packages).
#
# Host rule: on Windows, run this script inside WSL, not PowerShell.
#
# CPU and GPU bundles share the analyzer image name on GHCR; use distinct TAG values
# per flavor (defaults below include cpu- / gpu- prefixes) so pushes do not overwrite.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OWNER="${GHCR_OWNER:-dreyna001}"
PLATFORM="${DOCKER_PLATFORM:-linux/amd64}"
ANALYZER_DOCKERFILE="${ROOT}/llm_notable_analysis_analyzer_image/Dockerfile.analyzer"
VLLM_UPSTREAM="${VLLM_UPSTREAM_IMAGE:-vllm/vllm-openai:v0.14.1}"
VLLM_MIRROR_TAG_DEFAULT="${VLLM_MIRROR_TAG_DEFAULT:-v0.14.1}"

usage() {
  cat <<'EOF'
Usage:
  ghcr-wsl-publish.sh login
  ghcr-wsl-publish.sh build-push-cpu-analyzer [TAG]
  ghcr-wsl-publish.sh mirror-push-cpu-llama
  ghcr-wsl-publish.sh build-push-gpu-analyzer [TAG]
  ghcr-wsl-publish.sh mirror-push-gpu-vllm [TAG]
  ghcr-wsl-publish.sh all-cpu [TAG]      # analyzer + llama mirror
  ghcr-wsl-publish.sh all-gpu [ANALYZER_TAG] [VLLM_MIRROR_TAG]  # defaults: gpu-<sha> and v0.14.1

Environment:
  GHCR_OWNER          default dreyna001
  DOCKER_PLATFORM     default linux/amd64
  VLLM_UPSTREAM_IMAGE default vllm/vllm-openai:v0.14.1

TAG defaults (if not passed): cpu-<short_sha> or gpu-<short_sha> from git at ROOT.
EOF
}

short_sha() {
  git -C "${ROOT}" rev-parse --short HEAD
}

ensure_docker() {
  if ! docker version >/dev/null 2>&1; then
    echo "error: docker CLI cannot reach the engine. Start Docker Desktop and enable WSL integration, or start dockerd." >&2
    exit 1
  fi
}

cmd="${1:-}"
shift || true

case "${cmd}" in
  login)
    echo "Run (interactive): docker logout ghcr.io 2>/dev/null || true"
    echo "Run (interactive): docker login ghcr.io -u ${OWNER}"
    echo "Use a GitHub PAT with write:packages as the password."
    ;;
  build-push-cpu-analyzer)
    ensure_docker
    TAG="${1:-cpu-$(short_sha)}"
    cd "${ROOT}"
    docker buildx build \
      --platform "${PLATFORM}" \
      --provenance=false \
      -t "ghcr.io/${OWNER}/notable-analyzer-service:${TAG}" \
      -f "${ANALYZER_DOCKERFILE}" \
      --push \
      .
    echo "Pushed ghcr.io/${OWNER}/notable-analyzer-service:${TAG}"
    ;;
  mirror-push-cpu-llama)
    ensure_docker
    docker pull ghcr.io/ggml-org/llama.cpp:server
    docker tag ghcr.io/ggml-org/llama.cpp:server "ghcr.io/${OWNER}/llama-cpp-server-cpu-phi35-llamacpp:server"
    docker push "ghcr.io/${OWNER}/llama-cpp-server-cpu-phi35-llamacpp:server"
    echo "Pushed ghcr.io/${OWNER}/llama-cpp-server-cpu-phi35-llamacpp:server"
    ;;
  build-push-gpu-analyzer)
    ensure_docker
    TAG="${1:-gpu-$(short_sha)}"
    cd "${ROOT}"
    docker buildx build \
      --platform "${PLATFORM}" \
      --provenance=false \
      -t "ghcr.io/${OWNER}/notable-analyzer-service:${TAG}" \
      -f "${ANALYZER_DOCKERFILE}" \
      --push \
      .
    echo "Pushed ghcr.io/${OWNER}/notable-analyzer-service:${TAG}"
    ;;
  mirror-push-gpu-vllm)
    ensure_docker
    TAG="${1:-${VLLM_MIRROR_TAG_DEFAULT}}"
    docker pull "${VLLM_UPSTREAM}"
    docker tag "${VLLM_UPSTREAM}" "ghcr.io/${OWNER}/vllm-openai-gptoss120b:${TAG}"
    docker push "ghcr.io/${OWNER}/vllm-openai-gptoss120b:${TAG}"
    echo "Pushed ghcr.io/${OWNER}/vllm-openai-gptoss120b:${TAG}"
    ;;
  all-cpu)
    TAG="${1:-cpu-$(short_sha)}"
    "${BASH_SOURCE[0]}" build-push-cpu-analyzer "${TAG}"
    "${BASH_SOURCE[0]}" mirror-push-cpu-llama
    ;;
  all-gpu)
    ANALYZER_TAG="${1:-gpu-$(short_sha)}"
    VLLM_TAG="${2:-${VLLM_MIRROR_TAG_DEFAULT}}"
    "${BASH_SOURCE[0]}" build-push-gpu-analyzer "${ANALYZER_TAG}"
    "${BASH_SOURCE[0]}" mirror-push-gpu-vllm "${VLLM_TAG}"
    ;;
  ""|-h|--help)
    usage
    ;;
  *)
    echo "unknown command: ${cmd}" >&2
    usage >&2
    exit 1
    ;;
esac
