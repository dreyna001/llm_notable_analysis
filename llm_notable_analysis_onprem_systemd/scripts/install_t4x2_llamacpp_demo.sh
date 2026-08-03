#!/usr/bin/env bash
# One-command online installer for the two-NVIDIA-T4 llama.cpp demo profile.
# Run from a checked-out repository with sudo/root.
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

readonly LLAMACPP_ROOT="/opt/llamacpp-gemma"
readonly LLAMACPP_SOURCE_DIR="$LLAMACPP_ROOT/src"
readonly LLAMACPP_BUILD_DIR="$LLAMACPP_SOURCE_DIR/build-t4-sm75"
readonly LLAMACPP_MODEL_DIR="$LLAMACPP_ROOT/models"
readonly LLAMACPP_REPOSITORY="https://github.com/ggml-org/llama.cpp.git"
readonly LLAMACPP_REVISION="dbadb68eecdfb3ab0e86872d011738fc937f0364"
readonly MODEL_REPOSITORY="google/gemma-4-26B-A4B-it-qat-q4_0-gguf"
readonly MODEL_REVISION="d1c082be9cf3c8a514acf63b8761f4b41935842e"
readonly MODEL_FILE="gemma-4-26B_q4_0-it.gguf"
readonly MODEL_SHA256="3eca3b8f6d7baf218a7dd6bba5fb59a56ee25fe2d567b6f5f589b4f697eca51d"
readonly MMPROJ_FILE="gemma-4-26B-it-mmproj.gguf"
readonly MMPROJ_SHA256="a359953a076b877db30c31dbbb4c6d93b4a6e017ee5db5784247e4d4c0dd4f3b"
readonly MODEL_BASE_URL="https://huggingface.co/$MODEL_REPOSITORY/resolve/$MODEL_REVISION"

readonly CUDA_VISIBLE_DEVICES_VALUE="${T4_CUDA_VISIBLE_DEVICES:-0,1}"
readonly INSTALL_ANALYST_PORTAL_VALUE="${T4_INSTALL_ANALYST_PORTAL:-true}"
readonly AUTO_START_VALUE="${T4_AUTO_START:-true}"
readonly SKIP_BASE_INSTALL_VALUE="${T4_SKIP_BASE_INSTALL:-false}"
readonly SKIP_DISK_CHECK_VALUE="${T4_SKIP_DISK_CHECK:-false}"
readonly BUILD_JOBS_VALUE="${LLAMACPP_BUILD_JOBS:-8}"

err() {
    echo "ERROR: $*" >&2
    exit 1
}

info() {
    echo "  $*"
}

