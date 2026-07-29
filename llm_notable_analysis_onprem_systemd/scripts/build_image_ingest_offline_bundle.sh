#!/usr/bin/env bash
# Build an offline transfer bundle for image-ingest prerequisites on a connected
# Linux staging host (same OS/arch and Python 3.12 profile as the air-gapped target).
#
# Bundle contents:
#   wheels/     Pillow and pypdfium2 (linux py3.12 wheels + transitive deps)
#   tessdata/   eng.traineddata and osd.traineddata (tessdata_fast)
#   debs/       Optional Ubuntu .deb packages for tesseract-ocr stack (empty on non-Debian)
#   models/     IBM Granite embedding and reranker model trees (HF snapshot_download)
#
# Does NOT download Gemma vision weights (expected already on the target host).
#
# Related: docs/operations/rag/IMAGE_INGEST_PREREQUISITES.md
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

OUTPUT_DIR="${OUTPUT_DIR:-}"
INSTALL_DIR="${INSTALL_DIR:-/opt/notable-analyzer}"
ANALYZER_VENV="${ANALYZER_VENV:-$INSTALL_DIR/venv}"
PYTHON_BIN="${PYTHON_BIN:-}"
PYTHON_BIN_EXPLICIT="${PYTHON_BIN_EXPLICIT:-false}"
SKIP_MODELS="${SKIP_MODELS:-false}"
SKIP_WHEELS="${SKIP_WHEELS:-false}"
SKIP_TESSDATA="${SKIP_TESSDATA:-false}"
SKIP_DEBS="${SKIP_DEBS:-false}"

PILLOW_VERSION="${PILLOW_VERSION:-11.1.0}"
PYPDFIUM2_VERSION="${PYPDFIUM2_VERSION:-4.30.0}"
HUGGINGFACE_HUB_PIP_SPEC="${HUGGINGFACE_HUB_PIP_SPEC:-huggingface-hub==1.16.4}"

EMBED_REPO_ID="ibm-granite/granite-embedding-english-r2"
RERANK_REPO_ID="ibm-granite/granite-embedding-reranker-english-r2"
EMBED_BUNDLE_NAME="granite-embedding-english-r2"
RERANK_BUNDLE_NAME="granite-embedding-reranker-english-r2"

TESSDATA_ENG_URL="${TESSDATA_ENG_URL:-https://github.com/tesseract-ocr/tessdata_fast/raw/main/eng.traineddata}"
TESSDATA_OSD_URL="${TESSDATA_OSD_URL:-https://github.com/tesseract-ocr/tessdata_fast/raw/main/osd.traineddata}"

usage() {
    cat <<'EOF'
Usage: build_image_ingest_offline_bundle.sh [options]

Build an offline bundle for image-ingest prerequisites on a connected staging host.
Target host must match this machine's Linux arch and Python 3.12 profile.

Default output directory: ./offline-bundles/image-ingest-YYYYMMDD

Options:
  --output-dir PATH      Bundle root directory (created if missing)
  --skip-models          Skip IBM Granite model downloads
  --skip-wheels          Skip Python wheel download (Pillow, pypdfium2)
  --skip-tessdata        Skip Tesseract language data download
  --skip-debs            Skip apt-get download of tesseract OS packages
  --analyzer-venv PATH   Analyzer virtualenv for pip/model staging
                         (default: /opt/notable-analyzer/venv)
  --python PATH          Python interpreter (overrides --analyzer-venv)
  -h, --help             Show this help

Python selection (first match wins after explicit --python):
  1. --python PATH or PYTHON_BIN env
  2. \$ANALYZER_VENV/bin/python when present
  3. python3.12 on PATH (must have pip)

Environment overrides:
  OUTPUT_DIR, INSTALL_DIR, ANALYZER_VENV, PYTHON_BIN,
  SKIP_MODELS, SKIP_WHEELS, SKIP_TESSDATA, SKIP_DEBS,
  PILLOW_VERSION, PYPDFIUM2_VERSION, HUGGINGFACE_HUB_PIP_SPEC,
  TESSDATA_ENG_URL, TESSDATA_OSD_URL, HF_TOKEN, HUGGINGFACE_TOKEN
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

python_has_pip() {
    local py="$1"
    [[ -x "$py" || "$(command -v "$py" 2>/dev/null || true)" != "" ]] || return 1
    "$py" -m pip --version >/dev/null 2>&1
}

resolve_python_bin() {
    if [[ "$PYTHON_BIN_EXPLICIT" == "true" && -n "$PYTHON_BIN" ]]; then
        return 0
    fi

    if [[ -n "$PYTHON_BIN" ]]; then
        return 0
    fi

    if [[ -x "$ANALYZER_VENV/bin/python" ]]; then
        PYTHON_BIN="$ANALYZER_VENV/bin/python"
        return 0
    fi

    if command -v python3.12 >/dev/null 2>&1; then
        PYTHON_BIN="python3.12"
        return 0
    fi

    err "No Python 3.12 found. Pass --python PATH or install the analyzer venv at $ANALYZER_VENV"
}

require_python_with_pip() {
    resolve_python_bin
    require_command "$PYTHON_BIN"
    python_has_pip "$PYTHON_BIN" || err \
        "Python at $PYTHON_BIN has no pip module. Use the analyzer venv (--analyzer-venv $ANALYZER_VENV) or pass --python to a venv with pip."
}

require_arg_value() {
    local option="$1"
    local value="${2:-}"
    [[ -n "$value" && "$value" != --* ]] || err "Missing value for $option"
}

detect_manylinux_platform() {
    local arch
    arch="$(uname -m)"
    case "$arch" in
        x86_64|amd64)
            echo "manylinux2014_x86_64"
            ;;
        aarch64|arm64)
            echo "manylinux2014_aarch64"
            ;;
        *)
            err "Unsupported Linux arch for wheel download: $arch (expected x86_64 or aarch64)"
            ;;
    esac
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir)
            require_arg_value "$1" "${2:-}"
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --skip-models)
            SKIP_MODELS="true"
            shift
            ;;
        --skip-wheels)
            SKIP_WHEELS="true"
            shift
            ;;
        --skip-tessdata)
            SKIP_TESSDATA="true"
            shift
            ;;
        --skip-debs)
            SKIP_DEBS="true"
            shift
            ;;
        --analyzer-venv)
            require_arg_value "$1" "${2:-}"
            ANALYZER_VENV="$2"
            shift 2
            ;;
        --python)
            require_arg_value "$1" "${2:-}"
            PYTHON_BIN="$2"
            PYTHON_BIN_EXPLICIT="true"
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

