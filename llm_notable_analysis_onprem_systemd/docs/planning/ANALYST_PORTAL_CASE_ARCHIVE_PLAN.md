# Analyst Portal And Case Archive Deferred Work

## Status

Backlog and open decisions for the shipped on-prem analyst portal and case
archive. This document is non-normative and intentionally excludes shipped
implementation detail.

Use these documents for current behavior and operations:

- [`../technical_specs/analyst_portal_case_archive_technical_spec.md`](../technical_specs/analyst_portal_case_archive_technical_spec.md)
- [`../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md)
- [`../operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md)
- [`../operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md`](../operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md)

AWS portal and archive parity is shipped separately under
[`../../../s3_notable_pipeline/docs/technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`](../../../s3_notable_pipeline/docs/technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md).

## Deferred Capabilities

- `global_archive` chat mode for cross-case retrieval without a pinned case.
- Prior-case retrieval as a tertiary chat lane, behind current-case evidence and
  approved Knowledge Base context.
- Cooperative backend cancellation of in-flight chat generation. The shipped UI
  Stop control aborts the client request and performs best-effort transcript
  cleanup only.
- Per-case RBAC or other case-level authorization boundaries.
- Portal-triggered rerun, writeback, ticket, suppression, remediation, or SOAR
  actions.
- Automatic chunk rebuild after analyzer replay or embedding-model changes.
- A dedicated least-privilege `notable_portal` database role in the shipped DDL;
  operators currently grant the portal role separately.

Threat-intelligence, CMDB, SOAR, observability, and evaluation work belongs in
[`FUTURE_ENHANCEMENTS_ROADMAP.md`](FUTURE_ENHANCEMENTS_ROADMAP.md) or
[`golden_eval_harness_todo.md`](golden_eval_harness_todo.md), not in this plan.

## Boundaries That Future Work Must Preserve

- The analyzer remains the canonical case writer. The portal is read-only unless
  a future action surface introduces an explicit capability flag, policy gate,
  approval metadata, audit trail, tests, and least-privilege credentials.
- Postgres JSONB remains the canonical case record; retrieval chunks are derived
  and rebuildable. Markdown and HTML are presentation or compatibility outputs.
- Current-case evidence, approved advisory context, model inference, and unknowns
  remain separate lanes. Weak retrieval must not fall back to unbounded model
  memory.
- Chat must not execute SPL or Elasticsearch queries or call Splunk, ServiceNow,
  SOAR, threat-intelligence, CMDB, or cloud APIs.
- Transcript persistence remains optional, bounded, and excluded from retrieval
  memory.
- All authenticated analysts currently see all retained cases. Enabling
  `global_archive` before case-level authorization therefore requires an explicit
  security review.

## Open Decisions

- Whether markdown remains a first-class output or only a compatibility artifact
  while the portal renders from Postgres JSONB.
- Which alert fields may become retrieval chunks and which require redaction or
  exclusion.
- Whether the next authentication example should cover an SSO-injected identity
  header, mTLS, or both. nginx remains the production trust boundary.
- What relevance, authorization, and source-separation thresholds are required
  before enabling `global_archive` or prior-case retrieval.
- Whether a future action-enabled portal should remain part of this service or
  use a separately deployed, separately credentialed workflow.

## Promotion Criteria

Move a deferred item into the technical spec only after its runtime contract,
configuration gates, failure behavior, security boundary, tests, and operator
procedure are approved. Remove the item from this file when the corresponding
implementation and canonical documentation ship.
