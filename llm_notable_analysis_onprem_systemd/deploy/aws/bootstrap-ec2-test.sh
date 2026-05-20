#!/usr/bin/env bash
# Bootstrap a RHEL 8/9 GPU host for the on-prem notable analyzer test VM.
# Invoked by cloud-init UserData (see template-ec2-test.yaml). Safe to re-run.
set -euo pipefail
IFS=$'\n\t'

LOG_FILE="${LOG_FILE:-/var/log/notable-analyzer-bootstrap.log}"
MARKER_DIR="${MARKER_DIR:-/var/lib/notable-analyzer-bootstrap}"
REPO_ROOT="${REPO_ROOT:-/opt/llm-notable-analysis-src}"
ONPREM_DIR="${ONPREM_DIR:-$REPO_ROOT/llm_notable_analysis_onprem_systemd}"
PYTHON_BIN="${PYTHON_BIN:-}"

exec >>"$LOG_FILE" 2>&1
echo "=== notable-analyzer bootstrap $(date -Is) ==="

require_root() {
  [[ "${EUID:-$(id -u)}" -eq 0 ]] || {
    echo "ERROR: bootstrap must run as root"
    exit 1
  }
}

marker() {
  touch "$MARKER_DIR/$1"
}

has_marker() {
  [[ -f "$MARKER_DIR/$1" ]]
}

detect_rhel_major_version() {
  if [[ -n "${RHEL_MAJOR_VERSION:-}" ]]; then
    printf '%s' "$RHEL_MAJOR_VERSION"
    return 0
  fi
  if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    if [[ "${ID:-}" == "rhel" && -n "${VERSION_ID:-}" ]]; then
      printf '%s' "${VERSION_ID%%.*}"
      return 0
    fi
  fi
  echo "ERROR: could not detect RHEL major version; set RHEL_MAJOR_VERSION=8 or 9"
  exit 1
}

select_python_bin() {
  local rhel_major="$1"
  local candidate=""

  if [[ "$rhel_major" == "9" ]]; then
    candidate="python3.12"
  elif [[ "$rhel_major" == "8" ]]; then
    if dnf -q list available python3.12 2>/dev/null | grep -q '^python3.12'; then
      candidate="python3.12"
    else
      candidate="python3.11"
    fi
  else
    echo "ERROR: unsupported RHEL major version: $rhel_major (expected 8 or 9)"
    exit 1
  fi

  dnf -y install \
    "$candidate" \
    "${candidate}-pip" \
    "${candidate}-devel"
  command -v "$candidate" >/dev/null 2>&1 || {
    echo "ERROR: failed to install Python interpreter: $candidate"
    exit 1
  }
  PYTHON_BIN="$candidate"
  echo "[python] selected $PYTHON_BIN for RHEL $rhel_major"
}

install_base_packages() {
  local rhel_major="$1"

  echo "[packages] installing OS prerequisites for RHEL $rhel_major"
  dnf -y update
  dnf -y install \
    git \
    curl \
    rsync \
    tar \
    gcc \
    make \
    policycoreutils-python-utils \
    kernel-devel-"$(uname -r)" \
    kernel-headers-"$(uname -r)"

  select_python_bin "$rhel_major"
  marker "python-${PYTHON_BIN}"
}

install_nvidia_drivers() {
  local rhel_major="$1"

  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    echo "[nvidia] driver already present"
    return 0
  fi

  echo "[nvidia] installing CUDA driver stack for RHEL $rhel_major"
  dnf config-manager --add-repo \
    "https://developer.download.nvidia.com/compute/cuda/repos/rhel${rhel_major}/x86_64/cuda-rhel${rhel_major}.repo"
  dnf -y install cuda-drivers
  modprobe nvidia || true
}

clone_repo() {
  local git_url="$1"
  local git_ref="$2"

  echo "[git] cloning $git_url (ref=$git_ref)"
  rm -rf "$REPO_ROOT"
  git clone --depth 1 --branch "$git_ref" "$git_url" "$REPO_ROOT"
  [[ -f "$ONPREM_DIR/scripts/install.sh" ]]
  [[ -d "$REPO_ROOT/onprem_rag_notable_analysis" ]] || {
    echo "ERROR: expected sibling package at $REPO_ROOT/onprem_rag_notable_analysis"
    exit 1
  }
}

fetch_hf_token() {
  local secret_arn="${1:-}"
  if [[ -n "$secret_arn" && "$secret_arn" != "none" ]]; then
    aws secretsmanager get-secret-value \
      --secret-id "$secret_arn" \
      --query SecretString \
      --output text
    return 0
  fi
  if [[ -n "${HF_TOKEN:-}" ]]; then
    printf '%s' "$HF_TOKEN"
    return 0
  fi
  echo ""
}

