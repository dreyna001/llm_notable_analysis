# On-Prem Notable Analyzer — Security Posture (Hardening, Supply Chain, FIPS)

This document describes the **security posture implemented in `llm_notable_analysis_onprem_systemd/`**: runtime hardening, ingest and portal boundaries, integration gates, supply-chain controls, and FIPS posture.

For **customer decisions** (exposure choices, rotation, TLS ownership, rollout validation), see [`../operations/security/SECURITY_OPERATIONS.md`](../operations/security/SECURITY_OPERATIONS.md). This file is the authoritative implemented-controls reference, not an operations runbook.

## Operating assumptions / boundary

- **On-prem, single-host deployment** (RHEL 8/9 or compatible).
- **Air-gapped capable**: the analyzer can run without internet access.
- **Local-only LLM**: inference uses a local OpenAI-compatible LiteLLM endpoint on the same host, with vLLM behind it by default.
- **Primary ingest path**: file-drop into an incoming directory (commonly via SFTP chroot upload from a SOAR host).
- **Optional integrations**: Splunk REST writeback and read-only search, Elasticsearch read-only search, ServiceNow draft/create — all customer-controlled endpoints and credentials.
- **Optional analyst portal**: read-only FastAPI on loopback, typically fronted by nginx TLS and basic auth on the internal network.

## Least privilege: dedicated service identities

The installer creates **non-login** system users (`/sbin/nologin`) to isolate responsibilities:

| User | Role |
|------|------|
| `notable-analyzer` | Python analyzer, portal, and retention jobs |
| `litellm` | Local LiteLLM proxy |
| `vllm` | vLLM inference server |
| `soar-uploader` | SFTP-only file delivery |

- `soar-uploader` is in the `notable-analyzer` group for controlled shared access to the incoming drop.
- SOAR public keys belong only in `/var/sftp/soar/.ssh/authorized_keys` (`600`).

## Network exposure minimization

### Local inference (loopback by default)

- **LiteLLM** binds to `127.0.0.1:4000` (`--host 127.0.0.1` in `litellm.service`).
- **vLLM** binds to `127.0.0.1:8000` (`--host 127.0.0.1` in `vllm.service`).
- Default analyzer client URL: `LLM_API_URL=http://127.0.0.1:4000/v1/chat/completions`.
- `LLM_API_TOKEN` is optional on loopback; set only when LiteLLM or vLLM enforces API-key auth.

Remote inference requires deliberate unit/config changes and is a customer exposure decision (see SECURITY_OPERATIONS).

### Outbound integrations (capability-gated)

The analyzer makes outbound HTTPS only when the corresponding capability profile and settings are enabled:

| Integration | Default | When enabled |
|-------------|---------|--------------|
| Local LiteLLM | Always (loopback) | — |
| Splunk REST (writeback, search) | Off | `action_gated`, `spl_readonly`, or explicit flags |
| Elasticsearch read-only search | Off | `elastic_readonly` or explicit flags |
| ServiceNow draft/create | Off | `ticket_draft`, `action_gated`, or explicit flags |

Splunk search and Elasticsearch execution use deterministic allowlists, bounds, and timeouts defined in `config.env.example` (indexes, commands, fields, row limits, time ranges).

### Analyst portal (loopback + nginx edge)

- **`notable-portal.service`** listens on `127.0.0.1:8080` by default (`PORTAL_BIND_HOST=127.0.0.1`).
- Production access is intended via **nginx on TCP 443**: TLS termination, basic auth, static SPA, and API proxy to loopback.
- nginx injects `X-Notable-Portal-Proxy-Secret` (must match `PORTAL_PROXY_SECRET`) and `X-Forwarded-User` so direct loopback callers cannot forge authenticated identity.
- `PORTAL_ALLOW_NON_LOOPBACK_BIND=false` by default; non-loopback bind requires explicit approval.
- Recommended future state: loopback oauth2-proxy + nginx `auth_request` + corporate OIDC with MFA and an approved analyst group.
- OIDC replaces edge authentication only; the proxy-secret boundary remains and per-case RBAC is still a separate deferred control.
- Portal chat is text-in/text-out only; it does not execute Splunk, ServiceNow, SOAR, or filesystem actions. See [`../operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md`](../operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md).