if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="$REPO_DIR/offline-bundles/image-ingest-$(date +%Y%m%d)"
fi

require_python_with_pip
require_command curl
require_command sha256sum

info "Using Python for bundle staging: $PYTHON_BIN"

py_version="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$py_version" != "3.12" ]]; then
    err "Expected Python 3.12, found $("$PYTHON_BIN" --version 2>&1)"
fi

mkdir -p "$OUTPUT_DIR"/{wheels,tessdata,debs,models}

info "Building image-ingest offline bundle at: $OUTPUT_DIR"

if [[ "$SKIP_WHEELS" != "true" ]]; then
    platform_tag="$(detect_manylinux_platform)"
    info "Downloading Python wheels for $platform_tag / Python 3.12"
    "$PYTHON_BIN" -m pip install --quiet --upgrade pip wheel
    "$PYTHON_BIN" -m pip download \
        --dest "$OUTPUT_DIR/wheels" \
        --only-binary=:all: \
        --platform "$platform_tag" \
        --python-version 312 \
        --implementation cp \
        "Pillow==${PILLOW_VERSION}" \
        "pypdfium2==${PYPDFIUM2_VERSION}"
else
    info "SKIP_WHEELS=true; wheels/ left unchanged"
fi

if [[ "$SKIP_TESSDATA" != "true" ]]; then
    info "Downloading tessdata_fast language files"
    curl -fsSL "$TESSDATA_ENG_URL" -o "$OUTPUT_DIR/tessdata/eng.traineddata"
    curl -fsSL "$TESSDATA_OSD_URL" -o "$OUTPUT_DIR/tessdata/osd.traineddata"
else
    info "SKIP_TESSDATA=true; tessdata/ left unchanged"
fi

