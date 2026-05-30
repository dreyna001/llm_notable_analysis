# ServiceNow Operations

## What This Controls

This guide covers optional ServiceNow incident draft creation and
approval-gated incident create for AWS notable analysis.

## Recommended Starting Posture

Start with `SERVICENOW_DRAFT_ENABLED=false` and
`SERVICENOW_CREATE_ENABLED=false`. Enable `ticket_draft` first so analysts can
review generated incident payloads without network side effects. Enable create
only in `action_gated` deployments with idempotency and payload approval.

## Customer Decisions

- Which assignment group should receive incident drafts?
- Which ServiceNow instance and table path should be used?
- Who is allowed to set `servicenow_create_approval` in the incoming notable
  payload?
- How long should DynamoDB idempotency rows be retained?

## Config Quick Reference

- `CAPABILITY_PROFILES=core,ticket_draft`
- `CAPABILITY_PROFILES=core,action_gated`
- `SERVICENOW_BASE_URL`
- `SERVICENOW_CREATE_PATH`
- `SERVICENOW_API_TOKEN_SECRET_ARN`
- `SERVICENOW_ASSIGNMENT_GROUP`
- `SERVICENOW_TIMEOUT_SECONDS`
- `SERVICENOW_CREATE_REQUIRES_APPROVAL`
- `SIDE_EFFECT_IDEMPOTENCY_TABLE`

Create approval payload:

```json
{
  "servicenow_create_approval": {
    "approved": true,
    "approved_by": "analyst@example.com",
    "approval_ref": "CHANGE-123",
    "approved_at": "2026-05-29T21:00:00Z"
  }
}
```

## Validation And Rollout

1. Confirm draft output appears under `servicenow_section.draft` with no HTTP
   call.
2. Confirm create is denied without approval metadata.
3. Confirm Secrets Manager contains only the token value or `{"token": "..."}`.
4. Confirm duplicate approved creates are skipped by DynamoDB idempotency.

Unit test command:

```bash
python -m unittest discover -s s3_notable_pipeline/tests -p "test_servicenow.py" -v
```

## Related Docs

- `SPLUNK_WRITEBACK_OPERATIONS.md`
- `SECURITY_OPERATIONS.md`
- `../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`