Network deployment steps: [`../operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md).

## Process and credential separation

| Process | Config source | Holds integration/action secrets? |
|---------|---------------|-----------------------------------|
| `notable-analyzer.service` | `/etc/notable-analyzer/config.env` | Yes (Splunk, ServiceNow, Elasticsearch, retention, ingest) |
| `notable-portal.service` | `/etc/notable-analyzer/portal.env` | No — portal LLM, Postgres read path, proxy secret only |
| `litellm.service` | `/etc/litellm/config.yaml` | LiteLLM routing only (may reference upstream auth) |

The installer sets restrictive permissions on protected config:

- `chmod 600` on `config.env`, `portal.env`, and `/etc/litellm/config.yaml`
- Owner: `notable-analyzer:notable-analyzer` for analyzer/portal env; `litellm:litellm` for LiteLLM config

Examples in-repo: `config.env.example`, `config.portal.env.example`.

## Integration writeback and action gates

Consequential external writes are **off by default** and gated by capability profiles:

- **`action_gated`** enables Splunk notable comment writeback (`SPLUNK_SINK_ENABLED`), ServiceNow draft/create, payload-level create approval (`SERVICENOW_CREATE_REQUIRES_APPROVAL=true`), and side-effect idempotency markers for Splunk/ServiceNow writes.
- **ServiceNow create** requires explicit approval metadata in the incoming notable JSON (`servicenow_create_approval` with `approved`, `approved_by`, etc.); missing or denied approval blocks create.
- **`ticket_draft`** enables draft-only ServiceNow content without create.
- Splunk writeback and ServiceNow operations run in the **analyzer process**, not portal chat.

Operational rollout for writeback: [`../operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](../operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md), [`../operations/integrations/SERVICENOW_OPERATIONS.md`](../operations/integrations/SERVICENOW_OPERATIONS.md).

## Systemd sandboxing / service hardening

Shipped units under `deploy/systemd/` enable layered hardening. Summary by unit:

| Unit | User | Sandbox highlights |
|------|------|-------------------|
| `notable-analyzer.service` | `notable-analyzer` | Full sandbox: `ProtectSystem=strict`, kernel protections, `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`, `ReadWritePaths=/var/notables /var/notables/cache /var/sftp/soar` |
| `notable-portal.service` | `notable-analyzer` | Same sandbox pattern; `ReadOnlyPaths=/etc/notable-analyzer`; writes only under `/var/notables/cache` |
| `notable-retention.service` | `notable-analyzer` | Oneshot; `ProtectSystem=strict`; `ReadWritePaths=/var/notables` |
| `litellm.service` | `litellm` | Loopback bind; `ProtectSystem=full`; lighter sandbox (no kernel module/tunables restrictions) |
| `vllm.service` | `vllm` | Loopback bind; reduced restrictions for Gloo/NCCL bootstrap (see below) |

Common directives on analyzer and LiteLLM units include:

- **Privilege restrictions**: `NoNewPrivileges=yes`, empty `CapabilityBoundingSet` and `AmbientCapabilities`
- **Kernel/interface protections** (analyzer + portal): `ProtectKernelTunables`, `ProtectKernelModules`, `ProtectControlGroups`, `ProtectKernelLogs`
- **Namespace / personality / syscall architecture** (analyzer + portal): `RestrictNamespaces=yes`, `SystemCallArchitectures=native`, `LockPersonality=yes`
- **File creation defaults**: `UMask=0077`
- **Filesystem protections**: `ProtectHome=yes`, `PrivateTmp=yes`
- **Resilience**: `Restart=on-failure` with bounded restart delay
- **Logging**: `StandardOutput=journal`, `StandardError=journal`

Notes:

- `ReadWritePaths` includes `/var/notables/cache` for RAG model caches under `ProtectSystem=strict`.
- `INCOMING_DIR` is often a symlink (`/var/notables/incoming` -> `/var/sftp/soar/incoming`); `/var/sftp/soar` must be writable for moves out of the drop.
- **`vllm.service`** intentionally relaxes several protections: no `ProtectSystem`, no `RestrictAddressFamilies`, and `ProtectKernelTunables=no` (and related kernel protections off) due to Gloo/NCCL bootstrap failures on some virtualized hosts.
- **Local-only rendezvous** for vLLM distributed primitives: `VLLM_HOST_IP=127.0.0.1`, `MASTER_ADDR=127.0.0.1`, `NCCL_SOCKET_IFNAME=lo`, `GLOO_SOCKET_IFNAME=lo`.

## Secure file ingestion (SFTP chroot)

`scripts/install.sh` appends an sshd `Match User soar-uploader` block:

- **ChrootDirectory** `/var/sftp/soar`
- **ForceCommand internal-sftp**
- **Forwarding disabled**: `AllowTcpForwarding no`, `X11Forwarding no`
- **Password authentication disabled** for that user

Filesystem permissions:

- `/var/sftp/soar`: `root:root`, mode `755` (chroot parent not writable by uploader)
- `/var/sftp/soar/incoming`: `soar-uploader:notable-analyzer`, mode `775`
- `/var/notables/incoming` commonly symlinks into the chroot incoming directory

## TLS verification for outbound HTTPS

- **Splunk** (writeback and search): TLS verification **on by default**; optional `SPLUNK_CA_BUNDLE` for internal CAs; unset uses the system trust store.
- **Elasticsearch**: HTTPS required when execution is enabled (API key in headers); optional `ELASTICSEARCH_CA_BUNDLE`.
- **ServiceNow**: HTTPS base URL expected; token in Authorization header.
- There is no supported production path to disable TLS verification for these integrations.

## Model loading hardening (`--trust-remote-code`)

The shipped `vllm.service` keeps **`--trust-remote-code` disabled by default**.

- Enabling it can execute arbitrary Python bundled with model artifacts during load.
- Enable only after verified offline import and checksum validation of model artifacts.

## Structured logging for audit/forensics

