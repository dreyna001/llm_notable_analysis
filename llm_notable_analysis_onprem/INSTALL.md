# Installation Guide

## Prerequisites

| Requirement | Details |
|-------------|---------|
| OS | RHEL 8/9 (or compatible: Rocky, Alma, CentOS Stream) |
| Python | 3.10+ |
| Root access | Required for user/directory creation |
| GPU | NVIDIA GPU with CUDA drivers (for vLLM) |
| Model weights | Downloaded to local path before starting vLLM |

## Quick Install

```bash
# Clone or copy llm_notable_analysis_onprem/ to the host
cd /path/to/llm_notable_analysis_onprem

# Run installer as root
sudo bash install.sh
```

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
- `LLM_API_URL` — vLLM endpoint (default: `http://127.0.0.1:8000/v1/completions`)
- `LLM_MODEL_NAME` — Model name matching vLLM `--served-model-name`
- `SPLUNK_BASE_URL` / `SPLUNK_API_TOKEN` — If Splunk writeback enabled

### 2. Install vLLM (if not already installed)

The analyzer talks to an OpenAI-compatible local endpoint (vLLM). The included `vllm.service` expects vLLM to be installed in:

- `/opt/vllm/venv` (Python venv)

If you ran `install.sh` without overrides, it will create this venv and install vLLM automatically.

If you need to skip vLLM install (common in air-gapped environments where you pre-stage wheels), run:

```bash
sudo VLLM_SKIP_INSTALL=true bash install.sh
```

Then install vLLM yourself into `/opt/vllm/venv` (or update `vllm.service` to point to your chosen interpreter).

### 3. Download Model Weights

Transfer model weights to `/opt/models/gpt-oss-20b` (or your chosen path).

Update `vllm.service` if using a different path:
```bash
sudo vi /etc/systemd/system/vllm.service
# Edit --model parameter
sudo systemctl daemon-reload
```

### 4. Add SOAR SSH Key

```bash
# Get public key from SOAR appliance
# Paste into:
sudo vi /var/sftp/soar/.ssh/authorized_keys

# Verify permissions
ls -la /var/sftp/soar/.ssh/
# -rw------- soar-uploader soar-uploader authorized_keys
```

### 5. Restart sshd

```bash
sudo systemctl restart sshd
```

### 6. Start Services

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

