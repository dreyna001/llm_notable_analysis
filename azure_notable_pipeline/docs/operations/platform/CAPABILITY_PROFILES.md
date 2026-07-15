# Azure capability profiles

## Profile contract

Profiles are additive configuration bundles. `core` is always present and is
the only default. A profile is not authorization by itself: risky profiles also
require identity, network, secret, approval, idempotency, and test evidence.
Profile changes are deployment changes, not analyst-level toggles.

| Profile | Enables | Risk and dependency gate |
| --- | --- | --- |
| `core` | Intake, analysis, durable reports | Azure OpenAI analyzer, Blob/Queue identity, and basic monitoring |
| `html_reports` | HTML report generation | Sanitized output review and portal/content policy |
| `rag` | General advisory retrieval | Azure AI Search index, ingestion owner, provenance, and suppression behavior |
| `spl_readonly` | SPL generation and bounded Splunk investigation | Search allowlists, time/row caps, read-only credential, and query test |
| `elastic_readonly` | Elasticsearch Query DSL generation and bounded investigation | One index allowlist, field allowlist, read-only credential, and query test |
| `ticket_draft` | ServiceNow draft payloads | Field mapping, assignment-group owner, and human review |
| `action_gated` | Splunk writeback and ServiceNow create | Explicit approval, Key Vault secret, side-effect idempotency, reconciliation, and rollback |
| `analyst_portal` | Case archive, case Q&A, portal, chat quota | Entra/JWT configuration, private Front Door/Function path, Search, Cosmos containers, synthetic monitor |

`spl_readonly` and `elastic_readonly` are mutually exclusive investigation
backends. A customer can run both integrations outside this profile model only
through a separately reviewed deployment design.

## Enablement sequence

1. Start with `core` and prove private intake, analysis, durable report, queue
   poison handling, and duplicate delivery behavior.
2. Add `html_reports`, `rag`, or one read-only investigation profile after its
   corpus/schema, endpoint, allowlist, and synthetic test are approved.
3. Add `ticket_draft` only after analysts can inspect the draft without creating
   a ticket.
4. Add `analyst_portal` after cross-user ownership, authenticated readiness,
   private-origin denial, and chat quota tests pass.
5. Add `action_gated` last. Keep Splunk writeback and ServiceNow create disabled
   until approval evidence and idempotent reconciliation are rehearsed.

## Fail-closed dependency checks

At startup or deployment validation, reject a profile when required endpoint,
index, container, secret name, identity, or approval dependency is absent. If a
downstream dependency becomes unavailable at runtime, suppress the optional
capability or return a structured failure; do not silently substitute a
commercial endpoint, a different model lane, or a write-capable credential.

## Rollback

Rollback is profile-specific. Disable only the affected profile when possible,
drain or preserve queued work, reconcile any external-success uncertainty, and
re-enable after synthetic validation. `action_gated` rollback always leaves
durable reports and audit records intact.
