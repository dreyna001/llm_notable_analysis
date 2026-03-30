# On-Prem/Air-Gapped Notable Analysis Service Architecture

Air-gapped, single-host deployment for security notable analysis using local LLM inference (vLLM + gpt-oss-120b) and MITRE ATT&CK TTP validation. We don't assume the customer has any of the hardware/software resources; keep that in mind when looking at cost & setup.

## Notes / Clarifications

- **Doc intent / naming**: This doc is meant to capture the **architecture + service design** for an **on-prem / air-gapped** operating model (not only “how to deploy”).
- **Why `__init__.py` exists**: `onprem_service/__init__.py` makes `onprem_service` a Python package so imports are reliable (and `python -m onprem_service.onprem_main` works predictably).

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Single Host (RHEL)                       │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐     ┌──────────────────┐     ┌─────────────┐   │
│  │  Incoming   │────>│  notable-analyzer│────>│   Reports   │   │
│  │  Directory  │     │     Service      │     │  Directory  │   │
│  └─────────────┘     └────────┬─────────┘     └─────────────┘   │
│                               │                                 │
│                               ▼                                 │
│                      ┌────────────────┐                         │
│                      │  vLLM Server   │                         │
│                      │ (gpt-oss-120b) │                         │
│                      └────────────────┘                         │
│                               │                                 │
│                      ┌────────────────┐                         │
│                      │  RTX PRO 6000  │                         │
│                      │    (96 GB)     │                         │
│                      └────────────────┘                         │
└─────────────────────────────────────────────────────────────────┘
```

## VM walkthrough (unpacked tree → running with `onprem_qwen3_sudo_llamacpp_service`)

For a **single markdown** path from “code is on the VM” through `llama-server` on loopback **8000** and this service as client, see [`onprem_qwen3_sudo_llamacpp_service/docs/VM_WALKTHROUGH_UNPACKED_TO_RUNNING.md`](../onprem_qwen3_sudo_llamacpp_service/docs/VM_WALKTHROUGH_UNPACKED_TO_RUNNING.md).

For a concise "what to download first" checklist for offline setup, see [`OFFLINE_PRESTAGE_GUIDE.md`](OFFLINE_PRESTAGE_GUIDE.md).

## Mini/Qwen CPU client one-command install

If your inference layer is already provided by `onprem_qwen3_sudo_llamacpp_service`, install this package in **client mode** (no vLLM/GPU setup) with:

```bash
cd /path/to/llm_notable_analysis_onprem
sudo bash install_mini_qwen_cpu_client.sh
```

What this script does:

- Installs `onprem_service` into `/opt/notable-analyzer`.
- Creates `/opt/notable-analyzer/venv` and installs dependencies.
- Installs the local SDK from `../onprem-llm-sdk` by default.
- Creates/updates `/etc/notable-analyzer/config.env` for mini defaults:
  - `LLM_API_URL=http://127.0.0.1:8000/v1/chat/completions`
  - `LLM_MODEL_NAME=Qwen3-4B-Q4_K_M.gguf`
- Creates `/usr/local/bin/notable-analyzer-mini-run` launcher.
- Optionally installs a `systemd` unit when runtime support is available.

If your SDK is not at `../onprem-llm-sdk`, set:

```bash
sudo SDK_SOURCE_DIR=/path/to/onprem-llm-sdk bash install_mini_qwen_cpu_client.sh
```

## Quick Start

### 1. Install Dependencies

```bash
# Create installation directory
sudo mkdir -p /opt/notable-analyzer
sudo chown $USER:$USER /opt/notable-analyzer

# Copy files
cp -r onprem_service /opt/notable-analyzer/
cp requirements.txt /opt/notable-analyzer/

# Create virtual environment
cd /opt/notable-analyzer
python3.10 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

```bash
# Create config directory
sudo mkdir -p /etc/notable-analyzer

