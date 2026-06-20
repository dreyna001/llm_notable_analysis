# Installation Guide

## What This Controls

Host bring-up: users, directories, virtual environments, systemd units, model
service startup, LiteLLM/vLLM wiring, and post-install smoke checks. Per-feature
tuning belongs in the area-specific operations guides under
[`../README.md`](../README.md).

## Recommended Starting Posture

- Use `scripts/install.sh` for the standard production-shaped systemd chain.
- Pin Python to 3.12 in regulated environments.
- Leave post-install smoke checks enabled unless debugging installer behavior.
- Keep service endpoints on loopback.
- Review [`../../../config.env.example`](../../../config.env.example) with the
  area guides before enabling optional integrations.

## Related Docs

| Guide | Purpose |
|-------|---------|
| [`../README.md`](../README.md) | Operations index by area |
| [`OFFLINE_PRESTAGE_GUIDE.md`](OFFLINE_PRESTAGE_GUIDE.md) | Artifacts to stage before an air-gapped install |
| [`AIRGAPPED_DEPLOYMENT.md`](AIRGAPPED_DEPLOYMENT.md) | Air-gapped bring-up and acceptance checks |
| [`deployment_profiles/README.md`](deployment_profiles/README.md) | GPU/CPU starting values for vLLM and `config.env` |
| [`../../../README.md`](../../../README.md) | Package overview and filesystem map |

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
| Python | 3.10+ (installer defaults to **3.12** and installs OS packages when `python3.12` is missing) |
| Root access | Required for user/directory creation |
| GPU | NVIDIA GPU with CUDA drivers (for vLLM) |
| Model weights | Downloaded to local path before starting vLLM |
| Monorepo bundles | Full install expects sibling directories `onprem-llm-sdk/` and `onprem_rag_notable_analysis/` (override with `SDK_SOURCE_DIR` / `RAG_PACKAGE_SRC_DIR`) |

### Python version

- **Default:** The installer defaults both analyzer and vLLM venvs to `python3.12`. When `python3.12` is not on PATH, `scripts/install.sh` runs `scripts/install_python312.sh` beside it (or the monorepo-root copy when present). Set `INSTALL_PYTHON=false` on air-gapped hosts where Python 3.12 is installed manually.
- **Minimum:** Python 3.10+ is required; the installer fails if the chosen interpreter is older.
- **3.13+:** If the interpreter is 3.13 or newer, the installer warns (does not fail). If vLLM later fails to start, pin to Python 3.12.
- **Pinning (regulated envs):** Pin both venvs explicitly, e.g. `sudo ANALYZER_PYTHON_BIN=python3.12 VLLM_PYTHON_BIN=python3.12 bash scripts/install.sh`.
- **Debian/Ubuntu headers:** Ensure Python dev headers match the vLLM interpreter (for Triton/Inductor runtime compile), e.g. `python3.12-dev` for `python3.12`.

## Quick Install

```bash
# Clone or copy the monorepo (or at least llm_notable_analysis_onprem_systemd/
# plus onprem-llm-sdk/ and onprem_rag_notable_analysis/) to the host
cd /path/to/llm_notable_analysis_onprem_systemd

# Run installer as root
sudo bash scripts/install.sh

# scripts/install.sh also attempts post-install service start and a canned
# inference smoke test (best-effort, non-fatal). To skip:
# sudo AUTO_START_SERVICES=false RUN_SMOKE_TEST=false bash scripts/install.sh
# Tune readiness windows if model startup is slow:
# sudo VLLM_HEALTH_TIMEOUT_SECONDS=420 SMOKE_TEST_TIMEOUT_SECONDS=240 bash scripts/install.sh
```

### Common installer flags

