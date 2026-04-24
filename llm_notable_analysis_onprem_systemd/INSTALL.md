# Installation Guide

## Prerequisites

| Requirement | Details |
|-------------|---------|
| OS | RHEL 8/9 (or compatible: Rocky, Alma, CentOS Stream) |
| Python | 3.10+ |
| Root access | Required for user/directory creation |
| GPU | NVIDIA GPU with CUDA drivers (for vLLM) |
| Model weights | Downloaded to local path before starting vLLM |

### Python version

- **Default:** The installer defaults both analyzer and vLLM venvs to `python3.12`. Override with `ANALYZER_PYTHON_BIN` and `VLLM_PYTHON_BIN` if needed.
- **Minimum:** Python 3.10+ is required; the installer fails if the chosen interpreter is older.
- **3.13+:** If the interpreter is 3.13 or newer, the installer warns (does not fail). If vLLM later fails to start, pin to Python 3.12.
- **Pinning (regulated envs):** For reproducible installs, pin both venvs to a specific interpreter, e.g. `sudo ANALYZER_PYTHON_BIN=python3.12 VLLM_PYTHON_BIN=python3.12 bash install.sh`. See README "Reproducibility: pinning Python".
- **Debian/Ubuntu headers:** Ensure Python dev headers match the vLLM interpreter (for Triton/Inductor runtime compile), e.g. `python3.11-dev` for `python3.11`, `python3.12-dev` for `python3.12`.

## Quick Install

```bash
# Clone or copy llm_notable_analysis_onprem_systemd/ to the host
cd /path/to/llm_notable_analysis_onprem_systemd

# Run installer as root
sudo bash install.sh

# install.sh will also attempt post-install service start and a canned
# inference smoke test (best-effort, non-fatal). To skip:
# sudo AUTO_START_SERVICES=false RUN_SMOKE_TEST=false bash install.sh
# Tune readiness windows if model startup is slow:
# sudo VLLM_HEALTH_TIMEOUT_SECONDS=420 SMOKE_TEST_TIMEOUT_SECONDS=240 bash install.sh
```

## Mini/Qwen CPU client-mode install (with mini llama.cpp service)

Use this when your inference service is already running from `onprem_qwen3_sudo_llamacpp_service` on `127.0.0.1:8000` and you only need the notable-analysis client setup.

```bash
# Expected sibling layout:
#   /path/to/llm_notable_analysis_onprem_systemd
#   /path/to/onprem-llm-sdk
cd /path/to/llm_notable_analysis_onprem_systemd
sudo bash install_mini_qwen_cpu_client.sh
```

Behavior highlights:

- No vLLM install/GPU setup.
- Installs analyzer runtime into `/opt/notable-analyzer`.
- Installs local SDK from `../onprem-llm-sdk` (override with `SDK_SOURCE_DIR=...`).
- Writes/updates `/etc/notable-analyzer/config.env` for:
  - `LLM_API_URL=http://127.0.0.1:8000/v1/chat/completions`
  - `LLM_MODEL_NAME=Qwen3-4B-Q4_K_M.gguf`
- Creates launcher: `/usr/local/bin/notable-analyzer-mini-run`

Optional flags:

```bash
# Explicit SDK path
sudo SDK_SOURCE_DIR=/opt/notable-analyzer-src/onprem-llm-sdk bash install_mini_qwen_cpu_client.sh

# Install/start systemd unit when available
sudo INSTALL_SYSTEMD_UNIT=true AUTO_START_ANALYZER=true bash install_mini_qwen_cpu_client.sh
```

## Manual Inputs Still Required

After install completes, these may still require operator input:

- Ensure model weights exist at `/opt/models/gemma-4-31B-it` (unless your service points to a different model path).
- Set `LLM_API_TOKEN` only if vLLM is configured with `--api-key`.
- Set `SPLUNK_BASE_URL` / `SPLUNK_API_TOKEN` only if Splunk writeback is enabled.
- Add SOAR key(s) to `/var/sftp/soar/.ssh/authorized_keys` only for SOAR SFTP ingest.
- Review and clear any post-install non-fatal issues reported by `install.sh`.

## What install.sh Does

