# System Security Plan (SSP) — Template (On-Prem)

**Document status:** Draft  
**System name:** `[SYSTEM NAME]`  
**System identifier:** `[SYSTEM ID]`  
**System owner:** `[NAME / ORG]`  
**Information System Security Officer (ISSO/ISSM):** `[NAME / ORG]`  
**Version:** `v0.1`  
**Date:** `[YYYY-MM-DD]`

## 1. Purpose and scope

Describe the purpose of the SSP and the authorization boundary it covers.

- **Authorization type:** `[Initial ATO / Re-ATO / other]`
- **Boundary summary:** `[TBD]`
- **Intended operating environment:** `[on-prem enclave, air-gapped, connected]`

## 2. System description

### 2.1 Mission / business function

`[TBD: what the system does for the mission]`

### 2.2 System components (logical)

At minimum, include:

- Analyzer service (systemd: `notable-analyzer` / optional `notable-analyzer-freeform`)
- Local LLM inference service (systemd: `vllm`)
- Ingest interface (SFTP chroot user + file drop directory)
- Output/reporting (filesystem reports; optional Splunk REST writeback)
- Retention/archiving function

### 2.3 Deployment topology (physical)

- **Host count:** `[1]` *(or describe scaling, if applicable)*
- **OS:** `[RHEL 8/9 or compatible]`
- **GPU requirements:** `[TBD]`
- **Storage locations:** `/opt/notable-analyzer`, `/opt/vllm`, `/opt/models`, `/var/notables`, `/var/sftp/soar`

## 3. System boundary

### 3.1 In-boundary elements

List what is inside the authorization boundary (hosts, services, storage, configs).

### 3.2 Out-of-boundary / external dependencies

Examples (edit for your enclave):

- SOAR platform delivering files via SFTP
- Splunk (optional) receiving writeback via REST
- Enterprise services (IdP/PAM, SIEM forwarding, vuln scanning, patching) — if used

### 3.3 Interconnections

| Connection | Source | Destination | Protocol/Port | Direction | Data | AuthN/AuthZ | Encryption | Notes |
|---|---|---|---|---|---|---|---|---|
| SFTP ingest | `[SOAR HOST]` | `[Analyzer Host]` | `SSH/22` | inbound | notable files | SSH key | SSH | chrooted SFTP user |
| Local LLM | localhost | localhost | `HTTP/8000` | local | prompt+response | `[none/token]` | none (loopback) | vLLM bound to 127.0.0.1 |
| Splunk writeback (optional) | `[Analyzer Host]` | `[Splunk]` | `HTTPS/8089` | outbound | markdown comment/status | token | TLS | CA bundle optional |

## 4. Information types and data handling

- **Primary data types processed:** `[TBD]`
- **PII/PHI/classified:** `[Yes/No/Unknown]` *(state assumptions; define handling requirements)*
- **Data at rest:** `[filesystem paths + protection mechanisms]`
- **Data in transit:** `[SFTP/SSH, TLS to Splunk (if enabled), local loopback to vLLM]`
- **Retention policy:** `[reference retention settings and operational policy]`

## 5. Roles, responsibilities, and access

### 5.1 Roles

| Role | Responsibilities | Privileges | Notes |
|---|---|---|---|
| System Owner | `[TBD]` | `[TBD]` | |
| ISSO/ISSM | `[TBD]` | `[TBD]` | |
| System Administrator | `[TBD]` | `[TBD]` | |
| Operator/Analyst | `[TBD]` | `[TBD]` | |
| Assessor | `[TBD]` | `[TBD]` | |

### 5.2 Service accounts

Document service identities used by the system and what they can access:

- `notable-analyzer` (runs analyzer)
- `vllm` (runs inference)
- `soar-uploader` (SFTP-only ingest)

## 6. Architecture and data flows

### 6.1 Architecture diagram

- **Diagram location:** `[path/link]`
- **Narrative:** `[TBD]`

### 6.2 Data flow diagrams

At minimum, document:

1. SOAR → SFTP ingest → incoming directory
2. Analyzer → local vLLM prompt/response
3. Analyzer → report writing / optional Splunk writeback
4. Retention flow (processed/quarantine/reports → archive → delete)

Include:

- trust boundaries
- encryption points
- authentication points
- audit/logging points

## 7. Security-relevant configuration (high level)

- **Configuration source:** `/etc/notable-analyzer/config.env`
- **Key settings:** `[INGEST_MODE, directories, LLM_API_URL, SPLUNK_*]`
- **File permissions/ownership expectations:** `[TBD; reference hardening doc]`
- **Systemd unit hardening:** `[NoNewPrivileges, ProtectSystem, ReadWritePaths]`
- **Model artifact controls:** `[checksum verification process; trust_remote_code policy]`

## 8. Control implementation summary (NIST 800-53 mapping)

> This section is the heart of the SSP: for each required control, describe how it is implemented **in this environment**, and point to evidence.

### 8.1 Control baseline

- **Framework:** `[NIST 800-53 Rev 5]`
- **Baseline:** `[Low/Moderate/High]`
- **Tailoring/overlays:** `[TBD]`

### 8.2 Control implementation statements (template)

Repeat the block below for each applicable control.

#### Control `[AC-2]` — `[Account Management]`

- **Control applicability:** `[Applicable/Not Applicable]`
- **Implementation summary:** `[TBD: how the control is met]`
- **Inheritance:** `[System / Shared / Inherited]`
- **Responsible party:** `[TBD]`
- **How it is operated:** `[procedures/runbooks]`
- **Evidence (examples):**
  - `[system configuration, screenshots, command outputs, tickets, logs, policies]`
- **Continuous monitoring:** `[how you verify it stays in place]`

*(Repeat for all controls in the selected baseline.)*

## 9. Continuous monitoring (ConMon)

- **Vulnerability scanning cadence:** `[TBD]`
- **Patch management cadence:** `[TBD]`
- **Log review / alerting:** `[TBD]`
- **Config baseline checks:** `[TBD]`
- **Model update governance:** `[TBD: offline media, checksums, approvals]`

## 10. Appendices

- A. Asset inventory / component inventory
- B. Ports, protocols, and services
- C. Evidence index (artifact IDs + hashes/locations)
- D. Interconnection agreements (if applicable)
- E. Glossary / acronyms