| Variable | Default | Purpose |
|----------|---------|---------|
| `AUTO_START_SERVICES` | `true` | Best-effort enable/start of vLLM, LiteLLM, analyzer (and portal when enabled) |
| `RUN_SMOKE_TEST` | `true` | Canned file-drop inference smoke after services are healthy |
| `VLLM_SKIP_INSTALL` | `false` | Skip vLLM venv creation (air-gapped / preinstalled vLLM) |
| `INSTALL_PYTHON` | `true` | Run `install_python312.sh` when `python3.12` is missing |
| `INSTALL_ANALYST_PORTAL` | `false` | OS packages, npm build, Postgres schema, nginx site, `analyst_portal` profile |
| `INSTALL_SYSTEMD_UNITS` | `true` | Copy units from `deploy/systemd/` |
| `MODEL_DOWNLOAD` | `false` | Best-effort Hugging Face snapshot when `HF_TOKEN` is set |
| `VLLM_RESET_OVERRIDES` | `false` | Clear existing `vllm.service.d/*.conf` drop-ins |

See the installer summary at the end of `scripts/install.sh` for the full flag list.

## Non-Default Mini/Qwen CPU Client-Mode Install

Lab/CPU alternate path, not the default production deployment. Use the main
`install.sh` path for the standard `vLLM -> LiteLLM -> analyzer` systemd chain.
Use this mini path only when inference is already running from
`onprem_qwen3_sudo_llamacpp_service` on `127.0.0.1:8000` and you only need the
notable-analysis client setup.

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
- Review `/etc/notable-analyzer/portal.env` and nginx TLS/basic-auth paths before exposing the analyst portal.
- `INSTALL_ANALYST_PORTAL=true` installs nginx/PostgreSQL packages and runs the portal frontend `npm run build` on supported hosts; operator still supplies TLS, htpasswd, and nginx `server_name`.
- Run full analyst portal bring-up when Postgres schema and `analyst_portal` profile are not yet enabled: `sudo INSTALL_ANALYST_PORTAL=true bash scripts/install.sh`
- Review and clear any post-install non-fatal issues reported by `scripts/install.sh`.

## What `scripts/install.sh` Does

| Step | Action | Failure Handling |
|------|--------|------------------|
| 1 | Create system users (`notable-analyzer`, `litellm`, `vllm`, `soar-uploader`) | Skips if user exists |
| 2 | Create data/SFTP directories, cache paths, incoming symlink | Fails with path on error |
| 2b | Prepare `/opt/models/` (best-effort) | Warns; does not fail install |
| 3 | Configure SELinux contexts (if enabled) | Warns if semanage missing |
| 3b | Build analyst portal frontend (`npm run build`) when `INSTALL_ANALYST_PORTAL=true` | Fails install |
| 4 | Copy application code to `/opt/notable-analyzer` (including RAG package and optional portal `dist/`) | Fails if source missing |
| 5 | Create analyzer Python venv and install dependencies | Fails with pip output |
| 5b | Create vLLM venv and install pinned vLLM (unless `VLLM_SKIP_INSTALL=true`) | Fails with pip output |
| 5c | Create LiteLLM venv and install pinned `litellm[proxy]` | Fails with pip output |
| 6 | Install `config.env` and LiteLLM `config.yaml` templates | Skips if files exist |
| 6b | Install portal env, nginx proxy secret, optional analyst portal bring-up | Portal env always; Postgres/nginx site when `INSTALL_ANALYST_PORTAL=true` |
| 7 | Install systemd units from `deploy/systemd/`; patch `vllm.service` paths/CUDA | Fails if unit file missing |
| 8 | Configure SFTP chroot in `/etc/ssh/sshd_config`; optional auto-start + smoke test | SFTP skips if present; auto-start/smoke best-effort |

Installed systemd units: `notable-analyzer.service`, `litellm.service`, `vllm.service`, `notable-portal.service`, `notable-retention.service`, `notable-retention.timer`.

---

## Directory Layout (Post-Install)

```
/opt/notable-analyzer/
├── src/                              # Installed package source tree
├── onprem_rag_notable_analysis/      # Installed RAG package
├── frontend/analyst-portal/dist/     # Built React SPA (when present)
├── pyproject.toml
├── venv/
└── requirements.txt

/opt/vllm/venv/                       # vLLM inference venv
/opt/litellm/venv/                    # LiteLLM proxy venv
/opt/models/gemma-4-31B-it/           # Default model weights path

/etc/notable-analyzer/
├── config.env                        # Runtime configuration (mode 600)
└── portal.env                        # Portal-only configuration (mode 600)

/etc/litellm/
└── config.yaml                       # LiteLLM proxy configuration (mode 600)

/var/notables/
├── incoming -> /var/sftp/soar/incoming
├── processed/
├── quarantine/
├── reports/
├── archive/
│   ├── processed/
│   ├── quarantine/
│   └── reports/
└── cache/                            # HF and sentence-transformers caches

/var/sftp/soar/
├── incoming/
└── .ssh/
    └── authorized_keys
```