# Copy and edit configuration
sudo cp config.env.example /etc/notable-analyzer/config.env
sudo chmod 600 /etc/notable-analyzer/config.env
sudo nano /etc/notable-analyzer/config.env
```

### 3. Create Directories

```bash
sudo mkdir -p /var/notables/{incoming,processed,quarantine,reports}
sudo chown -R notable-analyzer:notable-analyzer /var/notables
```

### 4. Install Systemd Services

```bash
sudo cp systemd/notable-analyzer.service /etc/systemd/system/
sudo cp systemd/vllm.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable notable-analyzer vllm
sudo systemctl start vllm
sudo systemctl start notable-analyzer
```

### Note on vLLM installation

The analyzer expects a local OpenAI-compatible vLLM endpoint. For a `gpt-oss-120b` deployment on RTX PRO 6000 (96 GB), use:

- Interpreter: `/opt/vllm/venv/bin/python`
- Model path: `/opt/models/gpt-oss-120b`
- Executor backend: `--distributed-executor-backend mp`

Note: the repo's base `systemd/vllm.service` still defaults to `gpt-oss-20b`; update `--model` and `--served-model-name` for `gpt-oss-120b`.

If you use `install.sh`, it will create `/opt/vllm/venv` and install vLLM by default (using `python3.12` unless overridden; set `VLLM_SKIP_INSTALL=true` to skip).
If you install vLLM elsewhere, set `VLLM_INSTALL_DIR` and `VLLM_VENV_DIR` when running `install.sh`; the installer patches the installed `/etc/systemd/system/vllm.service` `WorkingDirectory` and `ExecStart` automatically.
Single-node loopback rendezvous settings (`VLLM_HOST_IP`, `MASTER_ADDR`, NCCL/Gloo loopback interface vars) are included directly in `systemd/vllm.service`; no extra drop-in is required for normal installs.

Examples:

```bash
# Default layout
sudo bash install.sh

