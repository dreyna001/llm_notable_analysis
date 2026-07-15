# ServiceNow writeback operations

## Separate the three paths

| Path | Direction | Default | Approval |
| --- | --- | --- | --- |
| Draft | Pipeline to analyst | Disabled | Human review before use |
| Create | Pipeline to ServiceNow | Disabled | Explicit approval, secret/identity, idempotency, and reconciliation |
| Disposition sync | ServiceNow to pipeline | Disabled | Separate read-only credential and cursor owner |

The existing [closed-disposition sync runbook](SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md)
defines the inbound path. It must not share a create token, cursor, or approval
secret with outbound operations.

## Create boundary

ServiceNow create requires a customer-configured base URL and path, approved
field map, assignment group, Key Vault secret name or workload identity,
approval artifact, stable correlation/finding ID, and side-effect idempotency
container. Validate URL, payload fields, size, allowed values, and ownership
before sending. Do not accept arbitrary model-generated field names or URLs.

Persist a durable draft/result before attempting create. If the request times
out after submission, mark `external_success_unrecorded` and reconcile by the
stable idempotency key; never blindly retry a create. A successful response
must be recorded with the remote `sys_id` and operation metadata.

## Rollout and rollback

Keep create disabled in staging. Test draft rendering, missing approval,
malformed mapping, duplicate delivery, remote 4xx/5xx, timeout-after-commit,
and rerun behavior with fake responses. In an isolated ServiceNow instance,
perform one approved synthetic create only after the customer owner signs off.
Rollback disables create or the whole action profile; it does not delete
reports, dispositions, checkpoints, or audit metadata.
