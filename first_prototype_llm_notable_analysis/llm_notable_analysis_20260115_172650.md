
## Test Case: WinSec_4625_password_spray_1

### Alert Text

[SUMMARY]
Synthetic notable: WinSec_4625_password_spray_1

[RISK INDEX]
Risk Score: N/A
Source Product: WINEVENT
Threat Category: Credential Access

[RAW EVENT]
timestamp=2024-03-20T10:00:00Z event_id=4625 source=Microsoft-Windows-Security-Auditing FailureReason=Unknown user name or bad password. LogonType=3 TargetUserName=admin TargetDomainName=DOMAIN WorkstationName=WORKSTATION-01 IpAddress=198.51.100.54 computer=WORKSTATION-01 message=An account failed to log on.

### Indicators of Compromise (IOCs)

**IP Addresses:** 198.51.100.54
**Domains:** DOMAIN
**User Accounts:** admin
**Hostnames:** WORKSTATION-01
**Event IDs:** 4625

### Correlation Keys

**Primary Indicators:** IpAddress=198.51.100.54, TargetUserName=admin
**Search Terms:** event_id=4625, FailureReason=Unknown user name or bad password, LogonType=3
**Suggested Time Window:** -24h to +24h around 2024-03-20T10:00:00Z

### Evidence vs Inference

**Evidence (Facts):**
- event_id=4625
- FailureReason=Unknown user name or bad password.
- LogonType=3
- TargetUserName=admin
- IpAddress=198.51.100.54
- WorkstationName=WORKSTATION-01

**Inferences (Hypotheses):**
- Repeated failures from a single IP may indicate password spraying; needs confirmation by volume.
- Source 198.51.100.54 may be external; ownership and geolocation unknown.
- TargetUserName=admin suggests attempt against privileged account.

### Containment Playbook

**Immediate Actions (within hours):**
- Correlate IP 198.51.100.54 with other login failures in last 24h; block if confirmed malicious.
- Force reset of 'admin' account credentials if compromise suspected.
- Enable temporary lockout policy for account failure thresholds.

**Short-term Actions (24-48h):**
- Review and tighten remote logon policies (network logon type 3).
- Enable MFA for administrative accounts.
- Apply adaptive authentication and conditional access controls.

**References (ATT&CK Mitigations):**
- M1027
- M1032
- M1030
- M1047

### Scored TTPs

#### High Confidence (≥0.80)

**T1110.003** - Brute Force: Password Spraying: **0.850**
  - **Explanation:** The alert shows multiple 'event_id=4625' failures with 'FailureReason=Unknown user name or bad password' and 'LogonType=3' indicating repeated network logon attempts using the same password across accounts or repeated attempts against a specific account (TargetUserName=admin) from IpAddress=198.51.100.54. This matches password spraying behavior rather than single credential misuse. Uncertainty: the single event does not confirm multiple hosts/users; needs aggregation of similar events to confirm spray pattern.
  - **Tactic Span:** This technique primarily supports the Credential Access tactic but may also relate to Initial Access or Defense Evasion when used to validate harvested credentials.
  - **Evidence Fields:** event_id=4625, FailureReason=Unknown user name or bad password., LogonType=3, TargetUserName=admin, IpAddress=198.51.100.54
  - **Immediate Actions:** Check for repeated 4625 events from the same IP addressing multiple accounts; block or rate-limit source IP 198.51.100.54 if verified malicious.
  - **Remediation:** Enforce account lockout policies (M1027), require MFA on remote logons (M1032), monitor failed login volume (M1047), deploy network rate limiting (M1030).
  - **MITRE URL:** https://attack.mitre.org/techniques/T1110/003/

### Attack Chain Analysis

**Likely Previous Step:** Reconnaissance (TA0043)

MITRE URL: https://attack.mitre.org/tactics/TA0043/

**Why:** Adversaries often perform user enumeration or credential collection before password spraying; the host may have been identified via prior reconnaissance. Evidence: event_id=4625, TargetUserName=admin.

**Check:** Look for event_id=4648, LDAP enumeration logs, or web directory access patterns.

**Uncertainty:** Could have been an automated spray targeting generic accounts without prior recon.

**Investigation Questions:**

- Q1: Are there enumeration events (LDAP queries or SMB session setup attempts) from the same IP before the spray?
- Q2: Was the IP 198.51.100.54 previously seen interacting with other hosts?
- Q3: Does this IP correlate with known threat reconnaissance activity?

**Likely Next Step:** Credential Access (TA0006)

MITRE URL: https://attack.mitre.org/tactics/TA0006/

**Why:** If successful logins occur, adversaries may escalate or reuse gained credentials. Evidence: repeated failed logons show credential probing intent.

**Check:** Query for event_id=4624 success events from the same IP after this time in +24h window.

**Uncertainty:** If no subsequent success events occur, this might be purely scanning or misconfiguration.

**Investigation Questions:**

- Q1: Were any successful logons (4624) from the same IP observed shortly after?
- Q2: Were credential dumpers or suspicious processes spawned on target?
- Q3: Were abnormal authentications from this IP seen across other systems?

**Kill Chain Phase:** Credential Access

**Tactic Span Note:** Password spraying ties primarily to Credential Access but can also serve Initial Access in opportunistic credential-use campaigns.

### Splunk Enrichment Queries