Optional RAG content paths (from [`../../../config.env.example`](../../../config.env.example)): `/opt/llm-notable-analysis/knowledge_base/` for source docs and ingest indexes.

---

## Users and Permissions

| User | Purpose | Shell | Home |
|------|---------|-------|------|
| `notable-analyzer` | Runs Python analyzer and portal services | `/sbin/nologin` | `/opt/notable-analyzer` |
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
`SENTENCE_TRANSFORMERS_HOME=/var/notables/cache/sentence-transformers` so local
Mixedbread embedder/reranker caches remain writable under `ProtectSystem=strict`.
Keep those paths under `/var/notables/cache` unless you also update the unit
`ReadWritePaths`.

#### Analyst portal bring-up

Every install writes `/etc/notable-analyzer/portal.env` when it does not already
exist. The file includes a generated `PORTAL_PROXY_SECRET` and aligns
`CASE_POSTGRES_DSN` to the same database host/path as `config.env`. The same
proxy secret is also written to `config.env` when it is empty so the analyzer
does not fail profile validation after `analyst_portal` is enabled.

When nginx is installed, the installer also writes
`/etc/nginx/notable-portal-proxy-secret.conf` so nginx can forward
`PORTAL_PROXY_SECRET_HEADER` to loopback FastAPI.

Full portal wiring is opt-in:

```bash
sudo INSTALL_ANALYST_PORTAL=true bash scripts/install.sh
```

That flag:

- adds `analyst_portal` to `CAPABILITY_PROFILES` in `config.env` when missing,
- generates Postgres passwords in the analyzer and portal `CASE_POSTGRES_DSN`
  values when TCP localhost DSNs omit passwords,
- runs `scripts/setup_postgres_case_archive.sh` to create roles, database, and
  `notable_cases` schema,
- installs `/etc/nginx/conf.d/notable-portal.conf` when nginx is present,
- best-effort starts `notable-portal.service` during post-install auto-start.

Postgres schema setup is required for `INSTALL_ANALYST_PORTAL=true`. Set
`INSTALL_PORTAL_ALLOW_PARTIAL=true` only when staging files before database
access is available; otherwise failed schema setup fails the install.

