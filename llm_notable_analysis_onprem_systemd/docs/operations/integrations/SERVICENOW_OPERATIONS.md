# ServiceNow Operations

This guide helps customers tune optional ServiceNow incident draft and create
behavior. It covers capability profiles, routing, approval boundaries, token
handling, idempotency, and rollout.

## What This Controls

The analyzer can build a ServiceNow incident draft from validated analysis
output and render it in report metadata. With create enabled, it can POST that
draft to the ServiceNow Incident Table API only when create is enabled and, by
default, payload-level approval is present.

Results are recorded under `servicenow_section` in the analysis output:
`draft.status` / `draft.message` and `create.status` / `create.message` /
`create.number` / `create.sys_id` / `create.approval`.

## Recommended Starting Posture

- Add `ticket_draft` first and validate draft payloads in reports.
- Add `action_gated` only after the ServiceNow owner approves incident create.
- Configure `SERVICENOW_ASSIGNMENT_GROUP` before draft mode.
- Keep `SERVICENOW_CREATE_REQUIRES_APPROVAL=true`.
- Set `SERVICENOW_BASE_URL`, `SERVICENOW_API_TOKEN`, and `SERVICENOW_CREATE_PATH`
  before enabling create.
- Use HTTPS only for `SERVICENOW_BASE_URL`.
- Validate with a lab/test ServiceNow instance before production.

## Customer Decisions

### Draft only or create?

**Profiles:** `ticket_draft`, `action_gated`

| Profile | Sets |
|---------|------|
| `ticket_draft` | `SERVICENOW_DRAFT_ENABLED=true` |
| `action_gated` | `SERVICENOW_DRAFT_ENABLED=true`, `SERVICENOW_CREATE_ENABLED=true`, `SERVICENOW_CREATE_REQUIRES_APPROVAL=true`, `SIDE_EFFECT_IDEMPOTENCY_ENABLED=true` (also enables Splunk notable writeback; see [`SPLUNK_WRITEBACK_OPERATIONS.md`](SPLUNK_WRITEBACK_OPERATIONS.md)) |

- Draft mode has no downstream side effect: `CAPABILITY_PROFILES=core,ticket_draft`.
- Create mode opens a real incident and is writeback:
  `CAPABILITY_PROFILES=core,action_gated`.
- Direct `SERVICENOW_DRAFT_ENABLED` / `SERVICENOW_CREATE_ENABLED` flags exist for
  lab use; profile selection takes precedence over the baseline `false` values
  in `config.env.example`.
- Keep create disabled until assignment group, token, approval flow, and incident
  field expectations are signed off.

### What approval is required?

**Setting:** `SERVICENOW_CREATE_REQUIRES_APPROVAL` (default `true`; forced
`true` by `action_gated`)

Approval is read from the root of the incoming alert JSON via
`servicenow_create_approval`:

```json
{
  "servicenow_create_approval": {
    "approved": true,
    "approved_by": "analyst@example.com",
    "approval_ref": "SNOW-CHANGE-123",
    "approved_at": "2026-04-27T19:40:00Z"
  }
}
```

When approval is required:

- `approved` must be `true`.
- `approved_by` must be a non-empty string.
- `approval_ref` and `approved_at` are optional; they are stored in create
  metadata but are not validated.

If approval is missing or invalid, create status is `denied` and the reason is
recorded in report metadata. Do not set `SERVICENOW_CREATE_REQUIRES_APPROVAL=false`
unless the customer has explicitly accepted automatic incident creation.

Create is also denied when the draft step did not produce a usable
`incident_payload` (for example, missing assignment group).

### Which routing and fields are acceptable?

**Settings:** `SERVICENOW_ASSIGNMENT_GROUP`, `SERVICENOW_CREATE_PATH`

- `SERVICENOW_ASSIGNMENT_GROUP` is required when draft is enabled; draft fails
  with status `error` if it is empty.
- Default create path: `/api/now/table/incident`. Change only when the
  customer's instance requires a supported equivalent; path must be non-empty
  and start with `/`.
- Draft payload uses fixed standard fields: `short_description`, `description`,
  `assignment_group`, `category` (`security`), `subcategory` (`analysis`),
  `impact` (`2`), `urgency` (`2`), `correlation_id` (`finding_id` or
  `notable_id`), `correlation_display` (`notable_id`), and `work_notes`.
  Custom fields are not configurable.

### How should auth and timeout be set?

**Settings:** `SERVICENOW_BASE_URL`, `SERVICENOW_API_TOKEN`,
`SERVICENOW_TIMEOUT_SECONDS`

- `SERVICENOW_BASE_URL` must use HTTPS when create is enabled.
- Create uses `Authorization: Bearer <SERVICENOW_API_TOKEN>` and
  `Content-Type: application/json`.
- Token is required for create; store it only in protected host config or the
  customer's secret process.
- Default timeout is 15 seconds; keep it bounded so create cannot stall the
  analyzer.

## Config Quick Reference

| Area | Primary variables |
|------|-------------------|
| Enablement | `CAPABILITY_PROFILES=core,ticket_draft` or `CAPABILITY_PROFILES=core,action_gated`; direct flags `SERVICENOW_DRAFT_ENABLED`, `SERVICENOW_CREATE_ENABLED`; gate `SERVICENOW_CREATE_REQUIRES_APPROVAL` |
| Endpoint/auth | `SERVICENOW_BASE_URL`, `SERVICENOW_CREATE_PATH`, `SERVICENOW_API_TOKEN`, `SERVICENOW_TIMEOUT_SECONDS` |
| Routing | `SERVICENOW_ASSIGNMENT_GROUP` |
| Payload approval | `servicenow_create_approval` object in incoming alert JSON |
| Idempotency | `SIDE_EFFECT_IDEMPOTENCY_ENABLED` (on with `action_gated`), `SIDE_EFFECT_IDEMPOTENCY_DIR`, `SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS` |

When side-effect idempotency is enabled, ServiceNow create uses draft
`correlation_id` or `correlation_display` as the operation key. Create fails
before POST if neither value is present or the key is generic (`unknown`,
`none`, `null`, `n/a`, `na`). `SIDE_EFFECT_IDEMPOTENCY_DIR` must be an
absolute, writable path. A duplicate successful create returns create status
`skipped` with the prior `sys_id` and `number`.

## Validation And Rollout

1. Add `ticket_draft` and confirm draft metadata in `servicenow_section`.
2. Confirm assignment group value and field shape with the ServiceNow owner.
3. Add `action_gated` in a lab instance with approval metadata present.
4. Confirm create status `denied` when approval metadata is missing or
   `approved_by` is empty.
5. Confirm incident `number` and `sys_id` appear in create metadata on success.
6. Re-run the same notable and confirm idempotent `skipped` behavior when
   idempotency is enabled.
7. Promote to production only after token ownership and approval workflow are
   documented.

## Related Docs

- [`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md)
- [`../../delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md`](../../delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md)
- [`../security/SECURITY_OPERATIONS.md`](../security/SECURITY_OPERATIONS.md)
- [`../platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](../platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md)
- [`SPLUNK_WRITEBACK_OPERATIONS.md`](SPLUNK_WRITEBACK_OPERATIONS.md)