| Step | Action | Failure Handling |
|------|--------|------------------|
| 1 | Create system users (`notable-analyzer`, `vllm`, `soar-uploader`) | Skips if user exists |
| 2 | Create directories with correct ownership/permissions | Fails with path on error |
| 3 | Configure SELinux contexts (if enabled) | Warns if semanage missing |
| 4 | Copy application code to `/opt/notable-analyzer` | Fails if source missing |
| 5 | Create Python venv and install dependencies | Fails with pip output |
| 6 | Install config template to `/etc/notable-analyzer/config.env` | Skips if exists |
| 7 | Install systemd units | Fails if unit file missing |
| 8 | Configure SFTP chroot in `/etc/ssh/sshd_config` | Skips if already present |
| 9 | Post-install auto-start + canned inference smoke test | Best-effort (non-fatal) |

---

## Directory Layout (Post-Install)

```
/opt/notable-analyzer/
├── onprem_service/          # Python package
├── venv/                    # Virtual environment
└── requirements.txt

/etc/notable-analyzer/
└── config.env               # Runtime configuration (mode 600)

/var/notables/
├── incoming -> /var/sftp/soar/incoming  # Symlink to SFTP drop
├── processed/               # Successfully analyzed
├── quarantine/              # Failed/invalid files
├── reports/                 # Markdown output
└── archive/                 # Retention stage 2
    ├── processed/
    ├── quarantine/
    └── reports/

/var/sftp/soar/
├── incoming/                # SOAR drops files here via SFTP
└── .ssh/
    └── authorized_keys      # SOAR public key
```

---

## Users and Permissions

| User | Purpose | Shell | Home |
|------|---------|-------|------|
| `notable-analyzer` | Runs Python service | `/sbin/nologin` | `/opt/notable-analyzer` |
| `vllm` | Runs vLLM inference | `/sbin/nologin` | `/opt/vllm` |
| `soar-uploader` | SFTP-only for SOAR | `/sbin/nologin` | `/var/sftp/soar` |

**Group membership:**
- `soar-uploader` is added to `notable-analyzer` group
- `/var/sftp/soar/incoming` is owned `soar-uploader:notable-analyzer` with mode `775`

This allows SOAR to write files and the analyzer service to read/move them.

---

## SFTP Chroot Requirements

For `sshd` chroot to work:

1. **Chroot directory ownership:** `root:root` with mode `755` (no group/other write)
2. **User directory inside chroot:** Can be owned by user
3. **SELinux:** `ssh_chroot_rw_homedirs` boolean must be on (install.sh handles this)

If SFTP fails with "broken pipe" or "permission denied":

```bash
# Check ownership chain
ls -ld /var/sftp /var/sftp/soar /var/sftp/soar/incoming

# Expected:
# drwxr-xr-x root root /var/sftp
# drwxr-xr-x root root /var/sftp/soar
# drwxrwxr-x soar-uploader notable-analyzer /var/sftp/soar/incoming

# Check SELinux
ls -Z /var/sftp/soar
```

---

## Post-Install Steps

### 1. Edit Configuration

```bash
sudo vi /etc/notable-analyzer/config.env
```

Required settings:
- `LLM_API_URL` — vLLM endpoint (default: `http://127.0.0.1:8000/v1/chat/completions`)
- `LLM_MODEL_NAME` — Model name matching vLLM `--served-model-name`
- `SPLUNK_BASE_URL` / `SPLUNK_API_TOKEN` — If Splunk writeback enabled

### 2. Install vLLM (if not already installed)

The analyzer talks to an OpenAI-compatible local endpoint (vLLM). The included `vllm.service` expects vLLM to be installed in:

- `/opt/vllm/venv` (Python venv)

If you ran `install.sh` without overrides, it will create this venv and install vLLM automatically.

If you need a different path (for example, Python 3.12 side-by-side), set:

- `VLLM_INSTALL_DIR` (default: `/opt/vllm`)
- `VLLM_VENV_DIR` (default: `$VLLM_INSTALL_DIR/venv`)

`install.sh` now patches the installed `/etc/systemd/system/vllm.service` `WorkingDirectory` and `ExecStart` to match these values automatically.
Single-node loopback rendezvous settings are already embedded in the base `vllm.service`; an additional `override.conf` is not required for normal deployments.

If you need to skip vLLM install (common in air-gapped environments where you pre-stage wheels), run:

```bash
sudo VLLM_SKIP_INSTALL=true bash install.sh
```

Then install vLLM yourself into your chosen venv path (or update `vllm.service` to point to your chosen interpreter).

### 3. Download Model Weights

Transfer model weights to `/opt/models/gemma-4-31B-it` (or your chosen path).

Update `vllm.service` if using a different path:
```bash
sudo vi /etc/systemd/system/vllm.service
# Edit --model parameter
sudo systemctl daemon-reload
```

If prior host-local drop-ins exist and you want deterministic behavior from the repo unit, rerun installer with:

