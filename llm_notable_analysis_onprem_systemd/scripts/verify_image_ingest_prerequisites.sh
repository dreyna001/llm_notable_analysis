#!/usr/bin/env bash
# Verify image-ingest prerequisites on an air-gapped or connected host.
# Uses loopback HTTP only for the optional multimodal smoke (no external network).
#
# Exit 0 when all checks pass; exit 1 with a missing-items list on failure.
#
# Related: docs/operations/rag/IMAGE_INGEST_PREREQUISITES.md
set -euo pipefail
IFS=$'\n\t'

CONFIG_ENV="${CONFIG_ENV:-/etc/notable-analyzer/config.env}"
ANALYZER_VENV="${ANALYZER_VENV:-/opt/notable-analyzer/venv}"
SKIP_MULTIMODAL_TEST="${SKIP_MULTIMODAL_TEST:-false}"
NO_PAGER="${NO_PAGER:-false}"
GEMMA_MODEL_DIR="${GEMMA_MODEL_DIR:-/opt/models/gemma-4-31B-it}"

EMBED_REPO_ID="ibm-granite/granite-embedding-english-r2"
RERANK_REPO_ID="ibm-granite/granite-embedding-reranker-english-r2"
DEFAULT_HF_HOME="/var/notables/cache/huggingface"
DEFAULT_ST_HOME="/var/notables/cache/sentence-transformers"

export SYSTEMD_PAGER=cat

usage() {
    cat <<'EOF'
Usage: verify_image_ingest_prerequisites.sh [options]

Verify image-ingest prerequisites without external network access.
Optional multimodal test uses loopback LLM_API_URL from config.env only.

Options:
  --config-env PATH          Analyzer config.env (default: /etc/notable-analyzer/config.env)
  --analyzer-venv PATH       Analyzer virtualenv (default: /opt/notable-analyzer/venv)
  --skip-multimodal-test     Skip loopback vision/chat completion curl test
  --no-pager                 Pass --no-pager to systemctl status checks
  --gemma-model-dir PATH     Gemma vision model directory (default: /opt/models/gemma-4-31B-it)
  -h, --help                 Show this help

Environment overrides:
  CONFIG_ENV, ANALYZER_VENV, SKIP_MULTIMODAL_TEST, NO_PAGER, GEMMA_MODEL_DIR
EOF
}

err() {
    echo "ERROR: $*" >&2
    exit 1
}

info() {
    echo "  $*"
}

warn() {
    echo "WARN: $*" >&2
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || err "Missing required command: $1"
}

require_arg_value() {
    local option="$1"
    local value="${2:-}"
    [[ -n "$value" && "$value" != --* ]] || err "Missing value for $option"
}

read_config() {
    local key="$1"
    local fallback="$2"
    if [[ ! -f "$CONFIG_ENV" ]]; then
        echo "$fallback"
        return 0
    fi
    python3 - "$CONFIG_ENV" "$key" "$fallback" <<'PY'
import shlex
import sys
from pathlib import Path

path = Path(sys.argv[1])
target_key = sys.argv[2]
fallback = sys.argv[3]

if not path.is_file():
    print(fallback)
    raise SystemExit(0)

for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    try:
        tokens = shlex.split(stripped, comments=True, posix=True)
    except ValueError as exc:
        raise SystemExit(f"Invalid config.env line {line_number}: {exc}") from exc
    if tokens and tokens[0] == "export":
        tokens = tokens[1:]
    if len(tokens) != 1 or "=" not in tokens[0]:
        raise SystemExit(f"Invalid config.env line {line_number}: expected KEY=VALUE.")
    key, value = tokens[0].split("=", 1)
    if key == target_key:
        print(value)
        raise SystemExit(0)
print(fallback)
PY
}

hf_hub_cache_name() {
    local repo_id="$1"
    python3 - "$repo_id" <<'PY'
import sys
print("models--" + sys.argv[1].replace("/", "--"))
PY
}

