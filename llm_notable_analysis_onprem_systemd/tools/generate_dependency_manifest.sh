#!/usr/bin/env bash
# generate_dependency_manifest.sh
#
# Generate an evidence-based dependency manifest for government/on-prem review.
# - Captures OS + kernel + GPU driver versions
# - Captures system packages (rpm/dpkg) if available
# - Captures Python + venv package inventories (pip freeze) for:
#     - /opt/notable-analyzer/venv
#     - /opt/vllm/venv
# - Captures systemd unit file contents + hashes (if present)
# - Captures model directory inventory + SHA256 hashes (if present)
#
# Usage:
#   sudo bash llm_notable_analysis_onprem_systemd/tools/generate_dependency_manifest.sh
#
# Output:
#   ./dependency_manifest_YYYYmmdd_HHMMSS/ (created in current working directory)
#
set -euo pipefail
IFS=$'\n\t'

ts="$(date -u +%Y%m%d_%H%M%S)"
out_dir="dependency_manifest_${ts}"
mkdir -p "$out_dir"

note() { echo "  $*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }

write_cmd() {
  local name="$1"
  shift
  local file="${out_dir}/${name}.txt"
  {
    echo "### command: $*"
    echo "### utc_time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo
    "$@"
  } >"$file" 2>&1 || {
    echo "### command failed" >>"$file"
    return 0
  }
}

write_file_copy() {
  local src="$1"
  local dest_rel="$2"
  local dest="${out_dir}/${dest_rel}"
  mkdir -p "$(dirname "$dest")"
  if [[ -f "$src" ]]; then
    cp -f "$src" "$dest"
  else
    echo "missing: $src" >"$dest"
  fi
}

note "Writing manifest to: ${out_dir}"

# --- OS / platform ---
write_cmd "os_release" bash -lc 'cat /etc/os-release 2>/dev/null || true'
write_cmd "uname" uname -a
write_cmd "date_utc" date -u
write_cmd "env_basic" bash -lc 'echo "PATH=$PATH"; echo "SHELL=${SHELL:-}"; echo "USER=${USER:-}"; echo "SUDO_USER=${SUDO_USER:-}"'

# --- GPU / drivers ---
if have nvidia-smi; then
  write_cmd "nvidia_smi" nvidia-smi
  write_cmd "nvidia_smi_query" bash -lc 'nvidia-smi --query-gpu=name,driver_version,cuda_version,memory.total --format=csv,noheader 2>/dev/null || true'
else
  echo "nvidia-smi not found" > "${out_dir}/nvidia_smi.txt"
fi

if have rocm-smi; then
  write_cmd "rocm_smi" rocm-smi
fi

# --- System packages (capture whichever system uses) ---
if have rpm; then
  write_cmd "rpm_all" rpm -qa
  if have dnf; then
    write_cmd "dnf_repolist" dnf repolist -v
  fi
  if have yum; then
    write_cmd "yum_repolist" yum repolist -v
  fi
fi

if have dpkg-query; then
  write_cmd "dpkg_list" dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n'
fi
if have apt-cache; then
  write_cmd "apt_sources" bash -lc 'grep -Rhs "^[^#].*" /etc/apt/sources.list /etc/apt/sources.list.d/*.list 2>/dev/null || true'
fi

# --- Python / venv inventories ---
write_cmd "python3_version" python3 --version
write_cmd "python3_pip_version" bash -lc 'python3 -m pip --version 2>/dev/null || true'

freeze_venv() {
  local venv_dir="$1"
  local label="$2"
  local pip_bin="${venv_dir}/bin/pip"
  local py_bin="${venv_dir}/bin/python"

  if [[ -x "$pip_bin" ]]; then
    write_cmd "${label}_python_version" "$py_bin" --version
    write_cmd "${label}_pip_version" "$pip_bin" --version
    write_cmd "${label}_pip_freeze" "$pip_bin" freeze
    write_cmd "${label}_pip_show_vllm" "$pip_bin" show vllm
    write_cmd "${label}_pip_show_requests" "$pip_bin" show requests
  else
    echo "missing venv: ${venv_dir}" > "${out_dir}/${label}_pip_freeze.txt"
  fi
}

freeze_venv "/opt/notable-analyzer/venv" "notable_analyzer_venv"
freeze_venv "/opt/vllm/venv" "vllm_venv"

# --- systemd unit files + hashes (if present) ---
if [[ -d /etc/systemd/system ]]; then
  write_file_copy "/etc/systemd/system/notable-analyzer.service" "systemd/notable-analyzer.service"
  write_file_copy "/etc/systemd/system/vllm.service" "systemd/vllm.service"
  write_file_copy "/etc/systemd/system/notable-retention.service" "systemd/notable-retention.service"
  write_file_copy "/etc/systemd/system/notable-retention.timer" "systemd/notable-retention.timer"
  if have sha256sum; then
    write_cmd "systemd_sha256" bash -lc 'cd /etc/systemd/system && sha256sum notable-analyzer.service vllm.service notable-retention.service notable-retention.timer 2>/dev/null || true'
  fi
fi

# --- Model inventory + hashes (large; can take time) ---
model_dir="${MODEL_DIR:-/opt/models/gemma-4-31B-it}"
{
  echo "### model_dir: ${model_dir}"
  if [[ -d "$model_dir" ]]; then
    echo "### present: yes"
  else
    echo "### present: no"
  fi
} > "${out_dir}/model_dir.txt"

if [[ -d "$model_dir" ]]; then
  write_cmd "model_tree" bash -lc "cd \"${model_dir}\" && find . -maxdepth 3 -type f -printf '%p\t%k KB\n' | sort"
  if have sha256sum; then
    # WARNING: can be expensive on large models; still required for strict evidence.
    write_cmd "model_sha256" bash -lc "cd \"${model_dir}\" && find . -type f -print0 | sort -z | xargs -0 sha256sum"
  else
    echo "sha256sum not found; cannot hash model files" > "${out_dir}/model_sha256.txt"
  fi
fi

# --- Optional SBOM tooling hooks (if present) ---
# We don't install these automatically; orgs often have their own scanners.
if have syft; then
  write_cmd "sbom_syft_json" syft packages dir:/opt/notable-analyzer -o json
else
  echo "syft not installed; skipping SBOM generation" > "${out_dir}/sbom_syft.txt"
fi

note "Done. Review: ${out_dir}/"

