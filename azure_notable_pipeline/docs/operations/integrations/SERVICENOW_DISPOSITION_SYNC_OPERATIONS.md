# Azure ServiceNow closed-disposition sync operations

This optional daily timer is read-only toward ServiceNow: closed security
incidents are normalized into Cosmos. It never creates or updates a ServiceNow
ticket. Model verdict and analyst disposition remain separate fields.

## Prerequisites and contract

Use a dedicated Table API read identity/token stored in Key Vault under
`SERVICENOW_DISPOSITION_SYNC_TOKEN_SECRET_NAME`; never reuse the outbound create
token. Configure validated field/code maps from
`deploy/servicenow/disposition_*_example.json`, customer closed-state values,
`DISPOSITION_CONTAINER`, and `DISPOSITION_SYNC_STATE_CONTAINER`. Defaults are
disabled, 90-day initial backfill, and 365-day disposition retention.

Disposition documents partition by `/snow_sys_id`; checkpoint state partitions
by `/job_name`. Incremental reads use `sys_updated_on`. Authentication, malformed
page threshold, or request failure leaves the cursor unadvanced. Reopened rows
remain auditable and become inactive. Correlation linking is exact only; no
fuzzy/time match is permitted.

## Dry run and rollout

1. Keep `SERVICENOW_DISPOSITION_SYNC_ENABLED=false` and run
   `scripts/test-pipeline.*`; the disabled timer path must skip, and native fake
   tests prove map, upsert, link, ETag, retention, and checkpoint behavior.
2. Validate maps against a sanitized ServiceNow response and confirm the token
   has read-only access to the one table.
3. In an isolated ServiceNow test instance, enable sync and manually invoke the
   timer from the Functions admin endpoint using a short-lived host key obtained
   at execution time. Do not store or log the key.
4. Confirm normalized Cosmos rows and cursor, then test close, reopen, no-row,
   401/403, 429, malformed-row, and rerun/idempotency outcomes.
5. Enable the daily schedule only after the ServiceNow owner approves field,
   state, and code mappings.

Manual invocation is an operational action, not a public HTTP route. Prefer the
Azure portal's Function **Code + Test / Run** control or POST the timer admin
endpoint from the private operator runner with the ephemeral master key; record
only invocation time, Function name, result counts, and operation ID.

Alert on a missed daily success, auth failure, repeated retryable failures,
malformed-page rejection, and Cosmos throttling. Recovery corrects the cause and
reruns from the unchanged cursor. Roll back by disabling the setting/schedule;
do not delete disposition or checkpoint containers during incident response.