# Custom side-by-side vLLM path (optional)
sudo VLLM_INSTALL_DIR=/opt/vllm312 VLLM_VENV_DIR=/opt/vllm312/venv VLLM_PYTHON_BIN=python3.12 bash install.sh
```

Note: During vLLM installation, the installer may appear idle for several minutes after creating `/opt/vllm/venv` while `pip` resolves/builds dependencies. This is expected on some hosts.

### Note on model weights directory

`install.sh` will also **best-effort** create `/opt/models` (and the configured model path) and attempt to `chown` it to the invoking sudo user to make it easier to download/copy model weights. If this fails due to permissions, the install continues and you can create/chown the directory manually.

### Optional install.sh flags (quality-of-life)

- **Skip vLLM install**: `sudo VLLM_SKIP_INSTALL=true bash install.sh` (useful for air-gapped hosts where you pre-stage wheels)
- **Enable extra vLLM smoke checks**: `sudo VLLM_SMOKE_TEST=true bash install.sh` (non-fatal checks like `nvidia-smi` + model path presence)
- **Download model weights (non-interactive)**: `sudo MODEL_DOWNLOAD=true HF_TOKEN=... bash install.sh`
  - Optional: `MODEL_REPO=openai/gpt-oss-120b`
  - Notes: best-effort; uses `huggingface_hub` HTTP downloads (no `git lfs` required)
- **Auto-start services after install (best-effort, default true)**: `sudo AUTO_START_SERVICES=true bash install.sh`
- **Skip post-install service start**: `sudo AUTO_START_SERVICES=false bash install.sh`
- **Run canned inference smoke test after auto-start (best-effort, default true)**: `sudo RUN_SMOKE_TEST=true bash install.sh`
- **Skip canned inference smoke test**: `sudo RUN_SMOKE_TEST=false bash install.sh`
- **Override vLLM health timeout (default: 420s)**: `sudo VLLM_HEALTH_TIMEOUT_SECONDS=420 bash install.sh`
- **Override smoke test timeout (default: 240s)**: `sudo SMOKE_TEST_TIMEOUT_SECONDS=240 bash install.sh`
- **Reset existing vLLM systemd drop-ins (recommended when standardizing)**: `sudo VLLM_RESET_OVERRIDES=true bash install.sh`

### Manual Inputs Still Required

Even with one-command install, these items remain environment-specific:

- Confirm model weights are present at `/opt/models/gpt-oss-120b` (or set your chosen path in `vllm.service`).
- Set `LLM_API_TOKEN` only if your vLLM command includes `--api-key`.
- Set `SPLUNK_BASE_URL` / `SPLUNK_API_TOKEN` only when `SPLUNK_SINK_ENABLED=true`.
- Add SOAR public key(s) to `/var/sftp/soar/.ssh/authorized_keys` only if using SOAR SFTP ingest.
- Review the final `install.sh` "Non-fatal issues encountered" summary and resolve items before production.

## Compliance / Gov-ready: generating a dependency manifest (what was installed)

For environments that require scanning/approving every installed component, generate an evidence-based manifest on the target host:

```bash
cd /path/to/llm_notable_analysis_onprem
sudo bash tools/generate_dependency_manifest.sh
```

This produces a timestamped folder (example: `dependency_manifest_20260117_033000/`) containing:
- OS/kernel info
- GPU driver/runtime info (`nvidia-smi` if present)
- System package inventory (RPM or DPKG, depending on distro)
- Python venv inventories (`pip freeze`) for `/opt/notable-analyzer/venv` and `/opt/vllm/venv`
- systemd unit file copies + hashes
- Model directory inventory + SHA256 hashes (if present at your configured model path, for example `/opt/models/gpt-oss-120b`)

This is generally more accurate than a hand-written list because it reflects the *actual* host state after install.

## Reproducibility: pinning Python for the venvs (recommended for regulated envs)

For the highest-confidence installs over time, pin the Python interpreter used for each virtualenv.

Recommended baseline: **Python 3.12**.

Example (pin both venvs to Python 3.12):

```bash
sudo ANALYZER_PYTHON_BIN=python3.12 VLLM_PYTHON_BIN=python3.12 bash install.sh
```

If the specified interpreter is not present on the host, `install.sh` will fail early (so you don’t end up with a partially working deployment).

## Freeform paragraphs mode (no JSON schema)

If you want a report that is just a few paragraphs (to avoid schema/tooling fragility), you can run the alternative service:

- systemd unit: `notable-analyzer-freeform.service`
- entrypoint: `python -m onprem_service.freeform_main`

It writes reports as `*_freeform.md` into `REPORT_DIR` (default: `/var/notables/reports`).

Enable it (make sure `vllm` is running first):

```bash
sudo systemctl enable --now notable-analyzer-freeform
sudo journalctl -u notable-analyzer-freeform -f
```

Note: Do not run both the structured analyzer and freeform analyzer against the same `INCOMING_DIR` at the same time.

### 5. Verify

```bash
# Check service status
sudo systemctl status notable-analyzer
sudo systemctl status vllm

# View logs
sudo journalctl -u notable-analyzer -f
```

## Usage

## Knowledge Base Ingestion (RAG)

When `RAG_ENABLED=true`, the analyzer can inject SOC-specific operational context
from local retrieval artifacts. Build/update those artifacts manually:

```bash
python3 -m onprem_rag.future.corpus_ingest \
  --source-dir /opt/llm-notable-analysis/knowledge_base/source_docs \
  --index-dir /opt/llm-notable-analysis/knowledge_base/index \
  --embedding-model sentence-transformers/all-MiniLM-L6-v2
