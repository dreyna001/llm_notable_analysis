# On-Prem/Air-Gapped Notable Analysis Service Architecture

Air-gapped, single-host deployment for security notable analysis using local LLM inference (vLLM + gpt-oss-20b) and MITRE ATT&CK TTP validation. We don't assume the customer has any of the hardware/software resources; keep that in mind when looking at cost & setup.

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
│                      │  (gpt-oss-20b) │                         │
│                      └────────────────┘                         │
│                               │                                 │
│                      ┌────────────────┐                         │
│                      │  RTX PRO 6000  │                         │
│                      │    (96 GB)     │                         │
│                      └────────────────┘                         │
└─────────────────────────────────────────────────────────────────┘
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

The analyzer expects a local OpenAI-compatible vLLM endpoint. The included `vllm.service` uses:

- Interpreter: `/opt/vllm/venv/bin/python`
- Model path: `/opt/models/gpt-oss-20b`

If you use `install.sh`, it will create `/opt/vllm/venv` and install vLLM by default (set `VLLM_SKIP_INSTALL=true` to skip). If you install vLLM elsewhere, update `systemd/vllm.service` accordingly.

### Note on model weights directory

`install.sh` will also **best-effort** create `/opt/models` (and `/opt/models/gpt-oss-20b`) and attempt to `chown` it to the invoking sudo user to make it easier to download/copy model weights. If this fails due to permissions, the install continues and you can create/chown the directory manually.

### Optional install.sh flags (quality-of-life)

- **Skip vLLM install**: `sudo VLLM_SKIP_INSTALL=true bash install.sh` (useful for air-gapped hosts where you pre-stage wheels)
- **Enable extra vLLM smoke checks**: `sudo VLLM_SMOKE_TEST=true bash install.sh` (non-fatal checks like `nvidia-smi` + model path presence)
- **Download model weights (non-interactive)**: `sudo MODEL_DOWNLOAD=true HF_TOKEN=... bash install.sh`
  - Optional: `MODEL_REPO=openai/gpt-oss-20b`
  - Notes: best-effort; uses `huggingface_hub` HTTP downloads (no `git lfs` required)
- **Auto-start services after install (best-effort)**: `sudo AUTO_START_SERVICES=true bash install.sh`

### 5. Verify

```bash
# Check service status
sudo systemctl status notable-analyzer
sudo systemctl status vllm

# View logs
sudo journalctl -u notable-analyzer -f
```

## Usage

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
# SPLUNK_CA_BUNDLE=/path/to/internal-ca.pem  # If using internal CA (see Security Notes)
```

**Current implementation (placeholder):**

| Setting | Value |
|---------|-------|
| Endpoint | `POST {SPLUNK_BASE_URL}/services/notable_update` |
| Auth | `Authorization: Bearer {SPLUNK_API_TOKEN}` |
| Content-Type | `application/x-www-form-urlencoded` |
| Payload | `ruleUIDs={notable_id}&comment={markdown}&status=2` |

> **Note:** The endpoint and payload are placeholders. Confirm with your Splunk ES admin that `/services/notable_update` is the correct endpoint for your environment. The `status=2` value corresponds to "In Progress" in default ES configurations.

**Required fields from notable:**
- `notable_id` or `event_id` — Used as `ruleUIDs` parameter
- Falls back to `search_name` if no ID is present

---

## SOAR Integration (Recommended Workflow)

The recommended pattern mirrors the cloud S3 workflow: **SOAR pulls notables from Splunk ES and pushes them to the analyzer's incoming directory**. This keeps Splunk credentials in SOAR (not the analyzer) and preserves the existing operational model.

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
- Remote path: `/incoming/<notable_id>.json`

**Avoid partial reads (recommended):**
- Upload to a temporary filename that does **not** match `*.json` / `*.txt` (example: `/incoming/<notable_id>.json.tmp`)
- Atomically rename to `/incoming/<notable_id>.json` after the upload completes

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
- **Important limitation (current behavior)**: the current LLM prompt formatter only includes **top-level** values that are strings/numbers/booleans or lists. Nested objects may not be included in the prompt.
  - **Future consideration**: once the customer’s notable schema is finalized, we will update the formatter (and this payload contract) to match that schema permanently.
  - If you need to preserve the full notable today, include it as a string field (example: `raw_event`).

**Required (minimum):**
- `summary` (string): short description of the notable

**Strongly recommended (for correlation + writeback):**
- `notable_id` (string): stable ID (preferred for writeback)
- `event_id` (string): if available
- `search_name` (string): detection rule name / correlation search name
- `risk_score` (number or string)
- `threat_category` (string)
- `alert_time` (string): ISO-8601 preferred
- `raw_event` (string): optional full notable JSON serialized as a string (so it appears in the prompt)

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

By default the service processes one notable at a time (sequential mode). To enable bounded concurrent processing:

```bash
# In /etc/notable-analyzer/config.env
CONCURRENCY_ENABLED=true
MAX_WORKERS=2            # Thread pool size (keep small: 2-4)
MAX_QUEUE_DEPTH=20       # Backpressure limit
```

**How it works:**
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

