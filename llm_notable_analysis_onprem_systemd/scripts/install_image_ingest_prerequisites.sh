#!/usr/bin/env bash
# Install image-ingest prerequisites from an offline bundle on an air-gapped host.
# Idempotent: skips components that are already installed or staged.
#
# Does NOT enable network access. Operator must transfer the bundle directory first.
#
# Related: docs/operations/rag/IMAGE_INGEST_PREREQUISITES.md
set -euo pipefail
IFS=$'\n\t'

BUNDLE_DIR="${BUNDLE_DIR:-}"
CONFIG_ENV="${CONFIG_ENV:-/etc/notable-analyzer/config.env}"
ANALYZER_VENV="${ANALYZER_VENV:-/opt/notable-analyzer/venv}"
DRY_RUN="${DRY_RUN:-false}"

PILLOW_SPEC="${PILLOW_SPEC:-Pillow==11.1.0}"
PYPDFIUM2_SPEC="${PYPDFIUM2_SPEC:-pypdfium2==4.30.0}"

EMBED_REPO_ID="ibm-granite/granite-embedding-english-r2"
RERANK_REPO_ID="ibm-granite/granite-embedding-reranker-english-r2"
EMBED_BUNDLE_NAME="granite-embedding-english-r2"
RERANK_BUNDLE_NAME="granite-embedding-reranker-english-r2"

DEFAULT_HF_HOME="/var/notables/cache/huggingface"
DEFAULT_ST_HOME="/var/notables/cache/sentence-transformers"