download_tesseract_deb_closure() {
    local deb_dir="$1"
    shift
    local packages=("$@")
    local pkg deb_names=()

    if ! command -v apt-cache >/dev/null 2>&1; then
        warn "apt-cache not found; cannot resolve tesseract package dependencies"
        return 1
    fi

    mapfile -t deb_names < <(
        apt-cache depends --recurse --no-recommends --no-suggests \
            --no-conflicts --no-breaks --no-replaces --no-enhances \
            "${packages[@]}" 2>/dev/null \
            | awk '/^[[:alnum:]/ { print $1 }' \
            | sort -u
    )

    if [[ ${#deb_names[@]} -eq 0 ]]; then
        warn "Could not resolve dependency list for: ${packages[*]}"
        return 1
    fi

    mkdir -p "$deb_dir"
    (
        cd "$deb_dir"
        for pkg in "${deb_names[@]}"; do
            apt-get download "$pkg" 2>/dev/null || warn "apt-get download failed for $pkg"
        done
    )
}

if [[ "$SKIP_DEBS" != "true" ]]; then
    if command -v apt-get >/dev/null 2>&1; then
        info "Downloading Ubuntu/Debian tesseract runtime packages (with dependencies) into debs/"
        download_tesseract_deb_closure "$OUTPUT_DIR/debs" tesseract-ocr tesseract-ocr-eng \
            || warn "Dependency-aware deb download failed; debs/ may be incomplete"
        if [[ -z "$(find "$OUTPUT_DIR/debs" -maxdepth 1 -name '*.deb' -print -quit)" ]]; then
            warn "No .deb files downloaded. Air-gapped hosts must install tesseract-ocr manually."
        else
            deb_count="$(find "$OUTPUT_DIR/debs" -maxdepth 1 -name '*.deb' | wc -l | tr -d ' ')"
            info "debs/: $deb_count .deb file(s) staged"
        fi
    else
        warn "apt-get not found; debs/ will remain empty. Install tesseract OS packages manually on the target."
    fi
else
    info "SKIP_DEBS=true; debs/ left unchanged"
fi

if [[ "$SKIP_MODELS" != "true" ]]; then
    info "Ensuring huggingface_hub is available for model snapshots"
    "$PYTHON_BIN" -m pip install --quiet "$HUGGINGFACE_HUB_PIP_SPEC"

    download_model() {
        local repo_id="$1"
        local bundle_name="$2"
        local local_dir="$OUTPUT_DIR/models/$bundle_name"
        info "Downloading Hugging Face model: $repo_id -> $local_dir"
        HF_TOKEN="${HF_TOKEN:-${HUGGINGFACE_TOKEN:-}}" \
        "$PYTHON_BIN" - "$repo_id" "$local_dir" <<'PY'
import os
import sys
from huggingface_hub import snapshot_download

repo_id = sys.argv[1]
local_dir = sys.argv[2]
token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN") or None

snapshot_download(
    repo_id=repo_id,
    local_dir=local_dir,
    local_dir_use_symlinks=False,
    token=token,
    resume_download=True,
)
print(f"Downloaded {repo_id} to {local_dir}")
PY
    }

    download_model "$EMBED_REPO_ID" "$EMBED_BUNDLE_NAME"
    download_model "$RERANK_REPO_ID" "$RERANK_BUNDLE_NAME"
else
    info "SKIP_MODELS=true; models/ left unchanged"
fi

info "Writing manifest.json (sha256 per file)"
"$PYTHON_BIN" - "$OUTPUT_DIR" <<'PY'
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

bundle_root = Path(sys.argv[1])
files = []
for path in sorted(p for p in bundle_root.rglob("*") if p.is_file()):
    if path.name in {"manifest.json", "BUNDLE_README.txt"}:
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    rel = path.relative_to(bundle_root).as_posix()
    files.append({"path": rel, "sha256": digest, "bytes": path.stat().st_size})

manifest = {
    "bundle_type": "image-ingest-prerequisites",
    "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "file_count": len(files),
    "files": files,
}
(bundle_root / "manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(f"manifest.json: {len(files)} files")
PY

cat > "$OUTPUT_DIR/BUNDLE_README.txt" <<EOF
Image Ingest Offline Bundle
===========================

Built for air-gapped installation of image-ingest prerequisites:
  - Tesseract OCR language data (eng, osd)
  - Optional Ubuntu tesseract OS packages (debs/)
  - Python wheels: Pillow==${PILLOW_VERSION}, pypdfium2==${PYPDFIUM2_VERSION}
  - IBM Granite retrieval models (768-dim embed + rerank)

This bundle does NOT include Gemma 4 vision weights. Stage Gemma separately via
scripts/install.sh (MODEL_DOWNLOAD) or your approved offline model transfer.

Transfer steps (operator policy):
  1. Verify manifest.json checksums after copy (sha256sum -c on the target).
  2. Copy this entire directory to removable media or an approved transfer path.
  3. On the air-gapped host, after scripts/install.sh:
       sudo bash scripts/install_image_ingest_prerequisites.sh \\
         --bundle-dir /path/to/this/bundle
       sudo bash scripts/configure_us_granite_retrieval_defaults.sh \\
         --config-env /etc/notable-analyzer/config.env \\
         --portal-env /etc/notable-analyzer/portal.env
       sudo bash scripts/verify_image_ingest_prerequisites.sh \\
         --config-env /etc/notable-analyzer/config.env
  4. Rebuild KB and closed-ticket indexes after migrating from Mixedbread (768-dim).

See docs/operations/rag/IMAGE_INGEST_PREREQUISITES.md for full scope and migration notes.
EOF

info "Bundle complete: $OUTPUT_DIR"
info "Transfer manifest.json and BUNDLE_README.txt with the bundle directory"
