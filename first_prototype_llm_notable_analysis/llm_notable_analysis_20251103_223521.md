
## Test Case: Windows Event - Successful Logon from Suspicious IP

### Alert Text

[SUMMARY]
Event 4624: An account was successfully logged on from suspicious external IP

[RISK INDEX]
Risk Score: 4
Source Product: WINEVENT
Threat Category: Initial Access

[RAW EVENT]
timestamp=2024-03-20T10:00:00 event_id=4624 source=Microsoft-Windows-Security-Auditing level=Information logon_type=3 user=DOMAIN\admin workstation_name=WORKSTATION-01 ip_address=203.0.113.45 process_name=C:\Windows\System32\lsass.exe computer=DC-01 message=An account was successfully logged on

### Indicators of Compromise (IOCs)

**IP Addresses:** 203.0.113.45
**User Accounts:** DOMAIN\admin
**Hostnames:** DC-01, WORKSTATION-01
**Processes:** lsass.exe
**File Paths:** C:\Windows\System32\lsass.exe
**Event IDs:** 4624

### Correlation Keys

**Primary Indicators:** ip_address=203.0.113.45, user=DOMAIN\admin
**Search Terms:** 203.0.113.45, DOMAIN\admin, DC-01
**Suggested Time Window:** -24h to +24h

### Evidence vs Inference

**Evidence (Facts):**
- timestamp=2024-03-20T10:00:00
- event_id=4624
- logon_type=3
- user=DOMAIN\admin
- workstation_name=WORKSTATION-01
- ip_address=203.0.113.45
- process_name=C:\Windows\System32\lsass.exe
- computer=DC-01

**Inferences (Hypotheses):**
- IP 203.0.113.45 treated as external due to reserved test-net indicating off-network origin; lacks VPN/geo context.
- Credentials assumed compromised due to suspicious source and admin privileges.
- The account logon implies successful use of valid credentials but does not show theft vector or follow-on activity.

### Containment Playbook

**Immediate Actions (within hours):**
- Expire or kill all active sessions for DOMAIN\admin.
- Force password reset and reissue credentials for DOMAIN\admin.
- Block IP 203.0.113.45 at border and proxy layers.
- Isolate DC-01 from further remote inbound connections.

**Short-term Actions (24-48h):**
- Restrict administrative logons to approved management segments.
- Review recent AD object and group membership changes for privilege abuse.
- Preserve and collect security event logs around the time of compromise.
- Deploy MFA enforcement for privileged accounts enterprise-wide.

**References (ATT&CK Mitigations):**
- M1032 Multi-factor Authentication
- M1026 Privileged Account Management
- M1030 Network Segmentation
- M1018 User Account Management

### Scored TTPs

#### High Confidence (≥0.80)

**T1078.002** - Valid Accounts: Domain Accounts: **0.850**
  - **Explanation:** The alert shows 'event_id=4624' with 'user=DOMAIN\admin' successfully logged on from 'ip_address=203.0.113.45'. This indicates legitimate domain credentials were used for a network-based login (logon_type=3) from an external source. Uncertainty: No evidence on how credentials were obtained or whether the source IP is definitively external; geo/VPN data is missing.
  - **Tactic Span:** This technique also commonly supports Persistence (TA0003) and Privilege Escalation (TA0004) when adversaries maintain or elevate access using stolen credentials.
  - **Evidence Fields:** event_id=4624, logon_type=3, user=DOMAIN\admin, ip_address=203.0.113.45
  - **Immediate Actions:** Disable or temporarily lock 'DOMAIN\admin' account, force password reset, block external IP 203.0.113.45 at firewall, and terminate all active sessions associated with the account.
  - **Remediation:** Enforce MFA for domain accounts (M1032), limit remote logon privileges for admin users (M1026), and implement network segmentation to restrict DC exposure (M1030).
  - **MITRE URL:** https://attack.mitre.org/versions/v17/techniques/T1078/002/

### Attack Chain Analysis

**Likely Previous Step:** Credential Access (TA0006)

MITRE URL: https://attack.mitre.org/versions/v17/tactics/TA0006/

**Why:** The use of a valid domain account suggests an earlier credential theft operation before the remote logon ('user=DOMAIN\admin').

