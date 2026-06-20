# Splunk Writeback Operations

This guide helps customers tune optional Splunk notable comment writeback. It is
separate from read-only SPL investigation execution in
[`SPL_OPERATIONS.md`](../investigation/SPL_OPERATIONS.md).

## What This Controls

When `SPLUNK_SINK_ENABLED` is true (via `action_gated` or an explicit env
override), `update_splunk_notable()` in `sinks.py` POSTs the generated markdown
report to Splunk ES as a notable comment. The request uses form fields
`finding_id`, `comment`, and `status=2` (In Progress). `SPLUNK_BASE_URL` must
be HTTPS; the call uses a 30-second timeout.

This is a writeback path and should be approved separately from read-only search
execution.

## Recommended Starting Posture

- Keep `CAPABILITY_PROFILES=core` until report quality and identifier mapping
  are validated.
- Add `action_gated` only after the Splunk owner approves notable comment
  writeback.
- Use a lab Splunk environment or test notable first.
- Use a dedicated token with the minimum writeback capability.
- Keep TLS verification enabled; use `SPLUNK_CA_BUNDLE` for internal CAs.
- Keep side-effect idempotency enabled (`action_gated` turns it on).

## Customer Decisions

### Should writeback be enabled?

**Profile:** `action_gated` (sets `SPLUNK_SINK_ENABLED=true`)

- Enable only when analysts want the full markdown report attached to the
  originating notable.
- Keep disabled if reports are consumed from `REPORT_DIR` or another downstream
  process.
- Lab override: `SPLUNK_SINK_ENABLED=true` without `action_gated` is supported
  but does not enable idempotency by default.

### Which Splunk endpoint is correct?

**Settings:** `SPLUNK_BASE_URL`, `SPLUNK_NOTABLE_UPDATE_PATH`

- Confirm the endpoint with the Splunk ES owner; deployments often differ.
- Default path: `/services/notable_update`.
- Confirm the field used to identify the notable before production.

### Which token and TLS posture should be used?

**Settings:** `SPLUNK_API_TOKEN`, `SPLUNK_CA_BUNDLE`

- Use HTTPS and verify TLS by default.
- Configure an internal CA bundle instead of disabling verification.
- Keep the token out of source control and restrict config file permissions.
- Prefer separate identities for writeback and read-only investigation when the
  customer's Splunk governance supports it.

### How is the notable matched?

`finding_id` is the input filename stem (`file_path.stem`), for example
`abc123.json` -> `abc123`. The service sends that value as the `finding_id` form
field. Customers must confirm this mapping matches their SOAR/Splunk handoff
before enabling production writeback. An empty stem returns error and skips the
POST.

## Config Quick Reference

| Area | Primary variables |
|------|-------------------|
| Enablement | `CAPABILITY_PROFILES=core,action_gated`, `SPLUNK_SINK_ENABLED` |
| Endpoint | `SPLUNK_BASE_URL`, `SPLUNK_NOTABLE_UPDATE_PATH` |
| Auth/TLS | `SPLUNK_API_TOKEN`, `SPLUNK_CA_BUNDLE` |
| Idempotency | `SIDE_EFFECT_IDEMPOTENCY_ENABLED`, `SIDE_EFFECT_IDEMPOTENCY_DIR`, `SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS` |

When idempotency is enabled, Splunk writeback uses operation
`splunk_notable_update` with key `finding_id`. A completed marker skips the
POST on replay. Failed POSTs release the lock without writing a marker (safe to
retry). `SIDE_EFFECT_IDEMPOTENCY_DIR` must be an absolute path.

## Validation And Rollout

1. Generate reports locally with `CAPABILITY_PROFILES=core`.
2. Confirm filename stem to notable identifier mapping with the Splunk owner.
3. Add `action_gated` in lab with a test notable.
4. Verify the comment appears in Splunk ES and contains the expected report.
5. Confirm failed writeback still writes local reports and moves the input to
   `PROCESSED_DIR` without auto-retry (see recovery doc).
6. Promote with token rotation and endpoint ownership documented.

## Related Docs

- [`SPL_OPERATIONS.md`](../investigation/SPL_OPERATIONS.md) — read-only SPL
  generation and execution (separate credentials path).
- [`SECURITY_OPERATIONS.md`](../security/SECURITY_OPERATIONS.md)
- [`RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](../platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md) —
  crash/replay windows, idempotency mechanics, and processed-dir behavior when
  writeback fails.
