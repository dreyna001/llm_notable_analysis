# Installation Guide

## What This Controls

This guide controls host bring-up: users, directories, virtual environments,
systemd units, model service startup, LiteLLM/vLLM wiring, and post-install
smoke checks. Per-feature tuning belongs in the area-specific operations guides
in this folder.

## Recommended Starting Posture

- Use the main `scripts/install.sh` path for the standard production-shaped
  systemd chain.
- Pin Python to 3.12 in regulated environments.
- Leave post-install smoke checks enabled unless debugging installer behavior.
- Keep service endpoints on loopback.
- Review `config.env` with the area guides before enabling optional
  integrations.

## Customer Decisions

- Which RHEL-compatible host and GPU profile is approved?
- Which Python interpreter is the supported runtime?
- Are model weights and wheelhouse artifacts pre-staged for offline install?
- Should services auto-start during install or be started manually after config
  review?
- Who owns post-install smoke testing and rollback?

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
- **Pinning (regulated envs):** For reproducible installs, pin both venvs to a specific interpreter, e.g. `sudo ANALYZER_PYTHON_BIN=python3.12 VLLM_PYTHON_BIN=python3.12 bash scripts/install.sh`. See README "Reproducibility: pinning Python".
- **Debian/Ubuntu headers:** Ensure Python dev headers match the vLLM interpreter (for Triton/Inductor runtime compile), e.g. `python3.11-dev` for `python3.11`, `python3.12-dev` for `python3.12`.

## Quick Install

```bash
# Clone or copy llm_notable_analysis_onprem_systemd/ to the host
cd /path/to/llm_notable_analysis_onprem_systemd

# Run installer as root
sudo bash scripts/install.sh

# scripts/install.sh will also attempt post-install service start and a canned
# inference smoke test (best-effort, non-fatal). To skip:
# sudo AUTO_START_SERVICES=false RUN_SMOKE_TEST=false bash scripts/install.sh
# Tune readiness windows if model startup is slow:
# sudo VLLM_HEALTH_TIMEOUT_SECONDS=420 SMOKE_TEST_TIMEOUT_SECONDS=240 bash scripts/install.sh
```

## Non-Default Mini/Qwen CPU Client-Mode Install

This is a lab/CPU alternate path, not the default production deployment. Use
the main `install.sh` path for the standard `vLLM -> LiteLLM -> analyzer`
systemd chain. Use this mini path only when your inference service is already
running from `onprem_qwen3_sudo_llamacpp_service` on `127.0.0.1:8000` and you
only need the notable-analysis client setup.

```bash
# Expected sibling layout:
#   /path/to/llm_notable_analysis_onprem_systemd
#   /path/to/onprem-llm-sdk
cd /path/to/llm_notable_analysis_onprem_systemd
sudo bash scripts/install_mini_qwen_cpu_client.sh
```

Behavior highlights:

- No vLLM install/GPU setup.
- Installs analyzer runtime into `/opt/notable-analyzer`.
- Installs local SDK from `../onprem-llm-sdk` (override with `SDK_SOURCE_DIR=...`).
- Writes/updates `/etc/notable-analyzer/config.env` for:
  - `LLM_API_URL=http://127.0.0.1:8000/v1/chat/completions` (mini direct mode, bypasses LiteLLM)
  - `LLM_MODEL_NAME=Qwen3-4B-Q4_K_M.gguf`
- Creates launcher: `/usr/local/bin/notable-analyzer-mini-run`

Optional flags:

```bash
# Explicit SDK path
sudo SDK_SOURCE_DIR=/opt/notable-analyzer-src/onprem-llm-sdk bash scripts/install_mini_qwen_cpu_client.sh

# Install/start systemd unit when available
sudo INSTALL_SYSTEMD_UNIT=true AUTO_START_ANALYZER=true bash scripts/install_mini_qwen_cpu_client.sh
```

## Manual Inputs Still Required

After install completes, these may still require operator input:

- Ensure model weights exist at `/opt/models/gemma-4-31B-it` (unless your service points to a different model path).
- Set `LLM_API_TOKEN` only if vLLM is configured with `--api-key`.
- Set `SPLUNK_BASE_URL` / `SPLUNK_API_TOKEN` only if Splunk writeback is enabled.
- Add SOAR key(s) to `/var/sftp/soar/.ssh/authorized_keys` only for SOAR SFTP ingest.
- Review and clear any post-install non-fatal issues reported by `scripts/install.sh`.

## What `scripts/install.sh` Does