```

Supported source formats in `source_docs`:
- `.docx`
- `.txt`

Generated artifacts in `index`:
- `kb.sqlite3` (chunk metadata + FTS5)
- `kb.faiss` (vector index)
- `chunks.jsonl` (debug/exportable chunk corpus)
- `ingest_report.json` (ingestion summary)

## Automated Tests

Run the on-prem unittest suite from repo root:

```bash
python -m unittest discover -s llm_notable_analysis_onprem/tests -p "test*.py" -v
```

Preflight recommendation before first service start:

```bash
cd ~/llm_notable_analysis
PYTHONPATH=llm_notable_analysis_onprem /opt/notable-analyzer/venv/bin/python -m unittest discover -s llm_notable_analysis_onprem/tests -p "test*.py" -v
```

- Unit tests do not require `vllm` or `notable-analyzer` to be running.
- Proceed to service startup only after a clean `OK` test result.

Coverage details live in `TESTING.md`.

### File Drop Mode (Default)

Drop JSON or text files into `/var/notables/incoming`:

```bash
# Example: Submit a notable for analysis
echo '{"summary": "Suspicious login from unusual IP", "ip_address": "203.0.113.45", "user": "admin"}' > /var/notables/incoming/notable_001.json
```

Reports appear in `/var/notables/reports`:

```bash
ls /var/notables/reports/
# notable_001.md
```

### Splunk REST Integration (Optional)

When enabled, the analyzer updates Splunk ES notables with the generated markdown analysis.

**Enable in `/etc/notable-analyzer/config.env`:**

```bash
SPLUNK_SINK_ENABLED=true
SPLUNK_BASE_URL=https://splunk.internal:8089
SPLUNK_API_TOKEN=your_token_here
SPLUNK_NOTABLE_UPDATE_PATH=/services/notable_update
# SPLUNK_CA_BUNDLE=/path/to/internal-ca.pem  # If using internal CA (see Security Notes)
```

**Current implementation (placeholder):**

| Setting | Value |
|---------|-------|
| Endpoint | `POST {SPLUNK_BASE_URL}{SPLUNK_NOTABLE_UPDATE_PATH}` |
| Auth | `Authorization: Bearer {SPLUNK_API_TOKEN}` |
| Content-Type | `application/x-www-form-urlencoded` |
| Payload | `finding_id={filename_stem}&comment={markdown}&status=2` |

> **Note:** Splunk ES deployments can differ by customer. Confirm endpoint path and identifier contract with the customer's Splunk team before go-live.

**Current writeback identifier behavior:**
- The service derives `finding_id` from the dropped filename stem (for example, `/incoming/abc-123.json` -> `finding_id=abc-123`).
- This mirrors the current cloud pipeline behavior for identifier correlation.

---

## SOAR Integration (Recommended Workflow)

The recommended pattern mirrors the cloud S3 workflow: **SOAR pulls notables from Splunk ES and pushes them to the analyzer's incoming directory**. This keeps Splunk credentials in SOAR (not the analyzer) and preserves the existing operational model.

Phantom/SOAR template assets in this repo:

- Guide: [`SOAR_PLAYBOOK_PHANTOM.md`](SOAR_PLAYBOOK_PHANTOM.md)
- Playbook template: [`soar_playbook/phantom_notable_to_analyzer.py`](soar_playbook/phantom_notable_to_analyzer.py)

### Transport Options

#### SFTP (Recommended)

SFTP is the simplest and most secure transport for SOAR → analyzer file delivery.

**Setup on analyzer host (RHEL):**

```bash
# Create dedicated SFTP user (no shell access)
sudo useradd -m -s /sbin/nologin soar-uploader
sudo mkdir -p /var/notables/incoming
sudo chown soar-uploader:notable-analyzer /var/notables/incoming
sudo chmod 770 /var/notables/incoming

# Configure SSH for chroot SFTP
sudo nano /etc/ssh/sshd_config
```

Add to `/etc/ssh/sshd_config`:

```
Match User soar-uploader
    ChrootDirectory /var/notables
    ForceCommand internal-sftp
    AllowTcpForwarding no
    X11Forwarding no
```

```bash
# Fix ownership for chroot (root must own chroot dir)
sudo chown root:root /var/notables
sudo chmod 755 /var/notables
sudo chown soar-uploader:notable-analyzer /var/notables/incoming

