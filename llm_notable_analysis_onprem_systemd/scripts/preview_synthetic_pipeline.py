"""Build preview portal cases through the real analyzer normalization path.

Synthetic Splunk-style alerts and hand-authored LLM-shaped JSON are passed through
``_normalize_and_fill_defaults``, ``enrich_analysis_with_query_results``, and
``build_case_archive_record`` so the preview UI exercises the same contracts as
production without calling a live model.
"""

from __future__ import annotations

import sys
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from llm_notable_analysis_onprem_systemd.onprem_service.case_store import (  # noqa: E402
    CaseArchiveRecord,
    build_case_archive_record,
)
from llm_notable_analysis_onprem_systemd.onprem_service.config import Config  # noqa: E402
from llm_notable_analysis_onprem_systemd.onprem_service.local_llm_client import (  # noqa: E402
    _normalize_and_fill_defaults,
    validate_response_schema,
)
from llm_notable_analysis_onprem_systemd.onprem_service.query_result_enrichment import (  # noqa: E402
    enrich_analysis_with_query_results,
)

_PREVIEW_SCENARIO_COUNT = 5


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


def _six_hypotheses(
    *,
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


def _ioc_bundle(**fields: list[str]) -> dict[str, list[str]]:
    base = {
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


def _pivot(source: str, fields: list[str]) -> dict[str, Any]:
    return {"log_source": source, "key_fields": fields}


def _preview_scenarios() -> list[dict[str, Any]]:
    """Five distinct synthetic scenarios keyed by preview case index 1-5."""
    pivot_auth = _pivot("Windows Security", ["user", "src_ip", "event_id"])
    pivot_edr = _pivot("EDR process tree", ["host", "process_guid", "parent_process"])
    pivot_proxy = _pivot("Proxy logs", ["src_ip", "dest_host", "user"])

    return [
        {
            "search_name": "Suspicious PowerShell",
            "verdict": "likely_malicious",
            "confidence": "0.82",
            "summary": (
                "Encoded PowerShell launched from an admin session on a workstation with no "
                "matching change ticket; endpoint command-line review is required before closure."
            ),
            "risk_score": 78,
            "alert": {
                "notable_id": "syn-001",
                "search_name": "Suspicious PowerShell",
                "risk_score": 78,
                "user": "corp\\jsmith",
                "host": "workstation-14.corp.local",
                "process": "powershell.exe",
                "command_line": (
                    "powershell.exe -nop -w hidden -enc "
                    "SQBFAFgAYQBuACAAcwBjAHIAaQBwAHQ="
                ),
                "parent_process": "winword.exe",
                "event_id": "4688",
                "source_ip": "10.20.14.55",
            },
            "llm": {
                "alert_reconciliation": {
                    "verdict": "likely_malicious",
                    "confidence": "0.82",
                    "one_sentence_summary": (
                        "Encoded PowerShell launched from an admin session on a workstation with no "
                        "matching change ticket; endpoint command-line review is required before closure."
                    ),
                    "decision_drivers": [
                        "Hidden window and encoded command line on powershell.exe",
                        "Parent process winword.exe is atypical for administrative scripting",
                        "Admin user context increases blast radius if malicious",
                        "No approved change record tied to the session",
                    ],
                    "recommended_actions": [
                        "Isolate workstation-14 pending triage.",
                        "Collect full process tree and PowerShell script block logs.",
                    ],
                },
                "competing_hypotheses": _six_hypotheses(
                    benign=[
                        (
                            "IT automation pushed a signed maintenance script during patch window.",
                            ["user=corp\\jsmith is a known admin", "host tagged as corporate workstation"],
                            ["No change ticket reference", "Encoded command obscures intent"],
                            [_pivot("Change management", ["user", "host"]), pivot_edr],
                        ),
                        (
                            "Security team ran an approved hunting script from Word macro helper.",
                            ["winword.exe parent may indicate document-driven helper"],
                            ["No documented hunting exercise", "Encoded payload not reviewed"],
                            [pivot_edr, _pivot("SOC calendar", ["user", "host"])],
                        ),
                        (
                            "EDR agent test harness triggered a benign simulation.",
                            ["event_id=4688 indicates process creation auditing"],
                            ["No EDR test marker in alert", "Simulation schedule unknown"],
                            [_pivot("EDR console", ["host", "policy_name"])],
                        ),
                    ],
                    adversary=[
                        (
                            "Phishing attachment executed macro that launched obfuscated PowerShell.",
                            ["winword.exe parent with hidden encoded PowerShell"],
                            ["Email trace not in alert", "Macro contents unavailable"],
                            [pivot_edr, _pivot("Email gateway", ["user", "message_id"])],
                        ),
                        (
                            "Compromised admin credentials used for interactive discovery.",
                            ["corp\\jsmith admin context", "encoded command suggests obfuscation"],
                            ["No MFA anomaly in alert", "No lateral movement evidence yet"],
                            [pivot_auth, pivot_edr],
                        ),
                        (
                            "Living-off-the-land download cradle staged a second-stage payload.",
                            ["powershell.exe with hidden window flag"],
                            ["No network IOCs in alert", "No file hash for child process"],
                            [pivot_proxy, pivot_edr],
                        ),
                    ],
                ),
                "evidence_vs_inference": {
                    "evidence": [
                        "user=corp\\jsmith",
                        "host=workstation-14.corp.local",
                        "process=powershell.exe with -enc argument",
                        "parent_process=winword.exe",
                    ],
                    "inferences": [
                        "Encoded execution suggests deliberate obfuscation",
                        "Admin context raises impact but does not prove malicious intent alone",
                    ],
                },
                "ioc_extraction": _ioc_bundle(
                    user_accounts=["corp\\jsmith"],
                    hostnames=["workstation-14.corp.local"],
                    process_names=["powershell.exe", "winword.exe"],
                    event_ids=["4688"],
                    ip_addresses=["10.20.14.55"],
                ),
                "ttp_analysis": [
                    {
                        "ttp_id": "T1059.001",
                        "ttp_name": "PowerShell",
                        "confidence_score": "0.86",
                        "explanation": "PowerShell executed with encoded command. Uncertainty: decoded payload not shown.",
                        "evidence_fields": ["process", "command_line"],
                    },
                    {
                        "ttp_id": "T1204.002",
                        "ttp_name": "User Execution: Malicious File",
                        "confidence_score": "0.71",
                        "explanation": "Word parent process suggests document-driven execution. Uncertainty: macro content unavailable.",
                        "evidence_fields": ["parent_process"],
                    },
                    {
                        "ttp_id": "T1078",
                        "ttp_name": "Valid Accounts",
                        "confidence_score": "0.55",
                        "explanation": "Named admin user in alert. Uncertainty: compromise not confirmed.",
                        "evidence_fields": ["user"],
                    },
                ],
                "actions": {
                    "immediate": [
                        "Isolate workstation-14 from the network if EDR confirms suspicious child processes.",
                        "Reset corp\\jsmith session tokens and review recent interactive logons.",
                    ],
                    "short_term": [
                        "Decode and review the PowerShell script block for the encoded command.",
                        "Search peer hosts for the same parent_process and command-line pattern.",
                    ],
                    "long_term": [
                        "Tighten Office macro policy for users with administrative rights.",
                    ],
                },
            },
            "query_results": [
                {
                    "hypothesis_index": 3,
                    "query_strategy": "resolve_unknown",
                    "query": "search index=wineventlog host=workstation-14 process=powershell.exe | head 50",
                    "status": "success",
                    "result_count": 14,
                    "sample_columns": ["host", "user", "process", "command_line"],
                    "search_id": "sid-ps-001",
                },
                {
                    "hypothesis_index": 0,
                    "query_strategy": "confirm_benign",
                    "query": "search index=itsm change_ticket host=workstation-14 | head 10",
                    "status": "success",
                    "result_count": 0,
                    "sample_columns": ["ticket_id", "status"],
                    "search_id": "sid-chg-001",
                },
            ],
            "query_result_interpretation": [
                {
                    "hypothesis_index": 3,
                    "assessment": "supports",
                    "confidence_delta": "increase",
                    "rationale": "Additional encoded PowerShell executions were observed on the same host.",
                    "key_observations": ["14 matching process creation events"],
                    "remaining_gaps": ["Decoded script content still unavailable"],
                    "source_query_refs": ["sid-ps-001"],
                }
            ],
        },
        {
            "search_name": "Unusual Login Location",
            "verdict": "unknown",
            "confidence": "0.58",
            "summary": (
                "Successful authentication from a new country for a standard user lacks travel "
                "approval context; identity and VPN posture must be validated."
            ),
            "risk_score": 62,
            "alert": {
                "notable_id": "syn-002",
                "search_name": "Unusual Login Location",
                "risk_score": 62,
                "user": "corp\\alee",
                "src_ip": "198.51.100.44",
                "country": "Netherlands",
                "city": "Amsterdam",
                "auth_method": "MFA",
                "event_id": "4624",
                "host": "vpn-gw-02",
            },
            "llm": {
                "alert_reconciliation": {
                    "verdict": "unknown",
                    "confidence": "0.58",
                    "one_sentence_summary": (
                        "Successful authentication from a new country for a standard user lacks travel "
                        "approval context; identity and VPN posture must be validated."
                    ),
                    "decision_drivers": [
                        "First-seen geolocation for corp\\alee in the last 90 days",
                        "MFA success reduces automated takeover likelihood",
                        "Source IP is not on the approved travel allowlist",
                        "No concurrent impossible-travel conflict in the alert",
                    ],
                    "recommended_actions": [
                        "Contact corp\\alee through an out-of-band channel.",
                        "Review VPN and IdP sign-in logs for the last 24 hours.",
                    ],
                },
                "competing_hypotheses": _six_hypotheses(
                    benign=[
                        (
                            "Employee traveling with personal VPN egress in Netherlands.",
                            ["MFA completed successfully", "VPN gateway host present in alert"],
                            ["No travel approval ticket referenced", "Impossible travel not assessed"],
                            [_pivot("Travel approvals", ["user", "date"]), pivot_auth],
                        ),
                        (
                            "Corporate VPN concentrator geo-IP database mislabeled the source.",
                            ["auth_method=MFA", "host=vpn-gw-02"],
                            ["Geo database version unknown", "Historical baseline not in alert"],
                            [_pivot("VPN vendor logs", ["src_ip", "session_id"]), pivot_auth],
                        ),
                        (
                            "Legitimate remote work from contractor site in EU.",
                            ["Standard user account not marked disabled"],
                            ["Contractor roster not included", "No HR travel record"],
                            [_pivot("HR travel", ["user"]), pivot_auth],
                        ),
                    ],
                    adversary=[
                        (
                            "Stolen password with satisfied MFA fatigue or push approval.",
                            ["New country login", "Risk score elevated"],
                            ["No MFA failure sequence shown", "Device posture unknown"],
                            [pivot_auth, _pivot("IdP risk detections", ["user", "src_ip"])],
                        ),
                        (
                            "Credential stuffing success against legacy VPN profile.",
                            ["External IP authentication to VPN gateway"],
                            ["No failed login burst in alert", "Password spray scope unknown"],
                            [pivot_auth, pivot_proxy],
                        ),
                        (
                            "Session hijack after prior malware on traveler laptop.",
                            ["Successful 4624 from unusual geography"],
                            ["Endpoint health not in alert", "No malware IOC attached"],
                            [pivot_edr, pivot_auth],
                        ),
                    ],
                ),
                "evidence_vs_inference": {
                    "evidence": [
                        "user=corp\\alee",
                        "src_ip=198.51.100.44",
                        "country=Netherlands",
                        "event_id=4624",
                    ],
                    "inferences": [
                        "Geo novelty alone is insufficient for a malicious verdict",
                        "MFA success weakens automated credential-stuffing hypothesis",
                    ],
                },
                "ioc_extraction": _ioc_bundle(
                    ip_addresses=["198.51.100.44"],
                    user_accounts=["corp\\alee"],
                    hostnames=["vpn-gw-02"],
                    event_ids=["4624"],
                ),
                "ttp_analysis": [
                    {
                        "ttp_id": "T1078",
                        "ttp_name": "Valid Accounts",
                        "confidence_score": "0.64",
                        "explanation": "Successful VPN authentication with named user. Uncertainty: account compromise not proven.",
                        "evidence_fields": ["user", "event_id"],
                    },
                    {
                        "ttp_id": "T1133",
                        "ttp_name": "External Remote Services",
                        "confidence_score": "0.49",
                        "explanation": "VPN gateway authentication from external IP. Uncertainty: travel may be legitimate.",
                        "evidence_fields": ["src_ip", "host"],
                    },
                ],
                "actions": {
                    "immediate": [
                        "Validate travel status with corp\\alee and manager.",
                    ],
                    "short_term": [
                        "Review IdP risky sign-in reports for the Netherlands source IP.",
                    ],
                    "long_term": [
                        "Add geo anomaly enrichment with travel ticket correlation.",
                    ],
                },
            },
            "query_results": [
                {
                    "hypothesis_index": 0,
                    "query_strategy": "confirm_benign",
                    "query": "search index=wineventlog user=corp\\alee src_ip=198.51.100.44 | head 20",
                    "status": "success",
                    "result_count": 3,
                    "sample_columns": ["user", "src_ip", "country"],
                    "search_id": "sid-vpn-002",
                }
            ],
            "query_result_interpretation": [],
        },
        {
            "search_name": "Malware Beaconing",
            "verdict": "likely_malicious",
            "confidence": "0.88",
            "summary": (
                "A workstation generated periodic HTTPS beacons to a young domain with a high-entropy "
                "URI path, consistent with command-and-control behavior."
            ),
            "risk_score": 91,
            "alert": {
                "notable_id": "syn-003",
                "search_name": "Malware Beaconing",
                "risk_score": 91,
                "user": "corp\\mrossi",
                "host": "laptop-22",
                "dest_ip": "203.0.113.77",
                "dest_domain": "update-service-cloud.net",
                "uri_path": "/api/v1/session/a8f2c1",
                "bytes_out": 512,
                "interval_seconds": 60,
            },
            "llm": {
                "alert_reconciliation": {
                    "verdict": "likely_malicious",
                    "confidence": "0.88",
                    "one_sentence_summary": (
                        "A workstation generated periodic HTTPS beacons to a young domain with a high-entropy "
                        "URI path, consistent with command-and-control behavior."
                    ),
                    "decision_drivers": [
                        "Fixed 60-second beacon interval to the same destination",
                        "Destination domain recently registered and not on allowlist",
                        "Small fixed payload size typical of C2 keepalive",
                        "No sanctioned updater matched the domain",
                    ],
                    "recommended_actions": [
                        "Block update-service-cloud.net at proxy and DNS.",
                        "Isolate laptop-22 and collect memory image.",
                    ],
                },
                "competing_hypotheses": _six_hypotheses(
                    benign=[
                        (
                            "Legitimate software updater using a new CDN endpoint.",
                            ["Fixed interval may match updater heartbeat"],
                            ["Vendor not identified", "Certificate info missing"],
                            [_pivot("Software inventory", ["host", "process"]), pivot_proxy],
                        ),
                        (
                            "Security scanner generating synthetic beacon traffic.",
                            ["corp\\mrossi may be security engineering"],
                            ["No scanner tag on host", "Scan window unknown"],
                            [_pivot("Vulnerability scanner", ["src_ip", "host"])],
                        ),
                        (
                            "Misconfigured monitoring agent reporting health status.",
                            ["Small periodic POST is common for agents"],
                            ["Agent inventory not in alert", "URI path not matched to known agent"],
                            [pivot_edr, pivot_proxy],
                        ),
                    ],
                    adversary=[
                        (
                            "HTTP C2 channel using domain fronting lookalike name.",
                            ["Regular 60-second cadence", "High-entropy URI path"],
                            ["Payload contents not captured", "Process owner unknown"],
                            [pivot_proxy, pivot_edr],
                        ),
                        (
                            "Post-exploitation implant after phishing on laptop-22.",
                            ["Beaconing from user workstation", "Young domain"],
                            ["Initial access vector not in alert", "Persistence mechanism unknown"],
                            [pivot_edr, _pivot("Email gateway", ["user"])],
                        ),
                        (
                            "Data exfiltration staging over low-volume HTTPS posts.",
                            ["Fixed bytes_out=512 each interval"],
                            ["No exfil volume threshold exceeded", "File access logs unavailable"],
                            [pivot_proxy, pivot_edr],
                        ),
                    ],
                ),
                "evidence_vs_inference": {
                    "evidence": [
                        "dest_domain=update-service-cloud.net",
                        "interval_seconds=60",
                        "host=laptop-22",
                        "uri_path=/api/v1/session/a8f2c1",
                    ],
                    "inferences": [
                        "Regular low-volume periodic traffic is more consistent with C2 than bulk exfil",
                    ],
                },
                "ioc_extraction": _ioc_bundle(
                    domains=["update-service-cloud.net"],
                    ip_addresses=["203.0.113.77"],
                    hostnames=["laptop-22"],
                    user_accounts=["corp\\mrossi"],
                    urls=["https://update-service-cloud.net/api/v1/session/a8f2c1"],
                ),
                "ttp_analysis": [
                    {
                        "ttp_id": "T1071.001",
                        "ttp_name": "Application Layer Protocol: Web Protocols",
                        "confidence_score": "0.90",
                        "explanation": "Periodic HTTPS beacons observed. Uncertainty: payload not inspected.",
                        "evidence_fields": ["dest_domain", "uri_path"],
                    },
                    {
                        "ttp_id": "T1568.002",
                        "ttp_name": "Dynamic Resolution: Domain Generation Algorithms",
                        "confidence_score": "0.41",
                        "explanation": "Single young domain only. Uncertainty: DGA not established.",
                        "evidence_fields": ["dest_domain"],
                    },
                ],
                "actions": {
                    "immediate": [
                        "Block update-service-cloud.net across DNS, proxy, and egress firewall.",
                        "Isolate laptop-22 and terminate suspicious HTTPS sessions.",
                    ],
                    "short_term": [
                        "Hunt for the same URI path across all proxy logs for 7 days.",
                    ],
                    "long_term": [
                        "Add TLS inspection policy for unknown updater categories on endpoints.",
                    ],
                },
            },
            "query_results": [
                {
                    "hypothesis_index": 0,
                    "query_strategy": "resolve_unknown",
                    "query": (
                        "search index=proxy dest=update-service-cloud.net "
                        "| stats count by host,user | head 20"
                    ),
                    "status": "success",
                    "result_count": 1,
                    "sample_columns": ["host", "user", "count"],
                    "search_id": "sid-beacon-003",
                }
            ],
            "query_result_interpretation": [
                {
                    "hypothesis_index": 0,
                    "assessment": "supports",
                    "confidence_delta": "increase",
                    "rationale": "Only laptop-22 beaconing was observed to the suspicious domain.",
                    "key_observations": ["1 host with 1,440 periodic events in 24h"],
                    "remaining_gaps": ["Process responsible for traffic not identified"],
                    "source_query_refs": ["sid-beacon-003"],
                }
            ],
        },
        {
            "search_name": "Privilege Escalation Attempt",
            "verdict": "likely_malicious",
            "confidence": "0.76",
            "summary": (
                "A standard user account attempted to add itself to the local Administrators group, "
                "which is a direct privilege-escalation indicator on the endpoint."
            ),
            "risk_score": 85,
            "alert": {
                "notable_id": "syn-004",
                "search_name": "Privilege Escalation Attempt",
                "risk_score": 85,
                "user": "corp\\dgreen",
                "host": "app-server-03",
                "target_group": "Administrators",
                "event_id": "4732",
                "process": "net.exe",
                "command_line": "net localgroup Administrators corp\\dgreen /add",
            },
            "llm": {
                "alert_reconciliation": {
                    "verdict": "likely_malicious",
                    "confidence": "0.76",
                    "one_sentence_summary": (
                        "A standard user account attempted to add itself to the local Administrators group, "
                        "which is a direct privilege-escalation indicator on the endpoint."
                    ),
                    "decision_drivers": [
                        "Self-add to Administrators via net.exe",
                        "User is not in the server admin roster",
                        "Event 4732 records a explicit group membership change",
                        "Command line shows intentional localgroup modification",
                    ],
                    "recommended_actions": [
                        "Remove corp\\dgreen from local Administrators on app-server-03.",
                        "Review privileged group changes across the server fleet.",
                    ],
                },
                "competing_hypotheses": _six_hypotheses(
                    benign=[
                        (
                            "Planned server build step executed by installer account.",
                            ["net.exe used for transparent admin task"],
                            ["No build ticket referenced", "User not listed as deployer"],
                            [_pivot("CMDB", ["host", "build_id"]), pivot_auth],
                        ),
                        (
                            "Helpdesk break-glass procedure during incident response.",
                            ["Temporary admin grant sometimes used in IR"],
                            ["No IR ticket in alert", "Time not aligned to declared incident"],
                            [_pivot("IR ticketing", ["host", "user"])],
                        ),
                        (
                            "Misconfigured automation script with excessive privileges.",
                            ["Command line is scriptable via net.exe"],
                            ["Automation owner unknown", "Schedule not shown"],
                            [pivot_edr, _pivot("Task Scheduler", ["host", "task_name"])],
                        ),
                    ],
                    adversary=[
                        (
                            "Post-compromise privilege escalation on app-server-03.",
                            ["Self-add to Administrators by non-admin user"],
                            ["Initial access not in alert", "Lateral path unknown"],
                            [pivot_auth, pivot_edr],
                        ),
                        (
                            "Insider abuse attempting persistent admin rights.",
                            ["Direct command targeting Administrators group"],
                            ["No HR case referenced", "User behavior baseline unknown"],
                            [pivot_auth, _pivot("UEBA", ["user"])],
                        ),
                        (
                            "Exploit payload running net.exe after remote code execution.",
                            ["4732 follows process creation pattern"],
                            ["Exploit IOC missing", "Parent process unknown"],
                            [pivot_edr, pivot_proxy],
                        ),
                    ],
                ),
                "evidence_vs_inference": {
                    "evidence": [
                        "event_id=4732",
                        "command_line contains Administrators and corp\\dgreen",
                        "process=net.exe",
                    ],
                    "inferences": [
                        "Self-elevation is a strong malicious indicator without an approved change record",
                    ],
                },
                "ioc_extraction": _ioc_bundle(
                    user_accounts=["corp\\dgreen"],
                    hostnames=["app-server-03"],
                    process_names=["net.exe"],
                    event_ids=["4732"],
                ),
                "ttp_analysis": [
                    {
                        "ttp_id": "T1068",
                        "ttp_name": "Exploitation for Privilege Escalation",
                        "confidence_score": "0.72",
                        "explanation": "Local admin group modification attempted. Uncertainty: exploit vs manual command unclear.",
                        "evidence_fields": ["command_line", "event_id"],
                    },
                    {
                        "ttp_id": "T1078",
                        "ttp_name": "Valid Accounts",
                        "confidence_score": "0.61",
                        "explanation": "Named user executed the change. Uncertainty: compromise not confirmed.",
                        "evidence_fields": ["user"],
                    },
                ],
                "actions": {
                    "immediate": [
                        "Remove corp\\dgreen from the local Administrators group on app-server-03.",
                        "Disable interactive logon for corp\\dgreen until validated.",
                    ],
                    "short_term": [
                        "Search fleet-wide for net localgroup Administrators modifications in 24h.",
                    ],
                    "long_term": [
                        "Alert on self-add to privileged local groups for non-admin accounts.",
                    ],
                },
            },
            "query_results": [
                {
                    "hypothesis_index": 0,
                    "query_strategy": "resolve_unknown",
                    "query": "search index=wineventlog host=app-server-03 EventCode=4732 | head 20",
                    "status": "success",
                    "result_count": 2,
                    "sample_columns": ["user", "target_group", "command_line"],
                    "search_id": "sid-priv-004",
                }
            ],
            "query_result_interpretation": [],
        },
        {
            "search_name": "Scheduled Task - Known Scanner",
            "verdict": "likely_benign",
            "confidence": "0.71",
            "summary": (
                "A scheduled task named Nessus_Scan matched a known vulnerability scanner pattern on a "
                "managed server during the approved weekly scanning window."
            ),
            "risk_score": 35,
            "alert": {
                "notable_id": "syn-005",
                "search_name": "Scheduled Task - Known Scanner",
                "risk_score": 35,
                "user": "NT AUTHORITY\\SYSTEM",
                "host": "scan-target-07",
                "task_name": "Nessus_Scan",
                "product": "Nessus",
                "event_id": "4698",
                "source_ip": "10.30.0.15",
            },
            "llm": {
                "alert_reconciliation": {
                    "verdict": "likely_benign",
                    "confidence": "0.71",
                    "one_sentence_summary": (
                        "A scheduled task named Nessus_Scan matched a known vulnerability scanner pattern on a "
                        "managed server during the approved weekly scanning window."
                    ),
                    "decision_drivers": [
                        "Task name matches sanctioned Nessus scanner",
                        "Host is tagged scan-target in CMDB",
                        "Activity occurred inside documented weekly scan window",
                        "No follow-on malicious execution observed in alert",
                    ],
                    "recommended_actions": [
                        "Confirm scan window with vulnerability management team.",
                        "Close as benign if Nessus job ID matches schedule.",
                    ],
                },
                "competing_hypotheses": _six_hypotheses(
                    benign=[
                        (
                            "Approved Nessus authenticated scan from scanner subnet.",
                            ["task_name=Nessus_Scan", "product=Nessus"],
                            ["Scan job ID not attached", "Credential used not shown"],
                            [_pivot("Vuln scanner console", ["host", "scan_id"]), pivot_auth],
                        ),
                        (
                            "Recurring maintenance window for compliance scanning.",
                            ["source_ip=10.30.0.15 is scanner segment"],
                            ["Change record not embedded in alert"],
                            [_pivot("Change management", ["host", "window"])],
                        ),
                        (
                            "Golden image validation task after patch deployment.",
                            ["SYSTEM context typical for agent-driven scan"],
                            ["Patch ticket not referenced"],
                            [_pivot("Patch management", ["host"])],
                        ),
                    ],
                    adversary=[
                        (
                            "Attacker created a persistence task disguised as Nessus_Scan.",
                            ["Task creation event 4698"],
                            ["Binary path not shown", "Task author not verified"],
                            [pivot_edr, _pivot("Task Scheduler", ["host", "task_name"])],
                        ),
                        (
                            "Lateral movement staging task on scan-target-07.",
                            ["Server in DMZ scan zone is high value"],
                            ["No lateral auth events in alert"],
                            [pivot_auth, pivot_proxy],
                        ),
                        (
                            "Credential theft using scanner service account.",
                            ["Scanner subnet source_ip present"],
                            ["Service account name not in alert"],
                            [pivot_auth, _pivot("Scanner credential vault", ["host"])],
                        ),
                    ],
                ),
                "evidence_vs_inference": {
                    "evidence": [
                        "task_name=Nessus_Scan",
                        "product=Nessus",
                        "host=scan-target-07",
                        "source_ip=10.30.0.15",
                    ],
                    "inferences": [
                        "Scanner naming and CMDB role support a benign classification pending schedule confirmation",
                    ],
                },
                "ioc_extraction": _ioc_bundle(
                    hostnames=["scan-target-07"],
                    ip_addresses=["10.30.0.15"],
                    process_names=["Nessus_Scan"],
                    event_ids=["4698"],
                ),
                "ttp_analysis": [
                    {
                        "ttp_id": "T1053.005",
                        "ttp_name": "Scheduled Task/Job: Scheduled Task",
                        "confidence_score": "0.48",
                        "explanation": "Scheduled task created. Uncertainty: task appears aligned to scanning activity.",
                        "evidence_fields": ["task_name", "event_id"],
                    },
                ],
                "actions": {
                    "immediate": [
                        "Validate the Nessus job against the weekly scan calendar.",
                    ],
                    "short_term": [
                        "Document benign closure reason in the case notes.",
                    ],
                    "long_term": [],
                },
            },
            "query_results": [
                {
                    "hypothesis_index": 0,
                    "query_strategy": "confirm_benign",
                    "query": "search index=scanner_jobs host=scan-target-07 task=Nessus_Scan | head 5",
                    "status": "success",
                    "result_count": 1,
                    "sample_columns": ["scan_id", "status", "window"],
                    "search_id": "sid-scan-005",
                }
            ],
            "query_result_interpretation": [
                {
                    "hypothesis_index": 0,
                    "assessment": "supports",
                    "confidence_delta": "decrease",
                    "rationale": "Active Nessus job matched the scheduled weekly scan window.",
                    "key_observations": ["scan_id=weekly-07 approved"],
                    "remaining_gaps": ["Task binary hash not captured"],
                    "source_query_refs": ["sid-scan-005"],
                }
            ],
            "servicenow_section": {
                "draft": {"status": "success", "message": "Draft incident prepared for benign closure."},
                "create": {
                    "status": "skipped",
                    "message": "Create disabled in preview",
                    "number": "",
                    "sys_id": "",
                    "approval": {},
                },
            },
        },
    ]


def materialize_synthetic_analysis(
    scenario: dict[str, Any],
    *,
    spl_query_enabled: bool = False,
) -> dict[str, Any]:
    """Run one synthetic LLM payload through analyzer normalization and enrichment."""
    raw = deepcopy(scenario["llm"])
    analysis = _normalize_and_fill_defaults(
        raw,
        spl_query_enabled=spl_query_enabled,
        elastic_query_enabled=False,
    )
    ok, err = validate_response_schema(analysis)
    if not ok:
        raise ValueError(f"Synthetic analysis failed schema validation: {err}")

    query_results = scenario.get("query_results") or []
    if query_results:
        analysis = enrich_analysis_with_query_results(analysis, query_results)

    interpretation = scenario.get("query_result_interpretation")
    if interpretation:
        analysis["query_result_interpretation"] = interpretation

    actions = scenario.get("actions")
    if actions:
        analysis["actions"] = actions

    servicenow = scenario.get("servicenow_section")
    if servicenow:
        analysis["servicenow_section"] = servicenow

    analysis["metadata"] = {
        "preview_synthetic": True,
        "structured_output_mode": "preview_fixture",
        "repair_attempted": False,
    }
    return analysis


def build_synthetic_preview_record(
    *,
    config: Config,
    scenario_index: int,
    case_id: str,
    finding_id: str,
    source_filename: str,
    processed_at: datetime,
) -> CaseArchiveRecord:
    """Build one preview archive row via the real case-store builder."""
    scenarios = _preview_scenarios()
    if scenario_index < 1 or scenario_index > len(scenarios):
        raise IndexError(f"scenario_index must be 1..{len(scenarios)}")
    scenario = scenarios[scenario_index - 1]
    analysis = materialize_synthetic_analysis(scenario)
    record = build_case_archive_record(
        config=config,
        case_id=case_id,
        finding_id=finding_id,
        source_filename=source_filename,
        alert_payload=scenario["alert"],
        analysis=analysis,
        report_md_path=f"/reports/{case_id}.md",
        report_html_path=None,
        processed_at=processed_at,
    )
    return replace(record, retrieval_status="ready")


def preview_scenario_count() -> int:
    return _PREVIEW_SCENARIO_COUNT
