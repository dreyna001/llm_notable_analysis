# ServiceNow Operations

This guide helps customers tune optional ServiceNow incident draft and create
behavior. It covers routing, approval boundaries, token handling, and rollout.

## What This Controls

The analyzer can build a ServiceNow incident draft from the validated analysis
output. It can also create an incident through the ServiceNow Incident Table API
only when create is enabled and, by default, payload-level approval is present.

## Recommended Starting Posture

- Enable draft first: `SERVICENOW_DRAFT_ENABLED=true`,
  `SERVICENOW_CREATE_ENABLED=false`.
- Configure `SERVICENOW_ASSIGNMENT_GROUP` before draft mode.
- Keep `SERVICENOW_CREATE_REQUIRES_APPROVAL=true`.
- Use HTTPS only for `SERVICENOW_BASE_URL`.
- Validate with a lab/test ServiceNow instance before production.

## Customer Decisions

### Draft only or create?

**Settings:** `SERVICENOW_DRAFT_ENABLED`, `SERVICENOW_CREATE_ENABLED`

- Draft mode creates no downstream side effect and is suitable for initial
  validation.
- Create mode opens a real incident and should be treated as writeback.
- Keep create disabled until assignment group, token, approval flow, and
  incident field expectations are signed off.

### What approval is required?

**Setting:** `SERVICENOW_CREATE_REQUIRES_APPROVAL`

Default posture requires explicit approval in the incoming alert payload:

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

If approval is missing or invalid, create is denied and recorded in report
metadata. Do not turn approval off unless the customer has explicitly accepted
automatic incident creation for this workflow.

### Which routing and fields are acceptable?

**Settings:** `SERVICENOW_ASSIGNMENT_GROUP`, `SERVICENOW_CREATE_PATH`

- Use a standard assignment group approved by the ServiceNow owner.
- Keep the default incident table path unless the customer's instance requires a
  supported equivalent.
- The current draft uses standard incident fields; custom fields are out of
  scope for config-only tuning.

### How should auth and timeout be set?

**Settings:** `SERVICENOW_BASE_URL`, `SERVICENOW_API_TOKEN`,
`SERVICENOW_TIMEOUT_SECONDS`

- `SERVICENOW_BASE_URL` must use HTTPS.
- Store tokens only in protected host config or the customer's secret process.
- Keep timeout bounded so incident create cannot stall the analyzer.

## Config Quick Reference

| Area | Primary variables |
|------|-------------------|
| Enablement | `SERVICENOW_DRAFT_ENABLED`, `SERVICENOW_CREATE_ENABLED`, `SERVICENOW_CREATE_REQUIRES_APPROVAL` |
| Endpoint/auth | `SERVICENOW_BASE_URL`, `SERVICENOW_CREATE_PATH`, `SERVICENOW_API_TOKEN`, `SERVICENOW_TIMEOUT_SECONDS` |
| Routing | `SERVICENOW_ASSIGNMENT_GROUP` |
| Payload approval | `servicenow_create_approval` object in incoming alert JSON |

## Validation And Rollout

1. Enable draft only and confirm draft metadata renders in reports.
2. Confirm assignment group and field shape with the ServiceNow owner.
3. Enable create in a lab instance with approval metadata present.
4. Confirm denied behavior when approval metadata is missing.
5. Confirm incident `number` and `sys_id` appear in report metadata on success.
6. Promote to production only after token ownership and approval workflow are
   documented.

## Related Docs

- [`../delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md`](../delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md)
- [`SECURITY_OPERATIONS.md`](SECURITY_OPERATIONS.md)
- [`RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md)

