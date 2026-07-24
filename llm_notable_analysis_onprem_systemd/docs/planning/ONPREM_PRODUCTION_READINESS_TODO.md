# On-Prem Production Readiness TODO

The core stack is installed, but production readiness is not yet complete.

1. [x] Finish VM recovery and confirm one synthetic notable reaches `processed`,
   creates a report, and appears in the portal.
2. [x] Pull the reset-script fix onto the VM and verify reset preserves all
   runtime directories. The code fix is on remote `main`.
3. [ ] Validate real SOAR SFTP uploads. Uploaded files must be readable by
   `notable-analyzer`; the manual test exposed an incomplete
   ownership/permission contract.
4. [x] Fix the smoke script's authenticated LiteLLM `/v1/models` check. The fix
   is on remote `main`.
5. [ ] Configure production portal access: internal DNS, a trusted corporate,
   internal-CA, or approved self-signed TLS certificate, firewall access to TCP
   443, and loopback-only ports 8000 and 8080.
6. [ ] Operationalize nginx Basic Auth for this customer deployment:
   - [ ] Approve and record that every authenticated analyst can view every
     retained case.
   - [ ] Replace the shared lab account and password with named analyst accounts
     using corporate-compliant passwords and bcrypt-backed htpasswd entries.
   - [ ] Require trusted HTTPS and restrict the htpasswd file to `root` and the
     nginx service group.
   - [ ] Document ownership for account creation, password rotation, revocation,
     and analyst offboarding; use the approved password vault or the documented
     no-vault fallback below.
   - [ ] Confirm failed logins return `401` and access logs identify the
     authenticated username.
   - Corporate OIDC is deferred for this customer deployment.
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

## Basic Auth Item 6: What, Why, How, and Where

| Check | What | Why | How | Where |
| --- | --- | --- | --- | --- |
| Access-model approval | Confirm that any authenticated analyst can view every retained case. | Basic Auth proves identity but the portal does not provide per-case authorization. | Record customer security and SOC owner acceptance before go-live. | Readiness approval record and this checklist. |
| Named bcrypt accounts | Give each analyst a username whose password is stored only as a salted bcrypt hash, never as readable plaintext. | Named accounts improve accountability and bcrypt makes stolen password hashes expensive to guess. | Remove the shared lab account and run `htpasswd -B`, which prompts for the password and writes a `$2y$...` bcrypt hash. | `/etc/nginx/htpasswd/notable-portal` on the portal VM. |
| Trusted HTTPS and protected password file | Encrypt credentials in transit and limit access to stored password hashes. | Basic Auth credentials are only safely protected in transit by TLS, while file restrictions reduce offline hash exposure. | Prefer a corporate or internal CA; otherwise use the explicitly trusted self-signed fallback below, and restrict the htpasswd file to `root` and the nginx service group. | `/etc/nginx/tls/`, `/etc/nginx/htpasswd/notable-portal`, and `/etc/nginx/conf.d/notable-portal.conf`. |
| Account lifecycle and password storage | Assign responsibility for account creation, rotation, revocation, offboarding, and user-side password storage. | Unowned accounts and unmanaged passwords commonly remain active beyond their approved need. | Use the approved vault when available; otherwise use the documented no-vault fallback below. | Customer identity/access process, analyst credential manager, and portal operations record. |
| Authentication validation and logging | Prove denied and successful logins behave correctly and identify the user. | Operators need evidence that access is enforced and attributable during investigations. | Test invalid and valid credentials, confirm `401` for failures, and inspect `$remote_user` in access logs. | Portal HTTPS endpoint and `/var/log/nginx/notable-portal.access.log`. |
| OIDC deferral | Treat corporate OIDC as intentionally deferred rather than an untracked omission. | The customer selected Basic Auth for this VM, so ownership and future reconsideration should remain explicit. | Record Basic Auth as the approved production choice and revisit OIDC only when requirements change. | Customer architecture/security decision record and this checklist. |

## Fallbacks When Enterprise Services Are Unavailable

- **No corporate TLS certificate:** Prefer any available internal/private CA.
  If none exists, create a self-signed certificate whose SAN matches the final
  portal hostname, distribute that certificate to approved analyst
  workstations, and install it in their trusted certificate store. Verify its
  fingerprint through a separate trusted channel, protect the private key as
  `root:root` mode `0600`, assign a renewal owner, and never treat clicking
  through a browser warning as production trust.
- **No password vault:** The portal VM stores only bcrypt hashes, so it does not
  need recoverable plaintext passwords. Have each analyst store their own
  password in the operating-system or browser credential manager; create or
  deliver initial credentials through an approved encrypted or in-person
  channel, never email/chat/source control/plaintext files. Administrators reset
  forgotten passwords rather than retrieve them, and the customer records this
  exception and the account-lifecycle owner.

Immediate priorities are the SOAR SFTP ownership/permission contract,
production portal network access, and Basic Auth operationalization. The reset
and smoke-script code fixes are already committed to remote `main`.