| Step | Action | Failure Handling |
|------|--------|------------------|
| 1 | Create system users (`notable-analyzer`, `litellm`, `vllm`, `soar-uploader`) | Skips if user exists |
| 2 | Create directories with correct ownership/permissions | Fails with path on error |
| 3 | Configure SELinux contexts (if enabled) | Warns if semanage missing |
| 4 | Copy application code to `/opt/notable-analyzer` | Fails if source missing |
| 5 | Create Python venv and install dependencies | Fails with pip output |
| 6 | Install config template to `/etc/notable-analyzer/config.env` | Skips if exists |
| 7 | Install systemd units, including `litellm.service` | Fails if unit file missing |
| 8 | Configure SFTP chroot in `/etc/ssh/sshd_config` | Skips if already present |
| 9 | Post-install auto-start + canned inference smoke test | Best-effort (non-fatal) |

---

## Directory Layout (Post-Install)

```
/opt/notable-analyzer/
├── src/                     # Installed package source tree
├── pyproject.toml           # Package metadata
├── venv/                    # Virtual environment
└── requirements.txt

/etc/notable-analyzer/
└── config.env               # Runtime configuration (mode 600)

/etc/litellm/
└── config.yaml              # LiteLLM proxy configuration (mode 600)

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
| `litellm` | Runs LiteLLM proxy | `/sbin/nologin` | `/opt/litellm` |
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
3. **SELinux:** `ssh_chroot_rw_homedirs` boolean must be on (`scripts/install.sh` handles this)

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
- `LLM_API_URL` — LiteLLM endpoint (default: `http://127.0.0.1:4000/v1/chat/completions`)
- `LLM_MODEL_NAME` — Model name exposed by LiteLLM and routed to the local backend
- `SPLUNK_BASE_URL` / `SPLUNK_API_TOKEN` — If Splunk writeback enabled

The packaged analyzer units set `HF_HOME=/var/notables/cache/huggingface` and
`SENTENCE_TRANSFORMERS_HOME=/var/notables/cache/sentence-transformers` so BGE
model caches remain writable under `ProtectSystem=strict`. Keep those paths
under `/var/notables/cache` unless you also update the unit `ReadWritePaths`.

### 2. Install vLLM (if not already installed)

The analyzer talks to an OpenAI-compatible local LiteLLM endpoint, which routes
to vLLM by default. The included `litellm.service` expects config at
`/etc/litellm/config.yaml`; the installer copies
`deploy/litellm/config.yaml.example` there on first install.
The unit `Wants=vllm.service` for the default local backend but does not
`Require=` it, so operators can replace `/etc/litellm/config.yaml` with a
remote backend route without editing the service dependency graph.

`scripts/install.sh` installs LiteLLM into its own service venv using
`LITELLM_PIP_SPEC` (default `litellm[proxy]==1.83.14`). For pip-only lab
installs that do not run the installer, the analyzer package exposes the same
proxy dependency as an optional extra: `pip install ".[proxy]"`.

