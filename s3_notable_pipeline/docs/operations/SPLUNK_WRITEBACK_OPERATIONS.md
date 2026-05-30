# Splunk Writeback Operations

## What This Controls

This guide covers optional Splunk notable comment writeback through
`SPLUNK_SINK_MODE=notable_rest` and DynamoDB side-effect idempotency.

## Recommended Starting Posture

Keep `SPLUNK_SINK_MODE=s3` for initial validation. For parity deployments that
write back to Splunk, prefer `CAPABILITY_PROFILES=core,action_gated` and keep
`SIDE_EFFECT_IDEMPOTENCY_ENABLED=true`.

The legacy `SPLUNK_SINK_MODE=notable_rest` path remains supported for existing
deployments. New production-oriented deployments should use the action-gated
profile so duplicate S3 events do not create duplicate external updates.

## Customer Decisions

- Which Splunk REST endpoint updates notable comments?
- Which Secrets Manager secret stores the Splunk token?
- What `finding_id` mapping is expected by the Splunk notable update endpoint?
- How long should DynamoDB remember completed writebacks?

## Config Quick Reference

- `SPLUNK_SINK_MODE=notable_rest`
- `SPLUNK_BASE_URL`
- `SPLUNK_API_TOKEN_SECRET_ARN`
- `SPLUNK_API_TOKEN_SECRET_FIELD`
- `SPLUNK_NOTABLE_UPDATE_PATH`
- `SPLUNK_SINK_ENABLED`
- `SIDE_EFFECT_IDEMPOTENCY_ENABLED`
- `SIDE_EFFECT_IDEMPOTENCY_TABLE`
- `SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS`

## Validation And Rollout

1. Run `s3` sink mode first and inspect the markdown report.
2. Enable `notable_rest` with a non-production Splunk endpoint.
3. Upload the same notable twice and verify the second writeback is skipped when
   idempotency is enabled.
4. Confirm CloudWatch logs do not contain tokens or raw authorization headers.

Unit test commands:

```bash
python -m unittest discover -s s3_notable_pipeline/tests -p "test_idempotency.py" -v
python -m unittest discover -s s3_notable_pipeline/tests -p "test_lambda_handler.py" -v
```

## Related Docs

- `SERVICENOW_OPERATIONS.md`
- `SECURITY_OPERATIONS.md`
- `../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`
