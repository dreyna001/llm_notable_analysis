# Security Assessment Plan (SAP) — Template (Draft)

**Document status:** Draft template (typically finalized by assessor/3PAO)  
**System name:** `[SYSTEM NAME]`  
**System owner:** `[NAME / ORG]`  
**Assessment organization:** `[ORG / 3PAO]`  
**Version:** `v0.1`  
**Date:** `[YYYY-MM-DD]`

## 1. Purpose

Describe the purpose of this assessment and the authorization decision it supports (e.g., initial ATO, re-authorization, change-driven assessment).

## 2. System description (summary)

- **System boundary (high level):** `[TBD]`
- **Deployment model:** on‑prem single host (RHEL) + optional connections to SOAR/Splunk
- **Core components:** analyzer service, vLLM inference service, storage paths, SFTP ingest
- **Data types processed:** `[TBD: e.g., security alert metadata, user IDs, IPs; include PII marking if applicable]`

## 3. Categorization / impact level

- **FIPS 199 security category:** `[LOW / MODERATE / HIGH]`
- **Impact level / enclave classification (if applicable):** `[IL2/IL4/IL5/IL6/etc.]`
- **Rationale:** `[TBD]`

## 4. Applicable control baseline and tailoring

- **Control framework:** `[NIST 800-53 Rev 5 / org standard]`
- **Baseline:** `[Low/Moderate/High]`
- **Overlays / tailoring:** `[TBD]`
- **Excluded controls and rationale:** `[TBD]`

## 5. Assessment scope

### 5.1 In-scope boundary elements

- Hosts / nodes: `[TBD]`
- Services: `[notable-analyzer, vllm, sshd (SFTP chroot)]`
- Interfaces: `[SFTP from SOAR host, optional HTTPS to Splunk mgmt port]`
- Data stores: `[file system paths for incoming/processed/quarantine/reports/archive]`

### 5.2 Out-of-scope elements

- `[ORG PROVIDED: enclave perimeter controls, enterprise SIEM, IdP/PAM, endpoint management]`
- `[TBD]`

### 5.3 Assumptions and dependencies

- `[e.g., customer provides hardened OS baseline, patching, vulnerability scanning, log forwarding]`

## 6. Assessment approach / methodology

### 6.1 Standards and references

- `[NIST 800-53A assessment procedures]`
- `[Org-specific assessment methodology]`

### 6.2 Assessment methods

For each control/control family, indicate method(s):

- **Examine:** documentation/configs/logs/evidence
- **Interview:** system owner, admins, operators
- **Test:** technical validation (commands, scripts, scans, functional tests)

### 6.3 Sampling

- **Accounts sampled:** `[TBD]`
- **Logs sampled (time windows):** `[TBD]`
- **Configuration items sampled:** `[TBD]`
- **Ports/services sampled:** `[TBD]`

## 7. Rules of engagement (ROE)

- **Authorized testing windows:** `[TBD]`
- **Approved tools/scanners:** `[TBD]`
- **Operational constraints:** `[e.g., no load tests during business hours]`
- **Data handling restrictions:** `[PII/PHI/classified handling, media rules]`
- **Incident handling during testing:** `[TBD]`

## 8. Assessment schedule

- **Kickoff:** `[date/time]`
- **Evidence collection window:** `[date/time range]`
- **Technical testing window:** `[date/time range]`
- **Draft SAR delivery:** `[date]`
- **Final SAR delivery:** `[date]`

## 9. Evidence required (requested artifacts)

List evidence the assessor will request, with pointers if already available:

- **SSP**: `[path/link]`
- **Architecture/data flow diagrams**: `[path/link]`
- **Configuration baseline / hardening guide**: `[path/link]`
- **Access control procedures**: `[path/link]`
- **Vulnerability management evidence**: `[path/link]`
- **Logging/monitoring evidence**: `[path/link]`
- **IR plan/playbooks**: `[path/link]`
- **Backup/restore evidence**: `[path/link]`
- **Dependency inventory/SBOM**: `[path/link]`
- **Inherited controls documentation**: `[path/link]`

## 10. Deliverables

- **SAP (this document)**
- **SAR** (Security Assessment Report)
- **POA&M** (findings tracker)
- **Test evidence package** (scan outputs, screenshots, logs, checklists)

## 11. Roles and responsibilities

- **System Owner:** `[name]`
- **ISSO/ISSM:** `[name]`
- **Assessors:** `[names]`
- **Operators/Admins:** `[names]`
- **AO Representative (if applicable):** `[name]`

## 12. Approval

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Assessment Lead | `[TBD]` | `[TBD]` | `[TBD]` |
| System Owner | `[TBD]` | `[TBD]` | `[TBD]` |
| ISSO/ISSM | `[TBD]` | `[TBD]` | `[TBD]` |

