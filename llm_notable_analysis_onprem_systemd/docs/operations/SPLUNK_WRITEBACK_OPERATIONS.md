# Splunk Writeback Operations

This guide helps customers tune optional Splunk notable comment writeback. It is
separate from read-only SPL investigation execution in
[`SPL_OPERATIONS.md`](SPL_OPERATIONS.md).

## What This Controls

When the `action_gated` profile is selected, the analyzer can post the
generated markdown report back to Splunk ES as a notable comment using the
configured REST endpoint. This is a writeback path and should be approved
separately from read-only search execution.

## Recommended Starting Posture

- Keep `CAPABILITY_PROFILES=core` until report quality and identifier mapping
  are validated.
- Add `action_gated` only after the Splunk owner approves notable comment
  writeback.
- Use a lab Splunk environment or test notable first.
- Use a dedicated token with the minimum writeback capability.
- Keep TLS verification enabled; use `SPLUNK_CA_BUNDLE` for internal CAs.
- Keep side-effect idempotency enabled for writeback retries.

## Customer Decisions

### Should writeback be enabled?

**Profile:** `action_gated`

- Enable only when analysts want the full markdown report attached to the
  originating notable.
- Keep disabled if reports are consumed from `REPORT_DIR` or another downstream
  process.

### Which Splunk endpoint is correct?

**Settings:** `SPLUNK_BASE_URL`, `SPLUNK_NOTABLE_UPDATE_PATH`

- Confirm the endpoint with the Splunk ES owner; deployments often differ.
- The default path is suitable for many ES deployments but is not a universal
  guarantee.
- Confirm the field used to identify the notable before production.

### Which token and TLS posture should be used?

**Settings:** `SPLUNK_API_TOKEN`, `SPLUNK_CA_BUNDLE`

- Use HTTPS and verify TLS by default.
- Configure an internal CA bundle instead of disabling verification.
- Keep the token out of source control and restrict config file permissions.
- Prefer separate identities for writeback and read-only investigation when the
  customer's Splunk governance supports it.

### How is the notable matched?

The current writeback identifier is derived from the input filename stem and
sent as `finding_id`. Customers must confirm that this mapping matches their
SOAR/Splunk handoff before enabling production writeback.

## Config Quick Reference

| Area | Primary variables |
|------|-------------------|
| Enablement | `CAPABILITY_PROFILES=core,action_gated` |
| Endpoint | `SPLUNK_BASE_URL`, `SPLUNK_NOTABLE_UPDATE_PATH` |
| Auth/TLS | `SPLUNK_API_TOKEN`, `SPLUNK_CA_BUNDLE` |
| Idempotency | `SIDE_EFFECT_IDEMPOTENCY_DIR`, `SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS` |

When side-effect idempotency is enabled, Splunk writeback uses `finding_id` as
the operation key.

## Validation And Rollout

1. Generate reports locally with `CAPABILITY_PROFILES=core`.
2. Confirm filename stem to notable identifier mapping with the Splunk owner.
3. Add `action_gated` in lab with a test notable.
4. Verify the comment appears in Splunk ES and contains the expected report.
5. Confirm failed writeback behavior still writes local reports and preserves
   processed/quarantine semantics.
6. Promote with token rotation and endpoint ownership documented.

## Related Docs

- [`SPL_OPERATIONS.md`](SPL_OPERATIONS.md)
- [`SECURITY_OPERATIONS.md`](SECURITY_OPERATIONS.md)
- [`RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md)

