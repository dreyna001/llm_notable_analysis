#!/usr/bin/env bash
set -euo pipefail

BUNDLE_DIR="${1:-/opt/artifacts/onprem_llm_sdk}"

if [[ ! -d "$BUNDLE_DIR" ]]; then
  echo "ERROR: Bundle directory does not exist: $BUNDLE_DIR"
  exit 1
fi

cd "$BUNDLE_DIR"

for required in SHA256SUMS wheels VERSION; do
  if [[ ! -e "$required" ]]; then
    echo "ERROR: Missing required bundle item: $required"
    exit 1
  fi
done

sha256sum -c SHA256SUMS
echo "Bundle verification passed."

