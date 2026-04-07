#!/usr/bin/env bash
# shellcheck shell=bash
set -euo pipefail
IFS=$'\n\t'

err() { echo "ERROR: $*" >&2; exit 1; }

readonly KB_CONFIG_FILE="${KB_CONFIG_FILE:-/etc/notable-kb/config.env}"

[[ -f "$KB_CONFIG_FILE" ]] || err "Missing config file: $KB_CONFIG_FILE"

set -a
# shellcheck disable=SC1090
source "$KB_CONFIG_FILE"
set +a

: "${KB_SOURCE_DIR:?Missing KB_SOURCE_DIR in $KB_CONFIG_FILE}"
: "${KB_INDEX_DIR:?Missing KB_INDEX_DIR in $KB_CONFIG_FILE}"
: "${KB_EMBEDDING_MODEL:?Missing KB_EMBEDDING_MODEL in $KB_CONFIG_FILE}"
: "${KB_TARGET_WORDS:?Missing KB_TARGET_WORDS in $KB_CONFIG_FILE}"
: "${KB_OVERLAP_WORDS:?Missing KB_OVERLAP_WORDS in $KB_CONFIG_FILE}"
: "${KB_PYTHON:?Missing KB_PYTHON in $KB_CONFIG_FILE}"

[[ -d "$KB_SOURCE_DIR" ]] || err "KB source directory does not exist: $KB_SOURCE_DIR"
[[ -x "$KB_PYTHON" ]] || err "Python executable not found: $KB_PYTHON"

mkdir -p "$KB_INDEX_DIR"

exec "$KB_PYTHON" -m onprem_rag.future.corpus_ingest \
    --source-dir "$KB_SOURCE_DIR" \
    --index-dir "$KB_INDEX_DIR" \
    --embedding-model "$KB_EMBEDDING_MODEL" \
    --target-words "$KB_TARGET_WORDS" \
    --overlap-words "$KB_OVERLAP_WORDS"