```bash
sudo VLLM_RESET_OVERRIDES=true bash install.sh
```

### 4. Add SOAR SSH Key

`authorized_keys` is the standard OpenSSH file that lists the **public keys** allowed to log in as that user. The installer creates `/var/sftp/soar/.ssh/authorized_keys`; add the SOAR appliance's public key(s) there so SOAR can authenticate via key (no password) when uploading notables via SFTP.

For a simple Phantom playbook template that builds one notable JSON payload (including supporting events) and uploads it to `/incoming`, see:

- `SOAR_PLAYBOOK_PHANTOM.md`
- `soar_playbook/phantom_notable_to_analyzer.py`

For an alternative scheduled/query-based Phantom template that polls
`index=notable`, see:

- `SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md`
- `soar_playbook/phantom_notable_index_to_analyzer.py`

```bash
# Get public key from SOAR appliance
# Paste into:
sudo vi /var/sftp/soar/.ssh/authorized_keys

# Verify permissions
ls -la /var/sftp/soar/.ssh/
# -rw------- root root authorized_keys
```

### 5. Restart sshd

```bash
sudo systemctl restart sshd
```

### 6. Run Unit Tests (Preflight)

Run tests from repo root before first service start:

```bash
cd ~/llm_notable_analysis
PYTHONPATH=llm_notable_analysis_onprem_systemd /opt/notable-analyzer/venv/bin/python -m unittest discover -s llm_notable_analysis_onprem_systemd/tests -p "test*.py" -v
```

Expected result:
- `Ran ... tests`
- `OK`

Unit tests do not require `vllm` or `notable-analyzer` to be running.

### 7. Start Services

```bash
# Start vLLM first (analyzer depends on it)
sudo systemctl enable --now vllm

# Wait for vLLM to load model (check logs)
sudo journalctl -u vllm -f

# Start analyzer
sudo systemctl enable --now notable-analyzer

# Optional: enable retention timer
sudo systemctl enable --now notable-retention.timer
```

---

## Verification

```bash
# Service status
sudo systemctl status vllm notable-analyzer

# Test SFTP from another host
sftp -i /path/to/private_key soar-uploader@<analyzer-host>
sftp> put test.json incoming/
sftp> exit

# Check file arrived
ls -la /var/notables/incoming/

# Watch analyzer logs
sudo journalctl -u notable-analyzer -f
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Permission denied` on SFTP | Chroot ownership wrong | `chown root:root /var/sftp /var/sftp/soar` |
| `Permission denied` writing file | incoming/ permissions | `chmod 775 /var/sftp/soar/incoming` |
| vLLM won't start | Missing CUDA / model | Check `journalctl -u vllm` |
| Analyzer can't read files | Symlink broken | Recreate: `ln -sf /var/sftp/soar/incoming /var/notables/incoming` |
| SELinux denials | Missing context | `restorecon -Rv /var/sftp/soar` |
| Config not found | Wrong path in service | Check `EnvironmentFile=` in systemd unit |

---

## Uninstall

```bash
# Stop services
sudo systemctl disable --now notable-analyzer vllm notable-retention.timer

# Remove systemd units
sudo rm /etc/systemd/system/{notable-analyzer,vllm,notable-retention}.{service,timer}
sudo systemctl daemon-reload

# Remove users (optional)
sudo userdel notable-analyzer
sudo userdel vllm
sudo userdel soar-uploader

# Remove directories (optional - preserves data by default)
sudo rm -rf /opt/notable-analyzer
sudo rm -rf /etc/notable-analyzer
# sudo rm -rf /var/notables  # Uncomment to delete data

# Remove SFTP config from sshd_config (manual edit)
sudo vi /etc/ssh/sshd_config
# Delete lines from "# Notable Analyzer SFTP Config" to end of Match block
sudo systemctl restart sshd
```

---

## Ansible Alternative

For multi-host or enterprise deployments, consider converting `install.sh` to an Ansible playbook. Key modules:

| Task | Ansible Module |
|------|----------------|
| Create users | `ansible.builtin.user` |
| Create dirs | `ansible.builtin.file` |
| Copy files | `ansible.builtin.copy` / `synchronize` |
| Install venv | `ansible.builtin.pip` with `virtualenv` |
| Systemd | `ansible.builtin.systemd` |
| SELinux | `ansible.posix.seboolean`, `community.general.sefcontext` |
| SSH config | `ansible.builtin.blockinfile` |

Benefits: idempotency, `--check` dry-run, Ansible Vault for secrets, inventory for multiple hosts.