Production analyst login is nginx basic auth and is created by the operator, not
by the application. See
[`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md)
for htpasswd creation and lab-default credentials guidance.

Production portal ports are nginx on TCP `443` externally and FastAPI on
`127.0.0.1:8080` internally. Local tunnel ports such as `8443` are workstation
forwarding choices, not deployed service ports.

Manual Postgres setup after editing env files:

```bash
sudo bash scripts/setup_postgres_case_archive.sh \
  --config-env /etc/notable-analyzer/config.env \
  --portal-env /etc/notable-analyzer/portal.env
```

See [`../analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md)
for the step-by-step internal HTTPS URL rollout (DNS, TLS, firewall, analyst
browser validation). See [`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md)
for day-two ops: backfill, chunk rebuild, and troubleshooting.

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
[`../llm/LLM_INFERENCE_OPERATIONS.md`](../llm/LLM_INFERENCE_OPERATIONS.md#how-do-i-use-the-litellm-admin-ui).

The included `vllm.service` expects vLLM to be installed in `/opt/vllm/venv`.

If you ran `scripts/install.sh` without overrides, it creates this venv and
installs the pinned Gemma 4-compatible runtime automatically:

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

`scripts/install.sh` patches the installed `/etc/systemd/system/vllm.service`
`WorkingDirectory` and `ExecStart` to match these values automatically.
Single-node loopback rendezvous settings are already embedded in the base
`vllm.service`; an additional `override.conf` is not required for normal
deployments.

If you need to skip vLLM install (common in air-gapped environments where you
pre-stage wheels), run:

```bash
sudo VLLM_SKIP_INSTALL=true bash scripts/install.sh
```

Then install vLLM yourself into your chosen venv path (or update `vllm.service`
to point to your chosen interpreter).

### 3. Download Model Weights

Transfer model weights to `/opt/models/gemma-4-31B-it` (or your chosen path).

Optional non-interactive download during install (requires network and token):

```bash
sudo MODEL_DOWNLOAD=true HF_TOKEN=... bash scripts/install.sh
```

Update `vllm.service` if using a different path:

```bash
sudo vi /etc/systemd/system/vllm.service
# Edit --model parameter
sudo systemctl daemon-reload
```

Or rerun the installer with `VLLM_MODEL_PATH` / `VLLM_SERVED_MODEL_NAME`.

If prior host-local drop-ins exist and you want deterministic behavior from the
repo unit, rerun installer with:

```bash
sudo VLLM_RESET_OVERRIDES=true bash scripts/install.sh
```

### 4. Add SOAR SSH Key

`authorized_keys` is the standard OpenSSH file that lists the **public keys**
allowed to log in as that user. The installer creates
`/var/sftp/soar/.ssh/authorized_keys`; add the SOAR appliance's public key(s)
there so SOAR can authenticate via key (no password) when uploading notables
via SFTP.

For a simple Phantom playbook template that builds one notable JSON payload
(including supporting events) and uploads it to `/incoming`, see:

- [`../../integrations/SOAR_PLAYBOOK_PHANTOM.md`](../../integrations/SOAR_PLAYBOOK_PHANTOM.md)
- [`../../../src/llm_notable_analysis_onprem_systemd/soar_playbook/phantom_notable_to_analyzer.py`](../../../src/llm_notable_analysis_onprem_systemd/soar_playbook/phantom_notable_to_analyzer.py)

For an alternative scheduled/query-based Phantom template that polls
`index=notable`, see:

- [`../../integrations/SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md`](../../integrations/SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md)
- [`../../../src/llm_notable_analysis_onprem_systemd/soar_playbook/phantom_notable_index_to_analyzer.py`](../../../src/llm_notable_analysis_onprem_systemd/soar_playbook/phantom_notable_index_to_analyzer.py)

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

Run tests from monorepo root before first service start:

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

- [`../rag/KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md)

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
# Start vLLM first (LiteLLM depends on it by default)
sudo systemctl enable --now vllm

# Wait for vLLM to load model (check logs)
sudo journalctl -u vllm -f

# Start LiteLLM
sudo systemctl enable --now litellm

# Start analyzer
sudo systemctl enable --now notable-analyzer

# When analyst_portal is enabled
sudo systemctl enable --now notable-portal

# Optional: enable retention timer
sudo systemctl enable --now notable-retention.timer
```

---

## Verification

```bash
# Service status
sudo systemctl status vllm litellm notable-analyzer notable-portal

# Full local service-chain smoke:
# vLLM health -> LiteLLM models/chat -> analyzer file-drop report
sudo bash scripts/smoke_service_chain.sh \
  --config-env /etc/notable-analyzer/config.env

# Portal liveness when analyst_portal is enabled
curl -fsS http://127.0.0.1:8080/health

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
sudo systemctl disable --now notable-analyzer notable-portal litellm vllm notable-retention.timer

# Remove systemd units
sudo rm /etc/systemd/system/{notable-analyzer,notable-portal,litellm,vllm,notable-retention}.{service,timer}
sudo systemctl daemon-reload

# Remove users (optional)
sudo userdel notable-analyzer
sudo userdel litellm
sudo userdel vllm
sudo userdel soar-uploader

# Remove directories (optional - preserves data by default)
sudo rm -rf /opt/notable-analyzer /opt/litellm /opt/vllm
sudo rm -rf /etc/notable-analyzer /etc/litellm
# sudo rm -rf /var/notables  # Uncomment to delete data

# Remove SFTP config from sshd_config (manual edit)
sudo vi /etc/ssh/sshd_config
# Delete lines from "# Notable Analyzer SFTP Config" to end of Match block
sudo systemctl restart sshd
```

---

## Ansible Alternative

For multi-host or enterprise deployments, consider converting `scripts/install.sh`
to an Ansible playbook. Key modules:

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
