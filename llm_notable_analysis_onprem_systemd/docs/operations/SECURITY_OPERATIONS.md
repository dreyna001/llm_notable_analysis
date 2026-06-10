# Security Operations

This guide helps customers decide safe operational settings around exposure,
secrets, TLS, permissions, and audit posture. It summarizes customer decisions;
the deeper implemented posture lives in [`../security/SECURITY_POSTURE.md`](../security/SECURITY_POSTURE.md).

Portal chat non-execution boundaries (no tools, no filesystem, no integration
calls from `/api/chat`): [`ANALYST_PORTAL_CHAT_SECURITY.md`](ANALYST_PORTAL_CHAT_SECURITY.md).

## What This Controls

Security operations covers host-level and configuration choices that affect the
analyzer's risk profile: local-only model access, protected config files,
least-privilege service users, TLS validation, outbound integration tokens, and
runtime artifact handling.

## Recommended Starting Posture

- Keep LiteLLM and vLLM on loopback.
- Keep `/etc/notable-analyzer/config.env` permissioned `600`.
- Use separate tokens for read-only Splunk search, Splunk writeback, and
  ServiceNow where customer governance allows.
- Verify TLS by default; use CA bundles for internal CAs.
- Keep production notables, model weights, KB indexes, tokens, and customer data
  out of source control.

## Customer Decisions

### What network exposure is allowed?

**Related settings:** `LLM_API_URL`, `SPLUNK_BASE_URL`,
`SERVICENOW_BASE_URL`

- Local inference should remain loopback unless an authenticated edge listener
  is explicitly approved.
- Outbound Splunk and ServiceNow access should be limited to approved internal
  endpoints.
- Document any firewall exceptions and owning team.

### How are secrets supplied and rotated?

**Related settings:** `LLM_API_TOKEN`, `SPLUNK_API_TOKEN`,
`SERVICENOW_API_TOKEN`

- Do not commit tokens.
- Prefer host-managed protected config or the customer's approved secret store.
- Document rotation owner, rotation cadence, and emergency revocation path.
- Avoid reusing write-capable tokens for read-only execution when possible.

### How is TLS handled?

**Related settings:** `SPLUNK_CA_BUNDLE`, ServiceNow HTTPS base URL

- Use system trust store or an explicit internal CA bundle.
- Do not silently disable verification in production paths.
- Confirm certificate ownership and expiration monitoring with platform teams.

### What data may live on the host?

**Related paths:** runtime directories under `/var/notables`, KB source docs,
model cache paths

- Keep raw notables and reports governed by retention settings.
- Do not put secrets in KB source docs.
- Treat reports and quarantined inputs as potentially sensitive SOC artifacts.
- Ensure backups and exports follow the customer's incident data policy.

## Config Quick Reference

| Area | Primary variables |
|------|-------------------|
| Local inference | `LLM_API_URL`, `LLM_API_TOKEN` |
| Splunk auth/TLS | `SPLUNK_API_TOKEN`, `SPLUNK_CA_BUNDLE` |
| ServiceNow auth | `SERVICENOW_API_TOKEN`, `SERVICENOW_BASE_URL` |
| Runtime paths | `INCOMING_DIR`, `REPORT_DIR`, `QUARANTINE_DIR`, `ARCHIVE_DIR` |
| Retention | `INPUT_RETENTION_DAYS`, `REPORT_RETENTION_DAYS`, `ARCHIVE_RETENTION_DAYS` |
| Model/cache paths | `HF_HOME`, `SENTENCE_TRANSFORMERS_HOME` |

## Validation And Rollout

1. Verify service users and permissions after install.
2. Confirm model endpoints bind to loopback.
3. Confirm config file permissions and token ownership.
4. Validate TLS to Splunk and ServiceNow in lab before production.
5. Run a known-good file-drop test and confirm logs do not expose tokens.
6. Review retention settings with data owners.

## Related Docs

- [`../security/SECURITY_POSTURE.md`](../security/SECURITY_POSTURE.md)
- [`FILE_DROP_AND_RETENTION_OPERATIONS.md`](FILE_DROP_AND_RETENTION_OPERATIONS.md)
- [`SPLUNK_WRITEBACK_OPERATIONS.md`](SPLUNK_WRITEBACK_OPERATIONS.md)
- [`SERVICENOW_OPERATIONS.md`](SERVICENOW_OPERATIONS.md)