The proxy includes an optional Admin UI at `/ui`, but the default install does
**not** set `LITELLM_MASTER_KEY`. Operators who want UI login must set a master
key and a LiteLLM `DATABASE_URL` on the host, use an SSH tunnel from a desktop
browser, and sign in as `admin` with that key. See
[`LLM_INFERENCE_OPERATIONS.md` — LiteLLM Admin UI](LLM_INFERENCE_OPERATIONS.md#how-do-i-use-the-litellm-admin-ui).

The included `vllm.service` expects vLLM to be installed in:

- `/opt/vllm/venv` (Python venv)

If you ran `scripts/install.sh` without overrides, it will create this venv and
install the pinned Gemma 4-compatible runtime automatically:

- `VLLM_PIP_SPEC=vllm==0.21.0`
- Python 3.12 via `VLLM_PYTHON_BIN=python3.12` unless overridden

This vLLM generation uses Transformers v5 and supports the default
`google/gemma-4-31B-it` checkpoint (`model_type=gemma4`). If you override
`VLLM_PIP_SPEC`, keep it aligned with a Transformers version that recognizes
the configured model architecture.

Gemma 4 startup can require runtime CUDA kernel compilation through
FlashInfer/vLLM sampling paths. The host must have the CUDA toolkit available,
not only the NVIDIA driver. `scripts/install.sh` patches the installed
`vllm.service` with `CUDA_HOME` and `PATH` by checking, in order:

- explicit `CUDA_HOME` when it contains `bin/nvcc`
- `/usr/local/cuda/bin/nvcc`
- versioned toolkit paths such as `/usr/local/cuda-13.3/bin/nvcc`
- `nvcc` already on `PATH`

If no `nvcc` is found, install the CUDA toolkit for the host driver/runtime
before starting vLLM.

If you need a different path (for example, Python 3.12 side-by-side), set:

- `VLLM_INSTALL_DIR` (default: `/opt/vllm`)
- `VLLM_VENV_DIR` (default: `$VLLM_INSTALL_DIR/venv`)

`scripts/install.sh` now patches the installed `/etc/systemd/system/vllm.service` `WorkingDirectory` and `ExecStart` to match these values automatically.
Single-node loopback rendezvous settings are already embedded in the base `vllm.service`; an additional `override.conf` is not required for normal deployments.

If you need to skip vLLM install (common in air-gapped environments where you pre-stage wheels), run:

```bash
sudo VLLM_SKIP_INSTALL=true bash scripts/install.sh
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
sudo VLLM_RESET_OVERRIDES=true bash scripts/install.sh
```

### 4. Add SOAR SSH Key

`authorized_keys` is the standard OpenSSH file that lists the **public keys** allowed to log in as that user. The installer creates `/var/sftp/soar/.ssh/authorized_keys`; add the SOAR appliance's public key(s) there so SOAR can authenticate via key (no password) when uploading notables via SFTP.

For a simple Phantom playbook template that builds one notable JSON payload (including supporting events) and uploads it to `/incoming`, see:

- `../integrations/SOAR_PLAYBOOK_PHANTOM.md`
- `../../src/llm_notable_analysis_onprem_systemd/soar_playbook/phantom_notable_to_analyzer.py`

For an alternative scheduled/query-based Phantom template that polls
`index=notable`, see:

- `../integrations/SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md`
- `../../src/llm_notable_analysis_onprem_systemd/soar_playbook/phantom_notable_index_to_analyzer.py`

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
PYTHONPATH=llm_notable_analysis_onprem_systemd/src /opt/notable-analyzer/venv/bin/python -m unittest discover -s llm_notable_analysis_onprem_systemd/tests -p "test*.py" -v
```

Expected result:
- `Ran ... tests`
- `OK`

Unit tests do not require `vllm` or `notable-analyzer` to be running.

### 7. Optional: Build PostgreSQL RAG Corpus

If `RAG_BACKEND=postgres`, populate the configured Postgres table with the same
values operators set in `/etc/notable-analyzer/config.env`, including
`RAG_POSTGRES_DSN`, `RAG_POSTGRES_SCHEMA`, `RAG_POSTGRES_CHUNKS_TABLE`,
`RAG_POSTGRES_FTS_CONFIG`, `RAG_POSTGRES_STATEMENT_TIMEOUT_MS`, and
`RAG_VECTOR_DIMENSIONS`:

Recommended operator helper:

```bash
sudo bash scripts/setup_postgres_rag.sh \
  --config-env /etc/notable-analyzer/config.env \
  --source-dir /opt/llm-notable-analysis/knowledge_base/source_docs \
  --index-dir /opt/llm-notable-analysis/knowledge_base/index
```

This helper creates the configured local PostgreSQL role/database when needed,
creates the `vector` extension and configured schema, then runs corpus ingest
through the analyzer venv.

Before adding content, review the KB operations runbook:

- `docs/operations/KNOWLEDGE_BASE_OPERATIONS.md`

Manual ingest-only command:

```bash
/opt/notable-analyzer/venv/bin/python -m onprem_rag_notable_analysis.future.corpus_ingest \
  --config-env /etc/notable-analyzer/config.env \
  --backend postgres \
  --source-dir /opt/llm-notable-analysis/knowledge_base/source_docs \
  --index-dir /opt/llm-notable-analysis/knowledge_base/index
```

This creates/updates the pgvector schema, replaces rows in the configured chunks
table, and writes `chunks.jsonl` plus `ingest_report.json` under `--index-dir`.
The command reads `config.env` as simple `KEY=VALUE` text instead of sourcing it
as shell code, so database DSNs do not need to be placed on the process command
line.

For release validation, run the Docker-backed pgvector smoke when Docker is
available:

```bash
bash scripts/smoke_postgres_rag.sh
```

This uses a disposable pgvector container and validates the real schema, ingest,
and retrieval code path without requiring host `psql`. Docker is not part of the
production runtime; production uses the configured host PostgreSQL/pgvector
service.

### 8. Start Services

```bash
# Start vLLM first (LiteLLM depends on it)
sudo systemctl enable --now vllm

# Wait for vLLM to load model (check logs)
sudo journalctl -u vllm -f

# Start LiteLLM
sudo systemctl enable --now litellm

# Start analyzer
sudo systemctl enable --now notable-analyzer

# Optional: enable retention timer
sudo systemctl enable --now notable-retention.timer
```

---

## Verification

```bash
# Service status
sudo systemctl status vllm litellm notable-analyzer

# Full local service-chain smoke:
# vLLM health -> LiteLLM models/chat -> analyzer file-drop report
sudo bash scripts/smoke_service_chain.sh \
  --config-env /etc/notable-analyzer/config.env

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

For multi-host or enterprise deployments, consider converting `scripts/install.sh` to an Ansible playbook. Key modules:

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
