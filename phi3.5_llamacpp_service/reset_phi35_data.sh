#!/usr/bin/env bash
# reset_phi35_data.sh
# Wipe phi35 *data* under PHI_INSTALL_DIR for a clean re-run of the installers.
# Keeps:  models/  and  runtime/llama.cpp/  source (including .git), minus CMake build/.
# Removes: bin/, logs/, pid, CMake build tree, generated env file (optional).
#
# Does NOT touch the install scripts in your git clone — run this on the target host.
#
# Usage:
#   bash reset_phi35_data.sh
#   PHI_INSTALL_DIR=/other/path bash reset_phi35_data.sh
#   bash reset_phi35_data.sh --yes   # skip confirmation
set -euo pipefail

PHI_INSTALL_DIR="${PHI_INSTALL_DIR:-$HOME/.local/share/phi35_llamacpp}"
PHI_ENV_FILE="${PHI_ENV_FILE:-$HOME/.config/phi35_llamacpp/phi35.env}"
SKIP_CONFIRM=false
for a in "$@"; do
    [[ "$a" == "--yes" ]] || [[ "$a" == "-y" ]] && SKIP_CONFIRM=true
done

err() { echo "ERROR: $*" >&2; exit 1; }

[[ -d "$PHI_INSTALL_DIR" ]] || err "PHI_INSTALL_DIR does not exist: $PHI_INSTALL_DIR"

echo "PHI_INSTALL_DIR=$PHI_INSTALL_DIR"
echo "Will REMOVE (if present):"
echo "  - $PHI_INSTALL_DIR/bin/"
echo "  - $PHI_INSTALL_DIR/logs/"
echo "  - $PHI_INSTALL_DIR/llama-server.pid"
echo "  - $PHI_INSTALL_DIR/runtime/llama.cpp/build/"
echo "  - $PHI_ENV_FILE"
echo "Will KEEP:"
echo "  - $PHI_INSTALL_DIR/models/"
echo "  - $PHI_INSTALL_DIR/runtime/llama.cpp/  (except build/)"
echo ""

if [[ "$SKIP_CONFIRM" != "true" ]]; then
    read -r -p "Type YES to delete: " ans
    [[ "$ans" == "YES" ]] || { echo "Aborted."; exit 1; }
fi

rm -rf "$PHI_INSTALL_DIR/bin"
rm -rf "$PHI_INSTALL_DIR/logs"
rm -f "$PHI_INSTALL_DIR/llama-server.pid"
rm -rf "$PHI_INSTALL_DIR/runtime/llama.cpp/build"
rm -f "$PHI_ENV_FILE"

echo "Done. Re-run install_phi35_sudo.sh (e.g. with PHI_SKIP_RUNTIME_BUILD=false to rebuild)."