# Restart SSH
sudo systemctl restart sshd
```

**SOAR playbook configuration:**
- Host: `<analyzer-host>`
- Port: `22`
- User: `soar-uploader`
- Auth: SSH key (recommended) or password
- Remote path: `/incoming/<finding_id>.json`

**Avoid partial reads (recommended):**
- Upload to a temporary filename that does **not** match `*.json` / `*.txt` (example: `/incoming/<finding_id>.json.tmp`)
- Atomically rename to `/incoming/<finding_id>.json` after the upload completes

**Hardening checklist:**
- Key-based auth only (disable password in `sshd_config` for this user)
- Firewall: allow only SOAR host(s) → analyzer host on port 22
- Audit: SSH logs provide transfer audit trail

#### NFS (Alternative)

Use NFS if the organization already has a managed NFS infrastructure and prefers it over SFTP.

**What would need to change:**
1. Export `/var/notables/incoming` from analyzer host (or mount from shared NFS server)
2. Configure exports in `/etc/exports`:

   ```
   /var/notables/incoming  soar-host.internal(rw,sync,no_subtree_check,root_squash)
   ```

3. Firewall: allow NFS ports (2049, plus rpcbind if NFSv3) from SOAR host only
4. Ensure `notable-analyzer` user can read files written by SOAR's NFS client UID (match UIDs or use `all_squash` + `anonuid`/`anongid`)
5. No code changes needed—the analyzer watches `INCOMING_DIR` the same way

**NFS tradeoffs vs SFTP:**
- (+) May integrate better with existing enterprise storage
- (-) More complex permissions/UID mapping
- (-) Broader network surface (NFS ports + rpcbind)
- (-) Less granular audit trail than SSH

**Recommendation:** Use SFTP unless NFS is already standard and hardened in the environment.

---

## Notable Payload Contract (What SOAR Should Send)

The analyzer processes files matching `*.json` or `*.txt` in `INCOMING_DIR`.

### JSON (Recommended)

- **File format**: UTF-8 JSON object
- **Current behavior:** `.json` notables are passed to the LLM as raw JSON, and `.txt` notables are passed as raw text. The service does not require a fixed customer JSON schema for prompt input.

**Required (minimum):**
- `summary` (string): short description of the notable

**Strongly recommended (for correlation + writeback):**
- `notable_id` (string): stable notable identifier (retained for context/audit)
- `event_id` (string): if available
- `search_name` (string): detection rule name / correlation search name
- `finding_id` (string): SOAR correlation ID; should match filename stem used for writeback
- `risk_score` (number or string)
- `threat_category` (string)
- `alert_time` (string): ISO-8601 preferred
- `raw_event` (string): optional full notable JSON serialized as a string (so it appears in the prompt)

**SOAR/Splunk ID mapping note (customer integration):**
- In many customer workflows, SOAR uses `finding_id` while Splunk notable workflows refer to the same correlation value as `event_id`.
- During integration, ensure the SOAR playbook preserves and forwards that correlation ID consistently so writeback targets the same notable.
- Confirm exact field naming with the customer's Splunk team before go-live (`finding_id`, `event_id`, or another contract-specific field).

Example payload:

```json
{
  "notable_id": "12345678-90ab-cdef-1234-567890abcdef",
  "search_name": "Suspicious Authentication Pattern",
  "summary": "Multiple failed logins followed by success",
  "alert_time": "2025-12-12T01:23:45Z",
  "user": "DOMAIN\\\\admin",
  "src_ip": "203.0.113.45",
  "dest_host": "DC-01",
  "risk_score": 80,
  "threat_category": "Credential Access",
  "raw_event": "{\"_time\":\"...\",\"ruleUID\":\"...\",\"events\":[...]}"
}
```

### Text (Fallback)

If SOAR can only emit text, write a `.txt` file. The analyzer will treat the full file contents as raw alert text.

---

## Retention Policy (Archive Then Delete)

The service applies two-stage retention to reduce disk usage while keeping a short audit window:

- **Stage 1 (move to archive):**
  - Files in `PROCESSED_DIR` and `QUARANTINE_DIR` older than `INPUT_RETENTION_DAYS` are moved to `ARCHIVE_DIR/processed` and `ARCHIVE_DIR/quarantine`.
  - Reports in `REPORT_DIR` older than `REPORT_RETENTION_DAYS` are moved to `ARCHIVE_DIR/reports`.
- **Stage 2 (delete from archive):**
  - Files in `ARCHIVE_DIR/*` older than `ARCHIVE_RETENTION_DAYS` (time spent in archive) are deleted.

Notes:
- The archive move resets the file timestamp so archive deletion represents **time in archive**, not time since creation.
- Housekeeping runs every `RETENTION_RUN_INTERVAL_SECONDS` (default: daily).

### Switching to systemd Timer Retention (Optional)

By default, retention runs **inside the analyzer service** (simplest setup). If you prefer the more Linux-native approach (decoupled from the service), you can switch to **systemd timer-based retention**:

**What to change:**

1. **Disable in-service retention** — set a very large interval in `/etc/notable-analyzer/config.env`:

   ```bash
   RETENTION_RUN_INTERVAL_SECONDS=999999999
   ```

2. **Install the timer and oneshot service:**

   ```bash
   sudo cp systemd/notable-retention.service /etc/systemd/system/
   sudo cp systemd/notable-retention.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now notable-retention.timer
   ```

3. **Verify:**

   ```bash
   # Check timer is active
   sudo systemctl list-timers | grep notable-retention

   # Manually test the oneshot
   sudo systemctl start notable-retention.service
   sudo journalctl -u notable-retention -n 20
   ```

**Why you might prefer this:**
- Runs even if the analyzer is stopped
- Clear success/failure status in systemd
- Easier ops (standard `systemctl` / `journalctl` workflow)

---

## Concurrency (Optional)

By default the service processes one notable at a time (sequential mode). To enable bounded concurrent processing (Python multithreading via `ThreadPoolExecutor`):

```bash
# In /etc/notable-analyzer/config.env
CONCURRENCY_ENABLED=true
MAX_WORKERS=1            # RTX PRO 6000 (96 GB) + gpt-oss-120b conservative start
MAX_QUEUE_DEPTH=8        # RTX PRO 6000 (96 GB) + gpt-oss-120b conservative start
```

Recommended starting profiles (concise):
- **RTX PRO 6000 (96 GB) + gpt-oss-120b**: start `1/8`; if sustained headroom, try `2/12`.
- **RTX PRO 6000 (96 GB) + gpt-oss-20b**: start `3/24`; if sustained headroom, try `4/32`.
- **L40S (48 GB) + gpt-oss-20b**: start `2/16`; if sustained headroom, try `3/24`.
- **L40S + gpt-oss-120b**: single-GPU viability is environment-dependent (quantization/model build/VRAM fit). Treat as **unknown** until validated in your environment; if it loads, start conservative at `1/8`.

Intel comparison note for the EPYC profile:
- Treat this EPYC VM baseline as a conservative starting tier for this service.
- Increase toward the higher profile only after validating sustained CPU headroom and queue behavior in production-like load tests.

**SDK/App setting precedence for this service:**
- `MAX_WORKERS` and `MAX_QUEUE_DEPTH` in `/etc/notable-analyzer/config.env` are the effective concurrency controls for this app.
- The app maps `MAX_WORKERS` into SDK inflight capacity internally for each worker.
- SDK transport retries are intentionally disabled for this app (`llm_max_retries=0`) so legacy app retry/backoff semantics are preserved.
- SDK env vars such as `LLM_MAX_INFLIGHT` and `LLM_MAX_RETRIES` are not the source of truth for this service's runtime behavior.

                                         **How it works (multithreading):**
- Discovered files are dispatched to a ThreadPoolExecutor
- If in-flight jobs reach `MAX_QUEUE_DEPTH`, new files wait until next poll cycle (backpressure)
- Each job maintains its own correlation ID in logs
- On shutdown, the service waits for in-flight jobs to complete

**When to enable:**
- Bursty SFTP drops that build a backlog
- LLM latency is acceptable and GPU/CPU can handle parallelism

**When to keep sequential:**
- LLM is already at saturation (more parallelism won't help)
- Simpler debugging and log ordering

---

## File Structure

```
llm_notable_analysis_onprem/
├── README.md                    # This file
├── INSTALL.md                   # Detailed installation guide
├── install.sh                   # Automated installer (run as root)
├── install_mini_qwen_cpu_client.sh  # Mini/Qwen CPU client-mode installer
├── requirements.txt             # Python dependencies
├── config.env.example           # Configuration template
├── systemd/
│   ├── notable-analyzer.service   # Analyzer systemd unit
│   ├── vllm.service               # vLLM systemd unit
│   ├── notable-retention.service  # Retention cleanup oneshot (optional)
│   └── notable-retention.timer    # Daily timer for retention (optional)
└── onprem_service/
    ├── __init__.py              # Package init
    ├── config.py                # Configuration loading
    ├── logging_utils.py         # Structured JSON logging
    ├── ttp_validator.py         # MITRE ATT&CK validation
    ├── ingest.py                # File discovery and normalization
    ├── sinks.py                 # Output writers (filesystem, Splunk REST)
    ├── local_llm_client.py      # vLLM API client
    ├── markdown_generator.py    # Report generation
    ├── retention.py             # Two-stage retention cleanup
    ├── onprem_main.py           # Service entry point
    └── enterprise_attack_v17.1_ids.json  # MITRE TTP IDs
```

## Updating MITRE ATT&CK Data

To update TTP IDs in an air-gapped environment:

1. On an internet-connected machine, run `extract_ttp_ids.py` to generate a new JSON file
2. Transfer the JSON file to the air-gapped host via approved media
3. Replace the JSON file at the path configured in `MITRE_IDS_PATH` (default: `/opt/notable-analyzer/onprem_service/enterprise_attack_v17.1_ids.json`)
4. Restart the service: `sudo systemctl restart notable-analyzer`

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 8 cores | 16 cores (Xeon/EPYC) |
| RAM | 64 GB | 128 GB |
| GPU | RTX 4090 (24 GB) | RTX PRO 6000 (96 GB) |
| Storage | 500 GB NVMe | 1 TB NVMe |

## Security Notes

### vLLM --trust-remote-code (DISABLED by default)

The `--trust-remote-code` flag allows vLLM to execute arbitrary Python code bundled with model artifacts during loading. This is **disabled by default** for security hardening.

**When to enable:**
- Only if the model requires custom architecture code (some models ship `modeling_*.py` files)
- AND you have verified model artifacts via checksum from a trusted, controlled offline import process

**To enable:** Edit `/etc/systemd/system/vllm.service` and add `--trust-remote-code` to the `ExecStart` line, then run:

```bash
sudo systemctl daemon-reload
sudo systemctl restart vllm
```

### Splunk TLS with Internal CA

If your Splunk instance uses a private/internal CA:

**Option A (recommended):** Install the CA into the RHEL system trust store:

```bash
sudo cp internal-ca.pem /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust
```

**Option B:** Set the CA bundle path in config:

```bash
SPLUNK_CA_BUNDLE=/path/to/internal-ca.pem
```

---

## Troubleshooting

Recovery and restart semantics (including power-cut/reboot behavior and SDK-vs-app responsibilities) are documented in:

- `RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`

### Service won't start

```bash
# Check logs
sudo journalctl -u notable-analyzer -n 50

# Verify vLLM is running
curl http://127.0.0.1:8000/health
```

### LLM timeouts

Increase timeout in config:

```bash
LLM_TIMEOUT=300
```

### GPU memory errors

Reduce vLLM memory utilization in `/etc/systemd/system/vllm.service`:

```
--gpu-memory-utilization 0.8
```

