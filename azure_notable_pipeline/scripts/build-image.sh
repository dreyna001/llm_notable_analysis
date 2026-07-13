#!/usr/bin/env bash
set -euo pipefail

: "${CONTAINER_REGISTRY_RESOURCE_ID:?Set CONTAINER_REGISTRY_RESOURCE_ID}"
: "${IMAGE_REPOSITORY:=notable-analysis}"
: "${IMAGE_TAG:?Set immutable IMAGE_TAG (release version or commit SHA)}"

command -v az >/dev/null || { echo 'Azure CLI (az) is required.' >&2; exit 2; }
acr_name="$(az resource show --ids "${CONTAINER_REGISTRY_RESOURCE_ID}" --query name -o tsv)"
login_server="$(az resource show --ids "${CONTAINER_REGISTRY_RESOURCE_ID}" --query properties.loginServer -o tsv)"

az acr build \
  --registry "${acr_name}" \
  --image "${IMAGE_REPOSITORY}:${IMAGE_TAG}" \
  --platform linux/amd64 \
  --file deploy/docker/Dockerfile \
  .

digest="$(az acr repository show --name "${acr_name}" --image "${IMAGE_REPOSITORY}:${IMAGE_TAG}" --query digest -o tsv)"
if [[ "${digest}" != sha256:* ]]; then
  echo 'ACR did not return an immutable image digest.' >&2
  exit 1
fi
echo "CONTAINER_IMAGE_URI=${login_server}/${IMAGE_REPOSITORY}@${digest}"
