# On-Prem Notable Analyzer — Security Posture (Hardening, Supply Chain, FIPS)

This document describes the **security posture implemented in `llm_notable_analysis_onprem/`**, covering:

- **Runtime hardening** (systemd, least privilege, ingress/egress, logging)
- **Supply chain controls** (pinning, evidence/SBOM hooks, provenance guidance)
- **FIPS posture** (what we can vs cannot claim from the repo alone)

## Operating assumptions / boundary

- **On-prem, single-host deployment** (RHEL 8/9 or compatible).
- **Air-gapped capable**: the analyzer can run without internet access.
- **Local-only LLM**: inference is performed via a local OpenAI-compatible vLLM endpoint on the same host.
- **Primary ingest path**: file-drop into an incoming directory (commonly via SFTP chroot upload from a SOAR host).
- Optional integration: Splunk REST writeback (customer-controlled network path and credentials).

## Least privilege: dedicated service identities

The installer creates **non-login** system users to isolate responsibilities:

- **`notable-analyzer`**: runs the Python analyzer service
- **`vllm`**: runs the vLLM inference server
- **`soar-uploader`**: SFTP-only user for file delivery

Notes:

- `soar-uploader` is added to the `notable-analyzer` group to allow controlled shared access to the incoming drop.
- All three are configured with `/sbin/nologin` (no interactive shell).

## Network exposure minimization

- **vLLM binds to loopback only** (`127.0.0.1:8000`), preventing remote access unless the unit is modified:
  - `--host 127.0.0.1`
  - default client URL: `LLM_API_URL=http://127.0.0.1:8000/v1/completions`

- The analyzer only makes outbound HTTP calls to:
  - **local vLLM** (loopback) by default
  - **Splunk REST** only when enabled (`SPLUNK_SINK_ENABLED=true`)

## Systemd sandboxing / service hardening

The systemd units enable multiple hardening directives:

- **Privilege restrictions**
  - `NoNewPrivileges=yes`
  - `CapabilityBoundingSet=` (empty)
  - `AmbientCapabilities=` (empty)
- **Kernel/interface protections**
  - `ProtectKernelTunables=yes`
  - `ProtectKernelModules=yes`
  - `ProtectControlGroups=yes`
  - `ProtectKernelLogs=yes`
- **Namespace / personality / syscall architecture**
  - `RestrictNamespaces=yes`
  - `SystemCallArchitectures=native`
  - `LockPersonality=yes`
- **Address families**
  - Analyzer services (`notable-analyzer*`) use `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`
  - `vllm.service` intentionally does **not** enforce `RestrictAddressFamilies` due to known Gloo bootstrap failures on some virtualized hosts
- **File creation defaults**
  - `UMask=0077`
- **Filesystem protections**
  - `ProtectSystem=strict` (analyzer services)
  - `ProtectHome=yes`
  - `PrivateTmp=yes`
  - `ReadWritePaths=/var/notables /var/sftp/soar` (explicit writable allowlist; important when `INCOMING_DIR` is a symlink into the SFTP chroot)
- **Resilience**
  - `Restart=on-failure` with bounded restart delay
- **Logging**
  - `StandardOutput=journal`, `StandardError=journal` (centralized via journald)

Additional note:

- The `vllm.service` unit is configured for **local-only rendezvous** with:
  - `VLLM_HOST_IP=127.0.0.1`
  - `MASTER_ADDR=127.0.0.1`
  - `NCCL_SOCKET_IFNAME=lo`
  - `GLOO_SOCKET_IFNAME=lo`

## Secure file ingestion (SFTP chroot)

The installer adds a dedicated `sshd_config` Match block for the uploader user:

- **ChrootDirectory** set to `/var/sftp/soar`
- **ForceCommand internal-sftp**
- **Forwarding disabled**
  - `AllowTcpForwarding no`
  - `X11Forwarding no`
- **Password authentication disabled** for that user (`PasswordAuthentication no`)

Filesystem permissions are set to support chroot correctness and least privilege:

- Chroot path **owned by root** and not writable by others:
  - `/var/sftp/soar` is `root:root` with mode `755`
- Incoming drop is writable by uploader and readable by analyzer:
  - `/var/sftp/soar/incoming` is `soar-uploader:notable-analyzer` with mode `775`
- `/var/notables/incoming` is commonly a **symlink** to the chroot incoming directory.

## Configuration & secret handling

- Runtime configuration is sourced from an **EnvironmentFile**:
  - `/etc/notable-analyzer/config.env`
- The installer sets **restrictive permissions**:
  - `chmod 600 /etc/notable-analyzer/config.env`
- Secrets are expected to be provided via config/env variables (examples):
  - `SPLUNK_API_TOKEN`
  - optional `LLM_API_TOKEN`