usage() {
    cat <<'EOF'
Usage: install_image_ingest_prerequisites.sh [options]

Install image-ingest prerequisites from an offline bundle (air-gapped target).
Requires --bundle-dir pointing at a bundle built by build_image_ingest_offline_bundle.sh.

Installs (idempotent):
  - OS packages from bundle debs/*.deb when present (else warns for manual tesseract)
  - tessdata eng/osd into detected Tesseract tessdata directory
  - Pillow and pypdfium2 into the analyzer venv via offline wheels
  - IBM Granite embed/rerank models into HF_HOME and SENTENCE_TRANSFORMERS_HOME

Does not download Gemma or touch network settings.

Options:
  --bundle-dir PATH     Offline bundle root (required)
  --config-env PATH     Analyzer config.env for cache path overrides (default: /etc/notable-analyzer/config.env)
  --analyzer-venv PATH  Analyzer virtualenv (default: /opt/notable-analyzer/venv)
  --dry-run             Print planned actions without making changes
  -h, --help            Show this help

Environment overrides:
  BUNDLE_DIR, CONFIG_ENV, ANALYZER_VENV, DRY_RUN, PILLOW_SPEC, PYPDFIUM2_SPEC
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

run_or_dry() {
    if [[ "$DRY_RUN" == "true" ]]; then
        info "[dry-run] $*"
    else
        "$@"
    fi
}

read_config_value() {
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

detect_tessdata_dir() {
    local candidate
    for candidate in \
        /usr/share/tesseract-ocr/5/tessdata \
        /usr/share/tesseract-ocr/4.00/tessdata \
        /usr/share/tesseract-ocr/tessdata \
        /usr/share/tessdata; do
        if [[ -d "$candidate" ]]; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

install_debs_if_present() {
    local deb_dir="$BUNDLE_DIR/debs"
    if [[ ! -d "$deb_dir" ]]; then
        warn "Bundle has no debs/ directory; install tesseract-ocr manually if needed"
        return 0
    fi
    shopt -s nullglob
    local debs=( "$deb_dir"/*.deb )
    shopt -u nullglob
    if [[ ${#debs[@]} -eq 0 ]]; then
        warn "Bundle debs/ is empty; install tesseract-ocr, tesseract-ocr-eng, and leptonica manually"
        return 0
    fi
    if command -v tesseract >/dev/null 2>&1; then
        info "tesseract already installed; skipping OS package install"
        return 0
    fi
    if command -v apt-get >/dev/null 2>&1; then
        info "Installing OS packages from bundle debs/ via apt-get"
        info "When apt repositories are reachable, apt-get resolves any missing dependencies"
        if [[ "$DRY_RUN" == "true" ]]; then
            info "[dry-run] apt-get install -y ${debs[*]}"
        else
            apt-get install -y "${debs[@]}"
        fi
        return 0
    fi
    info "Installing OS packages from bundle debs/ via dpkg -i (air-gapped; bundle must include all dependencies)"
    if [[ "$DRY_RUN" == "true" ]]; then
        info "[dry-run] dpkg -i ${debs[*]}"
        return 0
    fi
    dpkg -i "${debs[@]}" || err \
        "dpkg failed. Rebuild the bundle on a connected host so debs/ includes dependency closures, or install tesseract-ocr from local apt media."
}

install_tessdata_if_needed() {
    local src_dir="$BUNDLE_DIR/tessdata"
    [[ -d "$src_dir" ]] || { warn "Bundle has no tessdata/; skipping language data install"; return 0; }

    local dest_dir
    dest_dir="$(detect_tessdata_dir)" || {
        warn "Could not detect Tesseract tessdata directory; copy eng.traineddata and osd.traineddata manually"
        return 0
    }

    local file
    for file in eng.traineddata osd.traineddata; do
        if [[ ! -f "$src_dir/$file" ]]; then
            warn "Missing bundle tessdata file: $file"
            continue
        fi
        if [[ -f "$dest_dir/$file" ]]; then
            info "Tessdata already present: $dest_dir/$file"
            continue
        fi
        info "Installing tessdata: $file -> $dest_dir/"
        run_or_dry install -m 0644 "$src_dir/$file" "$dest_dir/$file"
    done
}

venv_has_image_packages() {
    [[ -x "$ANALYZER_VENV/bin/python" ]] || return 1
    "$ANALYZER_VENV/bin/python" - "$PILLOW_SPEC" "$PYPDFIUM2_SPEC" <<'PY'
import importlib.metadata as md
import sys

pillow_spec = sys.argv[1]
pypdfium_spec = sys.argv[2]

def expected_version(spec: str) -> str:
    if "==" in spec:
        return spec.split("==", 1)[1]
    return ""

for module_name, spec in (("PIL", pillow_spec), ("pypdfium2", pypdfium_spec)):
    try:
        dist = md.version("Pillow" if module_name == "PIL" else "pypdfium2")
    except md.PackageNotFoundError:
        raise SystemExit(1)
    expected = expected_version(spec)
    if expected and dist != expected:
        raise SystemExit(1)
    __import__(module_name)
raise SystemExit(0)
PY
}

install_python_wheels() {
    local wheels_dir="$BUNDLE_DIR/wheels"
    [[ -d "$wheels_dir" ]] || err "Bundle missing wheels/ directory"

    [[ -x "$ANALYZER_VENV/bin/pip" ]] || err "Analyzer venv pip not found: $ANALYZER_VENV/bin/pip"

    if venv_has_image_packages; then
        info "Pillow and pypdfium2 already installed in analyzer venv; skipping pip install"
        return 0
    fi

    info "Installing offline wheels into analyzer venv: $PILLOW_SPEC, $PYPDFIUM2_SPEC"
    run_or_dry "$ANALYZER_VENV/bin/pip" install \
        --no-index \
        --find-links "$wheels_dir" \
        "$PILLOW_SPEC" \
        "$PYPDFIUM2_SPEC"
}

install_model_snapshot() {
    local repo_id="$1"
    local bundle_name="$2"
    local cache_root="$3"
    local src_dir="$BUNDLE_DIR/models/$bundle_name"
    local hub_name
    local dest_snapshot

    [[ -d "$src_dir" ]] || {
        warn "Bundle missing model directory: models/$bundle_name"
        return 0
    }
    [[ -f "$src_dir/config.json" ]] || warn "Model tree missing config.json: $src_dir"

    hub_name="$(hf_hub_cache_name "$repo_id")"
    dest_snapshot="$cache_root/hub/$hub_name/snapshots/offline-bundle"

    if [[ -f "$dest_snapshot/config.json" ]]; then
        info "Model already staged: $repo_id at $dest_snapshot"
        return 0
    fi

    info "Staging model offline: $repo_id -> $dest_snapshot"
    if [[ "$DRY_RUN" == "true" ]]; then
        info "[dry-run] mkdir -p $dest_snapshot && cp -a $src_dir/. $dest_snapshot/"
        info "[dry-run] write refs/main -> ../snapshots/offline-bundle under $cache_root/hub/$hub_name"
        return 0
    fi

    mkdir -p "$dest_snapshot"
    cp -a "$src_dir/." "$dest_snapshot/"
    mkdir -p "$cache_root/hub/$hub_name/refs"
    printf '../snapshots/offline-bundle\n' > "$cache_root/hub/$hub_name/refs/main"
}

install_granite_models() {
    local hf_home st_home
    hf_home="$(read_config_value HF_HOME "$DEFAULT_HF_HOME")"
    st_home="$(read_config_value SENTENCE_TRANSFORMERS_HOME "$DEFAULT_ST_HOME")"

    for cache_root in "$hf_home" "$st_home"; do
        run_or_dry mkdir -p "$cache_root/hub"
        install_model_snapshot "$EMBED_REPO_ID" "$EMBED_BUNDLE_NAME" "$cache_root"
        install_model_snapshot "$RERANK_REPO_ID" "$RERANK_BUNDLE_NAME" "$cache_root"
    done
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bundle-dir)
            require_arg_value "$1" "${2:-}"
            BUNDLE_DIR="$2"
            shift 2
            ;;
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
        --dry-run)
            DRY_RUN="true"
            shift
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

[[ -n "$BUNDLE_DIR" ]] || err "--bundle-dir is required"
[[ -d "$BUNDLE_DIR" ]] || err "Bundle directory not found: $BUNDLE_DIR"
[[ -f "$BUNDLE_DIR/manifest.json" ]] || warn "Bundle manifest.json not found; continue only if transfer was verified manually"

require_command python3
require_command install
require_command cp

info "Installing image-ingest prerequisites from bundle: $BUNDLE_DIR"
if [[ "$DRY_RUN" == "true" ]]; then
    warn "DRY_RUN=true; no changes will be made"
fi

install_debs_if_present
install_tessdata_if_needed
install_python_wheels
install_granite_models

info "Image-ingest prerequisite install complete"

cat <<'EOF'

Next steps:
  1. Apply Granite retrieval defaults in analyzer and portal env:
       sudo bash scripts/configure_us_granite_retrieval_defaults.sh \
         --config-env /etc/notable-analyzer/config.env \
         --portal-env /etc/notable-analyzer/portal.env
  2. Verify prerequisites (includes optional multimodal loopback test):
       sudo bash scripts/verify_image_ingest_prerequisites.sh \
         --config-env /etc/notable-analyzer/config.env
  3. Rebuild KB lanes and closed-ticket chunks after migrating from Mixedbread
     (768-dim Granite replaces 1024-dim indexes). See
     docs/operations/rag/IMAGE_INGEST_PREREQUISITES.md

EOF
