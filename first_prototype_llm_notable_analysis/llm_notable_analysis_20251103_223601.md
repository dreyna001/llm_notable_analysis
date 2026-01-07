
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
- user=DOMAIN\admin
- logon_type=3
- ip_address=203.0.113.45
- computer=DC-01
- workstation_name=WORKSTATION-01
- process_name=C:\Windows\System32\lsass.exe

**Inferences (Hypotheses):**
- External IP 203.0.113.45 presumed to be attacker-controlled due to being non-corporate range; alert lacks geo/VPN metadata.
- Credentials assumed compromised because admin logon originated externally without obvious remote management channel evidence.
- Possible that VPN or RDP gateway was used; this context is missing from the alert.

### Containment Playbook

**Immediate Actions (within hours):**
- Expire/kill active sessions for DOMAIN\admin.
- Reset DOMAIN\admin credentials immediately.
- Block or geofence IP 203.0.113.45 at perimeter and VPN concentrators.
- Capture and preserve DC-01 security logs for forensics.

**Short-term Actions (24-48h):**
- Audit all domain admin accounts for recent external logons.
- Enable or enforce MFA on privileged accounts.
- Restrict DC-01 administrative access to trusted management networks.
- Review AD modifications post-alert for unauthorized changes.

**References (ATT&CK Mitigations):**
- M1032 Multi-factor Authentication
- M1026 Privileged Account Management
- M1030 Network Segmentation
- M1018 User Account Management

### Scored TTPs

#### High Confidence (≥0.80)

**T1078.002** - Valid Accounts: Domain Accounts: **0.800**
  - **Explanation:** Alert shows 'event_id=4624', 'logon_type=3', and 'user=DOMAIN\admin' with 'ip_address=203.0.113.45'. These data indicate a successful network logon to a domain controller using valid domain credentials. The external IP suggests access from outside the corporate boundary. Uncertainty: The alert lacks geo/VPN metadata confirming the IP is truly external or attacker-controlled, and absence of context about network exposure limits confidence slightly.
  - **Tactic Span:** This technique also commonly supports Persistence (TA0003) and Defense Evasion (TA0005) by allowing continued authenticated access or blending with normal administrative activity.
  - **Evidence Fields:** event_id=4624, logon_type=3, user=DOMAIN\admin, ip_address=203.0.113.45, computer=DC-01
  - **Immediate Actions:** Disable or lock the DOMAIN\admin account, force credential reset, block IP 203.0.113.45 at the perimeter firewall, and review all recent administrative logons on DC-01.
  - **Remediation:** Implement Multi-factor Authentication (M1032) for domain admin accounts, enforce Privileged Account Management (M1026), and apply Network Segmentation (M1030) restricting administrative access to trusted subnets only.
  - **MITRE URL:** https://attack.mitre.org/versions/v17/techniques/T1078/002/

### Attack Chain Analysis

**Likely Previous Step:** Credential Access (TA0006)

MITRE URL: https://attack.mitre.org/versions/v17/tactics/TA0006/

**Why:** Use of 'DOMAIN\admin' credentials from an external IP implies the attacker previously obtained or harvested valid credentials.

**Check:** Investigate any prior suspicious authentication failures (Event ID 4625) or credential dumping activity on admin workstations.

**Uncertainty:** The admin may have used a legitimate remote connection via VPN; without VPN logs this cannot be ruled out.

**Investigation Questions:**

- Q1: Were there prior failed logons for DOMAIN\admin from 203.0.113.45 or other non-corporate IPs?
- Q2: Was credential theft activity (e.g., LSASS memory access, mimikatz indicators) detected before this timestamp?
- Q3: Did any password changes or Kerberos ticket anomalies occur for DOMAIN\admin preceding the alert?

**Likely Next Step:** Lateral Movement (TA0008)

MITRE URL: https://attack.mitre.org/versions/v17/tactics/TA0008/

**Why:** Successful domain admin logon from an untrusted IP ('ip_address=203.0.113.45', 'computer=DC-01') suggests potential pivoting or administrative actions to spread laterally.

**Check:** Search for remote service creation (Event IDs 7045, 4697) or file copy/WMIC/PowerShell remoting events from DC-01 shortly after this logon.

**Uncertainty:** The alert does not show follow-on actions; could be a single unauthorized access without confirmed lateral movement.

**Investigation Questions:**

- Q1: Did DC-01 initiate outbound administrative connections to other hosts post logon?
- Q2: Were scheduled tasks, services, or shares created from DC-01 within the next few hours?
- Q3: Were there additional 4624 type 3 logons from DC-01 to other systems?

**Kill Chain Phase:** Initial Access

**Tactic Span Note:** Valid Accounts often appear in Initial Access, Persistence, and Defense Evasion. This alert is mapped to Initial Access because it evidences external use of legitimate credentials to gain entry into the environment.

### Splunk Enrichment Queries

**Phase:** previous
**Supports Tactic:** Credential Access
**Purpose:** Check for brute-force or failed logon attempts involving DOMAIN\admin to identify password guessing or credential harvesting prior to this event.
**Query:** index=PLACEHOLDER sourcetype=PLACEHOLDER user="DOMAIN\\admin" EventCode=4625 earliest=-24h@h latest=2024-03-20T10:00:00
  - **Confidence Boost Rule:** Multiple failed 4625 events from 203.0.113.45 before success increase confidence of credential compromise.
  - **Confidence Reduce Rule:** No failed attempts or related errors reduces likelihood of brute-force credential access.

**Phase:** previous
**Supports Tactic:** Credential Access
**Purpose:** Check for LSASS access or credential dumping events on WORKSTATION-01 prior to the alert.
**Query:** index=PLACEHOLDER sourcetype=PLACEHOLDER host="WORKSTATION-01" (EventCode=10 OR EventCode=4673) earliest=-24h@h latest=2024-03-20T10:00:00
  - **Confidence Boost Rule:** Alerts showing LSASS memory access or mimikatz artifacts raise confidence of credential theft.
  - **Confidence Reduce Rule:** No suspicious memory access events reduce likelihood of local credential dumping.

**Phase:** next
**Supports Tactic:** Lateral Movement
**Purpose:** Look for remote service creation or scheduled task creation from DC-01 following this logon.
**Query:** index=PLACEHOLDER sourcetype=PLACEHOLDER host="DC-01" (EventCode=4697 OR EventCode=7045 OR EventCode=106 OR EventCode=4688) earliest=2024-03-20T10:00:00 latest=+24h@h
  - **Confidence Boost Rule:** Service or task creation events referencing NETWORK logons from DOMAIN\admin confirm post-access activity.
  - **Confidence Reduce Rule:** Absence of subsequent lateral movement artifacts within 24h lowers likelihood of immediate exploitation.

**Phase:** next
**Supports Tactic:** Lateral Movement
**Purpose:** Check for Kerberos ticket-granting events or unusual ticket use by DOMAIN\admin after alert time.
**Query:** index=PLACEHOLDER sourcetype=PLACEHOLDER user="DOMAIN\\admin" (EventCode=4769 OR EventCode=4776) earliest=2024-03-20T10:00:00 latest=+24h@h
  - **Confidence Boost Rule:** New Kerberos tickets issued to DOMAIN\admin from unusual hosts indicate continued adversary activity.
  - **Confidence Reduce Rule:** Stable ticket activity consistent with baseline reduces confidence of further compromise.