**Phase:** previous
**Supports Tactic:** Reconnaissance
**Purpose:** Identify possible username enumeration or prior failed authentications from same IP.
**Query:** index=PLACEHOLDER sourcetype=PLACEHOLDER event_id=4625 IpAddress=198.51.100.54 earliest=-24h@h latest=2024-03-20T10:00:00Z | stats count by TargetUserName
  - **Confidence Boost Rule:** Multiple distinct TargetUserName values increase likelihood of password spraying.
  - **Confidence Reduce Rule:** Only one account targeted suggests possible misconfiguration instead of spraying.

**Phase:** next
**Supports Tactic:** Credential Access
**Purpose:** Search for subsequent successful logons indicating partial credential compromise.
**Query:** index=PLACEHOLDER sourcetype=PLACEHOLDER event_id=4624 IpAddress=198.51.100.54 earliest=2024-03-20T10:00:00Z latest=+24h@h | stats count by TargetUserName
  - **Confidence Boost Rule:** Presence of 4624 events for same IP after failures.
  - **Confidence Reduce Rule:** No 4624 or continued failures indicate noise.

**Phase:** next
**Supports Tactic:** Credential Access
**Purpose:** Check if source IP also targeted other endpoints indicating horizontal spraying.
**Query:** index=PLACEHOLDER event_id=4625 IpAddress=198.51.100.54 earliest=-24h latest=+24h | stats dc(WorkstationName) as targets
  - **Confidence Boost Rule:** High number of distinct WorkstationName indicates wider spray.
  - **Confidence Reduce Rule:** Only one target indicates isolated issue.

### Tactic Framing

**Primary Tactic:** Credential Access (TA0006)
  - **Justification:** The failed logons with 'FailureReason=Unknown user name or bad password' clearly reflect attempts to obtain valid credentials.

**Secondary Tactics:**
- Initial Access (TA0001): If the attacker intended to gain entry via RDP or SMB using valid credentials, this could represent an initial access attempt.
- Discovery (TA0007): Bulk scanning of usernames prior to brute-force could represent discovery of valid account names.

**Disambiguation Checklist:**
- Was the IP internal or external (network boundary context)?
- Did multiple usernames experience failed logons from same IP?
- Were there subsequent successful (4624) logons from that IP?
- Is admin account used by automated tooling or human actor?
- What authentication protocol and service (RDP/SMB) was used?

### Benign Explanations (Legitimate Activity Hypotheses)

**Hypothesis 1:** User mistyped password during remote connection attempt.
  - **Expect if true:** Low number of failures, Followed by successful logon from same IP shortly after
  - **Argues against:** Dozens of failures and varying targets from same IP
  - **Best validation:** Windows Security Event Log search for repeated 4625 followed by 4624 for same user

**Hypothesis 2:** Service misconfiguration causing repeated authentication retries.
  - **Expect if true:** Consistent logon attempts from same service account, Application log errors at same time
  - **Argues against:** Different usernames or repeated IPs across hosts
  - **Best validation:** Application logs on WORKSTATION-01

**Hypothesis 3:** Penetration testing or vulnerability scanning in progress.
  - **Expect if true:** IP in known internal scanner range, Official change or test ticket reference
  - **Argues against:** External IP not in authorized scanner list
  - **Best validation:** Firewall/VPN logs mapping IP 198.51.100.54 to internal asset

### Competing Hypotheses & Pivots

**Hypothesis 1 (Adversary):** External attacker conducting password spraying against admin account.
  - **Evidence support:** event_id=4625, TargetUserName=admin, IpAddress=198.51.100.54, FailureReason=Unknown user name or bad password
  - **Evidence gaps:** No confirmation if IP external, No evidence of other accounts targeted, No successful logons confirmed
  - **Best pivots:**
    - Firewall logs: ['src_ip', 'dest_host']
    - Windows Security logs: ['IpAddress', 'TargetUserName']

**Hypothesis 2 (Adversary):** Compromised internal system performing brute-force against local admin account.
  - **Evidence support:** event_id=4625, LogonType=3
  - **Evidence gaps:** Cannot confirm internal IP range without network context
  - **Best pivots:**
    - EDR telemetry: ['process_name', 'network_connection_ip']
    - NetFlow logs: ['src_ip', 'dst_ip']

**Hypothesis 3 (Benign):** User or admin mistyped password or used wrong credentials via remote desktop session.
  - **Evidence support:** FailureReason=Unknown user name or bad password, LogonType=3
  - **Evidence gaps:** Need to know if subsequent success occurred, No knowledge if this was user activity window
  - **Best pivots:**
    - Windows Security logs: ['event_id', 'IpAddress', 'TargetUserName']
    - VPN logs: ['client_ip', 'user']

### Context Enrichment & Baseline

**Enrichment Steps:**
- IpAddress (geo): unknown
- IpAddress (ownership): unknown
- IpAddress (internal_vs_external): unknown
- IpAddress (known_egress): unknown
- IpAddress (reputation): not available

**Baseline Queries:**
- **Purpose:** Determine how often 198.51.100.54 authenticates to any domain host.
  - **Query:** index=PLACEHOLDER event_id=4625 OR event_id=4624 IpAddress=198.51.100.54 earliest=-7d@d latest=now | stats count by TargetUserName
- **Purpose:** Compare failed logon volume against baseline for admin account.
  - **Query:** index=PLACEHOLDER event_id=4625 TargetUserName=admin earliest=-30d latest=now | timechart count span=1d
- **Purpose:** Identify how many distinct source IPs usually attempt admin logons.
  - **Query:** index=PLACEHOLDER event_id=4625 TargetUserName=admin earliest=-7d latest=now | stats dc(IpAddress)

**Limitations:** No network context to confirm if 198.51.100.54 is internal or external; single event cannot prove spray pattern without broader correlation.

