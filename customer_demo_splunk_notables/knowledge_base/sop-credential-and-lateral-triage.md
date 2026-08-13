# SOP: Credential theft and lateral movement triage

**Document ID:** SOC-SOP-DEMO-022  
**Owner:** SOC Tier 2  
**Applies to:** LSASS access, DCSync, Kerberoasting, and lateral-movement notables

## Credential harvesting

1. Confirm whether `source_process` is a signed, approved security tool (e.g. Defender MsSense.exe).
2. For LSASS access: review `granted_access`, `process_signer`, and whether `dcsync_indicator` or post-harvest logons follow within minutes.
3. DCSync (Event 4662) without backup/PAM context requires immediate identity team escalation.

## Lateral movement / Kerberoasting

1. High-volume RC4 `4769` requests from non-admin accounts suggest Kerberoasting.
2. `key_length=0` with NTLM and `pass_the_hash_indicator=true` suggest pass-the-hash.
3. Compare `source_is_approved_jump_host`, `pam_ticket`, and `change_ticket` before treating Tier-0 RDP as malicious.

## Hunting queries

- **Kerberoasting (SPL):** `index=wineventlog EventCode=4769 TicketEncryptionType=0x17 | stats count by user service_name`
- **PtH (SPL):** `index=wineventlog EventCode=4624 key_length=0 authentication_package=NTLM`

## Benign indicators

Verified PAM sessions, approved jump hosts, Kerberos (not NTLM) auth with non-zero key length, and documented change tickets for database or backup operations.
