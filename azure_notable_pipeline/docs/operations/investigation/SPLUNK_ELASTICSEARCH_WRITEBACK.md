# Splunk, Elasticsearch, and writeback operations

## Read-only investigation first

`spl_readonly` and `elastic_readonly` are bounded investigative capabilities.
Generated queries are drafts until deterministic validation succeeds. Enforce
explicit index allowlists, field allowlists, read-only commands, maximum time
ranges, row counts, concurrency, and request timeouts. Preserve the generated
query, policy result, execution result, and source attribution in the report.

Splunk investigation uses the configured REST/MCP boundary. Elasticsearch uses
read-only Query DSL against the configured allowlisted index. Neither path may
delete, collect, modify, or trigger an external action.

## Splunk writeback

Splunk notable writeback belongs only to `action_gated` and is disabled by
default. Durable Blob reports are written before writeback. The customer must
provide a Key Vault secret name or approved workload identity, exact endpoint
path, payload allowlist, finding-ID policy, approval record, and side-effect
idempotency container. A timeout after the remote request is an uncertain
outcome: reconcile by stable finding/operation identity before retrying.

## Elasticsearch does not write back

This pipeline has no Elasticsearch writeback capability. Any customer request
to update or remediate Elasticsearch is outside this contract and needs a
separate reviewed adapter, authorization boundary, and deployment record.

## Safe rollout

1. Run query generation and policy tests with fakes.
2. Enable one read-only profile in an isolated customer environment.
3. Confirm bounded query behavior, TLS/private path, and redacted telemetry.
4. Keep writeback disabled while staging acceptance runs.
5. For production writeback, require named approver, idempotency/reconciliation
   test, rollback owner, and a synthetic or isolated live smoke.

The SOAR upload helper is a producer only. It writes a complete Blob under the
customer-configured `input/incoming` prefix and does not call Splunk APIs or
enable pipeline writeback.
