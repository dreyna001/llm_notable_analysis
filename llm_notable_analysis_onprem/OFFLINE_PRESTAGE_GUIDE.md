# Offline Pre-Stage Guide (`llm_notable_analysis_onprem`)

Goal: list exactly what to download before installing on an offline host.

## 1) Download source bundles

- `llm_notable_analysis_onprem/` (this package)
- `onprem-llm-sdk/` source bundle (recommended for offline)

## 2) Download Python artifacts (wheelhouse)

Create a wheelhouse on an internet-connected machine, then transfer it.

Required pins from this package:

- `requests==2.32.5`
- `onprem-llm-sdk==0.1.0` (or install from local `onprem-llm-sdk/` source)
- `vllm==0.14.1` (default installer pin; includes transitive dependencies)

Example:

```bash
mkdir -p wheelhouse
python3 -m pip download -d wheelhouse requests==2.32.5 vllm==0.14.1
```

For `onprem-llm-sdk`, either:

- build/download a wheel and place it in `wheelhouse`, or
- keep `onprem-llm-sdk/` as a local sibling source directory and install it from source offline.

## 3) Download model artifacts

Default service path expects:

- model directory: `/opt/models/gpt-oss-20b`
- model repo used by installer helper defaults: `openai/gpt-oss-20b`

Pre-download model files and transfer them so `config.json` exists under `/opt/models/gpt-oss-20b`.

## 4) Download OS-level dependencies (RPMs)

### Python interpreter (required)

- **Minimum:** Python **3.10+** (installer fails below that).
- **Default / recommended:** Python **3.12** for both analyzer and vLLM venvs (`install.sh` defaults `ANALYZER_PYTHON_BIN` / `VLLM_PYTHON_BIN` to `python3.12`).
- **Pin explicitly:** `sudo ANALYZER_PYTHON_BIN=python3.12 VLLM_PYTHON_BIN=python3.12 bash install.sh`
- **3.13+:** allowed; installer warns (vLLM wheel compatibility may break—prefer 3.12 for regulated builds).

Stage matching OS packages for your chosen interpreter (names vary by RHEL/variant), e.g. `python3.12`, pip/venv, and **devel** headers for the vLLM interpreter.

Minimum commands used by installer:

- `python3` (or the exact `python3.12` you pin)
- `pip3` (or `python3.12 -m ensurepip` / distro pip package)
- `systemctl` (systemd)

Commonly needed in practice:

- `python3-venv` / `python3-devel` (depends on distro packaging)
- `git`, `curl`, `openssh-server`
- `policycoreutils-python-utils` (for `semanage`, optional but recommended on SELinux hosts)

For full vLLM mode, also stage:

- NVIDIA driver + CUDA runtime/toolkit compatible with your GPU

## 5) Offline install modes

### A) Full vLLM mode

Install from local wheelhouse/model artifacts:

```bash
cd /path/to/llm_notable_analysis_onprem
sudo PIP_NO_INDEX=1 \
     PIP_FIND_LINKS=/mnt/media/wheelhouse \
     VLLM_PIP_SPEC="/mnt/media/wheelhouse/vllm-0.14.1-*.whl" \
     VLLM_SKIP_INSTALL=false \
     MODEL_DOWNLOAD=false \
     bash install.sh
```

`PIP_NO_INDEX/PIP_FIND_LINKS` make installer `pip install` steps use the local wheelhouse only.

### B) Client-only mode (using `onprem_qwen3_sudo_llamacpp_service`)

No vLLM/GPU install path:

```bash
cd /path/to/llm_notable_analysis_onprem
sudo SDK_SOURCE_DIR=/path/to/onprem-llm-sdk bash install_mini_qwen_cpu_client.sh
```