model_snapshot_ready() {
    local cache_root="$1"
    local repo_id="$2"
    local hub_name snapshot_dir
    hub_name="$(hf_hub_cache_name "$repo_id")"
    snapshot_dir="$cache_root/hub/$hub_name/snapshots/offline-bundle"
    [[ -f "$snapshot_dir/config.json" ]]
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config-env)
            require_arg_value "$1" "${2:-}"
            CONFIG_ENV="$2"
            shift 2
            ;;
        --analyzer-venv)
            require_arg_value "$1" "${2:-}"
            ANALYZER_VENV="$2"
            shift 2
            ;;
        --skip-multimodal-test)
            SKIP_MULTIMODAL_TEST="true"
            shift
            ;;
        --no-pager)
            NO_PAGER="true"
            shift
            ;;
        --gemma-model-dir)
            require_arg_value "$1" "${2:-}"
            GEMMA_MODEL_DIR="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            err "Unknown argument: $1"
            ;;
    esac
done

[[ -f "$CONFIG_ENV" ]] || err "Missing config file: $CONFIG_ENV"

missing=()
failures=0

record_missing() {
    missing+=("$1")
    failures=$((failures + 1))
}

info "Verifying image-ingest prerequisites"

if command -v tesseract >/dev/null 2>&1; then
    info "tesseract: $(tesseract --version 2>&1 | head -n 1)"
else
    record_missing "tesseract binary not found in PATH"
fi

if command -v tesseract >/dev/null 2>&1; then
    langs="$(tesseract --list-langs 2>/dev/null | tail -n +2 || true)"
    for lang in eng osd; do
        if grep -qx "$lang" <<<"$langs"; then
            info "tesseract language: $lang"
        else
            record_missing "tesseract language data missing: $lang"
        fi
    done
fi

if [[ -x "$ANALYZER_VENV/bin/python" ]]; then
    if "$ANALYZER_VENV/bin/python" - <<'PY'
import docx  # noqa: F401
import PIL  # noqa: F401
import pypdfium2  # noqa: F401
PY
    then
        info "analyzer venv imports: Pillow, pypdfium2, python-docx"
    else
        record_missing "analyzer venv missing importable Pillow, pypdfium2, or python-docx"
    fi
else
    record_missing "analyzer venv python not found: $ANALYZER_VENV/bin/python"
fi

HF_HOME="$(read_config HF_HOME "$DEFAULT_HF_HOME")"
ST_HOME="$(read_config SENTENCE_TRANSFORMERS_HOME "$DEFAULT_ST_HOME")"

for repo_id in "$EMBED_REPO_ID" "$RERANK_REPO_ID"; do
    if model_snapshot_ready "$HF_HOME" "$repo_id"; then
        info "HF_HOME model ready: $repo_id"
    else
        record_missing "HF_HOME missing offline Granite model: $repo_id"
    fi
    if model_snapshot_ready "$ST_HOME" "$repo_id"; then
        info "SENTENCE_TRANSFORMERS_HOME model ready: $repo_id"
    else
        record_missing "SENTENCE_TRANSFORMERS_HOME missing offline Granite model: $repo_id"
    fi
done

RAG_EMBEDDING_MODEL="$(read_config RAG_EMBEDDING_MODEL "$EMBED_REPO_ID")"
RAG_RERANK_MODEL="$(read_config RAG_RERANK_MODEL "$RERANK_REPO_ID")"
RAG_VECTOR_DIMENSIONS="$(read_config RAG_VECTOR_DIMENSIONS "768")"
CASE_QA_VECTOR_DIMENSIONS="$(read_config CASE_QA_VECTOR_DIMENSIONS "768")"

if [[ "$RAG_EMBEDDING_MODEL" == "$EMBED_REPO_ID" ]]; then
    info "RAG_EMBEDDING_MODEL=$RAG_EMBEDDING_MODEL"
else
    record_missing "RAG_EMBEDDING_MODEL expected $EMBED_REPO_ID, found $RAG_EMBEDDING_MODEL"
fi

if [[ "$RAG_RERANK_MODEL" == "$RERANK_REPO_ID" ]]; then
    info "RAG_RERANK_MODEL=$RAG_RERANK_MODEL"