**Check:** Look for signs of credential dumping or password harvesting (Event IDs 4625, 4648, 4672, 4688 on admin endpoints).

**Uncertainty:** Credentials may have been acquired via phishing, keylogging, or password reuse; alert lacks source vector detail.

**Investigation Questions:**

- Q1: Were there prior failed logons (Event ID 4625) for DOMAIN\admin from any source before this event?
- Q2: Was any credential dumping tool or LSASS handle access attempt observed on WORKSTATION-01 or DC-01?
- Q3: Were cached credentials or password hashes exposed on other systems tied to DOMAIN\admin?

**Likely Next Step:** Lateral Movement (TA0008)

MITRE URL: https://attack.mitre.org/versions/v17/tactics/TA0008/

**Why:** Since the logon type is 3 (network), adversaries could pivot within the environment using the same domain admin credentials.

**Check:** Review event logs (4698, 5140, 7045) for remote service creation, share access, and scheduled tasks from IP 203.0.113.45 post-logon.

**Uncertainty:** It’s unclear if the login was used interactively for lateral movement or reconnaissance due to missing command/process details.

**Investigation Questions:**

- Q1: Did subsequent remote execution or SMB connections originate from DC-01 to other hosts?
- Q2: Were new scheduled tasks or services created shortly after this login?
- Q3: Did the attacker enumerate AD data using the compromised account?

**Kill Chain Phase:** Initial Access

**Tactic Span Note:** Valid Accounts (T1078.002) fits Initial Access because it reflects use of known credentials to enter the environment; it also spans Persistence and Privilege Escalation where access reuse or token persistence occurs.

### Splunk Enrichment Queries

**Phase:** previous
**Supports Tactic:** Credential Access
**Purpose:** Identify possible credential theft or password attacks involving DOMAIN\admin in the 24h before alert time.
**Query:** index=PLACEHOLDER sourcetype=PLACEHOLDER user="DOMAIN\\admin" (EventCode=4625 OR EventCode=4648 OR EventCode=4672 OR EventCode=4688) earliest=-24h@h latest=2024-03-20T10:00:00
  - **Confidence Boost Rule:** Multiple failed logons or credential dumping processes linked to DOMAIN\admin increase confidence in prior credential access.
  - **Confidence Reduce Rule:** Absence of failed logons or credential dumping indicators reduces likelihood of local theft, suggesting reuse elsewhere.

**Phase:** previous
**Supports Tactic:** Credential Access
**Purpose:** Check for LSASS handle access or dumping attempts on WORKSTATION-01.
**Query:** index=PLACEHOLDER host="WORKSTATION-01" (EventCode=4688 OR EventCode=4656) (process_name="*lsass*" OR target_process_name="lsass.exe") earliest=-24h@h latest=2024-03-20T10:00:00
  - **Confidence Boost Rule:** LSASS access or memory dump events support credential theft hypothesis.
  - **Confidence Reduce Rule:** No LSASS access events suggest alternative compromise methods.

**Phase:** next
**Supports Tactic:** Lateral Movement
**Purpose:** Detect follow-on remote execution or share access from DC-01 using DOMAIN\admin.
**Query:** index=PLACEHOLDER host="DC-01" (EventCode=4698 OR EventCode=5140 OR EventCode=7045) user="DOMAIN\\admin" earliest=2024-03-20T10:00:00 latest=+24h@h
  - **Confidence Boost Rule:** New remote services, tasks, or SMB share access post-login confirms lateral movement attempt.
  - **Confidence Reduce Rule:** No remote activity indicates possible reconnaissance-only phase or early detection containment.

**Phase:** next
**Supports Tactic:** Lateral Movement
**Purpose:** Capture Kerberos ticket anomalies potentially associated with DOMAIN\admin after compromise.
**Query:** index=PLACEHOLDER host="DC-01" (EventCode=4769 OR EventCode=4776) user="DOMAIN\\admin" earliest=2024-03-20T10:00:00 latest=+24h@h
  - **Confidence Boost Rule:** Unusual ticket issuance or failed pre-auth events indicate credential misuse across systems.
  - **Confidence Reduce Rule:** Stable Kerberos event baseline suggests no propagation in that time window.