usage() {
    cat <<'EOF'
Usage: sudo bash scripts/install_t4x2_llamacpp_demo.sh

Environment flags:
  T4_CUDA_VISIBLE_DEVICES=0,1  Two physical GPU indexes (default: 0,1)
  T4_INSTALL_ANALYST_PORTAL=true
                               Install the full portal stack (default: true)
  T4_AUTO_START=true           Start and smoke-test services (default: true)
  T4_SKIP_BASE_INSTALL=false   Reuse an existing base installation
  T4_SKIP_DISK_CHECK=false     Skip the 25 GiB free-space preflight
  LLAMACPP_BUILD_JOBS=8        Parallel compile jobs

The NVIDIA driver and CUDA toolkit (nvcc) are host prerequisites because their
installation is OS/repository/reboot specific. Everything else is installed or
downloaded by this script. Model and llama.cpp revisions are checksum/pin locked.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi
[[ $# -eq 0 ]] || err "Unknown argument: $1 (use --help)"
[[ "${EUID:-$(id -u)}" -eq 0 ]] || err "Run this installer as root (sudo)"
[[ -f "$PROJECT_DIR/scripts/install.sh" ]] || err "Base installer is missing"
[[ -f "$PROJECT_DIR/scripts/apply_t4x2_llamacpp_demo_profile.sh" ]] || err "Profile installer is missing"

for boolean_value in \
    "$INSTALL_ANALYST_PORTAL_VALUE" \
    "$AUTO_START_VALUE" \
    "$SKIP_BASE_INSTALL_VALUE" \
    "$SKIP_DISK_CHECK_VALUE"; do
    [[ "$boolean_value" == "true" || "$boolean_value" == "false" ]] \
        || err "Boolean flags must be 'true' or 'false' (got: $boolean_value)"
done
[[ "$BUILD_JOBS_VALUE" =~ ^[1-9][0-9]*$ ]] || err "LLAMACPP_BUILD_JOBS must be a positive integer"

install_build_dependencies() {
    if command -v apt-get >/dev/null 2>&1; then
        info "Installing llama.cpp build dependencies with apt"
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y \
            build-essential ca-certificates cmake curl git pkg-config
    elif command -v dnf >/dev/null 2>&1; then
        info "Installing llama.cpp build dependencies with dnf"
        dnf install -y ca-certificates cmake curl gcc-c++ git make pkgconf-pkg-config
    elif command -v yum >/dev/null 2>&1; then
        info "Installing llama.cpp build dependencies with yum"
        yum install -y ca-certificates cmake curl gcc-c++ git make pkgconfig
    else
        err "Unsupported package manager; install CMake, Git, curl, GCC/G++, make, and pkg-config"
    fi
}

find_nvcc() {
    if [[ -n "${CUDA_HOME:-}" && -x "$CUDA_HOME/bin/nvcc" ]]; then
        printf '%s\n' "$CUDA_HOME/bin/nvcc"
    elif [[ -x /usr/local/cuda/bin/nvcc ]]; then
        printf '%s\n' /usr/local/cuda/bin/nvcc
    elif command -v nvcc >/dev/null 2>&1; then
        command -v nvcc
    else
        return 1
    fi
}

validate_gpu_contract() {
    command -v nvidia-smi >/dev/null 2>&1 \
        || err "nvidia-smi is missing; install a compatible NVIDIA driver first"

    local selected_gpus=()
    local split_ifs=','
    IFS="$split_ifs" read -r -a selected_gpus <<< "$CUDA_VISIBLE_DEVICES_VALUE"
    [[ "${#selected_gpus[@]}" -eq 2 ]] \
        || err "T4_CUDA_VISIBLE_DEVICES must contain exactly two GPU indexes"
    [[ "${selected_gpus[0]}" =~ ^[0-9]+$ && "${selected_gpus[1]}" =~ ^[0-9]+$ ]] \
        || err "T4_CUDA_VISIBLE_DEVICES must contain numeric GPU indexes"
    [[ "${selected_gpus[0]}" != "${selected_gpus[1]}" ]] \
        || err "T4_CUDA_VISIBLE_DEVICES must select two different GPUs"

    local gpu_id gpu_line gpu_name memory_mib
    for gpu_id in "${selected_gpus[@]}"; do
        gpu_line="$(nvidia-smi -i "$gpu_id" --query-gpu=name,memory.total --format=csv,noheader,nounits 2>/dev/null)" \
            || err "Unable to inspect NVIDIA GPU $gpu_id"
        gpu_name="${gpu_line%,*}"
        memory_mib="${gpu_line##*,}"
        memory_mib="${memory_mib//[[:space:]]/}"
        [[ "$memory_mib" =~ ^[0-9]+$ && "$memory_mib" -ge 15000 ]] \
            || err "GPU $gpu_id has less than 15,000 MiB VRAM: $gpu_line"
        [[ "$gpu_name" == *T4* ]] || err "GPU $gpu_id is not an NVIDIA T4: $gpu_name"
        info "GPU $gpu_id: $gpu_name, ${memory_mib} MiB"
    done
}

validate_disk_space() {
    [[ "$SKIP_DISK_CHECK_VALUE" != "true" ]] || return 0
    local available_kib
    available_kib="$(df -Pk /opt | awk 'NR == 2 {print $4}')"
    [[ "$available_kib" =~ ^[0-9]+$ ]] || err "Could not determine free space under /opt"
    (( available_kib >= 25 * 1024 * 1024 )) \
        || err "At least 25 GiB free under /opt is required for source, build, and model files"
}

create_service_user() {
    if ! getent group llamacpp >/dev/null 2>&1; then
        groupadd --system llamacpp
    fi
    if ! id llamacpp >/dev/null 2>&1; then
        local nologin_shell
        nologin_shell="$(command -v nologin || true)"
        [[ -n "$nologin_shell" ]] || nologin_shell=/sbin/nologin
        useradd --system --gid llamacpp --home-dir /nonexistent --shell "$nologin_shell" llamacpp
    fi
}

checkout_llamacpp() {
    install -d -o root -g root -m 0755 "$LLAMACPP_ROOT"
    if [[ -d "$LLAMACPP_SOURCE_DIR/.git" ]]; then
        local origin_url
        origin_url="$(git -C "$LLAMACPP_SOURCE_DIR" remote get-url origin)"
        [[ "$origin_url" == "$LLAMACPP_REPOSITORY" ]] \
            || err "$LLAMACPP_SOURCE_DIR has unexpected Git origin: $origin_url"
        [[ -z "$(git -C "$LLAMACPP_SOURCE_DIR" status --porcelain --untracked-files=no)" ]] \
            || err "$LLAMACPP_SOURCE_DIR has modified tracked files; refusing to overwrite them"
        git -C "$LLAMACPP_SOURCE_DIR" fetch --depth 1 origin "$LLAMACPP_REVISION"
    elif [[ -e "$LLAMACPP_SOURCE_DIR" ]]; then
        err "$LLAMACPP_SOURCE_DIR exists but is not a llama.cpp Git checkout"
    else
        install -d -o root -g root -m 0755 "$LLAMACPP_SOURCE_DIR"
        git -C "$LLAMACPP_SOURCE_DIR" init
        git -C "$LLAMACPP_SOURCE_DIR" remote add origin "$LLAMACPP_REPOSITORY"
        git -C "$LLAMACPP_SOURCE_DIR" fetch --depth 1 origin "$LLAMACPP_REVISION"
    fi
    git -C "$LLAMACPP_SOURCE_DIR" -c advice.detachedHead=false checkout --detach FETCH_HEAD
    [[ "$(git -C "$LLAMACPP_SOURCE_DIR" rev-parse HEAD)" == "$LLAMACPP_REVISION" ]] \
        || err "llama.cpp checkout does not match the pinned revision"
}

build_llamacpp() {
    local nvcc_path
    nvcc_path="$(find_nvcc)" \
        || err "CUDA toolkit compiler (nvcc) is missing; install a toolkit compatible with the NVIDIA driver"
    info "Building pinned llama.cpp for NVIDIA T4 compute capability 7.5"
    CUDACXX="$nvcc_path" cmake \
        -S "$LLAMACPP_SOURCE_DIR" \
        -B "$LLAMACPP_BUILD_DIR" \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_CUDA_ARCHITECTURES=75 \
        -DGGML_CUDA=ON \
        -DGGML_NATIVE=OFF \
        -DLLAMA_CURL=OFF \
        -DLLAMA_BUILD_SERVER=ON \
        -DBUILD_SHARED_LIBS=OFF
    cmake --build "$LLAMACPP_BUILD_DIR" --config Release --parallel "$BUILD_JOBS_VALUE"
    [[ -x "$LLAMACPP_BUILD_DIR/bin/llama-server" ]] \
        || err "llama-server was not produced by the build"
}

download_verified() {
    local url="$1"
    local destination="$2"
    local expected_sha256="$3"
    local partial="${destination}.partial"

    if [[ -f "$destination" ]]; then
        if printf '%s  %s\n' "$expected_sha256" "$destination" | sha256sum --check --status; then
            info "Using verified existing model file: $destination"
            return 0
        fi
        err "Existing model file failed checksum; move it aside and rerun: $destination"
    fi

    info "Downloading $(basename -- "$destination")"
    curl --fail --location --retry 5 --retry-delay 5 --continue-at - \
        --output "$partial" "$url"
    printf '%s  %s\n' "$expected_sha256" "$partial" | sha256sum --check --status \
        || {
            local rejected="${partial}.bad.$(date -u +%Y%m%dT%H%M%SZ)"
            mv -- "$partial" "$rejected"
            err "Checksum failed; rejected download retained at: $rejected"
        }
    install -o root -g llamacpp -m 0640 "$partial" "$destination"
    rm -f -- "$partial"
}

install_runtime_assets() {
    install -d -o root -g llamacpp -m 0750 "$LLAMACPP_MODEL_DIR"
    download_verified "$MODEL_BASE_URL/$MODEL_FILE" "$LLAMACPP_MODEL_DIR/$MODEL_FILE" "$MODEL_SHA256"
    download_verified "$MODEL_BASE_URL/$MMPROJ_FILE" "$LLAMACPP_MODEL_DIR/$MMPROJ_FILE" "$MMPROJ_SHA256"

    install -d -o root -g root -m 0755 /etc/notable-analyzer
    if [[ ! -f /etc/notable-analyzer/llamacpp-gemma.env ]]; then
        install -o root -g llamacpp -m 0640 \
            "$PROJECT_DIR/deploy/llamacpp/t4x2-gemma4.env.example" \
            /etc/notable-analyzer/llamacpp-gemma.env
    fi
    sed -i -E \
        "s/^CUDA_VISIBLE_DEVICES=.*/CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES_VALUE/" \
        /etc/notable-analyzer/llamacpp-gemma.env
    grep -Fqx "CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES_VALUE" \
        /etc/notable-analyzer/llamacpp-gemma.env \
        || err "Runtime env is missing a replaceable CUDA_VISIBLE_DEVICES assignment"

    install -o root -g root -m 0644 \
        "$PROJECT_DIR/deploy/systemd/llamacpp-gemma.service" \
        /etc/systemd/system/llamacpp-gemma.service
}

wait_for_url() {
    local url="$1"
    local attempts="$2"
    local delay_seconds="$3"
    local label="$4"
    local bearer_token="${5:-}"
    local request_headers=()
    if [[ -n "$bearer_token" ]]; then
        request_headers=(-H "Authorization: Bearer $bearer_token")
    fi
    local attempt
    for ((attempt = 1; attempt <= attempts; attempt++)); do
        if curl -fsS --max-time 5 "${request_headers[@]}" "$url" >/dev/null 2>&1; then
            info "$label is ready"
            return 0
        fi
        if (( attempt % 12 == 0 )); then
            info "Waiting for $label ($attempt/$attempts)"
        fi
        sleep "$delay_seconds"
    done
    journalctl -u llamacpp-gemma.service -n 80 --no-pager >&2 || true
    err "$label did not become ready: $url"
}

read_env_value() {
    local env_file="$1"
    local requested_key="$2"
    python3 - "$env_file" "$requested_key" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
requested_key = sys.argv[2]
assignment = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
for line in path.read_text(encoding="utf-8").splitlines():
    match = assignment.match(line)
    if match and match.group(1) == requested_key:
        print(match.group(2).strip())
        break
PY
}

start_and_verify() {
    local llm_api_token
    llm_api_token="$(read_env_value /etc/notable-analyzer/config.env LLM_API_TOKEN)"

    systemctl daemon-reload
    systemctl disable --now vllm.service >/dev/null 2>&1 || true
    systemctl enable --now llamacpp-gemma.service
    wait_for_url http://127.0.0.1:8000/health 240 5 "llama.cpp"

    systemctl enable litellm.service notable-analyzer.service
    systemctl restart litellm.service
    wait_for_url http://127.0.0.1:4000/v1/models 60 2 "LiteLLM" "$llm_api_token"
    systemctl restart notable-analyzer.service

    if [[ "$INSTALL_ANALYST_PORTAL_VALUE" == "true" ]]; then
        systemctl enable notable-portal.service
        systemctl restart notable-portal.service
        wait_for_url http://127.0.0.1:8080/health 30 2 "analyst portal"
    fi

    info "Running a direct OpenAI-compatible inference smoke test"
    local chat_payload
    chat_payload='{"model":"gemma-4-26B-A4B-it","messages":[{"role":"user","content":"Reply with exactly: OK"}],"temperature":0,"max_tokens":8}'
    curl --fail --silent --show-error --max-time 300 \
        -H 'Content-Type: application/json' \
        -d "$chat_payload" \
        http://127.0.0.1:8000/v1/chat/completions >/dev/null

    info "Running the same smoke test through LiteLLM"
    local gateway_headers=(-H 'Content-Type: application/json')
    if [[ -n "$llm_api_token" ]]; then
        gateway_headers+=(-H "Authorization: Bearer $llm_api_token")
    fi
    curl --fail --silent --show-error --max-time 300 \
        "${gateway_headers[@]}" \
        -d "$chat_payload" \
        http://127.0.0.1:4000/v1/chat/completions >/dev/null
}

echo "Installing two-T4 llama.cpp demo profile"
echo "  llama.cpp revision: $LLAMACPP_REVISION"
echo "  Model: $MODEL_REPOSITORY@$MODEL_REVISION"
echo "  GPUs: $CUDA_VISIBLE_DEVICES_VALUE"
echo "  Portal: $INSTALL_ANALYST_PORTAL_VALUE"

validate_gpu_contract
validate_disk_space
find_nvcc >/dev/null \
    || err "CUDA toolkit compiler (nvcc) is missing; driver installation alone is not sufficient"
install_build_dependencies

if [[ "$SKIP_BASE_INSTALL_VALUE" != "true" ]]; then
    info "Installing the base on-prem application without vLLM"
    VLLM_SKIP_INSTALL=true \
    AUTO_START_SERVICES=false \
    MODEL_DOWNLOAD=false \
    INSTALL_ANALYST_PORTAL="$INSTALL_ANALYST_PORTAL_VALUE" \
        bash "$PROJECT_DIR/scripts/install.sh"
else
    [[ -f /etc/notable-analyzer/config.env ]] \
        || err "T4_SKIP_BASE_INSTALL=true but /etc/notable-analyzer/config.env is missing"
    info "Reusing the existing base on-prem installation"
fi

create_service_user
checkout_llamacpp
build_llamacpp
install_runtime_assets
bash "$PROJECT_DIR/scripts/apply_t4x2_llamacpp_demo_profile.sh" --execute

if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload
    systemctl disable --now vllm.service >/dev/null 2>&1 || true
else
    err "systemd is required by this deployment profile"
fi

if [[ "$AUTO_START_VALUE" == "true" ]]; then
    start_and_verify
else
    info "T4_AUTO_START=false; services were installed but not started"
fi

echo
echo "Two-T4 llama.cpp demo installation complete."
echo "  Model endpoint: http://127.0.0.1:8000/v1"
echo "  Application gateway: http://127.0.0.1:4000/v1"
echo "  Model alias: gemma-4-26B-A4B-it"
echo "  Logs: journalctl -u llamacpp-gemma -u litellm -u notable-analyzer -f"
echo "  Runtime tuning: /etc/notable-analyzer/llamacpp-gemma.env"
echo "  Profile backups: /root/notable-profile-backups/t4x2-llamacpp-demo"