The analyzer uses **structured JSON logs** (stdout -> journald) with a per-notable **correlation ID** (`timestamp`, `level`, `logger`, `message`, `correlation_id`; exceptions include stack traces).

Operators should assess whether inbound notable content contains sensitive fields and align log forwarding/retention with local policy.

## Input safety and file-handling hygiene

- Only `*.json` and `*.txt` are processed in `INCOMING_DIR` (no recursion).
- Notable IDs in output filenames are **sanitized** to prevent path traversal.
- Oversized or invalid inputs are moved to **quarantine** for triage.
- `MAX_INPUT_FILE_BYTES` bounds read size before processing.

## Retention / data minimization

Two-stage retention reduces disk footprint:

- Stage 1: move older inputs/reports to an archive tree
- Stage 2: delete from archive after an additional retention window

Intervals are configurable in `config.env` (`INPUT_RETENTION_DAYS`, `REPORT_RETENTION_DAYS`, `ARCHIVE_RETENTION_DAYS`). Case archive and chat history retention are separate portal/Postgres settings when enabled.

---

## Supply chain (pinning / SBOM / provenance)

### Dependency pinning (Python)

#### Analyzer venv (`/opt/notable-analyzer/venv`)

- `requirements.txt` uses **exact pins** (example: `requests==2.32.5`).
- For regulated deployments, install from an **approved internal mirror** or offline wheelhouse.

#### vLLM venv (`/opt/vllm/venv`)

`scripts/install.sh` installs from pinned specs by default:

- `VLLM_PIP_SPEC` (default: `vllm==0.21.0`)
- `LITELLM_PIP_SPEC` (default: `litellm[proxy]==1.83.14`)
- `HUGGINGFACE_HUB_PIP_SPEC` (default: `huggingface_hub==1.16.4`, when `MODEL_DOWNLOAD=true`)

Override examples (air-gapped): internal mirror URLs or offline wheel paths (see `scripts/install.sh` comments).

### Declared dependency inventory

See [`../operations/deployment/DEPENDENCY_LIST.md`](../operations/deployment/DEPENDENCY_LIST.md) for repo-pinned direct dependencies (Python, npm, models, OS components). It is not a full transitive SBOM.

### Evidence-based dependency manifest (recommended)

On the target host:

```bash
sudo bash scripts/tools/generate_dependency_manifest.sh
```

Captures OS/kernel details, system packages when available, Python venv inventories, systemd unit copies with SHA256 hashes, model directory inventory, and optional Syft SBOM when `syft` is installed.

- The repo does **not** force-install SBOM tooling.
- Prefer generating SBOMs from the **installed environment** (captures transitive dependencies).

### Provenance and signing (recommended pattern)

This project supports evidence creation; **artifact signing is an org policy decision**.

Recommended approach:

1. Generate an evidence folder with `scripts/tools/generate_dependency_manifest.sh`
2. Retain SHA256s (included for unit files and model files when `sha256sum` exists)
3. Optionally sign the evidence bundle with org-approved tooling

The evidence bundle should be **immutable and attributable** (producer, timestamp, host, inputs).

---

## FIPS posture (what we can and cannot claim)

### What we can do in this repo

- Avoid insecure defaults (e.g., do not disable TLS verification for Splunk).
- Run in **FIPS-enabled OS environments** when the underlying platform supports it.
- Document that "must run in FIPS mode" is an **environment requirement** where mandated.

### What must come from the environment / enclave

FIPS compliance is not a property of this repo alone. Common requirements (org-dependent):

- **FIPS-enabled OS** (e.g., RHEL in FIPS mode)
- **FIPS-validated crypto modules** for system OpenSSL and relevant libraries
- **Approved SSH/TLS configurations** (sshd, Splunk TLS, nginx portal TLS, etc.)
- **Approved build inputs** (signed/pinned wheels, validated drivers/toolkits, verified model artifacts)

### Practical guidance (RHEL)

- Enable FIPS at the OS level and ensure TLS/SSH endpoints use FIPS-approved algorithms per local policy.
- Treat model artifacts as supply-chain inputs; move via approved media and validate with checksums before use.

---

## Related docs

| Topic | Document |
|-------|----------|
| Customer security decisions and validation | [`../operations/security/SECURITY_OPERATIONS.md`](../operations/security/SECURITY_OPERATIONS.md) |
| Install and hardening verification | [`../operations/deployment/INSTALL.md`](../operations/deployment/INSTALL.md) |
| Air-gapped deployment | [`../operations/deployment/AIRGAPPED_DEPLOYMENT.md`](../operations/deployment/AIRGAPPED_DEPLOYMENT.md) |
| File drop, quarantine, retention | [`../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) |
| Capability profiles | [`../operations/platform/CAPABILITY_PROFILES.md`](../operations/platform/CAPABILITY_PROFILES.md) |
| Splunk writeback | [`../operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](../operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md) |
| ServiceNow draft/create | [`../operations/integrations/SERVICENOW_OPERATIONS.md`](../operations/integrations/SERVICENOW_OPERATIONS.md) |
| Portal chat boundaries | [`../operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md`](../operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md) |
| Portal nginx/TLS deployment | [`../operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md) |
