# On-Prem Production Readiness TODO

The core stack is installed, but production readiness is not yet complete.

1. [ ] Finish VM recovery and confirm one synthetic notable reaches `processed`,
   creates a report, and appears in the portal.
2. [ ] Pull the reset-script fix onto the VM and verify reset preserves all
   runtime directories. The code fix is on remote `main`.
3. [ ] Validate real SOAR SFTP uploads. Uploaded files must be readable by
   `notable-analyzer`; the manual test exposed an incomplete
   ownership/permission contract.
4. [x] Fix the smoke script's authenticated LiteLLM `/v1/models` check. The fix
   is on remote `main`.
5. [ ] Configure production portal access: internal DNS, corporate TLS
   certificate, firewall access to TCP 443, and loopback-only ports 8000 and
   8080.
6. [ ] Replace lab Basic Auth credentials and obtain approval for Basic Auth or
   implement the documented corporate OIDC future state.
7. [ ] Pre-stage embedding/model assets and confirm the running stack makes no
   Hugging Face or other public downloads.
8. [ ] Run the full offline test suite, service-chain smoke test,
   malformed-input quarantine test, portal/chat test, and host reboot test.
9. [ ] Validate backups/restoration, retention timer, log forwarding, disk/GPU
   monitoring, and certificate-expiration monitoring.
10. [ ] Benchmark representative production notables and chat concurrency using
    the selected hardware profile.
11. [ ] Validate Splunk, ServiceNow, Elasticsearch, and writeback approval
    controls only for profiles intended for production.

Immediate priorities are VM recovery verification, deployment verification of
the reset fix, and the SOAR SFTP ownership/permission contract. The reset and
smoke-script code fixes are already committed to remote `main`.