else
    record_missing "RAG_RERANK_MODEL expected $RERANK_REPO_ID, found $RAG_RERANK_MODEL"
fi

if [[ "$RAG_VECTOR_DIMENSIONS" == "768" ]]; then
    info "RAG_VECTOR_DIMENSIONS=768"
else
    record_missing "RAG_VECTOR_DIMENSIONS expected 768, found $RAG_VECTOR_DIMENSIONS"
fi

if [[ "$CASE_QA_VECTOR_DIMENSIONS" == "768" ]]; then
    info "CASE_QA_VECTOR_DIMENSIONS=768"
else
    record_missing "CASE_QA_VECTOR_DIMENSIONS expected 768, found $CASE_QA_VECTOR_DIMENSIONS"
fi

if [[ -f "$GEMMA_MODEL_DIR/config.json" ]]; then
    info "Gemma vision model files present: $GEMMA_MODEL_DIR/config.json"
else
    record_missing "Gemma model directory missing config.json: $GEMMA_MODEL_DIR"
fi

if command -v systemctl >/dev/null 2>&1; then
    systemctl_args=()
    if [[ "$NO_PAGER" == "true" ]]; then
        systemctl_args+=(--no-pager)
    fi
    for unit in vllm litellm; do
        if systemctl is-active --quiet "$unit"; then
            info "$unit.service is active"
        else
            record_missing "$unit.service is not active"
        fi
    done
else
    warn "systemctl not available; skipping vllm/litellm active checks"
fi

if [[ "$SKIP_MULTIMODAL_TEST" != "true" ]]; then
    require_command curl
    LLM_API_URL="$(read_config LLM_API_URL "http://127.0.0.1:4000/v1/chat/completions")"
    LLM_MODEL_NAME="$(read_config LLM_MODEL_NAME "gemma-4-31B-it")"
    LLM_API_TOKEN="$(read_config LLM_API_TOKEN "")"

    if [[ "$LLM_API_URL" != http://127.0.0.1:* && "$LLM_API_URL" != http://localhost:* ]]; then
        warn "Skipping multimodal test: LLM_API_URL is not loopback ($LLM_API_URL)"
    else
        tmpdir="$(mktemp -d)"
        payload="$tmpdir/multimodal_payload.json"
        response="$tmpdir/multimodal_response.json"
        python3 - "$LLM_MODEL_NAME" > "$payload" <<'PY'
import json
import sys

model = sys.argv[1]
img_b64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
print(
    json.dumps(
        {
            "model": model,
            "max_tokens": 64,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "What color is this image? Reply with one word.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                        },
                    ],
                }
            ],
        }
    )
)
PY

        curl_args=(-fsS --max-time 60 -H "Content-Type: application/json")
        if [[ -n "$LLM_API_TOKEN" ]]; then
            curl_args+=(-H "Authorization: Bearer $LLM_API_TOKEN")
        fi

        info "Running loopback multimodal test against $LLM_API_URL"
        if curl "${curl_args[@]}" -d @"$payload" "$LLM_API_URL" > "$response"; then
            if python3 - "$response" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
choices = payload.get("choices") or []
if not choices:
    raise SystemExit("no choices in multimodal response")
message = choices[0].get("message") or {}
content = str(message.get("content") or "").strip()
if not content:
    raise SystemExit("empty multimodal response content")
PY
            then
                info "multimodal loopback test passed"
            else
                record_missing "multimodal loopback test returned empty or invalid response"
            fi
        else
            record_missing "multimodal loopback curl to LLM_API_URL failed"
        fi
        rm -rf "$tmpdir"
    fi
else
    info "SKIP_MULTIMODAL_TEST=true; multimodal loopback test skipped"
fi

if (( failures > 0 )); then
    echo "FAILED: image-ingest prerequisite verification ($failures issue(s))" >&2
    for item in "${missing[@]}"; do
        echo "  - $item" >&2
    done
    exit 1
fi

info "All image-ingest prerequisite checks passed"
exit 0
