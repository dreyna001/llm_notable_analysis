"""Stored analyzer-shaped preview analysis for cases 1-5.

Content follows the analyze_notable prompt contract (ANALYST DOCTRINE, EVIDENCE-GATE,
6 competing hypotheses, schema keys) and is grounded in each alert fixture.
"""

from __future__ import annotations

from typing import Any


def _pivot(log_source: str, key_fields: list[str]) -> dict[str, Any]:
    return {"log_source": log_source, "key_fields": key_fields}


def _hypothesis(
    *,
    hypothesis_type: str,
    hypothesis: str,
    evidence_support: list[str],
    evidence_gaps: list[str],
    best_pivots: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "hypothesis_type": hypothesis_type,
        "hypothesis": hypothesis,
        "evidence_support": evidence_support,
        "evidence_gaps": evidence_gaps,
        "best_pivots": best_pivots,
    }


def _six(
    benign: list[tuple[str, list[str], list[str], list[dict[str, Any]]]],
    adversary: list[tuple[str, list[str], list[str], list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for title, support, gaps, pivots in benign:
        items.append(
            _hypothesis(
                hypothesis_type="benign",
                hypothesis=title,
                evidence_support=support,
                evidence_gaps=gaps,
                best_pivots=pivots,
            )
        )
    for title, support, gaps, pivots in adversary:
        items.append(
            _hypothesis(
                hypothesis_type="adversary",
                hypothesis=title,
                evidence_support=support,
                evidence_gaps=gaps,
                best_pivots=pivots,
            )
        )
    return items


def _ioc(**fields: list[str]) -> dict[str, list[str]]:
    base: dict[str, list[str]] = {
        "ip_addresses": [],
        "domains": [],
        "user_accounts": [],
        "hostnames": [],
        "process_names": [],
        "file_paths": [],
        "file_hashes": [],
        "event_ids": [],
        "urls": [],
    }
    for key, values in fields.items():
        if key in base and values:
            base[key] = values
    return base


def analysis_case_1_beaconing(alert: dict[str, Any]) -> dict[str, Any]:
    return {
        "alert_reconciliation": {
            "verdict": "likely_malicious",
            "confidence": "0.88",
            "one_sentence_summary": (
                "Workstation laptop-22 sent 1,427 near-regular HTTPS POST beacons to a "
                "11-day-old domain with narrow 768-to-896-byte payloads, consistent with C2 "
                "keepalive rather than a known updater."
            ),
            "decision_drivers": [
                "beacon_interval_seconds=60 with beacon_count_24h=1427",
                "domain_age_days=11 for dest_domain=update-service-cloud.net",
                "median_payload_bytes=824 with a 768-to-896-byte range with uri_path=/api/v1/session/a8f2c1",
                "proxy_action=allowed by Zscaler standard user policy",
            ],
            "recommended_actions": [
                "Block dest_domain=update-service-cloud.net at DNS and proxy.",
                "Isolate src_host=laptop-22.corp.local and collect EDR triage package.",
            ],
        },
        "competing_hypotheses": _six(
            benign=[
                (
                    "Sanctioned endpoint updater using a newly rotated CDN hostname.",
                    ["dest_port=443", "http_method=POST", "user_agent mentions UpdateAgent"],
                    ["No inventory match for UpdateAgent on laptop-22", "domain_age_days=11"],
                    [_pivot("Software inventory", ["host", "process"]), _pivot("Proxy logs", ["dest_domain", "uri_path"])],
                ),
                (
                    "Monitoring agent health checks misclassified as beaconing.",
                    ["Fixed beacon_interval_seconds=60", "Narrow payload range of 768-to-896 bytes"],
                    ["Agent name not in alert", "No CMDB monitoring tag on host"],
                    [_pivot("CMDB", ["host", "monitoring_role"]), _pivot("EDR", ["host", "process"])],
                ),
                (
                    "User-initiated cloud sync with periodic session refresh.",
                    ["src_user=corp\\mrossi present", "HTTPS to external domain"],
                    ["No sync product identified", "URI path entropy not explained"],
                    [_pivot("Proxy logs", ["user", "dest_domain"]), _pivot("Cloud app logs", ["user"])],
                ),
            ],
            adversary=[
                (
                    "HTTP C2 channel using periodic POST keepalive to young domain.",
                    [
                        "beacon_interval_seconds=60",
                        "beacon_count_24h=1427",
                        "dest_domain=update-service-cloud.net",
                        "domain_age_days=11",
                    ],
                    ["Process reputation not independently confirmed", "TLS certificate and JA3 require independent reputation validation"],
                    [_pivot("Proxy logs", ["src_host", "dest_domain", "uri_path"]), _pivot("EDR", ["host", "process"])],
                ),
                (
                    "Post-phishing implant on laptop-22 calling out for tasking.",
                    ["src_host=laptop-22.corp.local", "Regular external POST cadence"],
                    ["Initial access vector not in alert", "Persistence mechanism unknown"],
                    [_pivot("EDR", ["host", "parent_process"]), _pivot("Email gateway", ["user"])],
                ),
                (
                    "Low-and-slow exfil staging over repeated small HTTPS posts.",
                    ["payload_size_min=768 and payload_size_max=896", "High event count in 24h"],
                    ["No file access telemetry in alert", "Exfil volume threshold not exceeded"],
                    [_pivot("Proxy/DLP", ["host", "bytes_out"]), _pivot("EDR", ["host", "file_path"])],
                ),
            ],
        ),
        "evidence_vs_inference": {
            "evidence": [
                "src_host=laptop-22.corp.local",
                "src_user=corp\\mrossi",
                "dest_domain=update-service-cloud.net",
                "dest_ip=203.0.113.77",
                "beacon_interval_seconds=60",
                "beacon_count_24h=1427",
                "median_payload_bytes=824",
                "domain_age_days=11",
            ],
            "inferences": [
                "Near-regular cadence plus young domain is more consistent with C2 than bulk exfil",
                "Process responsible for traffic is unknown from this notable alone",
            ],
        },
        "ioc_extraction": _ioc(
            domains=[str(alert.get("dest_domain", ""))],
            ip_addresses=[str(alert.get("dest_ip", "")), str(alert.get("src_ip", ""))],
            user_accounts=[str(alert.get("src_user", ""))],
            hostnames=[str(alert.get("src_host", ""))],
            urls=[f"https://{alert.get('dest_domain', '')}{alert.get('uri_path', '')}"],
        ),
        "ttp_analysis": [
            {
                "ttp_id": "T1071.001",
                "ttp_name": "Application Layer Protocol: Web Protocols",
                "confidence_score": "0.90",
                "explanation": "Periodic HTTPS POST beacons to external domain. Uncertainty: payload contents not inspected.",
                "evidence_fields": ["dest_domain", "http_method", "beacon_interval_seconds"],
            },
            {
                "ttp_id": "T1568.002",
                "ttp_name": "Dynamic Resolution: Domain Generation Algorithms",
                "confidence_score": "0.35",
                "explanation": "Single young domain only; DGA not established. Uncertainty: domain_age_days=11 alone is weak.",
                "evidence_fields": ["domain_age_days", "dest_domain"],
            },
        ],
        "actions": {
            "immediate": [
                "Block update-service-cloud.net across DNS, proxy, and egress firewall.",
                "Isolate laptop-22 from the network pending EDR review.",
            ],
            "short_term": [
                "Hunt for the same uri_path across proxy logs for 7 days.",
                "Identify the process responsible for the beaconing session.",
            ],
            "long_term": [
                "Add alerting on fixed-interval POST patterns to domains under 30 days old.",
            ],
        },
    }


def analysis_case_2_impossible_travel(alert: dict[str, Any]) -> dict[str, Any]:
    return {
        "alert_reconciliation": {
            "verdict": "likely_malicious",
            "confidence": "0.79",
            "one_sentence_summary": (
                "corp\\alee authenticated to VPN from Amsterdam 13 minutes after a successful "
                "login from New York, which is physically impossible and suggests credential "
                "misuse or session replay despite MFA success."
            ),
            "decision_drivers": [
                "elapsed_minutes=13 with minimum_flight_hours=7",
                "prior_login_country=United States then current_login_country=Netherlands",
                "prior_src_ip=73.68.210.14 differs from current_src_ip=198.51.100.44",
                "mfa_result=success on current login",
            ],
            "recommended_actions": [
                "Disable corp\\alee sessions and force password reset plus MFA re-registration.",
                "Pull IdP and VPN authentication logs for both source IPs in the last 24 hours.",
            ],
        },
        "competing_hypotheses": _six(
            benign=[
                (
                    "Geo-IP mislabeling caused false impossible-travel signal.",
                    ["host=vpn-gw-02.corp.local", "auth_method=MFA"],
                    ["Geo database version unknown", "Both IPs not mapped to carriers"],
                    [_pivot("VPN vendor logs", ["src_ip", "session_id"]), _pivot("IdP sign-in", ["user", "src_ip"])],
                ),
                (
                    "User on VPN split-tunnel with rapid carrier handoff mis-timed in SIEM.",
                    ["Two successful 4624 events for same user", "MFA success on current login"],
                    ["Client device telemetry missing", "SIEM correlation window unknown"],
                    [_pivot("VPN logs", ["user", "client_ip"]), _pivot("Endpoint compliance", ["user", "device_id"])],
                ),
                (
                    "Shared credential used by two employees in different regions (policy violation, not malware).",
                    ["user=corp\\alee on both events", "Both logons successful"],
                    ["No concurrent session detail in alert", "HR roster not included"],
                    [_pivot("HR identity", ["user"]), _pivot("VPN concurrent sessions", ["user"])],
                ),
            ],
            adversary=[
                (
                    "Stolen password with MFA approval (fatigue or push hijack) from actor in Netherlands.",
                    [
                        "elapsed_minutes=13 between distant geos",
                        "current_src_ip=198.51.100.44 external to prior US login",
                    ],
                    ["No MFA denial history shown", "Device posture unknown"],
                    [_pivot("IdP risky sign-in", ["user", "src_ip"]), _pivot("VPN logs", ["user", "src_ip"])],
                ),
                (
                    "Session token replay after prior US compromise.",
                    ["Two successful authentications in impossible window", "event_id=4624"],
                    ["Token issuance logs not in alert", "Initial compromise vector unknown"],
                    [_pivot("IdP token logs", ["user"]), _pivot("AD auth", ["user", "src_ip"])],
                ),
                (
                    "VPN credential stuffing success after prior geo anomaly.",
                    ["prior_failed_logons not shown but risk_score=74", "External IP to VPN gateway"],
                    ["No failed login burst in alert", "Password spray scope unknown"],
                    [_pivot("VPN auth failures", ["src_ip"]), _pivot("IdP lockouts", ["user"])],
                ),
            ],
        ),
        "evidence_vs_inference": {
            "evidence": [
                "user=corp\\alee",
                "prior_login_city=New York",
                "current_login_city=Amsterdam",
                "elapsed_minutes=13",
                "minimum_flight_hours=7",
                "prior_src_ip=73.68.210.14",
                "current_src_ip=198.51.100.44",
                "mfa_result=success",
            ],
            "inferences": [
                "Physical impossibility outweighs MFA success alone for benign closure",
                "Travel approval status is unknown from alert fields",
            ],
        },
        "ioc_extraction": _ioc(
            ip_addresses=[str(alert.get("prior_src_ip", "")), str(alert.get("current_src_ip", ""))],
            user_accounts=[str(alert.get("user", ""))],
            hostnames=[str(alert.get("host", ""))],
            event_ids=[str(alert.get("event_id", ""))],
        ),
        "ttp_analysis": [
            {
                "ttp_id": "T1078",
                "ttp_name": "Valid Accounts",
                "confidence_score": "0.72",
                "explanation": "Successful VPN authentication for named user from two distant locations. Uncertainty: account compromise not directly proven.",
                "evidence_fields": ["user", "event_id", "mfa_result"],
            },
            {
                "ttp_id": "T1133",
                "ttp_name": "External Remote Services",
                "confidence_score": "0.58",
                "explanation": "External IP authentication to VPN gateway. Uncertainty: legitimate travel cannot be ruled out without approval records.",
                "evidence_fields": ["current_src_ip", "host"],
            },
        ],
        "actions": {
            "immediate": [
                "Revoke active sessions for corp\\alee and require out-of-band identity verification.",
            ],
            "short_term": [
                "Review IdP sign-in risk detections for 198.51.100.44 and 73.68.210.14.",
            ],
            "long_term": [
                "Enable impossible-travel blocking policy with travel-ticket enrichment.",
            ],
        },
    }


def analysis_case_3_powershell(alert: dict[str, Any]) -> dict[str, Any]:
    return {
        "alert_reconciliation": {
            "verdict": "likely_malicious",
            "confidence": "0.84",
            "one_sentence_summary": (
                "User corp\\jsmith launched hidden encoded PowerShell from winword.exe "
                "on workstation-14 with no change ticket, indicating probable document-driven "
                "execution rather than approved automation."
            ),
            "decision_drivers": [
                "command_line contains -enc and -w hidden on powershell.exe",
                "parent_process=winword.exe",
                "change_ticket empty",
                "integrity_level=high for interactive admin context",
            ],
            "recommended_actions": [
                "Isolate workstation-14.corp.local and collect PowerShell script block logs.",
                "Review recent email attachments for corp\\jsmith.",
            ],
        },
        "competing_hypotheses": _six(
            benign=[
                (
                    "IT pushed encoded maintenance script during patch window.",
                    ["user=corp\\jsmith is admin", "event_id=4688 process creation audited"],
                    ["change_ticket empty", "Encoded payload not reviewed"],
                    [_pivot("Change management", ["user", "host"]), _pivot("EDR", ["host", "command_line"])],
                ),
                (
                    "Security exercise script launched from document helper.",
                    ["winword.exe parent may indicate document workflow"],
                    ["No documented exercise", "EDR action=not blocked without context"],
                    [_pivot("SOC calendar", ["user", "host"]), _pivot("EDR", ["host", "process"])],
                ),
                (
                    "EDR vendor test harness on admin workstation.",
                    ["powershell.exe with encoded argument pattern"],
                    ["No test marker in alert", "Vendor schedule unknown"],
                    [_pivot("EDR console", ["host", "policy_name"])],
                ),
            ],
            adversary=[
                (
                    "Phishing attachment executed macro that spawned obfuscated PowerShell.",
                    ["parent_process=winword.exe", "command_line uses -enc and hidden window"],
                    ["Macro content unavailable", "Email trace not in alert"],
                    [_pivot("EDR", ["host", "parent_process"]), _pivot("Email gateway", ["user"])],
                ),
                (
                    "Compromised admin credentials used for scripted discovery.",
                    ["user=corp\\jsmith", "integrity_level=high", "Encoded command line"],
                    ["No lateral movement in alert", "MFA anomaly not shown"],
                    [_pivot("AD auth", ["user", "src_ip"]), _pivot("EDR", ["host", "process"])],
                ),
                (
                    "Living-off-the-land download cradle staged next-stage payload.",
                    ["powershell.exe with hidden window", "Obfuscated invocation"],
                    ["Network IOCs not in alert", "Child process tree unknown"],
                    [_pivot("Proxy logs", ["host", "user"]), _pivot("EDR", ["host", "process_guid"])],
                ),
            ],
        ),
        "evidence_vs_inference": {
            "evidence": [
                "user=corp\\jsmith",
                "host=workstation-14.corp.local",
                "process=powershell.exe",
                "parent_process=winword.exe",
                "command_line contains -enc",
                "change_ticket empty",
            ],
            "inferences": [
                "Encoded execution from Office parent is atypical for normal admin tasks",
                "Decoded script content is required before closure",
            ],
        },
        "ioc_extraction": _ioc(
            user_accounts=[str(alert.get("user", ""))],
            hostnames=[str(alert.get("host", ""))],
            ip_addresses=[str(alert.get("src_ip", ""))],
            process_names=[str(alert.get("process", "")), str(alert.get("parent_process", ""))],
            event_ids=[str(alert.get("event_id", ""))],
        ),
        "ttp_analysis": [
            {
                "ttp_id": "T1059.001",
                "ttp_name": "PowerShell",
                "confidence_score": "0.88",
                "explanation": "PowerShell executed with encoded hidden command line. Uncertainty: decoded payload not shown.",
                "evidence_fields": ["process", "command_line"],
            },
            {
                "ttp_id": "T1204.002",
                "ttp_name": "User Execution: Malicious File",
                "confidence_score": "0.74",
                "explanation": "Word parent process suggests document-driven execution. Uncertainty: macro content unavailable.",
                "evidence_fields": ["parent_process"],
            },
            {
                "ttp_id": "T1078",
                "ttp_name": "Valid Accounts",
                "confidence_score": "0.52",
                "explanation": "Named admin user in alert. Uncertainty: compromise not confirmed.",
                "evidence_fields": ["user"],
            },
        ],
        "actions": {
            "immediate": [
                "Isolate workstation-14 and terminate suspicious PowerShell descendants.",
            ],
            "short_term": [
                "Decode script block logging for the encoded command line.",
            ],
            "long_term": [
                "Constrain Office macro execution for privileged users.",
            ],
        },
    }


def analysis_case_4_privilege_escalation(alert: dict[str, Any]) -> dict[str, Any]:
    return {
        "alert_reconciliation": {
            "verdict": "likely_malicious",
            "confidence": "0.80",
            "one_sentence_summary": (
                "An IIS worker spawned PrintSpoofer64.exe and obtained a SYSTEM token before "
                "using net.exe to add a standard user to local Administrators on "
                "app-server-03, consistent with post-exploitation privilege escalation."
            ),
            "decision_drivers": [
                "event_id=4732 membership change",
                "command_line adds corp\\dgreen to Administrators",
                "grandparent_process=PrintSpoofer64.exe with integrity_level=System",
                "server_role=application with cmdb_owner_team=finance-apps",
            ],
            "recommended_actions": [
                "Remove corp\\dgreen from local Administrators on app-server-03.",
                "Isolate app-server-03 and preserve the IIS and token-impersonation process tree.",
            ],
        },
        "competing_hypotheses": _six(
            benign=[
                (
                    "Planned build step executed without recorded change ticket.",
                    ["process=net.exe used for group management"],
                    ["change_ticket not in alert", "User not listed as deployer in CMDB"],
                    [_pivot("CMDB", ["host", "build_id"]), _pivot("Change management", ["host", "user"])],
                ),
                (
                    "Break-glass IR procedure granting temporary admin.",
                    ["Explicit localgroup modification command"],
                    ["No IR ticket referenced", "Timing not aligned to incident"],
                    [_pivot("IR ticketing", ["host", "user"])],
                ),
                (
                    "Misconfigured automation script with excessive privileges.",
                    ["Command line is scriptable via net.exe"],
                    ["Automation owner unknown", "Task scheduler context missing"],
                    [_pivot("Task Scheduler", ["host", "task_name"]), _pivot("EDR", ["host", "process"])],
                ),
            ],
            adversary=[
                (
                    "Post-exploitation self-elevation on app-server-03.",
                    ["Self-add to Administrators by non-admin user", "event_id=4732"],
                    ["Initial access not in alert", "Exploit IOC missing"],
                    [_pivot("Windows Security", ["host", "user"]), _pivot("EDR", ["host", "process"])],
                ),
                (
                    "Insider attempt to gain persistent admin rights.",
                    ["Direct command targeting Administrators group", "grandparent_process=PrintSpoofer64.exe with integrity_level=System"],
                    ["UEBA baseline unknown", "HR context not included"],
                    [_pivot("UEBA", ["user"]), _pivot("PAM logs", ["user"])],
                ),
                (
                    "Remote execution of net.exe after lateral movement.",
                    ["4732 follows privileged group change pattern", "Application server target"],
                    ["Source host of command unknown", "Parent process not shown"],
                    [_pivot("EDR", ["host", "parent_process"]), _pivot("Network auth", ["host", "user"])],
                ),
            ],
        ),
        "evidence_vs_inference": {
            "evidence": [
                "user=corp\\dgreen",
                "host=app-server-03.corp.local",
                "event_id=4732",
                "target_group=Administrators",
                "command_line=net localgroup Administrators corp\\dgreen /add",
                "grandparent_process=PrintSpoofer64.exe with integrity_level=System",
            ],
            "inferences": [
                "Self-elevation without approved change is a strong malicious indicator",
                "Compromise versus insider intent requires identity and UEBA context",
            ],
        },
        "ioc_extraction": _ioc(
            user_accounts=[str(alert.get("user", ""))],
            hostnames=[str(alert.get("host", ""))],
            process_names=[str(alert.get("process", ""))],
            event_ids=[str(alert.get("event_id", ""))],
        ),
        "ttp_analysis": [
            {
                "ttp_id": "T1068",
                "ttp_name": "Exploitation for Privilege Escalation",
                "confidence_score": "0.76",
                "explanation": "Local Administrators group modified via net.exe by non-admin user. Uncertainty: exploit versus manual command unclear.",
                "evidence_fields": ["command_line", "event_id", "subject_is_admin"],
            },
            {
                "ttp_id": "T1078",
                "ttp_name": "Valid Accounts",
                "confidence_score": "0.60",
                "explanation": "Named user executed the change. Uncertainty: account compromise not proven.",
                "evidence_fields": ["user"],
            },
        ],
        "actions": {
            "immediate": [
                "Remove corp\\dgreen from local Administrators and disable interactive logon pending review.",
            ],
            "short_term": [
                "Search for net localgroup Administrators modifications across the fleet.",
            ],
            "long_term": [
                "Alert on self-add to privileged local groups for non-admin accounts.",
            ],
        },
    }


def analysis_case_5_lateral_rdp(alert: dict[str, Any]) -> dict[str, Any]:
    return {
        "alert_reconciliation": {
            "verdict": "likely_malicious",
            "confidence": "0.82",
            "one_sentence_summary": (
                "Service account corp\\svc-backup opened interactive RDP from jump-01 to "
                "db-prod-01 after six failed logons, outside the approved jump path for "
                "that account on a production database host."
            ),
            "decision_drivers": [
                "protocol=RDP with logon_type=10 interactive remote",
                "prior_failed_logons_15m=6 before success",
                "service_account_expected_on_dest=false",
                "dest_host=db-prod-01.corp.local is production database tier",
            ],
            "recommended_actions": [
                "Terminate active RDP session and disable corp\\svc-backup until ownership verified.",
                "Review PAM and jump-server authorization for svc-backup on db-prod-01.",
            ],
        },
        "competing_hypotheses": _six(
            benign=[
                (
                    "Emergency DBA access via break-glass service account.",
                    ["src_host=jump-01.corp.local is jump server", "Successful 4624 after failures"],
                    ["No break-glass ticket in alert", "service_account_expected_on_dest=false"],
                    [_pivot("PAM session logs", ["user", "dest_host"]), _pivot("Change management", ["dest_host"])],
                ),
                (
                    "Backup software vendor remote support session misrouted through jump-01.",
                    ["src_user=corp\\svc-backup naming suggests backup role"],
                    ["Vendor maintenance window unknown", "RDP instead of backup protocol unexpected"],
                    [_pivot("Backup console", ["host", "job_id"]), _pivot("VPN/jump logs", ["user"])],
                ),
                (
                    "Automated jump-box script testing connectivity to db-prod-01.",
                    ["Multiple attempts then success pattern could be retry logic"],
                    ["Script name not in alert", "Automation schedule unknown"],
                    [_pivot("Task Scheduler", ["src_host", "task_name"]), _pivot("Windows Security", ["dest_host"])],
                ),
            ],
            adversary=[
                (
                    "Stolen service account used for lateral movement to database tier.",
                    [
                        "RDP from jump-01 to db-prod-01",
                        "prior_failed_logons_15m=6",
                        "service_account_expected_on_dest=false",
                    ],
                    ["Initial credential theft not in alert", "Post-RDP activity unknown"],
                    [_pivot("AD auth", ["user", "src_ip"]), _pivot("EDR", ["dest_host", "logon_type"])],
                ),
                (
                    "Pass-the-hash or brute force success against svc-backup on jump-01.",
                    ["Six failed logons within 15 minutes", "Interactive RDP success follows"],
                    ["Auth failure codes not shown", "Source attacker IP unknown"],
                    [_pivot("Windows Security", ["src_host", "user"]), _pivot("NDR", ["src_ip", "dest_ip"])],
                ),
                (
                    "Operator misused service account after prior compromise of jump-01.",
                    ["Service account on approved jump host reaching prod DB", "logon_type=10"],
                    ["Jump-01 compromise evidence missing", "Session duration unknown"],
                    [_pivot("EDR", ["src_host", "process"]), _pivot("PAM", ["user", "dest_host"])],
                ),
            ],
        ),
        "evidence_vs_inference": {
            "evidence": [
                "src_user=corp\\svc-backup",
                "src_host=jump-01.corp.local",
                "dest_host=db-prod-01.corp.local",
                "dest_ip=10.30.8.40",
                "protocol=RDP",
                "prior_failed_logons_15m=6",
                "service_account_expected_on_dest=false",
                "logon_type=10",
            ],
            "inferences": [
                "Interactive RDP to prod DB by backup service account is high risk without PAM record",
                "Failed logon burst increases likelihood of credential guessing or stale credential reuse",
            ],
        },
        "ioc_extraction": _ioc(
            user_accounts=[str(alert.get("src_user", ""))],
            hostnames=[str(alert.get("src_host", "")), str(alert.get("dest_host", ""))],
            ip_addresses=[str(alert.get("src_ip", "")), str(alert.get("dest_ip", ""))],
            event_ids=[str(alert.get("event_id", ""))],
        ),
        "ttp_analysis": [
            {
                "ttp_id": "T1021.001",
                "ttp_name": "Remote Services: Remote Desktop Protocol",
                "confidence_score": "0.85",
                "explanation": "Interactive RDP logon from jump host to database server. Uncertainty: authorized break-glass not confirmed.",
                "evidence_fields": ["protocol", "logon_type", "dest_host"],
            },
            {
                "ttp_id": "T1078",
                "ttp_name": "Valid Accounts",
                "confidence_score": "0.68",
                "explanation": "Service account used for remote authentication. Uncertainty: credential theft not proven.",
                "evidence_fields": ["src_user", "event_id"],
            },
            {
                "ttp_id": "T1110",
                "ttp_name": "Brute Force",
                "confidence_score": "0.55",
                "explanation": "Six failed logons within 15 minutes before success. Uncertainty: failure reason codes not shown.",
                "evidence_fields": ["prior_failed_logons_15m"],
            },
        ],
        "actions": {
            "immediate": [
                "Kill active RDP session to db-prod-01 and rotate svc-backup credentials.",
            ],
            "short_term": [
                "Validate PAM recordings and approved jump paths for database tier access.",
            ],
            "long_term": [
                "Block interactive RDP for service accounts except through recorded PAM sessions.",
            ],
        },
    }


STORED_PREVIEW_ANALYSIS: dict[int, Any] = {
    1: analysis_case_1_beaconing,
    2: analysis_case_2_impossible_travel,
    3: analysis_case_3_powershell,
    4: analysis_case_4_privilege_escalation,
    5: analysis_case_5_lateral_rdp,
}
