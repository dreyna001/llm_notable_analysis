# Azure capability profiles

Canonical operator guide for supported feature bundles on Azure Government. Set
`CapabilityProfiles` in Bicep or `CAPABILITY_PROFILES` on Function App settings,
then configure only the endpoints, indexes, secrets, and tuning values required
by the selected profiles.

Low-level `*_ENABLED` flags remain supported for legacy lab configs when no
selected profile controls that capability; when a profile controls a capability,
the profile takes precedence. Bicep parameters in `deploy/azure/main.bicep` are
the official deployment path (`CapabilityProfiles` -> `CAPABILITY_PROFILES`,
`HtmlReportEnabled` -> `HTML_REPORT_ENABLED`, and so on).

Profiles are additive configuration bundles. `core` is always present and is the
only default. A profile is not authorization by itself: risky profiles also
require identity, network, secret, approval, idempotency, and test evidence.
Profile changes are deployment changes, not analyst-level toggles.

## Supported profiles

| Profile | Operator intent | Risk class |
| --- | --- | --- |
| `core` | Private Blob intake, Azure OpenAI analysis, durable markdown + JSON reports. Sets no feature flags. | Blob/Queue identity access; Azure OpenAI inference. |
| `html_reports` | HTML report generation as an additional artifact. | Additional report artifact only. |
| `rag` | General advisory SOC retrieval from Azure AI Search in the main analysis prompt. | Read-only retrieval; advisory context only. |
| `spl_readonly` | SPL generation and bounded read-only Splunk investigation. | Read-only external Splunk queries. |
| `elastic_readonly` | Elasticsearch Query DSL generation and bounded read-only investigation. | Read-only external Elasticsearch queries. |
| `ticket_draft` | ServiceNow draft payloads in JSON reports. | Report content only; no ServiceNow POST. |
| `action_gated` | Splunk writeback and ServiceNow create with approval and side-effect idempotency. | External write/action path. |
| `analyst_portal` | Case archive, CaseIndex, read-only portal API, and retrieval-bound case Q&A. | Read-only analyst browse/chat over retained case evidence. |

Profiles are additive. `core` is automatically included when omitted. Profiles
may be separated with commas or semicolons. Startup rejects unknown profile names
and rejects selecting both `spl_readonly` and `elastic_readonly`.

`spl_readonly` and `elastic_readonly` are mutually exclusive investigation
backends. A customer can run both integrations outside this profile model only
through a separately reviewed deployment design.

```bash
CAPABILITY_PROFILES=core,rag,analyst_portal   # customer-default example
CAPABILITY_PROFILES=core,rag,spl_readonly     # not with elastic_readonly
```

Primary Bicep parameter: `CapabilityProfiles` (default: `core`).

## Profile-to-flag mapping

Authoritative mapping from `src/azure_notable_pipeline/config.py`
(`_CAPABILITY_PROFILE_FLAGS` and backend selection in `_profile_flag_defaults`):

| Profile | Flags set to `true` | Derived settings |
| --- | --- | --- |
| `core` | _(none)_ | — |
| `html_reports` | `HTML_REPORT_ENABLED` | — |
| `rag` | `RAG_ENABLED` | — |
| `spl_readonly` | `SPL_QUERY_GENERATION_ENABLED`, `INVESTIGATION_QUERY_EXECUTION_ENABLED` | `INVESTIGATION_QUERY_BACKEND=splunk` |
| `elastic_readonly` | `ELASTIC_QUERY_GENERATION_ENABLED`, `INVESTIGATION_QUERY_EXECUTION_ENABLED` | `INVESTIGATION_QUERY_BACKEND=elasticsearch` |
| `ticket_draft` | `SERVICENOW_DRAFT_ENABLED` | — |
| `action_gated` | `SPLUNK_SINK_ENABLED`, `SERVICENOW_DRAFT_ENABLED`, `SERVICENOW_CREATE_ENABLED`, `SERVICENOW_CREATE_REQUIRES_APPROVAL`, `SIDE_EFFECT_IDEMPOTENCY_ENABLED` | — |
| `analyst_portal` | `CASE_ARCHIVE_ENABLED`, `PORTAL_ENABLED`, `CASE_QA_ENABLED` | — |

`action_gated` includes draft behavior (`SERVICENOW_DRAFT_ENABLED`); `ticket_draft`
is the draft-only bundle when create/writeback are not approved.

Flags not controlled by any profile (legacy/lab only unless noted):

- `SPL_QUERY_RAG_ENABLED`
- `ELASTICSEARCH_GROUNDING_ENABLED`
- `QUERY_RESULT_INTERPRETATION_ENABLED` (env override only)
- `CASE_QA_CHAT_HISTORY_ENABLED` (default `false`; not enabled by `analyst_portal`)

## Operator workflow

1. Start with `CapabilityProfiles=core` and prove private intake, analysis,
   durable report, queue poison handling, and duplicate delivery behavior.
2. Add one profile at a time in a non-production stack.
3. Configure required Search indexes, Cosmos containers, Entra values, secret
   names, and tuning values for the selected profile.
4. Run smoke steps in the relevant operations guide and
   [`../testing/AZURE_GOVERNMENT_TESTING.md`](../testing/AZURE_GOVERNMENT_TESTING.md).
5. Promote the same profile list after ownership, approval boundaries, and
   rollback expectations are documented.

**Azure Government Path B customer-default (`core,rag,analyst_portal`):** use the
Bicep preset in
[`../deployment/AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md`](../deployment/AZURE_CUSTOMER_DEFAULT_DEPLOYMENT.md)
instead of assembling flags manually.

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

## Deploy path — next

Continue Path C from [`../../../README.md`](../../../README.md#path-c-custom-profiles) —
optional Search provisioning, Azure OpenAI enablement, portal Entra, image build,
Bicep deploy, profile ops guides, then
[`../testing/AZURE_GOVERNMENT_TESTING.md`](../testing/AZURE_GOVERNMENT_TESTING.md).