## TLS verification for Splunk writeback

When Splunk writeback is enabled:

- TLS verification is **ON by default**.
- If an internal/private CA is used, a PEM bundle can be configured:
  - `SPLUNK_CA_BUNDLE=/path/to/internal-ca.pem`
- If unset, the system trust store is used.

## Model loading hardening (`--trust-remote-code`)

The included `vllm.service` explicitly documents and keeps **`--trust-remote-code` disabled by default**.

- Rationale: enabling it can execute arbitrary Python code bundled with model artifacts during load.
- If a model truly requires it, the unit must be deliberately changed and the model artifacts should be verified via an approved offline import + checksum process.

## Structured logging for audit/forensics

The analyzer uses **structured JSON logs** (stdout → journald) and includes a per-notable **correlation ID**:

- `timestamp`, `level`, `logger`, `message`, `correlation_id`
- Exceptions include formatted stack traces

Operational note:

- Operators should consider whether inbound notable content contains sensitive fields and ensure log forwarding/retention meets local policy.

## Input safety and file-handling hygiene

- Only `*.json` and `*.txt` are processed in `INCOMING_DIR` (no recursion).
- Notable IDs used in output filenames are **sanitized** to avoid path traversal / unsafe characters.
- Failed or invalid inputs are moved to a **quarantine directory** for triage.

## Retention / data minimization

The service supports two-stage retention to reduce disk footprint and keep a short audit window:

- Stage 1: move older files to an archive tree
- Stage 2: delete from archive after an additional retention window

Retention intervals are configurable in `/etc/notable-analyzer/config.env` (defaults are conservative and should be tuned to local policy).

---

## Supply chain (pinning / SBOM / provenance)

### Dependency pinning (Python)

#### Analyzer venv (`/opt/notable-analyzer/venv`)

- `llm_notable_analysis_onprem/requirements.txt` uses **exact pins** (example: `requests==...`).
- For regulated deployments, install from an **approved internal mirror** or offline wheelhouse.

#### vLLM venv (`/opt/vllm/venv`)

By default, `install.sh` installs vLLM from a **pinned** spec:

- `VLLM_PIP_SPEC` (default: `vllm==0.14.1`)

Override examples (air‑gapped):

- `VLLM_PIP_SPEC="vllm==0.14.1"` (internal mirror)
- `VLLM_PIP_SPEC="/mnt/media/wheels/vllm-0.14.1-*.whl"` (offline media)

### Evidence-based dependency manifest (recommended)

Run on the target host:

- `sudo bash tools/generate_dependency_manifest.sh`

This captures (at minimum):

- OS/kernel details
- System packages (RPM/DPKG) when available
- Python venv inventories (`pip freeze`)
- systemd unit copies and SHA256 hashes
- Model directory inventory + SHA256 hashes (if present)
- SBOM hook:
  - **Syft SBOM** (if `syft` is installed on the host)

Notes:

- In strict environments, SBOM tools are often provided by the org (or run on a staging build host). This repo **does not force-install** SBOM tooling.
- Prefer generating SBOMs from the **installed environment** (captures transitive dependencies).

### Provenance and signing (recommended pattern)

This project supports evidence creation; **artifact signing is an org policy decision**.

Recommended approach:

1. Generate an evidence folder using `tools/generate_dependency_manifest.sh`
2. Compute/retain SHA256s (already included for unit files + model files when `sha256sum` exists)
3. Optionally sign the evidence bundle using org-approved tooling (GPG / enterprise signing systems)

The key requirement is that the **evidence bundle is immutable and attributable** (who produced it, when, on which host, with what inputs).

---

## FIPS posture (what we can and cannot claim)

### What we can do in this repo

- Avoid insecure defaults (e.g., do not disable TLS verification for Splunk).
- Run cleanly in **FIPS-enabled OS environments** when the underlying platform supports it.
- Document an expectation that “must run in FIPS mode” is an **environment requirement** where mandated.

### What must come from the environment / enclave

FIPS compliance is not a property of this repo alone. Common requirements (org-dependent):

- **FIPS-enabled OS** (e.g., RHEL in FIPS mode)
- **FIPS-validated crypto modules** for system OpenSSL and relevant libraries
- **Approved SSH/TLS configurations** (sshd, Splunk TLS, etc.)
- **Approved build inputs** (signed/pinned wheels, validated drivers/toolkits, verified model artifacts)

### Practical guidance (RHEL)

- If your enclave requires FIPS, enable it at the OS level and ensure all TLS/SSH endpoints use FIPS-approved algorithms per local policy.
- Treat model artifacts as software supply chain inputs; move them via approved media and validate with checksums before use.

