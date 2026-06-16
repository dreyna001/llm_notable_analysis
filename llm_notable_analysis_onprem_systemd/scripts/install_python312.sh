#!/usr/bin/env bash
# Install Python 3.12 system packages on supported Linux distros.
# Used by scripts/install.sh (on-prem) and scripts/bootstrap_dev_venv.sh (dev).
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: install_python312.sh [options]

Install Python 3.12 and venv support on a supported Linux distribution.
Requires sudo for package installation.

Options:
  -h, --help   Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "Automatic install is only supported on Linux." >&2
    echo "Install Python 3.12 manually, then re-run the installer." >&2
    exit 1
fi

run_privileged() {
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
        "$@"
    else
        sudo "$@"
    fi
}

if [[ ! -f /etc/os-release ]]; then
    echo "Cannot detect OS (/etc/os-release missing)." >&2
    exit 1
fi

# shellcheck source=/dev/null
source /etc/os-release

id_like="${ID_LIKE:-}"
distro_id="${ID:-}"

install_debian_family() {
    local version_id="${VERSION_ID:-}"
    run_privileged apt-get update
    if [[ "$version_id" == "24.04" || "$version_id" == "12" ]]; then
        run_privileged apt-get install -y python3.12 python3.12-venv python3.12-dev
        return 0
    fi
    run_privileged apt-get install -y software-properties-common
    run_privileged add-apt-repository -y ppa:deadsnakes/ppa
    run_privileged apt-get update
    run_privileged apt-get install -y python3.12 python3.12-venv python3.12-dev
}

install_rhel_family() {
    if ! command -v dnf >/dev/null 2>&1; then
        echo "dnf is required but not found." >&2
        return 1
    fi
    run_privileged dnf install -y python3.12 python3.12-devel
}

case "$distro_id" in
    ubuntu|debian|linuxmint|pop)
        install_debian_family
        ;;
    rhel|centos|rocky|almalinux|fedora|ol)
        install_rhel_family
        ;;
    *)
        if [[ "$id_like" == *debian* ]]; then
            install_debian_family
        elif [[ "$id_like" == *rhel* || "$id_like" == *fedora* ]]; then
            install_rhel_family
        else
            echo "Unsupported distribution: ${PRETTY_NAME:-$distro_id}" >&2
            echo "Install Python 3.12 manually, then re-run the installer." >&2
            exit 1
        fi
        ;;
esac

if ! command -v python3.12 >/dev/null 2>&1; then
    echo "python3.12 is still not on PATH after package install." >&2
    exit 1
fi

if ! python3.12 -m venv --help >/dev/null 2>&1; then
    echo "python3.12 is installed but the venv module is unavailable." >&2
    echo "On Debian/Ubuntu, install python3.12-venv." >&2
    echo "On RHEL/Fedora, install python3.12-devel." >&2
    exit 1
fi

python3.12 --version
echo "Python 3.12 is ready."
