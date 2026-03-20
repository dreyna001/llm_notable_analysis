# Scripts Reference

This document explains all scripts under `scripts/`.

## `build_offline_bundle.sh`

Builds an offline release bundle containing SDK wheel(s), dependency wheels, lockfile, checksum manifest, and compressed archive.

- **Default Python:** `python3.12`
- **Override:** `PYTHON_BIN=python3.12`
- **Output:** `bundle/onprem_llm_sdk_bundle_<version>.tar.gz`

## `verify_bundle.sh`

Verifies an extracted bundle directory before installation.

- **Usage:** `bash scripts/verify_bundle.sh [BUNDLE_DIR]`
- **Default `BUNDLE_DIR`:** `/opt/artifacts/onprem_llm_sdk`
- **Checks:** required files + `sha256sum -c SHA256SUMS`

## `install_from_bundle.sh`

Installs SDK from local wheelhouse only (no internet index).

- **Usage:** `bash scripts/install_from_bundle.sh [BUNDLE_DIR] [VENV_DIR] [VERSION]`
- **Defaults:**
  - `BUNDLE_DIR=/opt/artifacts/onprem_llm_sdk`
  - `VENV_DIR=/opt/venvs/myapp`
  - `VERSION` from bundle `VERSION` file if omitted
- **Default Python:** `python3.12` (override via `PYTHON_BIN`)

## `smoke_test_install.sh`

Runs post-install import verification and optional endpoint health check.

- **Usage:** `bash scripts/smoke_test_install.sh [VENV_DIR]`
- **Default `VENV_DIR`:** `/opt/venvs/myapp`
- **Optional env:**
  - `RUN_ENDPOINT_CHECK=true` to also call `http://127.0.0.1:8000/health`

## Recommended order in air-gapped installs

1. `verify_bundle.sh`
2. `install_from_bundle.sh`
3. `smoke_test_install.sh`

