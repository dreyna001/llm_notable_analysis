# Security Operations

Customer decisions for exposure, secrets, TLS, permissions, systemd hardening,
and audit posture. Implemented controls are in
[`../../security/SECURITY_POSTURE.md`](../../security/SECURITY_POSTURE.md).

Portal chat non-execution boundaries: [`../analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md`](../analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md).

Analyst portal network exposure (nginx, TLS, basic auth): [`../analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md).

## What This Controls

Host-level and configuration choices that affect risk: service identities,
systemd sandboxing, loopback inference, SFTP ingest, protected config files,
outbound integration tokens, TLS verification, runtime artifact handling, and
logging.

## Recommended Starting Posture

- Keep LiteLLM (`127.0.0.1:4000`) and vLLM (`127.0.0.1:8000`) on loopback.
- Keep `/etc/notable-analyzer/config.env` and `/etc/notable-analyzer/portal.env`
  at mode `600`, owned by `notable-analyzer`.
- Keep `/etc/litellm/config.yaml` at mode `600`, owned by `litellm`.
- Split credentials by role: analyzer uses `config.env`; portal uses `portal.env`
  (no Splunk, ServiceNow, or SOAR action secrets in the portal process).
- Use separate, least-privilege Splunk and ServiceNow tokens where governance
  allows (read-only search scope vs writeback scope; ServiceNow create vs draft).
- Verify TLS for outbound HTTPS; use `SPLUNK_CA_BUNDLE` for internal CAs.
- Keep production notables, model weights, KB indexes, tokens, and customer data
  out of source control.
- Leave vLLM `--trust-remote-code` disabled unless a verified offline model
  import explicitly requires it.

## Service Identities And Systemd Hardening

The installer creates non-login users: `notable-analyzer`, `litellm`, `vllm`,
and `soar-uploader` (SFTP only). `soar-uploader` is in the `notable-analyzer`
group for controlled access to the incoming drop.

| Unit | User | Config source | Hardening notes |
|------|------|---------------|-----------------|
| `notable-analyzer.service` | `notable-analyzer` | `/etc/notable-analyzer/config.env` | Full sandbox: `ProtectSystem=strict`, `RestrictAddressFamilies`, kernel protections, `ReadWritePaths=/var/notables /var/notables/cache /var/sftp/soar` |
| `notable-portal.service` | `notable-analyzer` | `/etc/notable-analyzer/portal.env` | Same sandbox pattern; `ReadOnlyPaths=/etc/notable-analyzer`; writes only under `/var/notables/cache` |
| `notable-retention.service` | `notable-analyzer` | `config.env` | Oneshot; `ProtectSystem=strict`; `ReadWritePaths=/var/notables` |
| `litellm.service` | `litellm` | `/etc/litellm/config.yaml` | Loopback bind; `ProtectSystem=full`; lighter sandbox than analyzer |
| `vllm.service` | `vllm` | unit `Environment=` | Loopback bind; reduced systemd restrictions (no `ProtectSystem`, no `RestrictAddressFamilies`) for Gloo/NCCL bootstrap |

Common directives on analyzer and LiteLLM units: `NoNewPrivileges=yes`, empty
capability sets, `UMask=0077`, `PrivateTmp=yes`, `ProtectHome=yes`, journal
logging. After install, verify units were not modified to widen bind addresses
or drop sandbox settings.

## SFTP Ingest

SOAR file delivery uses `soar-uploader` with an sshd `Match` block: chroot
`/var/sftp/soar`, `ForceCommand internal-sftp`, forwarding disabled, password
auth disabled. Chroot parent is `root:root` `755`; incoming drop is
`soar-uploader:notable-analyzer` `775`. `/var/notables/incoming` is commonly a
symlink into the chroot. Add SOAR keys only to
`/var/sftp/soar/.ssh/authorized_keys` (`600`).

## Customer Decisions

### What network exposure is allowed?

**Related settings:** `LLM_API_URL`, `SPLUNK_BASE_URL`, `SERVICENOW_BASE_URL`,
`ELASTICSEARCH_BASE_URL`, `PORTAL_BIND_HOST`, `PORTAL_ALLOW_NON_LOOPBACK_BIND`

- Local inference stays loopback unless an authenticated edge listener is
  explicitly approved.
- Outbound Splunk, ServiceNow, and Elasticsearch access should target approved
  internal endpoints only.
- Portal defaults to `127.0.0.1:8080` behind nginx; do not bind the portal
  broadly without TLS and identity controls documented in the portal network guide.
- Document firewall exceptions and owning teams.

### How are secrets supplied and rotated?

**Related settings:** `LLM_API_TOKEN`, `SPLUNK_API_TOKEN`, `SERVICENOW_API_TOKEN`,
`ELASTICSEARCH_API_KEY`, `PORTAL_PROXY_SECRET`, `CASE_POSTGRES_DSN`

| File | Holds | Permissions |
|------|-------|-------------|
| `/etc/notable-analyzer/config.env` | Analyzer runtime, integrations, retention | `600`, `notable-analyzer:notable-analyzer` |
| `/etc/notable-analyzer/portal.env` | Portal LLM, Postgres read path, proxy secret | `600`, `notable-analyzer:notable-analyzer` |
| `/etc/litellm/config.yaml` | LiteLLM routing (may reference upstream auth) | `600`, `litellm:litellm` |

- Do not commit tokens or paste secrets into KB source docs.
- Prefer host-managed protected files or the customer's approved secret store;
  the repo does not integrate external vaults.
- Document rotation owner, cadence, and emergency revocation for each token.
- `LLM_API_TOKEN` is optional on loopback; set only when LiteLLM or vLLM enforces
  API-key auth.
- `PORTAL_PROXY_SECRET` is generated at install and shared with nginx; rotate with
  coordinated portal and proxy restarts.
- When both `spl_readonly` and `action_gated` are enabled, prefer distinct
  Splunk tokens scoped to search vs notable update even though both use
  `SPLUNK_API_TOKEN` today.

### How is TLS handled?

**Related settings:** `SPLUNK_CA_BUNDLE`, HTTPS base URLs for Splunk, ServiceNow,
Elasticsearch

- Splunk writeback verifies TLS by default; unset `SPLUNK_CA_BUNDLE` uses the
  system trust store.
- Elasticsearch execution requires HTTPS when enabled (API key in headers).
- Do not disable verification in production paths.
- Confirm certificate ownership and expiration monitoring with platform teams.
- Portal TLS terminates at nginx; certificate and cipher policy are customer-operated.

### What data may live on the host?

**Related paths:** `/var/notables/*`, KB source docs, `/opt/models/*`, Hugging
Face caches (`HF_HOME`, `SENTENCE_TRANSFORMERS_HOME`)

- Only `*.json` and `*.txt` in `INCOMING_DIR` are processed (no recursion).
- Invalid inputs go to quarantine; notable IDs in output filenames are sanitized.
- Govern raw notables, reports, and quarantine content via retention settings.
- Structured JSON logs (journald) include correlation IDs; review whether inbound
  notable fields require log redaction or restricted forwarding.
- Ensure backups and exports follow the customer's incident data policy.

## Config Quick Reference

| Area | Primary variables |
|------|-------------------|
| Capability bundles | `CAPABILITY_PROFILES` |
| Local inference | `LLM_API_URL`, `LLM_API_TOKEN`, `LLM_MODEL_NAME` |
| Splunk auth/TLS | `SPLUNK_API_TOKEN`, `SPLUNK_CA_BUNDLE`, `SPLUNK_BASE_URL` |
| Splunk read-only | `SPLUNK_SEARCH_*` allowlists and bounds (profile `spl_readonly`) |
| ServiceNow auth | `SERVICENOW_API_TOKEN`, `SERVICENOW_BASE_URL`, `SERVICENOW_CREATE_REQUIRES_APPROVAL` |
| Elasticsearch read-only | `ELASTICSEARCH_API_KEY`, `ELASTICSEARCH_BASE_URL` |
| Portal boundary | `PORTAL_BIND_HOST`, `PORTAL_PROXY_SECRET`, `PORTAL_ALLOW_NON_LOOPBACK_BIND` |
| Runtime paths | `INCOMING_DIR`, `REPORT_DIR`, `QUARANTINE_DIR`, `ARCHIVE_DIR` |
| Retention | `INPUT_RETENTION_DAYS`, `REPORT_RETENTION_DAYS`, `ARCHIVE_RETENTION_DAYS` |
| Model/cache paths | `HF_HOME`, `SENTENCE_TRANSFORMERS_HOME` |

## Validation And Rollout

1. Verify service users, unit hardening, and file permissions after install.
2. Confirm LiteLLM and vLLM bind to loopback (`ss` / `curl` to local endpoints).
3. Confirm `config.env`, `portal.env`, and LiteLLM config are `600` and owned
   correctly; portal process must not load action integration secrets.
4. Validate TLS to Splunk, ServiceNow, and Elasticsearch in lab before production.
5. Run a known-good file-drop test; confirm journal logs do not expose tokens.
6. Review retention settings and log forwarding with data owners.
7. If `action_gated` is enabled, confirm writeback mapping and approval gates
   with integration owners before production traffic.

## Supply Chain And FIPS

- Pin Python dependencies from approved mirrors or offline wheelhouses; generate
  an evidence bundle with `scripts/tools/generate_dependency_manifest.sh`.
- FIPS mode is an environment requirement (OS, OpenSSL, approved endpoints);
  see supply-chain and FIPS sections in [`SECURITY_POSTURE.md`](../../security/SECURITY_POSTURE.md).

## Related Docs

- [`../../security/SECURITY_POSTURE.md`](../../security/SECURITY_POSTURE.md)
- [`../deployment/INSTALL.md`](../deployment/INSTALL.md)
- [`../platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../platform/FILE_DROP_AND_RETENTION_OPERATIONS.md)
- [`../integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](../integrations/SPLUNK_WRITEBACK_OPERATIONS.md)
- [`../integrations/SERVICENOW_OPERATIONS.md`](../integrations/SERVICENOW_OPERATIONS.md)
- [`../investigation/SPL_OPERATIONS.md`](../investigation/SPL_OPERATIONS.md)
- [`../analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md`](../analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md)
- [`../analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md)