ensure_repo_checkout() {
  local git_url="${GIT_CLONE_URL:-}"
  local git_ref="${GIT_BRANCH:-main}"

  if [[ -f "$ONPREM_DIR/scripts/install.sh" && -d "$REPO_ROOT/onprem_rag_notable_analysis" ]]; then
    echo "[git] repo already present at $REPO_ROOT"
    return 0
  fi

  [[ -n "$git_url" ]] || {
    echo "ERROR: GIT_CLONE_URL is required when repo is not already present"
    exit 1
  }

  clone_repo "$git_url" "$git_ref"
}

run_installer() {
  local hf_token="$1"
  local model_download="${MODEL_DOWNLOAD:-true}"
  local python_bin="${PYTHON_BIN:-python3.12}"

  echo "[install] running scripts/install.sh"
  cd "$ONPREM_DIR"

  export ANALYZER_PYTHON_BIN="$python_bin"
  export VLLM_PYTHON_BIN="$python_bin"
  export AUTO_START_SERVICES=true
  export RUN_SMOKE_TEST=true
  export VLLM_HEALTH_TIMEOUT_SECONDS="${VLLM_HEALTH_TIMEOUT_SECONDS:-900}"
  export SMOKE_TEST_TIMEOUT_SECONDS="${SMOKE_TEST_TIMEOUT_SECONDS:-600}"
  export MODEL_DOWNLOAD="$model_download"
  export MODEL_REPO="${MODEL_REPO:-google/gemma-4-31B-it}"
  export VLLM_MODEL_PATH="${VLLM_MODEL_PATH:-/opt/models/gemma-4-31B-it}"
  export VLLM_SERVED_MODEL_NAME="${VLLM_SERVED_MODEL_NAME:-gemma-4-31B-it}"

  if [[ -n "$hf_token" ]]; then
    export HF_TOKEN="$hf_token"
  else
    echo "WARN: no Hugging Face token supplied; model download will be skipped"
    export MODEL_DOWNLOAD=false
  fi

  bash scripts/install.sh
}

run_smoke_chain() {
  echo "[verify] running smoke_service_chain.sh"
  cd "$ONPREM_DIR"
  bash scripts/smoke_service_chain.sh --config-env /etc/notable-analyzer/config.env
}

write_status() {
  cat >/etc/notable-analyzer/bootstrap-status.txt <<EOF
bootstrap_completed_at=$(date -Is)
repo_root=$REPO_ROOT
services=$(systemctl is-active vllm litellm notable-analyzer 2>/dev/null | paste -sd' ' -)
nvidia_smi=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -n1 || echo unavailable)
EOF
  chmod 644 /etc/notable-analyzer/bootstrap-status.txt
}

main() {
  require_root
  mkdir -p "$MARKER_DIR"

  if [[ -f /etc/notable-analyzer-bootstrap.env ]]; then
    set -a
    # shellcheck disable=SC1091
    source /etc/notable-analyzer-bootstrap.env
    set +a
  fi

  local rhel_major
  rhel_major="$(detect_rhel_major_version)"

  if ! has_marker packages; then
    install_base_packages "$rhel_major"
    marker packages
  elif [[ -z "$PYTHON_BIN" ]]; then
    for py_marker in "$MARKER_DIR"/python-*; do
      if [[ -f "$py_marker" ]]; then
        PYTHON_BIN="${py_marker##*/python-}"
        break
      fi
    done
    [[ -n "$PYTHON_BIN" ]] || select_python_bin "$rhel_major"
  fi

  if ! has_marker nvidia; then
    install_nvidia_drivers "$rhel_major"
    if ! command -v nvidia-smi >/dev/null 2>&1 || ! nvidia-smi >/dev/null 2>&1; then
      echo "[nvidia] driver install requires reboot"
      marker nvidia-pending
      systemctl reboot
      exit 0
    fi
    marker nvidia
  fi

  if has_marker nvidia-pending && ! has_marker nvidia; then
    if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
      marker nvidia
    else
      echo "ERROR: nvidia-smi still unavailable after reboot"
      exit 1
    fi
  fi

  if ! has_marker repo; then
    ensure_repo_checkout
    marker repo
  fi

  if ! has_marker installed; then
    token="$(fetch_hf_token "${HF_TOKEN_SECRET_ARN:-}")"
    run_installer "$token"
    marker installed
  fi

  if ! has_marker verified; then
    run_smoke_chain
    marker verified
  fi

  write_status
  echo "=== bootstrap complete $(date -Is) ==="
}

main "$@"
